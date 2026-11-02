"""The provider's small memory tool stays visible and reuses the session gates."""

from __future__ import annotations

from contextlib import chdir
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider  # noqa: E402
from omh.plugin_bundle.omh.tools import memory_tool  # noqa: E402
from project_identity_fixture import seed_project_identity  # noqa: E402
from test_memory_prefetch_canonical import SESSION, provider, rendered_ids  # noqa: E402
from test_memory_provider_hermes_order import hermes_turn  # noqa: E402


class RememberSchemaTests(unittest.TestCase):
    def test_provider_exposes_the_small_schema_before_initialize(self) -> None:
        schemas = OmhMemoryProvider().get_tool_schemas()
        self.assertEqual(len(schemas), 1)
        schema = schemas[0]
        self.assertEqual(schema, memory_tool.REMEMBER_TOOL_SCHEMA)
        self.assertEqual(set(schema), {"name", "description", "parameters"})
        self.assertEqual(schema["name"], memory_tool.REMEMBER_TOOL_NAME)
        self.assertEqual(schema["name"], "omh_remember")
        properties = schema["parameters"]["properties"]
        self.assertEqual(set(properties), {"action", "summary", "record_type", "subject", "query"})
        self.assertEqual(properties["action"]["enum"], ["save", "recall"])
        self.assertEqual(properties["action"]["default"], "save")
        self.assertEqual(properties["record_type"]["enum"], list(memory_tool.CAPTURE_RECORD_TYPES))
        self.assertLessEqual(len(json.dumps(schema, separators=(",", ":"))), 1200)
        for guidance in ("without asking", "preference", "decision", "setup", "project", "One fact", "self-contained", "absolute dates", "secrets", "logs", "transcripts", "task progress", "one short line", "recall"):
            self.assertIn(guidance, schema["description"])


class RememberStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        seed_project_identity(self.root)
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.home = self.root / ".omh"
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.home), "HERMES_HOME": str(self.hermes)}))
        self.enterContext(chdir(self.root))
        self.live = provider(self.root)

    def call(self, args: dict, live: OmhMemoryProvider | None = None, **kwargs) -> dict:
        target = live or self.live
        self.assertTrue(callable(getattr(target, "handle_tool_call", None)), "The provider must dispatch its memory tool")
        return json.loads(target.handle_tool_call("omh_remember", args, **kwargs))

    def record(self, record_id: str) -> dict:
        return json.loads((self.home / "memory" / "records" / f"{record_id}.json").read_text(encoding="utf-8"))

    def test_save_is_recalled_and_prefetched_with_the_provider_session_origin(self) -> None:
        summary = "Releases ship from the release branch."
        saved = self.call({"summary": summary, "record_type": "decision", "subject": "release-branch"})
        self.assertEqual((saved["status"], saved["plugin_tool"], saved["action"]), ("remembered", "omh_remember", "save"), saved)
        record_id = saved["record_id"]
        record = self.record(record_id)
        self.assertEqual(record["source_ref"], f"hermes-session:{SESSION}")
        self.assertEqual((record["summary"], record["record_type"], record["subject"]), (summary, "decision", "release-branch"))
        self.assertEqual((record["retention"]["class"], record["tags"]), ("durable", []))
        recalled = self.call({"action": "recall", "query": "release branch"})
        self.assertEqual((recalled["status"], recalled["plugin_tool"], recalled["action"]), ("found", "omh_remember", "recall"), recalled)
        self.assertEqual([row["record_id"] for row in recalled["records"]], [record_id])
        self.assertEqual(rendered_ids(hermes_turn(self.live, 1, "release branch")), [record_id])


    def store_bytes(self) -> dict[str, bytes]:
        directory = self.home / "memory"
        return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}

    def test_duplicate_save_leaves_the_store_unchanged(self) -> None:
        args = {"action": "save", "summary": "Releases ship from the release branch."}
        first = self.call(args)
        before = self.store_bytes()
        duplicate = self.call(args)
        self.assertEqual((duplicate["status"], duplicate["record_id"]), ("already_remembered", first["record_id"]), duplicate)
        self.assertEqual(self.store_bytes(), before)

    def test_session_ids_and_home_overrides_cannot_replace_the_provider_identity(self) -> None:
        saved = self.call(
            {"summary": "Builds use the pinned compiler.", "session_id": "another-session"},
            session_id="keyword-session", hermes_home=str(self.root / "other-home"), caller_gsk="fixture-key",
        )
        self.assertEqual(saved["status"], "remembered", saved)
        self.assertEqual(self.record(saved["record_id"])["source_ref"], f"hermes-session:{SESSION}")
        self.assertFalse((self.root / "other-home").exists())

    def test_save_keeps_defaults_instead_of_accepting_full_tool_options(self) -> None:
        saved = self.call({
            "summary": "Builds use the pinned compiler.", "scope": "user", "tags": ["injected"], "retention_class": "volatile",
        })
        self.assertEqual(saved["status"], "remembered", saved)
        record = self.record(saved["record_id"])
        self.assertEqual((record["scope"]["kind"], record["tags"], record["retention"]["class"]), ("project", [], "durable"))

    def test_discord_save_is_scoped_to_its_channel(self) -> None:
        channel = provider(
            self.root, session_id="discord-channel", platform="discord", chat_type="group",
            chat_id="1111111111111111111", user_id="987654321098765432", chat_name="fixture channel",
        )
        saved = self.call({"summary": "Channel reviews use the release checklist."}, channel)
        self.assertEqual(saved["status"], "remembered", saved)
        self.assertEqual(self.record(saved["record_id"])["scope"], channel._channel_scope)
        self.assertEqual(self.record(saved["record_id"])["source_ref"], "hermes-session:discord-channel")
        recalled = self.call({"action": "recall", "query": "release checklist"}, channel)
        self.assertEqual([row["record_id"] for row in recalled["records"]], [saved["record_id"]])
        other = provider(
            self.root, session_id="other-channel", platform="discord", chat_type="group",
            chat_id="2222222222222222222", user_id="987654321098765432", chat_name="other channel",
        )
        self.assertEqual(self.call({"action": "recall", "query": "release checklist"}, other)["records"], [])

    def test_background_save_is_refused_without_changing_store_bytes(self) -> None:
        for context in ("cron", "subagent"):
            with self.subTest(context=context):
                background = OmhMemoryProvider(self.home)
                background.initialize(context, platform="cli", agent_context=context, hermes_home=str(self.hermes), cwd=str(self.root))
                before = self.store_bytes()
                refused = self.call({"summary": "Builds use the pinned compiler."}, background)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", "writes_disabled"), refused)
                self.assertEqual(self.store_bytes(), before)

    def test_unbound_save_is_refused_without_changing_store_bytes(self) -> None:
        unbound = OmhMemoryProvider(self.home)
        before = self.store_bytes()
        refused = self.call({"summary": "Builds use the pinned compiler."}, unbound)
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "session_lens_unavailable"), refused)
        self.assertEqual(self.store_bytes(), before)

    def test_invalid_save_inputs_keep_the_capture_refusals(self) -> None:
        for args, reason in (
            ({}, "summary_required"),
            ({"summary": "x" * 501}, "summary_too_long"),
            ({"summary": "Builds use the pinned compiler.", "record_type": "rumor"}, "unsupported_record_type"),
            ({"summary": "Builds use the pinned compiler.", "subject": "../invalid"}, "invalid_subject"),
        ):
            with self.subTest(reason=reason):
                before = self.store_bytes()
                refused = self.call(args)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", reason), refused)
                self.assertEqual(self.store_bytes(), before)

    def test_recall_uses_the_full_tools_query_and_limit_validation(self) -> None:
        for args, reason in (
            ({"query": ""}, "query_invalid"),
            ({"query": "x" * 501}, "query_invalid"),
            *(({"query": "compiler", "limit": limit}, "limit_invalid") for limit in (0, 7, True, "2")),
        ):
            with self.subTest(args=args):
                refused = self.call({"action": "recall", **args})
                self.assertEqual((refused["status"], refused["reason"]), ("refused", reason), refused)
        saved = self.call({"summary": "Builds use the pinned compiler."})
        recalled = self.call({"action": "recall", "query": "compiler", "limit": 1})
        self.assertEqual([row["record_id"] for row in recalled["records"]], [saved["record_id"]])

    def test_unknown_action_names_only_the_small_tools_actions(self) -> None:
        before = self.store_bytes()
        refused = self.call({"action": "retire"})
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "unknown_action"), refused)
        self.assertEqual(refused["supported_actions"], ["save", "recall"])
        self.assertEqual((refused["plugin_tool"], refused["action"]), ("omh_remember", "retire"))
        self.assertEqual(self.store_bytes(), before)

    def test_unknown_tool_returns_a_json_error(self) -> None:
        result = json.loads(self.live.handle_tool_call("other", {}, caller_gsk="fixture-key"))
        self.assertEqual((result["status"], result["reason"]), ("error", "unknown_tool"))

    def test_handler_records_and_attaches_its_own_tool_observation(self) -> None:
        args = {"summary": "Builds use the pinned compiler."}
        with patch.object(memory_tool, "observe_plugin_tool_call", wraps=memory_tool.observe_plugin_tool_call) as observe:
            saved = json.loads(memory_tool.omh_remember_handler(args, session_id=SESSION, host="fixture-host"))
        self.assertEqual(saved["status"], "remembered", saved)
        observe.assert_called_once_with("omh_remember", args, {"session_id": SESSION, "host": "fixture-host"})
        self.assertEqual(saved["plugin_host_observation"]["tool"], "omh_remember")
        self.assertEqual(saved["plugin_host_observation"]["session_id"], SESSION)

    def test_prompt_line_is_short_and_empty_on_background_surfaces(self) -> None:
        prompt = getattr(self.live, "system_prompt_block", None)
        self.assertTrue(callable(prompt), "The provider must publish its small save-tool prompt")
        line = self.live.system_prompt_block()
        self.assertLessEqual(len(line), 300)
        self.assertEqual(len(line.splitlines()), 1)
        for word in ("omh_remember", "preferences", "decisions", "facts"):
            self.assertIn(word, line)
        for platform, context in (("cron", "cron"), ("subagent", "subagent"), ("cli", "cron"), ("cli", "subagent")):
            with self.subTest(platform=platform, context=context):
                background = OmhMemoryProvider(self.home)
                background.initialize(f"prompt-{platform}-{context}", platform=platform, agent_context=context, hermes_home=str(self.hermes), cwd=str(self.root))
                self.assertEqual(background.system_prompt_block(), "")
                self.assertEqual(background.get_tool_schemas(), [memory_tool.REMEMBER_TOOL_SCHEMA])


class HermesAssemblyTests(unittest.TestCase):
    def test_provider_tool_stays_visible_when_plugin_tools_are_deferred(self) -> None:
        source_value = os.environ.get("HERMES_AGENT_SRC", "")
        if not source_value:
            self.skipTest("Set HERMES_AGENT_SRC to exercise Hermes tool assembly")
        source = Path(source_value).expanduser().resolve()
        if not (source / "tools" / "tool_search.py").is_file():
            self.skipTest("HERMES_AGENT_SRC does not name a Hermes checkout")
        python = Path(os.environ.get("HERMES_PY") or source / "venv" / "bin" / "python")
        if not python.is_file():
            self.skipTest("Hermes child interpreter is unavailable")
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        isolated = {key: str(root / name) for key, name in (("HOME", "home"), ("HERMES_HOME", "hermes"), ("OMH_HOME", "omh"), ("TMPDIR", "tmp"))}
        for directory in isolated.values():
            Path(directory).mkdir()
        script = r'''
import json
import sys
sys.path[0] = sys.argv[1]
from tools.memory_tool import MEMORY_SCHEMA
from tools.registry import registry
from tools.tool_search import ToolSearchConfig, assemble_tool_defs
provider_schema = json.load(sys.stdin)
plugin_schema = {"name": "fixture_plugin_memory", "description": "Fixture plugin tool.", "parameters": {"type": "object", "properties": {}}}
registry.register(name=plugin_schema["name"], toolset="fixture-plugin", schema=plugin_schema, handler=lambda args, **kwargs: "{}")
defs = [{"type": "function", "function": schema} for schema in (MEMORY_SCHEMA, plugin_schema, provider_schema)]
result = assemble_tool_defs(defs, context_length=32768, config=ToolSearchConfig.from_raw({"enabled": "on", "threshold_pct": 0}))
visible = [tool["function"]["name"] for tool in result.tool_defs]
assert "memory" in visible, visible
assert "omh_remember" in visible, visible
assert "fixture_plugin_memory" not in visible, visible
assert result.activated and result.deferred_count == 1, result
print(json.dumps({"visible": visible, "deferred_count": result.deferred_count, "activated": result.activated}))
'''
        result = subprocess.run(
            [str(python), "-B", "-c", script, str(source)],
            input=json.dumps(memory_tool.REMEMBER_TOOL_SCHEMA), capture_output=True, encoding="utf-8", timeout=60,
            cwd=root, env={**os.environ, **isolated, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1", "OMH_UPDATE_CHECK": "0"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(lines, result.stdout + result.stderr)
        observed = json.loads(lines[-1])
        self.assertIn("omh_remember", observed["visible"])
        self.assertNotIn("fixture_plugin_memory", observed["visible"])
        self.assertEqual(observed["deferred_count"], 1)
        self.assertTrue(observed["activated"])


if __name__ == "__main__":
    unittest.main()

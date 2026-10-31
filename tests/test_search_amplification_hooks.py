"""Only an existing selected research route may receive search guidance."""
from copy import deepcopy
import ast
import hashlib
import json
import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import register  # noqa: E402
from test_search_tool import SearchContext  # noqa: E402


class SearchHookTests(unittest.TestCase):
    def test_cjk_trigger_inventory_unchanged(self):
        from omh.plugin_bundle.omh import awareness

        tree = ast.parse(Path(awareness.__file__).read_text(encoding="utf-8"))
        rows = sorted(node.value for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and isinstance(node.value, str)
                      and re.search("[\u1100-\u11ff\u3000-\u9fff\uac00-\ud7af]", node.value))
        # Frozen from HEAD before the helper: covers the whole CJK literal
        # inventory, stronger than checking only a few named cue tables.
        # 1352 -> 1296: the 56 removed literals were all cue words of the
        # bundle's own workflow-intent classifier copies, deleted when awareness
        # began importing the shared `workflow_intent` (which carries the
        # router's cue tables); no literal was added.
        self.assertEqual(len(rows), 1296)
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(digest, "574f700009cc1f96cb754e6502f1993b632c5604b76da4a052941af8ef1254f7")

    def test_disabled_awareness_uninstalled_research_and_ambiguous_requests_add_nothing(self):
        from omh.plugin_bundle.omh.hooks import llm_hooks

        request = "find datasets for browser agent benchmarks"
        self.assertNotIn("[OMH Search]", self.hook(request, include_omh_awareness=False).get("context", ""))
        with patch.object(llm_hooks, "installed_skill_names", return_value=frozenset()):
            self.assertNotIn("[OMH Search]", self.hook(request).get("context", ""))
        for request in ("관련 자료와 데이터를 찾아줘", "문제 해결에 참고할 자료/데이터 찾아줘"):
            self.assertNotIn("[OMH Search]", self.hook(request).get("context", ""))

    def hook(self, message, **extra):
        ctx = SearchContext()
        register(ctx)
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            kwargs = dict(session_id=self.id() + message, user_message=message, is_first_turn=True,
                          omh_home=str(home / "omh"), hermes_home=str(home / "hermes"), **extra)
            before = deepcopy(kwargs)
            result = ctx.hooks["pre_llm_call"](**kwargs) or {}
            self.assertEqual(kwargs, before)
            return result

    def test_research_route_loads_search_helper(self):
        result = self.hook("find datasets for browser agent benchmarks")
        self.assertIn("[OMH Search]", result.get("context", ""))
        self.assertIn("omh_search", result["context"])
        self.assertNotIn("$defs", result["context"])

    def test_translation_request_does_not_activate_search(self):
        result = self.hook('Translate "find datasets for browser agent benchmarks" into Korean')
        self.assertNotIn("[OMH Search]", result.get("context", ""))

    def test_file_lookup_keeps_direct_path(self):
        for request in ("Find ./docs/report.pdf", "Where is this file in ./reports?", "이 파일 어디 있어?"):
            with self.subTest(request=request):
                self.assertNotIn("[OMH Search]", self.hook(request).get("context", ""))

    def test_hook_does_not_mutate_system_prompt_history_or_tools(self):
        history = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "previous"}]
        tools = [{"name": "file_search", "parameters": {"type": "object"}}]
        self.hook("find datasets for browser agent benchmarks", system_prompt="frozen", tools=tools,
                  conversation_history=history)
        self.assertEqual(history[0]["content"], "fixed")
        self.assertEqual(len(tools), 1)

    def test_negation_quoted_request_and_coding_owners_stay_out(self):
        for request in ('Do not find datasets for browser agent benchmarks',
                        'The document says "find datasets for browser agent benchmarks".',
                        'Build a search feature that finds datasets for browser agent benchmarks',
                        'Fix the search bug in our app'):
            with self.subTest(request=request):
                self.assertNotIn("[OMH Search]", self.hook(request).get("context", ""))


if __name__ == "__main__":
    unittest.main()

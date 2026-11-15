"""Tool results keep non-ASCII text instead of escaping it as \\uXXXX.

Every OMH tool handler returns ``json.dumps(payload, sort_keys=True)`` whose
default ``ensure_ascii=True`` turns each CJK character into a six-character
``\\uXXXX`` escape. The result string stays in conversation history, so the
inflation is paid on every later model call -- measured in one deployment,
``omh_dag`` carried ~700k escapes over two weeks. These tests pin the literal
character surviving the handler round-trip.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler  # noqa: E402

SESSION = "non-ascii-session"
ITEM = "修复登录页"


class NonAsciiToolResultTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "hermes").mkdir()
        env = mock.patch.dict(
            os.environ,
            {"OMH_HOME": str(root / "omh"), "HERMES_HOME": str(root / "hermes")},
        )
        env.start()
        self.addCleanup(env.stop)

    def test_omh_todo_result_keeps_the_cjk_text(self) -> None:
        raw = omh_todo_handler(
            {"action": "set", "title": "修复登录页", "items": [{"text": ITEM, "state": "active"}]},
            session_id=SESSION,
        )
        self.assertIn(ITEM, raw)
        self.assertNotIn("\\u", raw)
        self.assertEqual(json.loads(raw)["todo"]["items"][0]["text"], ITEM)


if __name__ == "__main__":
    unittest.main()

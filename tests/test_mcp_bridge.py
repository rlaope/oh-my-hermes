from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class McpBridgeTests(unittest.TestCase):
    def test_mcp_manifest_exposes_stdio_server_and_allowlisted_tools(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(base + ["mcp", "manifest", "--command", "/tmp/omh"], output_json=False)

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_mcp_bridge/v1")
            self.assertEqual(payload["transport"], "stdio")
            self.assertEqual(payload["server"]["command"], "/tmp/omh")
            self.assertEqual(payload["server"]["args"][-2:], ["mcp", "serve"])
            tools = {tool["name"] for tool in payload["tools"]}
            self.assertEqual(tools, {"omh_status", "omh_recommend", "omh_probe"})
            self.assertIn("allowlisted local status", payload["claim_boundary"])

    def test_mcp_stdio_server_lists_and_calls_tools_without_stdout_noise(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "omh_recommend",
                        "arguments": {"message": "risky refactor", "limit": 2},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "omh_probe", "arguments": {"include_parity": True}},
                },
            ]
            stdin_text = "\n".join(json.dumps(request) for request in requests) + "\n"

            status, stdout, stderr = run_cli(base + ["mcp", "serve"], output_json=False, stdin_text=stdin_text)

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            lines = [json.loads(line) for line in stdout.splitlines()]
            self.assertEqual([line["id"] for line in lines], [1, 2, 3, 4])
            self.assertEqual(lines[0]["result"]["protocolVersion"], "2025-06-18")
            tools = {tool["name"] for tool in lines[1]["result"]["tools"]}
            self.assertEqual(tools, {"omh_status", "omh_recommend", "omh_probe"})
            recommend = lines[2]["result"]["structuredContent"]
            self.assertEqual(recommend["schema_version"], "omh_mcp_tool_result/v1")
            self.assertEqual(recommend["tool"], "omh_recommend")
            self.assertIn("recommendations", recommend["payload"])
            probe = lines[3]["result"]["structuredContent"]["payload"]["probe"]
            self.assertIn("parity_matrix", probe)
            self.assertEqual(probe["parity_matrix"]["probe_alignment"]["mcp_bridge_server"], "available")

            status, stdout, stderr = run_cli(base + ["probe"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            caps = {capability["name"]: capability for capability in json.loads(stdout)["capabilities"]}
            self.assertEqual(caps["mcp_bridge_server"]["status"], "available")
            self.assertEqual(caps["mcp_bridge_runtime"]["status"], "available")
            self.assertIn("tool call", caps["mcp_bridge_runtime"]["message"])

    def test_mcp_unknown_tool_returns_tool_error_result(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            request = {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "shell", "arguments": {"cmd": "whoami"}},
            }

            status, stdout, stderr = run_cli(
                base + ["mcp", "serve"],
                output_json=False,
                stdin_text=json.dumps(request) + "\n",
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertTrue(payload["result"]["isError"])
            structured = payload["result"]["structuredContent"]
            self.assertEqual(structured["status"], "tool_error")
            self.assertIn("Unknown tool", structured["error"])


if __name__ == "__main__":
    unittest.main()

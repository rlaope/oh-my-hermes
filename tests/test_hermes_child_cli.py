from __future__ import annotations

import json
import os
from pathlib import Path
import signal
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from omh.commands import hermes_child as hermes_child_command


_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys
import time

root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
(root / "argv.json").write_text(json.dumps(args), encoding="utf-8")
# Mirrors the installed Hermes CLI: `-z/--oneshot PROMPT` is an argv value
# and reads no stdin; only `chat --query-file -` reads stdin (#1824).
if "--oneshot" in args or "-z" in args:
    flag = "--oneshot" if "--oneshot" in args else "-z"
    prompt = args[args.index(flag) + 1]
elif args[:3] == ["chat", "--query-file", "-"]:
    prompt = sys.stdin.read()
else:
    raise SystemExit("no Hermes query transport in argv")
(root / "prompt.txt").write_text(prompt, encoding="utf-8")
# The `sessions` row a finished quiet turn leaves in the disposable home,
# the only place the chat transport records tokens and cost (#1831).
import sqlite3
with sqlite3.connect(Path(os.environ["HERMES_HOME"]) / "state.db") as db:
    db.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT,"
        " parent_session_id TEXT, started_at REAL NOT NULL, input_tokens INTEGER DEFAULT 0,"
        " output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0,"
        " cache_write_tokens INTEGER DEFAULT 0, reasoning_tokens INTEGER DEFAULT 0,"
        " billing_provider TEXT, estimated_cost_usd REAL, cost_status TEXT, cost_source TEXT,"
        " api_call_count INTEGER DEFAULT 0)"
    )
    db.execute(
        "INSERT INTO sessions VALUES ('20260925_000000_abc123', 'oneshot', ?, NULL, 1.0,"
        " 11, 7, 0, 0, 0, ?, 0.125, 'estimated', 'official_docs_snapshot', 1)",
        (args[args.index("--model") + 1], args[args.index("--provider") + 1]),
    )
if "hang" in prompt:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(60)
if "fail" in prompt:
    print("fake bad invocation", file=sys.stderr)
    raise SystemExit(7)
print("fake child complete")
"""


class HermesChildCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-hermes-child-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.omh_home = self.root / ".omh"
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)

    def base(self, action: str) -> list[str]:
        return [
            "--omh-home", str(self.omh_home), "coding", "hermes-child", action,
            "--model", "fake-model", "--provider", "fake-provider",
            "--reasoning", "high", "--parent-run-id", "parent-123",
            "--run-id", "child-456",
        ]

    def test_observation_key_uses_binary_mode_when_platform_requires_it(self) -> None:
        with patch.object(hermes_child_command.os, "O_BINARY", 0x8000, create=True):
            flags = hermes_child_command._observation_key_open_flags()

        self.assertEqual(flags & 0x8000, 0x8000)

    def test_prepare_is_default_safe_action_and_writes_no_prompt(self) -> None:
        secret = "SECRET_PREPARE_PROMPT_91"
        status, stdout, stderr = run_cli(self.base("prepare"), stdin_text=secret)
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual((payload["schema_version"], payload["claim"], payload["status"]), ("routing_observation/v1", "prepared", "prepared"))
        self.assertEqual(payload["role"], "agent_maintainer")
        self.assertFalse((self.root / "argv.json").exists())
        stored = (self.omh_home / "coding" / "hermes-child" / "child-456" / "observation.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, stored)

    def test_prepare_reports_a_damaged_integrity_key_by_the_size_it_read(self) -> None:
        root = self.omh_home / "coding" / "hermes-child"
        root.mkdir(parents=True)
        (root / ".observation-hmac-key").write_bytes(b"short")
        status, _, stderr = run_cli(self.base("prepare"), stdin_text="prepared prompt")
        self.assertEqual(status, 2)
        self.assertIn("Hermes child observation integrity key is 5 bytes, not 32", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_dispatch_requires_confirmation_before_fake_cli_starts(self) -> None:
        status, stdout, stderr = run_cli(self.base("dispatch"), stdin_text="do work")
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("--confirm-dispatch", stderr)
        self.assertFalse((self.root / "argv.json").exists())

    def test_skill_load_probe_requires_confirmation_and_real_unsupported_is_truthful(self) -> None:
        marker = self.root / "inventory-called"
        unsupported = self.root / "unsupported-hermes.py"
        unsupported.write_text(
            "#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\n"
            f"Path({str(marker)!r}).touch()\nraise SystemExit(2)\n",
            encoding="utf-8",
        )
        unsupported.chmod(0o755)
        command = [
            "--omh-home", str(self.omh_home), "coding", "hermes-child",
            "skill-load-probe", "--run-id", "probe-1", "--hermes", str(unsupported),
            "--expected-skill", "alpha",
        ]
        status, stdout, stderr = run_cli(command)
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("--confirm-dispatch", stderr)
        self.assertFalse(marker.exists())

        status, stdout, stderr = run_cli([*command, "--confirm-dispatch"])
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            (payload["schema_version"], payload["probe_status"], payload["reason_code"]),
            ("skill_load_observation/v1", "unsupported", "inventory_protocol_unavailable"),
        )
        self.assertNotIn("load_state", payload)
        self.assertTrue(marker.exists())
        stored = (
            self.omh_home / "coding" / "hermes-child" / "probe-1"
            / "skill-load-observation.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("prompt", stored)
        self.assertNotIn("credential", stored)

        status, status_stdout, stderr = run_cli([
            "--omh-home", str(self.omh_home), "coding", "hermes-child",
            "skill-load-status", "--run-id", "probe-1",
        ])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(status_stdout)["probe_status"], "unsupported")

    def test_skill_load_status_rejects_tampering(self) -> None:
        unsupported = self.root / "unsupported.py"
        unsupported.write_text("#!/usr/bin/env python3\nraise SystemExit(2)\n", encoding="utf-8")
        unsupported.chmod(0o755)
        command = [
            "--omh-home", str(self.omh_home), "coding", "hermes-child",
            "skill-load-probe", "--confirm-dispatch", "--run-id", "probe-tamper",
            "--hermes", str(unsupported),
        ]
        self.assertEqual(run_cli(command)[0], 0)
        path = (
            self.omh_home / "coding" / "hermes-child" / "probe-tamper"
            / "skill-load-observation.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["probe_status"] = "observed"
        payload["load_state"] = "all_loaded"
        path.write_text(json.dumps(payload), encoding="utf-8")
        status, stdout, stderr = run_cli([
            "--omh-home", str(self.omh_home), "coding", "hermes-child",
            "skill-load-status", "--run-id", "probe-tamper",
        ])
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)

    def test_real_fake_cli_happy_bad_timeout_and_secret_free_argv(self) -> None:
        cases = (
            ("SECRET_HAPPY_22", "completed", 0, "2"),
            ("fail SECRET_BAD_73", "failed", 1, "2"),
            ("hang", "timed_out", 1, "0.15"),
        )
        for index, (prompt, expected_status, expected_code, timeout) in enumerate(cases):
            with self.subTest(prompt=prompt):
                run_id = f"child-{index}"
                command = [item if item != "child-456" else run_id for item in self.base("dispatch")]
                command += ["--confirm-dispatch", "--hermes", str(self.hermes), "--timeout", timeout, "--termination-grace", "0.05"]
                # The fake writes one shared file; a stale copy from the
                # previous case must not be able to satisfy the readback.
                (self.root / "prompt.txt").unlink(missing_ok=True)
                status, stdout, stderr = run_cli(command, stdin_text=prompt)
                self.assertEqual(status, expected_code, stderr)
                payload = json.loads(stdout)
                self.assertEqual(payload["status"], expected_status)
                # Every terminal event of a spawned child carries the
                # dispatcher's own wall-clock seconds, signed into the receipt.
                self.assertIsInstance(payload["elapsed_seconds"], float)
                self.assertGreaterEqual(payload["elapsed_seconds"], 0.0)
                if expected_status != "timed_out":
                    # The child's spend reaches the observation from the
                    # `sessions` row of its disposable state.db, with the
                    # provenance that explains the cost (#1831).
                    self.assertEqual(
                        (payload["tokens"], payload["cost_usd"], payload["cost_status"], payload["cost_source"]),
                        (18, 0.125, "estimated", "official_docs_snapshot"),
                    )
                argv = json.loads((self.root / "argv.json").read_text(encoding="utf-8"))
                self.assertNotIn(prompt, json.dumps(argv))
                self.assertEqual(argv[:3], ["chat", "--query-file", "-"])
                self.assertNotIn("--oneshot", argv)
                if expected_status != "timed_out":
                    # The 0.15 s hang case can be killed before the fake
                    # reaches its write; the two finished cases prove the
                    # prompt arrived over stdin.
                    self.assertEqual((self.root / "prompt.txt").read_text(encoding="utf-8"), prompt)
                stored = (self.omh_home / "coding" / "hermes-child" / run_id / "observation.json").read_text(encoding="utf-8")
                self.assertNotIn(prompt, stored)
                self.assertFalse((self.omh_home / "coding" / "hermes-child" / run_id / "active.json").exists())

    def test_prompt_file_recursion_guard_status_rows_and_help(self) -> None:
        prompt_file = self.root / "prompt.md"
        prompt_file.write_text("file prompt", encoding="utf-8")
        command = self.base("dispatch") + [
            "--confirm-dispatch", "--hermes", str(self.hermes), "--prompt-file", str(prompt_file),
        ]
        previous = os.environ.get("OMH_ISOLATED_HERMES_DEPTH")
        os.environ["OMH_ISOLATED_HERMES_DEPTH"] = "1"
        try:
            status, stdout, stderr = run_cli(command)
        finally:
            if previous is None:
                os.environ.pop("OMH_ISOLATED_HERMES_DEPTH", None)
            else:
                os.environ["OMH_ISOLATED_HERMES_DEPTH"] = previous
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("depth is limited", stderr)
        self.assertFalse((self.root / "argv.json").exists())

        run_cli(self.base("prepare"), stdin_text="status prompt")
        status, stdout, stderr = run_cli([
            "--omh-home", str(self.omh_home), "coding", "hermes-child", "status", "--run-id", "child-456",
        ], output_json=False)
        self.assertEqual(status, 0, stderr)
        self.assertIn("AUDIENCE agent/maintainer", stdout)
        self.assertIn("STATE status prepared", stdout)
        self.assertNotIn("elapsed", stdout)

        with self.assertRaises(SystemExit) as raised:
            run_cli(["coding", "hermes-child", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_traversal_nested_and_symlink_run_ids_are_rejected_before_write(self) -> None:
        child_root = self.omh_home / "coding" / "hermes-child"
        outside = self.root / "outside"
        outside.mkdir()
        child_root.mkdir(parents=True)
        (child_root / "linked").symlink_to(outside, target_is_directory=True)

        for run_id in ("../escape", "nested/run", r"..\\escape", "linked"):
            with self.subTest(run_id=run_id):
                command = [item if item != "child-456" else run_id for item in self.base("prepare")]
                status, stdout, stderr = run_cli(command, stdin_text="safe prompt")
                self.assertEqual((status, stdout), (2, ""))
                self.assertIn("run_id", stderr)
        self.assertFalse((self.omh_home / "coding" / "escape" / "observation.json").exists())
        self.assertFalse((child_root / "nested" / "run" / "observation.json").exists())
        self.assertFalse((outside / "observation.json").exists())

    def test_symlinked_child_root_is_rejected(self) -> None:
        outside = self.root / "outside-root"
        outside.mkdir()
        coding = self.omh_home / "coding"
        coding.mkdir(parents=True, exist_ok=True)
        (coding / "hermes-child").symlink_to(outside, target_is_directory=True)
        status, stdout, stderr = run_cli(
            self.base("prepare"),
            stdin_text="secret prompt",
        )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("symlink", stderr)
        self.assertFalse((outside / "child-456" / "observation.json").exists())

    def test_duplicate_dispatch_run_id_is_rejected(self) -> None:
        command = [*self.base("dispatch"), "--confirm-dispatch", "--hermes", str(self.hermes)]
        first = run_cli(command, stdin_text="first prompt")
        self.assertEqual(first[0], 0)
        second = run_cli(command, stdin_text="second prompt")
        self.assertEqual(second[0], 2)
        self.assertIn("already exists", second[2])

    def test_status_rejects_unvalidated_persisted_payload_without_echoing_it(self) -> None:
        observation_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "observation.json"
        observation_path.parent.mkdir(parents=True)
        secret = "ULTRA_PRIVATE_PERSISTED_PROSE_791"
        observation_path.write_text(
            json.dumps({"schema_version": "attacker/v1", "status": "completed", "prose": secret}),
            encoding="utf-8",
        )
        status, stdout, stderr = run_cli([
            "--omh-home", str(self.omh_home), "coding", "hermes-child", "status",
            "--run-id", "child-456",
        ])
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)
        self.assertNotIn(secret, stdout + stderr)

    def test_status_rejects_shape_valid_tampered_observation(self) -> None:
        run_cli(self.base("prepare"), stdin_text="prepare")
        observation_path = (
            self.omh_home
            / "coding"
            / "hermes-child"
            / "child-456"
            / "observation.json"
        )
        payload = json.loads(observation_path.read_text(encoding="utf-8"))
        payload["status"] = "completed"
        payload["claim"] = "observed"
        payload["tokens"] = 987654
        observation_path.write_text(json.dumps(payload), encoding="utf-8")
        status, stdout, stderr = run_cli(
            [
                "--omh-home",
                str(self.omh_home),
                "coding",
                "hermes-child",
                "status",
                "--run-id",
                "child-456",
            ]
        )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)

    def test_cancel_signals_only_matching_live_process_identity(self) -> None:
        run_cli(self.base("prepare"), stdin_text="cancel target")
        active_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "active.json"
        identity = {"start_time": "123.456", "executable": "/safe/omh"}
        active_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes_child_active/v2",
                    "run_id": "child-456",
                    "run_nonce": "a" * 64,
                    "dispatcher_pid": 43210,
                    "child_pid": 43211,
                    "process_identity": identity,
                }
            ),
            encoding="utf-8",
        )
        with patch("omh.commands.hermes_child._process_identity", return_value=identity), patch(
            "omh.commands.hermes_child.os.kill"
        ) as kill:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(self.omh_home), "coding", "hermes-child",
                    "cancel", "--run-id", "child-456",
                ]
            )
        self.assertEqual(status, 0, stderr)
        kill.assert_called_once_with(43210, signal.SIGTERM)
        self.assertEqual(json.loads(stdout)["status"], "cancelled")

    def test_stale_or_forged_process_identity_never_signals_unrelated_pid(self) -> None:
        run_cli(self.base("prepare"), stdin_text="cancel target")
        active_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "active.json"
        active_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes_child_active/v2",
                    "run_id": "child-456",
                    "run_nonce": "b" * 64,
                    "dispatcher_pid": os.getpid(),
                    "child_pid": os.getpid(),
                    "process_identity": {"start_time": "stale", "executable": "/forged"},
                }
            ),
            encoding="utf-8",
        )
        live_identity = {"start_time": "live", "executable": "/actual"}
        with patch("omh.commands.hermes_child._process_identity", return_value=live_identity), patch(
            "omh.commands.hermes_child.os.kill"
        ) as kill:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(self.omh_home), "coding", "hermes-child",
                    "cancel", "--run-id", "child-456",
                ]
            )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("identity", stderr)
        kill.assert_not_called()

    def test_cancel_never_signals_pid_from_forged_or_legacy_active_record(self) -> None:
        run_cli(self.base("prepare"), stdin_text="cancel target")
        active_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "active.json"
        active_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes_child_active/v1",
                    "run_id": "child-456",
                    "dispatcher_pid": os.getpid(),
                    "child_pid": os.getpid(),
                }
            ),
            encoding="utf-8",
        )
        with patch("omh.commands.hermes_child.os.kill") as kill:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(self.omh_home), "coding", "hermes-child",
                    "cancel", "--run-id", "child-456",
                ]
            )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)
        kill.assert_not_called()

    def test_empty_prompt_and_argv_prompt_are_rejected(self) -> None:
        status, stdout, stderr = run_cli(self.base("prepare"), stdin_text="")
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("non-empty prompt", stderr)
        with self.assertRaises(SystemExit) as raised:
            run_cli(self.base("prepare") + ["secret-on-argv"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

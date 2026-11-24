from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Callable
import os
from pathlib import Path
import signal
import socket
from tempfile import TemporaryDirectory
import shutil
import stat
import tempfile
import textwrap
import time
import types
from threading import Event, Thread
import threading
import tracemalloc
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding import hermes_child_dispatch  # noqa: E402
from omh.coding.hermes_child_dispatch import (  # noqa: E402
    CancellationToken,
    DispatchConfirmationError,
    DispatchRecursionError,
    HermesChildEvaluationContext,
    HermesChildRequest,
    SpawnPreflightError,
    _child_env,
    dispatch_hermes_child,
)
from omh.coding.hermes_child_receipts import (  # noqa: E402
    load_hermes_child_receipt,
    write_signed_observation,
)
from omh.coding.routing_observation import (  # noqa: E402
    authenticate_child_observation,
    build_routing_observation,
)
from omh.coding._hermes_child_process import (  # noqa: E402
    BoundedStreamCapture,
    bounded_redacted_output,
    process_absent,
)


_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import subprocess
import socket
import sys
import threading
import time

root = Path.cwd()
args = sys.argv[1:]
(root / "argv.json").write_text(json.dumps(args), encoding="utf-8")
(root / "env.json").write_text(json.dumps({
    key: os.environ.get(key) for key in (
        "HOME", "HERMES_HOME", "HERMES_SAFE_MODE", "HERMES_IGNORE_USER_CONFIG",
        "HERMES_IGNORE_RULES", "OMH_ISOLATED_HERMES_ROUTING",
        "OMH_ISOLATED_HERMES_MAX_DEPTH", "OMH_ISOLATED_HERMES_DEPTH",
        "OMH_ISOLATED_HERMES_PARENT", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY",
    )
}), encoding="utf-8")
(root / "isolated-paths.json").write_text(json.dumps({
    "HOME": os.environ["HOME"], "HERMES_HOME": os.environ["HERMES_HOME"],
}), encoding="utf-8")
(root / "home-modes.json").write_text(json.dumps({
    name: oct(os.stat(os.environ[name]).st_mode & 0o777) for name in ("HOME", "HERMES_HOME")
}), encoding="utf-8")
# Mirrors the installed Hermes CLI (0.21.x): `-z/--oneshot PROMPT` takes the
# prompt from argv and never reads stdin, so a "-" there is the literal
# prompt "-"; only `chat --query-file -` reads stdin (#1824). Hermes writes
# its `--usage-file` report for `-z` alone, so this path writes none.
if "--oneshot" in args or "-z" in args:
    flag = "--oneshot" if "--oneshot" in args else "-z"
    prompt = args[args.index(flag) + 1]
elif args[:3] == ["chat", "--query-file", "-"]:
    prompt = sys.stdin.read()
else:
    raise SystemExit("no Hermes query transport in argv")
(root / "prompt-seen").write_text(prompt, encoding="utf-8")
(root / "started").touch()
state_db = Path(os.environ["HERMES_HOME"]) / "state.db"
if "state-db-not-sqlite" in prompt:
    state_db.write_text("ephemeral", encoding="utf-8")
elif "no-state-db" not in prompt:
    # What a finished `chat --query-file - --quiet` turn leaves in the
    # disposable home: one `sessions` row whose usage columns Hermes summed
    # per API call (`queue_token_counts`), the only place this transport
    # records tokens and cost (#1831). Columns OMH does not read carry text
    # that must not escape; the row is written before the prompt keywords
    # below, so a failed turn's spend is on file the way Hermes leaves it.
    import sqlite3
    with sqlite3.connect(state_db) as db:
        db.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT,"
            " parent_session_id TEXT, started_at REAL NOT NULL, ended_at REAL, end_reason TEXT,"
            " title TEXT, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,"
            " cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0,"
            " reasoning_tokens INTEGER DEFAULT 0, billing_provider TEXT, estimated_cost_usd REAL,"
            " cost_status TEXT, cost_source TEXT, api_call_count INTEGER DEFAULT 0)"
        )
        db.execute(
            "INSERT INTO sessions VALUES (?, 'oneshot', ?, NULL, 1.0, 2.0, 'cli_close',"
            " 'SECRET_TITLE_TEXT_MUST_NOT_ESCAPE', 11, 7, 3, 0, 2, ?, 0.125, 'estimated',"
            " 'official_docs_snapshot', 1)",
            ("20260925_000000_abc123", args[args.index("--model") + 1], args[args.index("--provider") + 1]),
        )
    state_db.chmod(0o600)
if "spawn-descendant" in prompt:
    child = subprocess.Popen([
        sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
    ])
    (root / "descendant.pid").write_text(str(child.pid), encoding="utf-8")
    if "notify-port=" in prompt:
        port = int(prompt.split("notify-port=", 1)[1].split()[0])
        with socket.create_connection(("127.0.0.1", port), timeout=2) as ready:
            ready.sendall(b"ready")
if "ignore-term" in prompt:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if "hang" in prompt or "cancel" in prompt:
    while True:
        time.sleep(60)
if "flood-both-100mb" in prompt:
    (root / "flood.pid").write_text(str(os.getpid()), encoding="utf-8")
    chunk = b"z" * (1024 * 1024)
    def flood(fd):
        for _ in range(100):
            view = memoryview(chunk)
            while view:
                written = os.write(fd, view)
                view = view[written:]
    threads = [threading.Thread(target=flood, args=(1,)), threading.Thread(target=flood, args=(2,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    raise SystemExit(9)
if "leak-output" in prompt:
    print(os.environ.get("OPENAI_API_KEY", "missing") + " SECRET_OUTPUT " + "x" * 50000)
    print("authorization bearer must not escape", file=sys.stderr)
    raise SystemExit(9)
if "fail" in prompt:
    print("fake failure", file=sys.stderr)
    raise SystemExit(9)
print("fake Hermes provider response")
"""


class HermesChildDispatchTests(unittest.TestCase):
    def test_truncated_complete_secret_prefix_is_redacted(self) -> None:
        output = bounded_redacted_output(
            BoundedStreamCapture(b"prefix-TOPSECRE", True),
            secrets={"TOPSECRET"},
        )
        self.assertNotIn("TOPSECRE", output)
        self.assertIn("[redacted]", output)

    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-hermes-child-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.omh_home = self.root / ".omh"
        self.omh_home.mkdir()
        self.env = {**os.environ, "OMH_HOME": str(self.omh_home)}

    def request(self, prompt: str = "do focused work", **changes: object) -> HermesChildRequest:
        values: dict[str, object] = {
            "prompt": prompt,
            "model": "fake/model",
            "provider": "fake-provider",
            "reasoning": "low",
            "parent_run_id": "parent-123",
            "run_id": "child-456",
            "timeout_seconds": 2.0,
            "termination_grace_seconds": 0.2,
            "hermes": str(self.hermes),
            "cwd": self.root,
            "env": self.env,
        }
        values.update(changes)
        return HermesChildRequest(**values)  # type: ignore[arg-type]

    def test_hidden_or_unconfirmed_dispatch_never_starts_hermes(self) -> None:
        for policy, confirmed in (("prepare_only", True), ("ask_before_dispatch", False)):
            with self.subTest(policy=policy, confirmed=confirmed):
                with self.assertRaises(DispatchConfirmationError):
                    dispatch_hermes_child(self.request(), dispatch_policy=policy, confirmed=confirmed)
                self.assertFalse((self.root / "started").exists())

    def test_capacity_launch_callable_refuses_before_actual_popen(self) -> None:
        def refuse(_spawn: Callable[[], subprocess.Popen[bytes]]) -> subprocess.Popen[bytes]:
            raise RuntimeError('test_capacity_blocked')
        with self.assertRaisesRegex(RuntimeError, '^test_capacity_blocked$'):
            _ = dispatch_hermes_child(self.request(), dispatch_policy='ask_before_dispatch',
                                      confirmed=True, launch=refuse)
        self.assertFalse((self.root / 'started').exists(), 'Hermes launched despite the supplied gate')

    def test_capacity_recovery_path_reaches_the_same_actual_popen_gate(self) -> None:
        from omh.coding.fanout_capacity import AdmissionBinding, AdmissionSupport, AdmissionReceipt, OwnerLaunchGate
        from omh.coding.fanout_dispatch import _hermes_recovery_dispatch
        from omh.system.paths import OmhPaths
        repo = self.root / 'repo'
        repo.mkdir()
        worktree = self.root / 'repo-fanout-a'
        # A real unit worktree on its own branch: the lane commits there once the child is done.
        for argv in (['init', '-q'], ['config', 'user.name', 't'], ['config', 'user.email', 't@t'],
                     ['commit', '-q', '--allow-empty', '-m', 'base'],
                     ['worktree', 'add', '-q', str(worktree), '-b', 'agent/a']):
            subprocess.run(['git', *argv], cwd=repo, check=True, capture_output=True)
        run_ref = 'fanout-123456789abc-a'
        gate = OwnerLaunchGate()
        binding = AdmissionBinding('hermes', 'fanout-123456789abc', 'prior', run_ref, 1,
                                   'a' * 40, str(worktree), 'invocation', 'prior-attempt')
        support = AdmissionSupport('fixture', 'fixture/v1', 'process_local')
        receipt = AdmissionReceipt('fixture', 'fixture/v1', binding, True, 1)
        self.assertIsNotNone(gate.context(binding, support=support).reject(receipt,
            process_started=True, returncode=1, implementation_started=False))
        request = self.request(parent_run_id=run_ref, run_id=run_ref + '-hermes-recovery',
                               cwd=worktree, model='m', provider='p', reasoning='low')
        paths = OmhPaths(omh_home=self.root / '.omh', hermes_home=self.root / '.hermes')

        def recover(launch_gate: OwnerLaunchGate, invocation_id: str) -> dict[str, object]:
            return _hermes_recovery_dispatch(paths, unit={'unit_id': 'a', 'run_ref': run_ref},
                repo_root=repo, timeout=2, routing={'model': 'm', 'provider': 'p', 'reasoning': 'low'},
                hermes_child=None, unit_dispatch_kwargs={
                    'fanout_id': 'fanout-123456789abc', 'goal_text': 'fixture', 'runner': subprocess.run,
                    'run_verification': False, 'environment_policy': None, 'base_env': None,
                    'dispatch_depth': 0, 'allow_unconfined': False, 'base_sha': 'a' * 40,
                    'invocation_id': invocation_id, 'launch_gate': launch_gate,
                    'verification_wave_width': 1, 'verification_execution_gate': None,
                })

        with patch('omh.coding.hermes_child_dispatch.HermesChildRequest', return_value=request):
            attempt = recover(gate, 'invocation')
        self.assertEqual(attempt['status'], 'not_started_capacity_blocked')
        self.assertFalse((worktree / 'started').exists())
        with patch('omh.coding.hermes_child_dispatch.HermesChildRequest', return_value=request):
            observed = recover(OwnerLaunchGate(), 'fresh')
        self.assertEqual((observed['status'], observed['exit_code']), ('completed', 0))
        self.assertTrue((worktree / 'started').exists())

    def test_depth_one_child_cannot_recursively_dispatch(self) -> None:
        with self.assertRaises(DispatchRecursionError):
            dispatch_hermes_child(
                self.request(depth=1),
                dispatch_policy="ask_before_dispatch",
                confirmed=True,
            )
        self.assertFalse((self.root / "started").exists())

    def test_prompt_reaches_the_child_over_query_file_stdin(self) -> None:
        # #1824: the former `--oneshot -` argv handed a real Hermes the
        # literal prompt "-" and ignored stdin. The fake mirrors that
        # contract, so this passes only when the transport is the one Hermes
        # reads from stdin.
        prompt = "PING789 reply with exactly this token"
        result = dispatch_hermes_child(
            self.request(prompt), dispatch_policy="ask_before_dispatch", confirmed=True
        )
        argv = json.loads((self.root / "argv.json").read_text(encoding="utf-8"))
        self.assertEqual(result.status, "completed")
        self.assertEqual((self.root / "prompt-seen").read_text(encoding="utf-8"), prompt)
        self.assertEqual(argv[:3], ["chat", "--query-file", "-"])
        self.assertNotIn("--oneshot", argv)
        self.assertNotIn("-z", argv)
        self.assertNotIn(prompt, json.dumps(argv))

    def test_real_fake_hermes_uses_secret_free_argv_and_reports_state_db_usage(self) -> None:
        secret = "SECRET_PROMPT_84f3c7"
        observed = []
        result = dispatch_hermes_child(
            self.request(f"do work with {secret}"),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            observe=observed.append,
        )

        argv = json.loads((self.root / "argv.json").read_text(encoding="utf-8"))
        child_env = json.loads((self.root / "env.json").read_text(encoding="utf-8"))
        self.assertEqual(
            argv[:10],
            [
                "chat",
                "--query-file",
                "-",
                "--quiet",
                "--provider",
                "fake-provider",
                "--model",
                "fake/model",
                "--reasoning",
                "low",
            ],
        )
        self.assertEqual(
            argv[10:],
            ["--safe-mode", "--ignore-user-config", "--ignore-rules", "--toolsets", "file"],
        )
        self.assertNotIn("--usage-file", argv)
        self.assertNotIn(secret, json.dumps(argv))
        self.assertEqual(
            (result.status, result.stdout.replace("\r\n", "\n"), result.exit_code),
            ("completed", "fake Hermes provider response\n", 0),
        )
        # Hermes writes its usage report for `-z` only; on the stdin
        # transport the child's spend is read from the `sessions` rows of
        # its disposable state.db before that home is removed (#1831).
        self.assertEqual(
            result.usage,
            {
                "input_tokens": 11,
                "output_tokens": 7,
                "cache_read_tokens": 3,
                "cache_write_tokens": 0,
                "reasoning_tokens": 2,
                "total_tokens": 18,
                "api_calls": 1,
                "estimated_cost_usd": 0.125,
                "model": "fake/model",
                "provider": "fake-provider",
                "cost_status": "estimated",
                "cost_source": "official_docs_snapshot",
            },
        )
        self.assertNotIn("SECRET_TITLE_TEXT", repr(result.usage))
        self.assertEqual([item.status for item in observed], ["prepared", "running", "completed"])
        self.assertTrue(all(secret not in repr(item) for item in observed))
        self.assertEqual(child_env["OMH_ISOLATED_HERMES_ROUTING"], "disabled")
        self.assertEqual(child_env["OMH_ISOLATED_HERMES_MAX_DEPTH"], "1")
        self.assertEqual(child_env["OMH_ISOLATED_HERMES_DEPTH"], "1")
        self.assertEqual(child_env["HERMES_SAFE_MODE"], "1")
        self.assertEqual(child_env["HERMES_IGNORE_USER_CONFIG"], "1")
        self.assertEqual(child_env["HERMES_IGNORE_RULES"], "1")
        self.assertNotIn("parent-123", child_env["OMH_ISOLATED_HERMES_PARENT"])
        self.assertNotIn("child-456", child_env["OMH_ISOLATED_HERMES_PARENT"])
        self.assertTrue(result.cleanup_verified)
        isolated = json.loads((self.root / "isolated-paths.json").read_text(encoding="utf-8"))
        self.assertFalse(Path(isolated["HOME"]).exists())
        self.assertFalse(Path(isolated["HERMES_HOME"]).exists())
        if os.name != "nt":
            # The disposable homes are the child's only writable roots; the
            # mode is what keeps another local user out of them while the
            # child runs (the usage-file 0600 pin this replaced is gone with
            # the file).
            modes = json.loads((self.root / "home-modes.json").read_text(encoding="utf-8"))
            self.assertEqual(modes, {"HOME": "0o700", "HERMES_HOME": "0o700"})
        self.assertNotIn(secret, "".join(path.read_text(encoding="utf-8") for path in self.omh_home.rglob("*") if path.is_file()))

    def test_real_dispatch_seals_actual_model_and_timeout_into_evaluation_receipt(self) -> None:
        context = HermesChildEvaluationContext(
            "task-1",
            "criteria-1",
            "a" * 64,
            "baseline",
            "hermes",
            "b" * 64,
            "rev-1",
        )
        events = []
        dispatch_hermes_child(
            self.request(
                model="actual-model",
                timeout_seconds=3.0,
                evaluation_context=context,
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            observe=events.append,
        )
        terminal = events[-1]
        receipt_home = self.omh_home.resolve()
        run_dir = receipt_home / "coding" / "hermes-child" / "child-456"
        run_dir.mkdir(parents=True)
        caller_payload = build_routing_observation(
            route={
                "selected_model": "caller/forged-model",
                "selected_reasoning_effort": "high",
                "role": "agent_maintainer",
                "executor_profile": "hermes_child",
                "chain": [],
            },
            child_dispatch=authenticate_child_observation(
                {"status": "completed", "run_id": "child-456"}
            ),
            run_id="child-456",
        )
        caller_payload["evaluation_binding"] = {
            "task_id": "task-1",
            "acceptance_criteria_ref": "criteria-1",
            "input_digest": "a" * 64,
            "arm": "baseline",
            "executor": "hermes",
            "model": "forged-model",
            "exposure_digest": "b" * 64,
            "execution_revision": "rev-1",
            "timeout_seconds": 1,
        }
        write_signed_observation(run_dir, caller_payload, terminal)

        binding = load_hermes_child_receipt(receipt_home, "child-456").evaluation_binding
        self.assertIsNotNone(binding)
        self.assertEqual((binding.model, binding.timeout_seconds), ("actual-model", 3.0))

    def test_env_override_cannot_remove_parent_recursion_marker(self) -> None:
        with patch.dict(os.environ, {"OMH_ISOLATED_HERMES_PARENT": "v1.opaque.signature"}):
            with self.assertRaises(DispatchRecursionError):
                dispatch_hermes_child(
                    self.request(env={}),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                )
        self.assertFalse((self.root / "started").exists())

    def test_active_in_process_dispatch_cannot_reenter_from_observer(self) -> None:
        recursion_errors: list[Exception] = []

        def observe(item: object) -> None:
            if getattr(item, "status", "") != "running":
                return
            try:
                dispatch_hermes_child(
                    self.request(env={}),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                )
            except DispatchRecursionError as exc:
                recursion_errors.append(exc)

        result = dispatch_hermes_child(
            self.request(), dispatch_policy="ask_before_dispatch", confirmed=True, observe=observe
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(recursion_errors), 1)

    def test_environment_allowlists_only_selected_provider_auth(self) -> None:
        openai_key = "opaque-auth-material-7731"
        aws_key = "unrelated-aws-material-9912"
        env = {
            "PATH": os.environ["PATH"],
            "OPENAI_API_KEY": openai_key,
            "AWS_SECRET_ACCESS_KEY": aws_key,
            "UNRELATED_CREDENTIAL": "other-material-5511",
        }
        result = dispatch_hermes_child(
            self.request(provider="openai", env=env),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        child_env = json.loads((self.root / "env.json").read_text(encoding="utf-8"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(child_env["OPENAI_API_KEY"], openai_key)
        self.assertIsNone(child_env["AWS_SECRET_ACCESS_KEY"])
        self.assertNotIn("UNRELATED_CREDENTIAL", child_env)

    def test_commandcode_key_reaches_only_a_commandcode_child(self) -> None:
        env = {
            "PATH": os.environ["PATH"],
            "COMMANDCODE_API_KEY": "opaque-relay-material-4471",
            "COMMANDCODE_BASE_URL": "https://relay.example/v1",
            "OPENAI_API_KEY": "opaque-auth-material-7731",
        }
        def child(provider: str) -> dict[str, str]:
            return _child_env(self.request(provider=provider, env=env), 1, self.root / "h", self.root / "u", "marker")

        selected = child("commandcode")
        self.assertEqual(selected["COMMANDCODE_API_KEY"], env["COMMANDCODE_API_KEY"])
        self.assertEqual(selected["COMMANDCODE_BASE_URL"], env["COMMANDCODE_BASE_URL"])
        self.assertNotIn("OPENAI_API_KEY", selected)
        other = child("openai")
        self.assertNotIn("COMMANDCODE_API_KEY", other)
        self.assertNotIn("COMMANDCODE_BASE_URL", other)

    def test_missing_working_directory_is_blocked_by_preflight_before_any_spawn(self) -> None:
        # Provider auth is deliberately NOT preflighted (see
        # `_spawn_preflight`'s docstring): only prerequisites unconditional on
        # every provider -- the executable and the working directory -- are
        # checked before the spawn.
        missing_cwd = self.root / "does-not-exist"
        with patch("omh.coding.hermes_child_dispatch.subprocess.Popen") as popen:
            with self.assertRaises(SpawnPreflightError) as ctx:
                dispatch_hermes_child(
                    self.request(cwd=missing_cwd),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                )
        popen.assert_not_called()
        failed = {item["check"] for item in ctx.exception.verdict["failed_checks"]}
        self.assertIn("working_directory", failed)
        self.assertFalse((self.root / "started").exists())

    def test_unknown_provider_cannot_project_dynamic_token(self) -> None:
        credential = "github-token-must-not-project"
        result = dispatch_hermes_child(
            self.request(
                provider="github",
                env={"PATH": os.environ["PATH"], "GITHUB_TOKEN": credential},
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        child_env = json.loads((self.root / "env.json").read_text(encoding="utf-8"))
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn(credential, result.stdout)

    def test_observer_failure_after_spawn_still_reaps_child(self) -> None:
        observed_pid: list[int] = []

        def observe(item) -> None:
            if item.pid is not None:
                observed_pid.append(item.pid)
                raise RuntimeError("observer failed")

        with self.assertRaisesRegex(RuntimeError, "observer failed"):
            dispatch_hermes_child(
                self.request("hang", timeout_seconds=10),
                dispatch_policy="ask_before_dispatch",
                confirmed=True,
                observe=observe,
            )
        self.assertTrue(observed_pid)
        self.assertTrue(process_absent(observed_pid[0]))

    def test_prepared_observer_failure_never_spawns(self) -> None:
        def observe(item) -> None:
            if item.status == "prepared":
                raise RuntimeError("prepared observer failed")

        with patch("omh.coding.hermes_child_dispatch.subprocess.Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "prepared observer failed"):
                dispatch_hermes_child(
                    self.request(),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                    observe=observe,
                )
        popen.assert_not_called()

    def test_output_and_spawn_errors_are_bounded_and_redacted(self) -> None:
        credential = "opaque-auth-material-8842"
        result = dispatch_hermes_child(
            self.request(
                "leak-output",
                provider="openai",
                env={"PATH": os.environ["PATH"], "OPENAI_API_KEY": credential},
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        self.assertLessEqual(len(result.stdout), 16_500)
        self.assertNotIn(credential, result.stdout)
        self.assertNotIn("SECRET_OUTPUT", result.stdout)
        self.assertNotIn("authorization", result.stderr.lower())

    def test_missing_hermes_executable_is_blocked_by_preflight_before_any_spawn(self) -> None:
        # Backlog G: a missing executable is resolved before the spawn is ever
        # attempted, not discovered by catching the OSError a doomed Popen
        # call would raise. Popen must never be called.
        with patch("omh.coding.hermes_child_dispatch.subprocess.Popen") as popen:
            with self.assertRaises(SpawnPreflightError) as ctx:
                dispatch_hermes_child(
                    self.request(hermes="/private/SECRET_EXECUTABLE_991/not-there"),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                )
        popen.assert_not_called()
        verdict = ctx.exception.verdict
        self.assertEqual(verdict["schema_version"], "omh_spawn_preflight_verdict/v1")
        self.assertFalse(verdict["ready"])
        self.assertEqual(verdict["status"], "blocked")
        failed = {item["check"]: item for item in verdict["failed_checks"]}
        self.assertIn("executable_presence", failed)
        self.assertIn("SECRET_EXECUTABLE_991", failed["executable_presence"]["detail"])
        self.assertTrue(failed["executable_presence"]["remedy"])
        self.assertFalse((self.root / "started").exists())

    def test_exact_100mb_on_both_streams_is_hard_capped_without_deadlock_or_leaks(self) -> None:
        prior_drainers = {
            thread.ident for thread in threading.enumerate()
            if thread.name.startswith("hermes-")
        }
        tracemalloc.start()
        try:
            result = dispatch_hermes_child(
                self.request("flood-both-100mb", timeout_seconds=10.0),
                dispatch_policy="ask_before_dispatch",
                confirmed=True,
            )
            _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertLess(peak_bytes, 4 * 1024 * 1024, "stream capture retained hostile output")
        self.assertEqual((result.status, result.exit_code), ("failed", 9))
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)
        marker = "[output truncated:"
        self.assertEqual(result.stdout.count(marker), 1)
        self.assertEqual(result.stderr.count(marker), 1)
        # The notice replaced a bare marker, so the payload says which cap fired
        # and how much it dropped -- and, because the drainer counts what it
        # discards, the real original size rather than "unknown".
        for stream, record in (
            (result.stdout, result.stdout_truncation),
            (result.stderr, result.stderr_truncation),
        ):
            self.assertEqual(record["reason_code"], "capture_cap")
            self.assertEqual(record["kept_bytes"], 16_384)
            self.assertGreaterEqual(record["original_bytes"], 100 * 1024 * 1024)
            self.assertEqual(record["spill_status"], "content_not_retained")
            self.assertNotIn("spill", record)
            self.assertIn(f"original_bytes={record['original_bytes']}", stream)
            self.assertNotIn("...", stream)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 17_000)
        self.assertLessEqual(len(result.stderr.encode("utf-8")), 17_000)
        self.assertTrue(result.cleanup_verified)
        pid = int((self.root / "flood.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_absent(pid))
        remaining = {
            thread.ident for thread in threading.enumerate()
            if thread.name.startswith("hermes-")
        }
        self.assertEqual(remaining, prior_drainers)

    def test_nonzero_exit_is_failed_and_usage_is_still_read(self) -> None:
        result = dispatch_hermes_child(
            self.request("fail"), dispatch_policy="ask_before_dispatch", confirmed=True
        )
        self.assertEqual(
            (result.status, result.exit_code, result.usage["api_calls"], result.usage["total_tokens"]),
            ("failed", 9, 1, 18),
        )
        self.assertTrue(result.cleanup_verified)

    def test_usage_stays_empty_when_the_child_left_no_readable_ledger(self) -> None:
        # Absent, never zero (AGENTS.md, Reporting Our Own Numbers): a home
        # the child never wrote and a state.db that is not a database both
        # read as no usage, and the disposable home is removed either way.
        for prompt in ("no-state-db", "state-db-not-sqlite"):
            with self.subTest(prompt=prompt):
                result = dispatch_hermes_child(
                    self.request(prompt), dispatch_policy="ask_before_dispatch", confirmed=True
                )
                self.assertEqual((result.status, result.usage), ("completed", {}))
                self.assertTrue(result.cleanup_verified)
                isolated = json.loads((self.root / "isolated-paths.json").read_text(encoding="utf-8"))
                self.assertFalse(Path(isolated["HERMES_HOME"]).exists())

    def test_timeout_sends_sigterm_then_sigkill_and_leaves_no_orphan(self) -> None:
        result = dispatch_hermes_child(
            self.request("spawn-descendant ignore-term hang", timeout_seconds=1.0),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        pid = int((self.root / "descendant.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_absent(pid))
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(
            result.termination_signals,
            (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)),
        )
        self.assertTrue(result.cleanup_verified)

    def test_explicit_cancellation_terminates_group_without_timing_luck(self) -> None:
        token = CancellationToken()
        outcome: list[object] = []
        finished = Event()
        ready = socket.socket()
        self.addCleanup(ready.close)
        ready.bind(("127.0.0.1", 0))
        ready.listen(1)
        ready.settimeout(2)
        port = ready.getsockname()[1]

        def run() -> None:
            try:
                outcome.append(
                    dispatch_hermes_child(
                        self.request(
                            f"spawn-descendant notify-port={port} cancel",
                            timeout_seconds=10,
                        ),
                        dispatch_policy="ask_before_dispatch",
                        confirmed=True,
                        cancellation=token,
                    )
                )
            finally:
                finished.set()

        thread = Thread(target=run)
        thread.start()
        connection, _ = ready.accept()
        with connection:
            self.assertEqual(connection.recv(5), b"ready")
        token.cancel()
        self.assertTrue(finished.wait(2), "cancelled dispatch did not finish")
        thread.join()
        result = outcome[0]
        self.assertEqual(result.status, "cancelled")
        pid = int((self.root / "descendant.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_absent(pid))
        self.assertTrue(result.cleanup_verified)

    def test_keyboard_interrupt_is_propagated_after_group_cleanup(self) -> None:
        class InterruptingProcess:
            pid = 991199
            returncode = None
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()

            def poll(self) -> int | None:
                return self.returncode

            def wait(self, timeout: float) -> int:
                raise KeyboardInterrupt

        events = []
        with patch("omh.coding.hermes_child_dispatch.subprocess.Popen", return_value=InterruptingProcess()), patch(
            "omh.coding.hermes_child_dispatch._terminate_process_group",
            return_value=(
                (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)),
                True,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                dispatch_hermes_child(
                    self.request(),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                    observe=events.append,
                )
        self.assertEqual(events[-1].status, "cancelled")



_REAL_RMTREE = shutil.rmtree


class ScratchHomeCleanupTests(unittest.TestCase):
    """A dispatch's result is its child's outcome; removing the scratch home is a bounded step reported beside it.

    Hermes' `chat` starts a detached `gateway run --idle-exit` for the scratch `HERMES_HOME` (a launchd job on macOS)
    that outlives the child and may still write into that home, or hold a log open, when the dispatch removes it.
    The removal is faked here, so nothing depends on the host or on timing: a writer that recreates a file right
    after the tree is gone, and Windows' refusal to unlink a file another process holds open.
    """

    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-scratch-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        tempdir = patch.object(tempfile, "tempdir", str(self.tmp))
        tempdir.start()
        self.addCleanup(tempdir.stop)
        no_wait = patch.object(hermes_child_dispatch, "_sleep", lambda seconds: None)
        no_wait.start()
        self.addCleanup(no_wait.stop)
        self.env = {**os.environ, "OMH_HOME": str(self.root / ".omh")}

    def home(self, name: str, *, age: float, text: str | None = None, deadline: float | None = None) -> Path:
        directory = self.tmp / name
        (directory / "hermes").mkdir(parents=True)
        marker = directory / ".omh-hermes-child-scratch"
        stamp = time.time() - age
        if text is None:
            text = f"omh-hermes-child-scratch/v1\n{int(stamp + 900 if deadline is None else deadline)}\n"
        marker.write_bytes(text.encode("ascii"))
        os.utime(marker, (stamp, stamp))
        return directory

    def dispatch(self, prompt: str = "do focused work", timeout: float = 5.0):
        request = HermesChildRequest(
            prompt=prompt, model="fake/model", provider="fake-provider", reasoning="low",
            parent_run_id="parent-123", run_id="child-456", timeout_seconds=timeout,
            termination_grace_seconds=0.2, hermes=str(self.hermes), cwd=self.root, env=self.env,
        )
        return dispatch_hermes_child(request, dispatch_policy="ask_before_dispatch", confirmed=True)

    def scratch_dir(self) -> Path:
        """The one scratch home of the running dispatch (a fake removal may get only an entry name and a dir_fd)."""
        return next(self.tmp.glob("omh-hermes-child-*"))

    def scratch_root(self) -> Path:
        isolated = json.loads((self.root / "isolated-paths.json").read_text(encoding="utf-8"))
        return Path(isolated["HERMES_HOME"]).parent

    def test_a_writer_recreating_a_file_after_removal_leaves_a_completed_dispatch_completed(self) -> None:
        seen: list[bool] = []

        def removal_then_a_gateway_write(path, *args, **kwargs):
            seen.append((self.scratch_dir() / ".omh-hermes-child-scratch").is_file())
            root = self.scratch_dir()
            _REAL_RMTREE(path, *args, **kwargs)
            if Path(path).name == "hermes":
                (root / "hermes" / "logs").mkdir(parents=True)
                (root / "hermes" / "logs" / "gateway-stdio.log").write_text("late line\n", encoding="utf-8")

        with patch("shutil.rmtree", side_effect=removal_then_a_gateway_write):
            result = self.dispatch()
        scratch = self.scratch_root()
        self.addCleanup(_REAL_RMTREE, scratch, True)
        self.assertEqual((result.status, result.exit_code), ("completed", 0))
        self.assertFalse(result.cleanup_verified)
        self.assertEqual(getattr(result, "scratch_left", None), str(scratch))
        self.assertIn(f"scratch home left at {scratch}", getattr(result, "cleanup_note", ""))
        self.assertTrue(seen and seen[0], "the scratch root carries OMH's marker while it exists")
        self.assertTrue((scratch / ".omh-hermes-child-scratch").read_text(encoding="utf-8").startswith(
            "omh-hermes-child-scratch/v1\n"), "a home recreated after removal is left with a valid marker again")

    def test_a_left_home_that_lost_its_marker_gets_it_back_and_a_later_sweep_takes_it(self) -> None:
        # NTFS lists `.omh-hermes-child-scratch` before `hermes`, so a removal that stops at the open log has
        # already taken the marker.
        def marker_first_then_refused(path, *args, **kwargs):
            (self.scratch_dir() / ".omh-hermes-child-scratch").unlink(missing_ok=True)
            raise PermissionError(13, "in use")

        with patch("shutil.rmtree", side_effect=marker_first_then_refused):
            result = self.dispatch()
        scratch = self.scratch_root()
        self.addCleanup(_REAL_RMTREE, scratch, True)
        self.assertEqual(result.status, "completed")
        restored = (scratch / ".omh-hermes-child-scratch").read_text(encoding="utf-8").split("\n")
        self.assertEqual(restored[0], "omh-hermes-child-scratch/v1")
        self.assertGreater(int(restored[1]), time.time() + 5.0, "the restored marker keeps this dispatch's deadline")
        self.assertIn("older than 86400 s and past this dispatch's deadline", result.cleanup_note)
        with patch.object(hermes_child_dispatch, "_clock", lambda: time.time() + 2 * 86400):
            hermes_child_dispatch._sweep_scratch_homes()
        self.assertFalse(scratch.exists())

    def test_a_live_dispatchs_home_is_kept_until_its_own_deadline(self) -> None:
        # Two days old, but its dispatch has a three-day timeout: still running, so never swept before its deadline.
        deadline = time.time() - 2 * 86400 + 3 * 86400 + 3600
        live = self.home("omh-hermes-child-live", age=2 * 86400, deadline=deadline)
        hermes_child_dispatch._sweep_scratch_homes()
        self.assertTrue(live.exists())
        with patch.object(hermes_child_dispatch, "_clock", lambda: deadline + 1):
            hermes_child_dispatch._sweep_scratch_homes()
        self.assertFalse(live.exists())

    def test_a_long_timeout_is_accepted_and_written_as_the_markers_deadline(self) -> None:
        seen: list[str] = []

        def read_marker(path, *args, **kwargs):
            seen.append((self.scratch_dir() / ".omh-hermes-child-scratch").read_text(encoding="utf-8"))
            _REAL_RMTREE(path, *args, **kwargs)

        with patch.object(hermes_child_dispatch, "_clock", lambda: 1_600_000_000.0), \
                patch("shutil.rmtree", side_effect=read_marker):
            result = self.dispatch(timeout=5 * 86400.0)
        self.assertEqual(result.status, "completed")
        self.assertEqual(seen[0], f"omh-hermes-child-scratch/v1\n{1_600_000_000 + 5 * 86400 + 3600 + 1}\n")

    def test_an_infinite_or_huge_timeout_still_runs_and_records_the_largest_deadline(self) -> None:
        for timeout in (float("inf"), 1e30):
            with self.subTest(timeout=timeout):
                seen: list[str] = []

                def read_marker(path, *args, **kwargs):
                    seen.append((self.scratch_dir() / ".omh-hermes-child-scratch").read_text(encoding="utf-8"))
                    _REAL_RMTREE(path, *args, **kwargs)

                with patch("shutil.rmtree", side_effect=read_marker):
                    result = self.dispatch(timeout=timeout)
                self.assertEqual(result.status, "completed")
                self.assertEqual(seen[0], "omh-hermes-child-scratch/v1\n" + "9" * 20 + "\n")

    def test_a_nan_timeout_is_refused_before_anything_is_emitted_or_created(self) -> None:
        observed: list[object] = []
        request = HermesChildRequest(
            prompt="p", model="fake/model", provider="fake-provider", reasoning="low", parent_run_id="parent-123",
            run_id="child-456", timeout_seconds=float("nan"), hermes=str(self.hermes), cwd=self.root, env=self.env,
        )
        with self.assertRaisesRegex(ValueError, "positive timeout"):
            dispatch_hermes_child(request, dispatch_policy="ask_before_dispatch", confirmed=True,
                                  observe=observed.append)
        self.assertEqual(observed, [])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_marker_that_cannot_be_written_is_a_typed_failure_before_the_child_starts(self) -> None:
        real_write = Path.write_bytes

        def refuse_marker(self_path, *args, **kwargs):
            if self_path.name == ".omh-hermes-child-scratch":
                raise OSError(28, "No space left on device")
            return real_write(self_path, *args, **kwargs)

        with patch.object(Path, "write_bytes", refuse_marker):
            result = self.dispatch()
        self.assertEqual((result.status, result.exit_code), ("failed", None))
        self.assertIn("could not be marked (OSError)", result.stderr)
        self.assertFalse((self.root / "argv.json").exists(), "the child never started")
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_forged_far_deadline_garbage_or_an_old_header_only_marker_keeps_the_home(self) -> None:
        kept = [
            self.home("omh-hermes-child-far", age=2 * 86400, deadline=time.time() + 10 ** 12),
            self.home("omh-hermes-child-garbage", age=2 * 86400, text="omh-hermes-child-scratch/v1\n12e5\n"),
            self.home("omh-hermes-child-negative", age=2 * 86400, text="omh-hermes-child-scratch/v1\n-5\n"),
            self.home("omh-hermes-child-extra", age=2 * 86400, text="omh-hermes-child-scratch/v1\n5\nmore\n"),
            self.home("omh-hermes-child-header-only", age=2 * 86400, text="omh-hermes-child-scratch/v1\n"),
        ]
        hermes_child_dispatch._sweep_scratch_homes()
        self.assertTrue(all(directory.exists() for directory in kept))

    def test_a_sweep_that_fails_after_the_first_entry_keeps_the_marker_for_the_next_one(self) -> None:
        old = self.home("omh-hermes-child-held", age=2 * 86400)
        (old / "home").mkdir()
        calls: list[str] = []

        def first_entry_then_refused(path, *args, **kwargs):
            calls.append(str(path))
            if len(calls) > 1:
                raise PermissionError(13, "in use")
            _REAL_RMTREE(path, *args, **kwargs)

        with patch("shutil.rmtree", side_effect=first_entry_then_refused):
            hermes_child_dispatch._sweep_scratch_homes()
        self.assertEqual(len(calls), 2)
        self.assertTrue((old / ".omh-hermes-child-scratch").is_file())
        hermes_child_dispatch._sweep_scratch_homes()
        self.assertFalse(old.exists())

    def test_a_sweep_whose_root_comes_back_restores_the_same_marker(self) -> None:
        old = self.home("omh-hermes-child-rewritten", age=2 * 86400)
        before = (old / ".omh-hermes-child-scratch").read_bytes()
        stamp = (old / ".omh-hermes-child-scratch").stat().st_mtime
        real_rmdir = os.rmdir

        def refused(target, *args, **kwargs):
            if Path(target).name == old.name:
                raise OSError(66, "Directory not empty")
            real_rmdir(target, *args, **kwargs)

        with patch.object(os, "rmdir", refused):
            hermes_child_dispatch._sweep_scratch_homes()
        marker = old / ".omh-hermes-child-scratch"
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual(int(marker.stat().st_mtime), int(stamp))
        hermes_child_dispatch._sweep_scratch_homes()
        self.assertFalse(old.exists())

    def populated_outside(self) -> Path:
        outside = self.root / "outside"
        (outside / "sub").mkdir(parents=True)
        (outside / "sub" / "f").write_text("keep\n", encoding="utf-8")
        (outside / "g").write_text("keep\n", encoding="utf-8")
        return outside

    def assert_untouched(self, outside: Path) -> None:
        self.assertEqual((outside / "sub" / "f").read_text(encoding="utf-8"), "keep\n")
        self.assertEqual((outside / "g").read_text(encoding="utf-8"), "keep\n")

    def link(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError:
            self.skipTest("this platform refuses to create symlinks for this user")

    def test_a_symlinked_root_is_refused_and_its_target_untouched(self) -> None:
        outside = self.populated_outside()
        (outside / ".omh-hermes-child-scratch").write_bytes(b"omh-hermes-child-scratch/v1\n1\n")
        root = self.tmp / "omh-hermes-child-link"
        self.link(root, outside)
        with self.assertRaises(OSError):
            hermes_child_dispatch._remove_marker_last(root)
        note = hermes_child_dispatch._remove_scratch(root, time.time(), "omh-hermes-child-scratch/v1\n1\n")
        self.assertIn("is not a plain directory", note)
        stamp = time.time() - 3 * 86400
        os.utime(outside / ".omh-hermes-child-scratch", (stamp, stamp))
        hermes_child_dispatch._sweep_scratch_homes()
        self.assert_untouched(outside)
        self.assertTrue((outside / ".omh-hermes-child-scratch").is_file())

    def test_the_dispatchs_own_home_swapped_after_creation_is_refused(self) -> None:
        # The dispatch removes only the directory its own mkdtemp made (same st_dev/st_ino). A file system may reuse
        # an inode for a recreated directory, so the identity it recorded is made to differ here, not left to chance.
        other = self.home("omh-hermes-child-made", age=0)
        (other / "home").mkdir()
        seen = os.lstat(other)
        recorded = types.SimpleNamespace(st_dev=seen.st_dev, st_ino=seen.st_ino + 1)
        note = hermes_child_dispatch._remove_scratch(other, time.time(), "omh-hermes-child-scratch/v1\n1\n", recorded)
        self.assertIn("changed after it was checked", note)
        self.assertTrue((other / "home").is_dir())

    def test_the_marker_is_written_as_bytes_so_no_platform_translates_its_newlines(self) -> None:
        # Text mode writes `\r\n` on Windows, which `_marker_deadline` refuses: no home would ever be swept.
        def no_text_mode(self_path, *args, **kwargs):
            raise AssertionError(f"text-mode write of {self_path.name}")

        seen: list[bytes] = []

        def read_marker(path, *args, **kwargs):
            seen.append((self.scratch_dir() / ".omh-hermes-child-scratch").read_bytes())
            raise PermissionError(13, "in use")

        with patch.object(Path, "write_text", no_text_mode), patch("shutil.rmtree", side_effect=read_marker):
            result = self.dispatch()
        self.addCleanup(_REAL_RMTREE, self.scratch_root(), True)
        self.assertEqual(result.status, "completed")
        self.assertNotIn(b"\r", seen[0])
        self.assertIsNotNone(hermes_child_dispatch._marker_deadline(seen[0]))

    def test_a_windows_shaped_sweep_takes_an_old_home_and_keeps_a_young_one(self) -> None:
        # Windows: no `os.getuid`, no O_NOFOLLOW / dir_fd removal. Both are taken away here.
        old = self.home("omh-hermes-child-win-old", age=2 * 86400, deadline=time.time() - 86400)
        young = self.home("omh-hermes-child-win-young", age=60)
        getuid = getattr(os, "getuid", None)
        if getuid is not None:
            del os.getuid
        try:
            with patch.object(hermes_child_dispatch, "_descriptor_removal", lambda: False):
                hermes_child_dispatch._sweep_scratch_homes()
        finally:
            if getuid is not None:
                os.getuid = getuid
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())

    def test_a_long_wait_is_taken_in_slices_windows_can_convert(self) -> None:
        # Windows' `Popen.wait` turns its timeout into whole milliseconds: `inf` raises OverflowError there.
        real_wait = subprocess.Popen.wait
        asked: list[float | None] = []

        def windows_like_wait(process, timeout=None):
            asked.append(timeout)
            if timeout is not None and (timeout == float("inf") or timeout * 1000 > 2 ** 32 - 2):
                raise OverflowError("cannot convert float infinity to integer")
            return real_wait(process, timeout=timeout)

        with patch.object(subprocess.Popen, "wait", windows_like_wait), \
                patch.object(hermes_child_dispatch, "_WAIT_SLICE_SECONDS", 0.05):
            for timeout in (float("inf"), 1e30):
                with self.subTest(timeout=timeout):
                    self.assertEqual(self.dispatch(timeout=timeout).status, "completed")
        self.assertTrue(all(value is None or value <= 3600.0 for value in asked))

    def test_a_root_swapped_for_a_link_after_the_sweeps_checks_is_refused(self) -> None:
        outside = self.populated_outside()
        old = self.home("omh-hermes-child-swapped", age=2 * 86400, deadline=time.time() - 86400)
        real = hermes_child_dispatch._remove_marker_last

        def swap_then_remove(path, expected=None):
            _REAL_RMTREE(path)
            self.link(path, outside)
            return real(path, expected)

        with patch.object(hermes_child_dispatch, "_remove_marker_last", swap_then_remove):
            hermes_child_dispatch._sweep_scratch_homes()
        self.assertTrue(old.is_symlink())
        self.assert_untouched(outside)

    def test_a_link_inside_the_home_is_removed_and_what_it_points_at_untouched(self) -> None:
        outside = self.populated_outside()
        home = self.home("omh-hermes-child-inner", age=0)
        self.link(home / "hermes" / "escape", outside)
        self.link(home / "escape-file", outside / "g")
        if not hermes_child_dispatch._descriptor_removal():
            with self.assertRaises(OSError):
                hermes_child_dispatch._remove_marker_last(home)
        else:
            hermes_child_dispatch._remove_marker_last(home)
            self.assertFalse(home.exists())
        self.assert_untouched(outside)

    def test_the_lstat_fallback_removes_a_plain_home_and_refuses_a_link_inside(self) -> None:
        # The branch Windows takes (no O_NOFOLLOW / dir_fd removal), run here by turning the descriptor path off.
        with patch.object(hermes_child_dispatch, "_descriptor_removal", lambda: False):
            plain = self.home("omh-hermes-child-plain", age=0)
            (plain / "home").mkdir()
            hermes_child_dispatch._remove_marker_last(plain)
            self.assertFalse(plain.exists())
            outside = self.populated_outside()
            linked = self.home("omh-hermes-child-linked", age=0)
            self.link(linked / "escape", outside)
            with self.assertRaisesRegex(OSError, "is a link or reparse point"):
                hermes_child_dispatch._remove_marker_last(linked)
            self.assertTrue((linked / ".omh-hermes-child-scratch").is_file())
        self.assert_untouched(outside)

    def test_a_reparse_point_root_is_refused(self) -> None:
        home = self.home("omh-hermes-child-junction", age=0)
        real = home.lstat()
        reparse = types.SimpleNamespace(st_mode=real.st_mode, st_dev=real.st_dev, st_ino=real.st_ino,
                                        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        real_lstat = os.lstat

        def lstat(target, *args, **kwargs):
            return reparse if Path(target) == home else real_lstat(target, *args, **kwargs)

        with patch.object(os, "lstat", lstat), self.assertRaisesRegex(OSError, "not a plain directory"):
            hermes_child_dispatch._remove_marker_last(home)
        self.assertTrue((home / ".omh-hermes-child-scratch").is_file())

    def test_young_homes_named_first_do_not_starve_an_old_one(self) -> None:
        for index in range(40):
            (self.tmp / f"aaa-other-{index:02d}").mkdir()
        young = [self.home(f"omh-hermes-child-a{index:02d}", age=60) for index in range(32)]
        old = self.home("omh-hermes-child-zzz", age=2 * 86400)
        hermes_child_dispatch._sweep_scratch_homes()
        self.assertFalse(old.exists())
        self.assertTrue(all(directory.exists() for directory in young))

    def test_the_sweep_takes_no_link_no_foreign_owner_and_no_other_marker(self) -> None:
        wrong_text = self.home("omh-hermes-child-wrong", age=2 * 86400, text="omh-hermes-child-scratch/v2\n1\n")
        foreign = self.home("omh-hermes-child-foreign", age=2 * 86400)
        target = self.home("target-old", age=2 * 86400)
        links: list[Path] = []
        try:
            (self.tmp / "omh-hermes-child-link").symlink_to(target, target_is_directory=True)
            linked_marker = self.tmp / "omh-hermes-child-linked-marker"
            (linked_marker / "hermes").mkdir(parents=True)
            (linked_marker / ".omh-hermes-child-scratch").symlink_to(target / ".omh-hermes-child-scratch")
            links = [self.tmp / "omh-hermes-child-link", linked_marker]
        except OSError:
            pass  # Windows without the symlink privilege: the two link cases cannot be built there
        owner = foreign.lstat().st_uid

        def uid_for(path_owner: int):
            # Only the foreign home reads as another user's.
            real_lstat = Path.lstat

            def lstat(self_path):
                info = real_lstat(self_path)
                if self_path == foreign:
                    return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink,
                                           path_owner + 1, info.st_gid, info.st_size,
                                           int(info.st_atime), int(info.st_mtime), int(info.st_ctime)))
                return info
            return lstat

        with patch.object(os, "getuid", lambda: owner, create=True), patch.object(Path, "lstat", uid_for(owner)):
            hermes_child_dispatch._sweep_scratch_homes()
        self.assertTrue(wrong_text.exists())
        self.assertTrue(foreign.exists())
        self.assertTrue((target / ".omh-hermes-child-scratch").is_file())
        self.assertTrue(all(path.exists() or path.is_symlink() for path in links))

    def test_a_file_another_process_holds_open_on_windows_is_a_note_not_a_failure(self) -> None:
        refusal = PermissionError(13, "The process cannot access the file because it is being used by another process")
        with patch("shutil.rmtree", side_effect=refusal) as removal:
            result = self.dispatch()
        scratch = self.scratch_root()
        self.addCleanup(_REAL_RMTREE, scratch, True)
        self.assertEqual(result.status, "completed")
        self.assertGreater(removal.call_count, 1, "the removal is retried before it is given up")
        self.assertIn("PermissionError", getattr(result, "cleanup_note", ""))
        self.assertTrue(scratch.exists())

    def test_a_removal_that_succeeds_on_retry_is_clean(self) -> None:
        calls: list[str] = []

        def busy_once(path, *args, **kwargs):
            calls.append(str(path))
            if len(calls) == 1:
                raise OSError(66, "Directory not empty")
            _REAL_RMTREE(path, *args, **kwargs)

        with patch("shutil.rmtree", side_effect=busy_once):
            result = self.dispatch()
        self.assertEqual((result.status, result.cleanup_verified), ("completed", True))
        self.assertEqual(getattr(result, "cleanup_note", None), "")
        self.assertFalse(self.scratch_root().exists())

    def test_a_failed_child_stays_failed_and_an_unreaped_child_group_still_fails(self) -> None:
        self.assertEqual(self.dispatch("fail").status, "failed")
        with patch("omh.coding.hermes_child_dispatch._terminate_process_group", return_value=((), False)):
            self.assertEqual(self.dispatch().status, "failed")
        with patch("omh.coding.hermes_child_dispatch._await_pipe_threads", return_value=False):
            self.assertEqual(self.dispatch().status, "failed")

    def test_the_next_dispatch_sweeps_only_old_scratch_homes_that_carry_omhs_marker(self) -> None:
        day_and_more = time.time() - 2 * 86400
        old = self.tmp / "omh-hermes-child-old"
        young = self.tmp / "omh-hermes-child-young"
        unmarked = self.tmp / "omh-hermes-child-unmarked"
        foreign = self.tmp / "someone-else-old"
        for directory in (old, young, unmarked, foreign):
            (directory / "hermes").mkdir(parents=True)
        for directory in (old, young, foreign):
            (directory / ".omh-hermes-child-scratch").write_bytes(
                f"omh-hermes-child-scratch/v1\n{int(day_and_more) + 900}\n".encode("ascii"))
        for directory in (old, unmarked, foreign):
            os.utime(directory / ".omh-hermes-child-scratch" if directory != unmarked else directory,
                     (day_and_more, day_and_more))
        result = self.dispatch()
        self.assertEqual(result.status, "completed")
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())
        self.assertTrue(unmarked.exists())
        self.assertTrue(foreign.exists())


    def test_the_fanout_record_carries_the_note_beside_a_completed_status(self) -> None:
        from omh.coding import dispatch_failure_recovery

        with patch("shutil.rmtree", side_effect=PermissionError(13, "in use")):
            result = self.dispatch()
        self.addCleanup(_REAL_RMTREE, self.scratch_root(), True)
        with patch("omh.coding.hermes_child_dispatch.dispatch_hermes_child", return_value=result):
            record = dispatch_failure_recovery.dispatch_unit_via_hermes_child(
                prompt="p", routing={"model": "fake/model", "provider": "fake-provider", "reasoning": "low"},
                parent_run_id="parent-123", run_id="child-456", cwd=self.root, timeout_seconds=5.0,
            )
        self.assertEqual(record["status"], "completed")
        self.assertIn("scratch home left at <temp>/omh-hermes-child-", record["cleanup_note"])
        self.assertNotIn(str(self.tmp), record["cleanup_note"])


if __name__ == "__main__":
    unittest.main()

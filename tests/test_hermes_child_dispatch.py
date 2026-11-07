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
import textwrap
from threading import Event, Thread
import threading
import tracemalloc
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

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


if __name__ == "__main__":
    unittest.main()

"""`omh_dag`: a dag-ulw run kept by OMH and run by the parent agent with Hermes' own `delegate_task`.

The handler is called the way Hermes calls a plugin tool: the model's
arguments, and the session id as a keyword. Children start and stop through
the delegation ledger's own observers with the payloads Hermes' hooks carry,
so the goal marker binding is exercised end to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _local_package import load_local_package
from _module_patch import patch_modules

load_local_package()

from _delegation_state import PARENT, homes, start, stop  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_contracts import FANOUT_SPAWN_PLAN_FIELDS, FANOUT_SPAWN_PLAN_THRESHOLD  # noqa: E402
from omh.coding.executors import EXTERNAL_CLI_PROFILES  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh import host_process  # noqa: E402
from omh.plugin_bundle.omh import runtime_paths  # noqa: E402
from omh.plugin_bundle.omh.delegation_ledger import dag_binding, read_ledger  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from omh.routing import owner_preference  # noqa: E402
from omh.routing.coding_route_actions import OWNER_PREFERENCE_ROUTE_FAMILY  # noqa: E402

PROMPT = "TASK: do it\nDELIVERABLE: a change\nSCOPE: only its files\nVERIFY: run `make test`, exit 0\nSTOP WHEN: green"


def node(node_id: str, *, category: str = "quick", depends_on: tuple[str, ...] = (), scope: tuple[str, ...] = (),
         label: str = "", prompt: str = PROMPT, role: str = "") -> dict:
    """A node as the parent sends it; ``role`` only when given, as a parent that names none sends none."""
    raw = {"id": node_id, "label": label or f"Node {node_id}", "category": category, "prompt": prompt,
           "depends_on": list(depends_on), "write_scope": list(scope)}
    if role:
        raw["role"] = role
    return raw


FEATURE = [
    node("api", scope=("src/api.py",)),
    node("ui", category="unspecified-low", scope=("src/ui.py",)),
    node("docs", category="writing", depends_on=("api",), scope=("docs/api.md",)),
    node("verify", category="unspecified-high", depends_on=("api", "ui", "docs"), label="Verify the feature",
         role="verify"),
]


def call(**arguments: object) -> dict:
    return json.loads(dag_tool.omh_dag_handler(arguments, session_id=PARENT))


def handoff(home, run: str, node_id: str, text: str = "done") -> Path:
    path = dag_run.handoff_path(home.omh, PARENT, run, node_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def child_started(home, run: str, node_id: str, *, now: float | None = None) -> None:
    start(home, f"child-{node_id}", f"sa-{node_id}", f"Node {node_id} [dag:{run}/{node_id}]",
          now=time.time() if now is None else now)


def slots_table(home, *, running: list[tuple[str, int]] = ()) -> None:
    """Hermes' `async_delegations` rows with the owner pid the pool belongs to."""
    home.execute("DROP TABLE async_delegations")
    home.execute("CREATE TABLE async_delegations (delegation_id TEXT PRIMARY KEY, parent_session_id TEXT, "
                 "state TEXT, dispatched_at REAL, task_json TEXT, owner_pid INTEGER)")
    for delegation_id, pid in running:
        home.execute("INSERT INTO async_delegations VALUES (?, ?, 'running', 0, '{}', ?)",
                     (delegation_id, PARENT, pid))


# The fake Docker or SSH terminal (`Sandbox`) runs a real bash over POSIX paths.
SANDBOX_SHELL = sys.platform != "win32" and shutil.which("bash") is not None
SANDBOX_SKIP = "the fake Docker or SSH terminal runs bash over POSIX paths: needs a POSIX host with bash"


class Base:
    """Hermes' `BaseEnvironment` as `omh_dag` imports it: its `execute` runs ``run`` and records the call.

    A subclass's own `execute` stands for `DockerEnvironment.execute`, whose
    recovery restarts or recreates a container that went away; it counts
    every time it is entered, and `omh_dag` must never enter it.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.recovered = 0

    def execute(self, command: str, cwd: str = "", *, timeout: object = None) -> object:
        self.calls.append((command, cwd, timeout))
        return self.run(command)

    def run(self, command: str) -> object:
        raise NotImplementedError


class Terminal:
    """Hermes' terminal modules as `omh_dag` imports them at call time.

    `tools.terminal_tool._get_env_config` names the backend (or raises it);
    `tools.terminal_tool_lifecycle.get_active_env` returns ``environment`` for
    every task id it is asked about, as Hermes resolves a delegated child's to
    its parent's (or raises it). Without ``lifecycle`` that module cannot be
    imported. `tools.environments.base.BaseEnvironment` is `Base`.
    """

    def __init__(self, backend: object, environment: object = None, *, lifecycle: bool = True) -> None:
        self.backend, self.environment, self.lifecycle = backend, environment, lifecycle
        self.asked: list[str] = []

    def modules(self) -> patch_modules:
        terminal = SimpleNamespace(_get_env_config=self._config)
        lifecycle = SimpleNamespace(get_active_env=self._active) if self.lifecycle else None
        base = SimpleNamespace(BaseEnvironment=Base)
        environments = SimpleNamespace(base=base)
        return patch_modules({"tools": SimpleNamespace(terminal_tool=terminal, environments=environments),
                              "tools.terminal_tool": terminal, "tools.terminal_tool_lifecycle": lifecycle,
                              "tools.environments": environments, "tools.environments.base": base})

    def _config(self) -> dict:
        if isinstance(self.backend, Exception):
            raise self.backend
        return {"env_type": self.backend}

    def _active(self, task_id: str) -> object:
        self.asked.append(task_id)
        if isinstance(self.environment, Exception):
            raise self.environment
        return self.environment


class Sandbox(Base):
    """A Docker or SSH terminal's filesystem: each file at its own absolute path, kept under ``root`` here.

    The command runs in `bash`, as Hermes runs it, after ``prelude`` (what the
    login shell's snapshot carries, such as a function or an alias): the
    handoff path it names is moved under ``root``, and ``$HOME`` is ``home``
    (made with ``mode``, or as a link to ``target`` made so), moved likewise
    and read back as the backend sees it, so a real shell judges both.
    """

    def __init__(self, root: Path, home: str = "/sandbox-home/dev", mode: int = 0o700, target: str = "",
                 prelude: str = "") -> None:
        super().__init__()
        self.root, self.home, self.prelude = root, home, prelude
        made = self.path(Path(target or home))
        made.mkdir(parents=True)
        made.chmod(mode)
        if target:
            self.path(Path(home)).parent.mkdir(parents=True)
            self.path(Path(home)).symlink_to(made)

    def path(self, host: Path) -> Path:
        return self.root / os.path.realpath(host).lstrip("/")

    def execute(self, command: str, cwd: str = "", *, timeout: object = None) -> object:
        self.recovered += 1
        return super().execute(command, cwd, timeout=timeout)

    def run(self, command: str) -> dict:
        tokens = shlex.split(command)
        if "-L" in tokens:
            named = tokens[tokens.index("-L") + 1]
            command = command.replace(shlex.quote(named), shlex.quote(str(self.path(Path(named)))))
        done = subprocess.run(["bash", "-c", self.prelude + command], capture_output=True, text=True, timeout=30,
                              check=False, env={**os.environ, "HOME": str(self.path(Path(self.home)))})
        output = (done.stdout + done.stderr).replace(os.path.realpath(self.root), "").replace(str(self.root), "")
        return {"output": output, "returncode": done.returncode}


class Answers(Base):
    """An environment that answers every command with ``answer``, or raises it."""

    def __init__(self, answer: object) -> None:
        super().__init__()
        self.answer = answer

    def execute(self, command: str, cwd: str = "", *, timeout: object = None) -> object:
        self.recovered += 1
        return super().execute(command, cwd, timeout=timeout)

    def run(self, command: str) -> object:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@contextmanager
def detector_module(source: str | None) -> Iterator[None]:
    """Import a real optional host package, restoring modules and path afterwards."""
    with TemporaryDirectory() as tmp, patch_modules({}):
        package = Path(tmp) / "agent"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        if source is not None:
            (package / "oneshot_footprint.py").write_text(source, encoding="utf-8")
        for name in list(sys.modules):
            if name == "agent" or name.startswith("agent."):
                del sys.modules[name]
        with patch.object(sys, "path", [tmp, *sys.path]):
            yield


@contextmanager
def terminal_env(value: str | None = None) -> Iterator[None]:
    """``TERMINAL_ENV`` as given, or unset: the variable `terminal_backend` falls back to."""
    with patch.dict(os.environ):
        os.environ.pop("TERMINAL_ENV", None)
        if value is not None:
            os.environ["TERMINAL_ENV"] = value
        yield


class DefineTests(unittest.TestCase):
    def test_saved_run_goal_reaches_every_native_builder_without_changing_its_assignment(self) -> None:
        goal = "Adapt the renderer: preserve motion, typography and audio; package tests alone are not parity."
        with homes() as home:
            slots_table(home)
            defined = call(action="define", run="feat", goal=goal, nodes=FEATURE)
            for call_row in defined["calls"]:
                for node_id, task in zip(call_row["nodes"], call_row["tasks"]):
                    with self.subTest(node=node_id):
                        self.assertIn(f"Run goal (saved):\n{goal}\n", task["context"])
                        self.assertTrue(task["context"].startswith(PROMPT + "\n"))
                        self.assertEqual(task["goal"], f"Node {node_id} [dag:feat/{node_id}]")
                        self.assertIn("The run goal is acceptance context, not permission to widen your SCOPE.",
                                      task["context"])
            handoff(home, "feat", "api")
            later = call(action="settle", run="feat", node="api", outcome="accepted")
            self.assertIn(f"Run goal (saved):\n{goal}\n", later["calls"][0]["tasks"][0]["context"])
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            self.assertEqual(stored["goal"], goal)
            self.assertEqual(stored["nodes"][0]["prompt"], PROMPT)

    def test_define_records_topology_and_hands_out_the_first_layer(self) -> None:
        with homes() as home:
            slots_table(home)
            result = call(action="define", run="feat", name="export feature", goal="export works", nodes=FEATURE)
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["topology"]["layers"], [["api", "ui"], ["docs"], ["verify"]])
        self.assertEqual(result["topology"]["critical_path"], ["api", "docs", "verify"])
        self.assertEqual(result["topology"]["bottlenecks"][0], {"node": "api", "blocks": 2})
        # api and ui write code and no node reviews them: advice, never a refusal.
        self.assertEqual(result["lint"], ["no_review_node"])
        self.assertEqual([(c["category"], c["nodes"], c["route"]["action"]) for c in result["calls"]],
                         [("quick", ["api"], "set"), ("unspecified-low", ["ui"], "set")])
        task = result["calls"][0]["tasks"][0]
        # The marker ends the goal, on its line: Hermes previews a goal by its first 40 characters.
        self.assertEqual(task["goal"], "Node api [dag:feat/api]")
        self.assertIn("Handoff: before you stop, write your report to", task["context"])
        self.assertEqual(dag_binding(task["goal"]), {"run": "feat", "node": "api"})

    def test_hard_rejects(self) -> None:
        cases = {
            "dependency_cycle": [node("a", depends_on=("b",)), node("b", depends_on=("a",))],
            "unknown_dependency": [node("a", depends_on=("ghost",))],
            "self_dependency": [node("a", depends_on=("a",))],
            "write_scope_overlap": [node("a", scope=("x.py",)), node("b", scope=("x.py",))],
            "too_many_nodes": [node(f"n{index}") for index in range(dag_run.MAX_NODES + 1)],
            "empty_graph": [],
            "duplicate_node_id": [node("a"), node("a")],
            "invalid_category": [node("a", category="fastest")],
            "invalid_label": [node("a", label="Fix [dag:feat/b] first")],
        }
        for reason, nodes in cases.items():
            with self.subTest(reason=reason), homes():
                result = call(action="define", run="feat", nodes=nodes)
                self.assertEqual((result["status"], result["reason"]), ("refused", reason), result)

    def test_a_label_holding_either_lanes_marker_is_refused(self) -> None:
        """Mutation: refuse only `[dag:`; a leading team key would bind this node's child to a team part."""
        for label in ("[omh-team:t1/a/attempt-1] Fix the parser", "Fix the parser [dag:feat/b]"):
            with self.subTest(label=label), homes():
                result = call(action="define", run="feat", nodes=[node("a", label=label)])
                self.assertEqual((result["status"], result["reason"]), ("refused", "invalid_label"), result)

    def test_an_edge_lets_two_nodes_share_a_write_scope(self) -> None:
        with homes():
            result = call(action="define", run="feat",
                          nodes=[node("a", scope=("x.py",)), node("b", scope=("x.py",), depends_on=("a",))])
        self.assertEqual(result["status"], "ok", result)

    def test_lint_is_advice_and_never_rejects(self) -> None:
        # A partial marker set is lint; a prompt with no marker at all is refused (see DefineTests.preflight).
        nodes = [node("a", category="deep", prompt="TASK: do the thing."), node("b", category="deep-work", scope=("b.py",)),
                 node("c", category="ultrabrain"), node("d", category="ultrabrain")]
        with homes():
            result = call(action="define", run="feat", nodes=nodes)
        self.assertEqual(result["status"], "ok", result)
        self.assertIn("missing_markers:a:DELIVERABLE,SCOPE,VERIFY,STOP_WHEN", result["lint"])
        self.assertIn("no_verification_node", result["lint"])
        self.assertIn("ultrabrain_more_than_once", result["lint"])
        with homes():
            deep = call(action="define", run="deep", nodes=[node("a", category="deep"), node("b", category="deep-work")])
        self.assertIn("all_nodes_deep", deep["lint"])
        with homes():
            miss = call(action="define", run="miss", nodes=[node("a", scope=("a.py",)), node("verify", role="verify")])
        self.assertIn("verification_misses:a", miss["lint"])

    def test_the_same_definition_is_reused_and_a_different_one_refused(self) -> None:
        with homes():
            call(action="define", run="feat", nodes=FEATURE)
            again = call(action="define", run="feat", nodes=FEATURE)
            other = call(action="define", run="feat", nodes=[node("solo")])
        self.assertTrue(again.get("reused"), again)
        self.assertEqual(other["reason"], "run_exists")

    def test_a_delegated_child_cannot_keep_a_run(self) -> None:
        with homes(), patch.object(dag_tool._nudge_budget, "session_is_delegated", return_value=True):
            result = call(action="define", run="feat", nodes=FEATURE)
        self.assertEqual(result["reason"], "called_from_child")

    def test_no_session_no_run(self) -> None:
        with homes():
            result = json.loads(dag_tool.omh_dag_handler({"action": "status"}, session_id=""))
        self.assertEqual(result["reason"], "session_required")


class SlotTests(unittest.TestCase):
    def test_ready_never_hands_out_more_calls_than_free_slots(self) -> None:
        with homes() as home:
            # Cap 3 with two units of one call and one other call running in this process: one slot left.
            home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 3\n")
            slots_table(home, running=[("deleg_a-1", os.getpid()), ("deleg_a-2", os.getpid()),
                                       ("deleg_b", os.getpid()), ("deleg_other", os.getpid() + 1)])
            result = call(action="define", run="feat", nodes=FEATURE)
        self.assertEqual(result["slots"], {"basis": "state_db", "cap": 3, "free": 1, "independent_completions": False,
                                           "running_calls": 2})
        self.assertEqual([c["nodes"] for c in result["calls"]], [["api"]])
        self.assertEqual(result["held_for_slots"], ["ui"])

    def test_an_unreadable_state_db_admits_one_call(self) -> None:
        with homes():
            result = call(action="define", run="feat", nodes=FEATURE)
        self.assertEqual(result["slots"]["basis"], "unread")
        self.assertEqual(len(result["calls"]), 1)

    def test_a_category_larger_than_the_cap_splits_into_calls(self) -> None:
        nodes = [node(f"n{index}", scope=(f"f{index}",)) for index in range(3)] + [
            node("verify", role="verify", depends_on=("n0", "n1", "n2"))]
        with homes() as home:
            home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 2\n")
            slots_table(home)
            result = call(action="define", run="feat", nodes=nodes)
        self.assertEqual([c["nodes"] for c in result["calls"]], [["n0", "n1"], ["n2"]])

    def test_the_cap_reads_config_then_environment_then_hermes_default(self) -> None:
        self.assertEqual(dag_tool._cap("4"), 4)
        with patch.dict(os.environ, {dag_tool.MAX_CONCURRENT_ENV: "6"}):
            self.assertEqual(dag_tool._cap(""), 6)
            self.assertEqual(dag_tool._cap("x"), 6)
        with patch.dict(os.environ, {dag_tool.MAX_CONCURRENT_ENV: ""}):
            self.assertEqual(dag_tool._cap(None), dag_tool.DEFAULT_MAX_CONCURRENT_CHILDREN)


class SettleTests(unittest.TestCase):
    def _run(self, home) -> None:
        slots_table(home)
        home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 10\n")
        call(action="define", run="feat", nodes=FEATURE)

    def test_accepted_needs_the_handoff_and_returns_what_is_ready_next(self) -> None:
        with homes() as home:
            self._run(home)
            child_started(home, "feat", "api")
            missing = call(action="settle", run="feat", node="api", outcome="accepted")
            handoff(home, "feat", "api")
            stop(home, "child-api", now=time.time())
            accepted = call(action="settle", run="feat", node="api", outcome="accepted")
        self.assertEqual(missing["reason"], "handoff_missing")
        self.assertEqual([c["nodes"] for c in accepted["calls"]], [["docs"]])
        self.assertEqual(accepted["counts"]["done"], 1)
        # Two nodes are out (ui, and docs just now) but no child of theirs runs yet: the line counts running children.
        self.assertEqual((accepted["counts"]["out"], accepted["counts"]["running"]), (2, 0))
        self.assertEqual(accepted["status_line"], "DAG feat · 1/4 done · 0 running")

    def test_a_child_hermes_reported_failed_is_never_accepted(self) -> None:
        with homes() as home:
            self._run(home)
            child_started(home, "feat", "api")
            handoff(home, "feat", "api")
            stop(home, "child-api", "failed", now=time.time())
            refused = call(action="settle", run="feat", node="api", outcome="accepted")
            blocked = call(action="settle", run="feat", node="api", outcome="blocked", reason="needs a key")
        self.assertEqual(refused["reason"], "child_reported_failure")
        self.assertEqual(blocked["status"], "ok")
        rows = {row["id"]: row for row in blocked["nodes"]}
        self.assertEqual(rows["api"]["state"], "blocked")
        self.assertEqual(rows["api"]["reason"], "needs a key")

    def test_a_failed_node_blocks_only_its_dependents(self) -> None:
        with homes() as home:
            self._run(home)
            result = call(action="settle", run="feat", node="api", outcome="failed", reason="tests red")
        rows = {row["id"]: row["state"] for row in result["nodes"]}
        self.assertEqual(rows, {"api": "failed", "ui": "handed_out", "docs": "held", "verify": "held"})
        self.assertEqual(result["calls"], [])

    def test_a_provider_error_gets_one_retry_on_the_fallback_route(self) -> None:
        with homes() as home:
            self._run(home)
            first = call(action="settle", run="feat", node="api", outcome="failed", provider_error=True)
            second = call(action="settle", run="feat", node="api", outcome="failed", provider_error=True)
        self.assertEqual(first["settled"], {"node": "api", "outcome": "retry"})
        self.assertEqual([(c["nodes"], c["route"]["action"]) for c in first["calls"]], [(["api"], "fallback")])
        self.assertEqual(second["settled"], {"node": "api", "outcome": "failed"})

    def test_a_node_not_out_is_not_settled(self) -> None:
        with homes() as home:
            self._run(home)
            result = call(action="settle", run="feat", node="docs", outcome="accepted")
        self.assertEqual(result["reason"], "node_not_out")


class WorktreeIsolationTests(unittest.TestCase):
    """Hermes' `delegation.worktree_isolation` gives each child a worktree of its own from the parent's HEAD.

    A dependent or the verify node would then start without the earlier nodes' edits, so a run is never defined
    with it on, and a run defined before it was turned on hands out no call while it is on.
    """

    def _config(self, home, text: bytes | str) -> None:
        path = home.hermes / "config.yaml"
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")

    def test_define_is_refused_while_isolation_is_on_and_keeps_no_record(self) -> None:
        for value in ("true", "True", "yes", "ON", "1", "'true'", "true  # one tree per child"):
            with self.subTest(value=value), homes() as home:
                slots_table(home)
                self._config(home, f"delegation:\n  max_concurrent_children: 3\n  worktree_isolation: {value}\n")
                result = call(action="define", run="feat", nodes=FEATURE)
                self.assertEqual((result["status"], result["reason"]), ("refused", "worktree_isolation_on"), result)
                self.assertEqual(result["say"], dag_tool.WORKTREE_ISOLATION_REFUSED)
                self.assertIn("delegation.worktree_isolation", result["say"])
                self.assertIsNone(dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat")))

    def test_isolation_off_or_absent_defines_as_before(self) -> None:
        configs: dict[str, bytes | str | None] = {
            "absent": None,
            "false": "delegation:\n  worktree_isolation: false\n",
            "off": "delegation:\n  worktree_isolation: off\n",
            "zero": "delegation:\n  worktree_isolation: 0\n",
            "other_section": "terminal:\n  worktree_isolation: true\n",
            "not_one_line": "delegation:\n  worktree_isolation:\n    - true\n",
        }
        expected = None
        for name, text in configs.items():
            with self.subTest(config=name), homes() as home:
                slots_table(home)
                if text is not None:
                    self._config(home, text)
                result = call(action="define", run="feat", nodes=FEATURE)
                self.assertEqual(result["status"], "ok", result)
                self.assertNotIn("worktree_isolation", result.get("say", ""))
                shape = ([c["nodes"] for c in result["calls"]], result.get("say", ""), result["state"])
                expected = expected or shape
                self.assertEqual(shape, expected)

    def test_an_unreadable_config_counts_as_off_and_define_answers_as_before(self) -> None:
        """Fail-open only on a read failure: the guard says off, and define answers as it did without the guard."""
        for name in ("not_utf8", "directory"):
            answers = []
            for guarded in (True, False):
                with self.subTest(config=name, guarded=guarded), homes() as home:
                    slots_table(home)
                    if name == "directory":
                        (home.hermes / "config.yaml").mkdir()
                    else:
                        self._config(home, b"delegation:\n  worktree_isolation: true\n  note: \xff\xfe\n")
                    self.assertFalse(dag_tool.worktree_isolation_on(home.hermes))
                    with nullcontext() if guarded else patch.object(dag_tool, "worktree_isolation_on",
                                                                    return_value=False):
                        answers.append(call(action="define", run="feat", nodes=FEATURE))
            self.assertEqual(answers[0], answers[1])
            self.assertNotEqual(answers[0].get("reason"), "worktree_isolation_on")

    def test_a_run_defined_before_isolation_hands_out_nothing_while_it_is_on(self) -> None:
        with homes() as home:
            slots_table(home)
            self._config(home, "delegation:\n  max_concurrent_children: 10\n")
            call(action="define", run="feat", nodes=FEATURE)
            child_started(home, "feat", "api")
            handoff(home, "feat", "api")
            stop(home, "child-api", now=time.time())
            self._config(home, "delegation:\n  max_concurrent_children: 10\n  worktree_isolation: true\n")
            settled = call(action="settle", run="feat", node="api", outcome="accepted")
            ready = call(action="ready", run="feat")
            self._config(home, "delegation:\n  max_concurrent_children: 10\n  worktree_isolation: false\n")
            after = call(action="ready", run="feat")
        # The outcome is still recorded; only the next node does not go out.
        self.assertEqual(settled["settled"], {"node": "api", "outcome": "accepted"})
        self.assertEqual(settled["counts"]["done"], 1)
        self.assertEqual(settled["calls"], [])
        self.assertTrue(settled["say"].endswith(dag_tool.WORKTREE_ISOLATION_HELD), settled["say"])
        self.assertNotIn("held_for_slots", settled)
        self.assertEqual(ready["calls"], [])
        self.assertIn(dag_tool.WORKTREE_ISOLATION_HELD, ready["say"])
        self.assertEqual([c["nodes"] for c in after["calls"]], [["docs"]])
        self.assertNotIn("worktree_isolation", after.get("say", ""))

    def test_the_setting_is_read_without_writing_the_config(self) -> None:
        text = "delegation:\n  worktree_isolation: yes\n"
        with homes() as home:
            self._config(home, text)
            before = (home.hermes / "config.yaml").stat()
            self.assertTrue(dag_tool.worktree_isolation_on(home.hermes))
            call(action="define", run="feat", nodes=FEATURE)
            after = (home.hermes / "config.yaml").stat()
            self.assertEqual((home.hermes / "config.yaml").read_text(encoding="utf-8"), text)
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))


FILE_ANSWER = {"output": "OMH_HANDOFF_FILE\n", "returncode": 0}
# A terminal whose home does not qualify: the run keeps this host's handoff path, as before the backend was read.
HOME_UNUSABLE = {"output": "OMH_BACKEND_HOME_UNUSABLE\n", "returncode": 0}
INTERRUPTED = {"output": "[Command interrupted]", "returncode": 130, "hermes_interrupted": True}


class RemoteBackendTests(unittest.TestCase):
    """On a Docker or SSH terminal a child's `write_file` lands in that backend, so `settle` reads its handoff there.

    Hermes' modules are the ones `omh_dag` imports at call time (`Terminal`),
    and the backend is a directory a real `sh` reads (`Sandbox`).
    """

    def _returned(self, home) -> None:
        """The run defined under whatever terminal is patched, and node api's child (`sa-api`) back."""
        slots_table(home)
        call(action="define", run="feat", nodes=FEATURE)
        child_started(home, "feat", "api")
        stop(home, "child-api", now=time.time())

    def _settle(self) -> dict:
        return call(action="settle", run="feat", node="api", outcome="accepted")

    def test_define_records_a_docker_or_ssh_backend_and_nothing_else(self) -> None:
        """Mutation: record every backend, skip `TERMINAL_ENV`, or let the variable beat Hermes' own resolver."""
        cases = [
            ("docker", None, "docker"), ("ssh", None, "ssh"), (" SSH ", None, "ssh"),
            ("local", "docker", None),  # Hermes' resolver, which reads the profile, wins over the variable
            ("modal", None, None), ("", None, None),
            (None, None, None),  # not Hermes, and the variable unset
            (None, "ssh", "ssh"), (None, "local", None),
            (ValueError("TERMINAL_DOCKER_VOLUMES is not valid JSON"), "docker", "docker"),
            (KeyError("env_type"), None, None),
        ]
        for backend, variable, recorded in cases:
            with self.subTest(backend=backend, variable=variable), homes() as home, terminal_env(variable), (
                    Terminal(backend).modules() if backend is not None else nullcontext()):
                call(action="define", run="feat", nodes=FEATURE)
                record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
                self.assertEqual(record.get("backend"), recorded, record)
                self.assertEqual("backend" in record, recorded is not None)

    @unittest.skipUnless(SANDBOX_SHELL, SANDBOX_SKIP)
    def test_a_handoff_inside_the_terminal_is_read_there_under_the_host_checks_rule(self) -> None:
        """Mutation: follow a link, take a directory, read the host, ask with the parent's task id, or hand out ~."""
        with homes() as home, terminal_env():
            self._returned(home)
            host_refusal = self._settle()  # the same run on a local terminal: the file missing on the host
        self.assertEqual(host_refusal["reason"], "handoff_missing")
        for backend in dag_tool.REMOTE_BACKENDS:
            with self.subTest(backend=backend), homes() as home, terminal_env(), TemporaryDirectory() as root:
                sandbox = Sandbox(Path(root))
                terminal = Terminal(backend, sandbox)
                with terminal.modules():
                    slots_table(home)
                    defined = call(action="define", run="feat", nodes=FEATURE)
                    child_started(home, "feat", "api")
                    stop(home, "child-api", now=time.time())
                    record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
                    told = dag_run.node_handoff(record, home.omh, "api")
                    inside = sandbox.path(Path(told))
                    missing = self._settle()
                    inside.mkdir(parents=True)
                    directory = self._settle()
                    inside.rmdir()
                    inside.with_name("elsewhere.md").write_text("done", encoding="utf-8")
                    inside.symlink_to(inside.with_name("elsewhere.md"))
                    link = self._settle()
                    inside.unlink()
                    inside.write_text("done", encoding="utf-8")
                    accepted = self._settle()
                    on_host = dag_run.handoff_path(home.omh, PARENT, "feat", "api").exists()
                # The root is the terminal user's own home, pinned on the run, and each child is told a path under it.
                self.assertEqual(record["handoff_root"], "/sandbox-home/dev/.omh/dag")
                self.assertTrue(told.startswith("/sandbox-home/dev/.omh/dag/"), told)
                self.assertIn(f"write your report to {told}:", defined["calls"][0]["tasks"][0]["context"])
                self.assertEqual([missing, directory, link], [host_refusal] * 3)
                self.assertEqual(accepted["status"], "ok", accepted)
                self.assertEqual(accepted["settled"], {"node": "api", "outcome": "accepted"})
                row = next(item for item in accepted["nodes"] if item["id"] == "api")
                self.assertEqual(row["state"], "accepted")
                self.assertNotIn("handoff_checked", row)
                self.assertNotIn("say", accepted)
                self.assertFalse(on_host)  # read only inside the terminal
                # The home once through the parent's task id; then each read with the child's own task id, which
                # Hermes resolves to the environment it wrote in: one bounded command each, with no cwd (the shared
                # shell stays where it was), and never through the backend's own `execute`, which on Docker
                # restarts or recreates a container that went away.
                self.assertEqual(terminal.asked, ["default"] + ["sa-api"] * 4)
                self.assertEqual({(cwd, timeout) for _command, cwd, timeout in sandbox.calls},
                                 {("", dag_tool.BACKEND_READ_SECONDS)})
                self.assertEqual((len(sandbox.calls), sandbox.recovered), (5, 0))

    @unittest.skipUnless(SANDBOX_SHELL, SANDBOX_SKIP)
    def test_a_home_another_user_can_write_keeps_this_hosts_path(self) -> None:
        """Mutation: take any home, judge a linked home by the link, or let a `$HOME` with a space through."""
        cases = {"0777": {"mode": 0o777}, "0770": {"mode": 0o770}, "1777": {"mode": 0o1777},
                 "link to 1777": {"mode": 0o1777, "target": "/shared/scratch"},
                 "trailing space": {"home": "/sandbox-home/dev "},
                 # The login shell's snapshot can override `find`; a find that prints nothing must not pass a home.
                 "0775, find a function": {"mode": 0o775, "prelude": "find() { :; }\n"},
                 "0775, find an alias": {"mode": 0o775, "prelude": "shopt -s expand_aliases\nalias find=true\n"}}
        for name, made in cases.items():
            with self.subTest(home=name), homes() as home, terminal_env(), TemporaryDirectory() as root:
                sandbox = Sandbox(Path(root), **made)
                with Terminal("ssh", sandbox).modules():
                    self._returned(home)
                    record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
                    host = dag_run.handoff_path(home.omh, PARENT, "feat", "api")
                    sandbox.path(host).parent.mkdir(parents=True)
                    sandbox.path(host).write_text("done", encoding="utf-8")  # written in the terminal, at the host path
                    accepted = self._settle()
            self.assertEqual(record["handoff_root"], "")
            self.assertEqual(dag_run.node_handoff(record, home.omh, "api"), str(host))
            self.assertEqual(accepted["settled"], {"node": "api", "outcome": "accepted"})
        # The same overrides leave a home only its user can write qualifying: the check runs the real `find`.
        for prelude in ("find() { :; }\n", "shopt -s expand_aliases\nalias find=true\n"):
            with self.subTest(prelude=prelude), homes() as home, terminal_env(), TemporaryDirectory() as root, \
                    Terminal("ssh", Sandbox(Path(root), prelude=prelude)).modules():
                call(action="define", run="feat", nodes=FEATURE)
                pinned = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))["handoff_root"]
            self.assertEqual(pinned, "/sandbox-home/dev/.omh/dag")
        # A home that is a link to a directory only its user can write is pinned as that directory.
        with homes() as home, terminal_env(), TemporaryDirectory() as root, Terminal(
                "docker", Sandbox(Path(root), target="/data/users/dev")).modules():
            call(action="define", run="feat", nodes=FEATURE)
            pinned = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))["handoff_root"]
        self.assertEqual(pinned, "/data/users/dev/.omh/dag")

    def test_a_home_that_does_not_qualify_keeps_this_hosts_path(self) -> None:
        """Mutation: take a home in a shared temp directory, at a relative path, with odd characters, or `/`."""
        for line in ("OMH_BACKEND_HOME=/", "OMH_BACKEND_HOME=/tmp/dev", "OMH_BACKEND_HOME=/var/tmp",
                     "OMH_BACKEND_HOME=/home/a b", "OMH_BACKEND_HOME=/home/../etc", "OMH_BACKEND_HOME=home/dev",
                     "OMH_BACKEND_HOME=/home/dev/", "OMH_BACKEND_HOME=/home/$(id)", "OMH_BACKEND_HOME_UNUSABLE",
                     "OMH_BACKEND_HOME=", "OMH_BACKEND_HOME=/home/dev ", " OMH_BACKEND_HOME=/home/dev",
                     # Two home lines (a $HOME with a newline in it): neither is taken.
                     "OMH_BACKEND_HOME=/home/dev\nOMH_BACKEND_HOME=/home/other"):
            with self.subTest(line=line), homes() as home, terminal_env(), Terminal(
                    "docker", Answers({"output": line + "\n", "returncode": 0})).modules():
                defined = call(action="define", run="feat", nodes=FEATURE)
                record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
                # This host's path as the tool builds it: from the OMH home it resolves (on Windows, the long name).
                host = dag_run.handoff_path(runtime_paths.default_omh_home(), PARENT, "feat", "api")
            self.assertEqual(record["handoff_root"], "")
            self.assertIn(f"write your report to {host}:", defined["calls"][0]["tasks"][0]["context"])
        with homes() as home, terminal_env(), Terminal(
                "docker", Answers({"output": "\x1b]0;t\x07OMH_BACKEND_HOME=/home/dev.ops@corp\n", "returncode": 0})
        ).modules():
            call(action="define", run="feat", nodes=FEATURE)
            pinned = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))["handoff_root"]
        self.assertEqual(pinned, "/home/dev.ops@corp/.omh/dag")

    def test_with_no_terminal_up_nothing_goes_out_until_one_is(self) -> None:
        """Mutation: hand out the host path, start an environment, or say it again once the root is pinned.

        The instruction comes with every result that holds the calls for it,
        the same short text each time, and never once the root is pinned, even
        after the environment went away again.
        """
        answers = Answers({"output": "OMH_BACKEND_HOME=/home/dev\n", "returncode": 0})
        terminal = Terminal("ssh", None)
        instruction = dag_tool.TERMINAL_FIRST.format(backend="ssh")
        retry = dag_tool.TERMINAL_INTERRUPTED.format(backend="ssh")
        with homes() as home, terminal_env(), terminal.modules():
            slots_table(home)
            results = [call(action="define", run="feat", nodes=FEATURE)]
            results.append(call(action="ready", run="feat"))
            results.append(call(action="status", run="feat"))
            terminal.environment = Answers(INTERRUPTED)  # a read the parent's interrupt stopped
            results.append(call(action="ready", run="feat"))
            held_record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            terminal.environment = answers
            results.append(call(action="ready", run="feat"))
            terminal.environment = None  # reaped again: the pinned root stays
            results.append(call(action="ready", run="feat"))
            child_started(home, "feat", "api")
            stop(home, "child-api", now=time.time())
            results.append(self._settle())
            record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
        define, ready, status, interrupted, resolved, later, settled = results
        for held in (define, ready):
            self.assertEqual((held["status"], held["calls"], held["say"]), ("ok", [], instruction))
        self.assertIn("In this same turn", instruction)
        # An interrupted read says so, not that no terminal is up.
        self.assertEqual((interrupted["calls"], interrupted["say"]), ([], retry))
        self.assertNotIn("say", status)
        self.assertNotIn("handoff_root", held_record)
        self.assertEqual([c["nodes"] for c in resolved["calls"]], [["api"], ["ui"]])
        self.assertIn("/home/dev/.omh/dag/", resolved["calls"][0]["tasks"][0]["context"])
        self.assertEqual(record["handoff_root"], "/home/dev/.omh/dag")
        self.assertEqual(sum(instruction in str(result.get("say", "")) for result in results), 2)
        self.assertEqual(later["calls"], [])
        # The pinned root no longer answers: the node is accepted with its handoff not checked, never refused.
        self.assertEqual(settled["settled"], {"node": "api", "outcome": "accepted"})
        row = next(item for item in settled["nodes"] if item["id"] == "api")
        self.assertEqual((row["handoff_checked"], row["handoff_unread"]), (False, "environment_gone"))
        self.assertEqual(terminal.asked, ["default"] * 4 + ["sa-api"])

    def test_an_unreadable_terminal_accepts_the_node_with_its_handoff_not_checked(self) -> None:
        """Mutation: refuse instead, treat a shell that printed no verdict as a missing file, or drop the reason."""
        cases = {
            "environment_gone": ("docker", None, True),
            "no_read_path": ("ssh", Answers(FILE_ANSWER), False),
            "no_read_path ": ("docker", RuntimeError("environment registry moved"), True),
            "backend_unanswered": ("ssh", Answers(ConnectionError("ssh: connect to host port 22")), True),
            "backend_unanswered ": ("docker", Answers({"output": "[Command timed out after 10s]", "returncode": 124}),
                                    True),
            "backend_unanswered  ": ("docker", Answers(None), True),
            # A gone container: the base `execute` gets Docker's error back, prints no verdict, and recovers nothing.
            "backend_unanswered   ": ("docker", Answers({"output": "Error response from daemon: No such container: 4f2a",
                                                         "returncode": 1}), True),
            # A line that only quotes a verdict is none.
            "backend_unanswered    ": ("ssh", Answers({"output": "echo OMH_HANDOFF_NONE; fi\n", "returncode": 0}), True),
            # An environment that is no `BaseEnvironment` (a backend Hermes adds later) is not read.
            "no_read_path  ": ("docker", SimpleNamespace(execute=lambda *args, **kwargs: FILE_ANSWER), True),
        }
        for reason, (backend, environment, lifecycle) in cases.items():
            # Defined while the terminal answers with a home that does not qualify: this host's path, read there first.
            terminal = Terminal(backend, Answers(HOME_UNUSABLE), lifecycle=lifecycle)
            with self.subTest(reason=reason), homes() as home, terminal_env(), terminal.modules():
                self._returned(home)
                terminal.environment = environment
                settled = self._settle()
                status = call(action="status", run="feat")
                attempt = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))["nodes"][0]["attempts"][-1]
            self.assertEqual(settled["status"], "ok", settled)
            self.assertEqual(settled["settled"], {"node": "api", "outcome": "accepted"})
            self.assertIn("its handoff was not checked", settled["say"])
            self.assertIn(f"({reason.strip()})", settled["say"])
            for result in (settled, status):
                row = next(item for item in result["nodes"] if item["id"] == "api")
                self.assertEqual((row["state"], row["handoff_checked"], row["handoff_unread"]),
                                 ("accepted", False, reason.strip()))
            self.assertEqual((attempt["handoff_checked"], attempt["handoff_unread"]), (False, reason.strip()))
            # Accepted counts: the node after it is handed out, and the run's status line counts the node too.
            self.assertEqual([c["nodes"] for c in settled["calls"]], [["docs"]])
            self.assertEqual(settled["status_line"], "DAG feat · 1/4 done · 0 running · 1 handoff not checked")
            if isinstance(environment, Base):
                self.assertEqual(environment.recovered, 0)

    def test_an_interrupted_read_settles_nothing(self) -> None:
        """Mutation: take an interrupted read for no answer, so the parent's stop becomes an unchecked accept."""
        terminal = Terminal("docker", Answers(HOME_UNUSABLE))
        with homes() as home, terminal_env(), terminal.modules():
            self._returned(home)
            before = dag_run.record_path(home.omh, PARENT, "feat").read_bytes()
            terminal.environment = Answers(INTERRUPTED)
            interrupted = self._settle()
            after = dag_run.record_path(home.omh, PARENT, "feat").read_bytes()
            terminal.environment = Answers(FILE_ANSWER)
            again = self._settle()
        self.assertEqual((interrupted["status"], interrupted["reason"]), ("refused", "settle_interrupted"))
        self.assertEqual(after, before)
        self.assertEqual(again["settled"], {"node": "api", "outcome": "accepted"})
        self.assertNotIn("handoff_checked", next(row for row in again["nodes"] if row["id"] == "api"))

    def test_a_verdict_a_terminal_escape_is_glued_to_is_still_read(self) -> None:
        """Mutation: compare lines as printed, so an OSC or a fence leak turns a missing file into an unchecked accept."""
        leaks = ["\x1b]133;D;0\x07OMH_HANDOFF_NONE\r\n", "OMH_HANDOFF_NONE\x1b]0;title\x1b\\\n",
                 "'\x07__HERMES_FENCE_a1b2__\x07'OMH_HANDOFF_LINK\n", "\x1b[0mOMH_HANDOFF_NONE\x1b[32m\x07\n"]
        for leak in leaks:
            with self.subTest(leak=leak), homes() as home, terminal_env(), \
                    Terminal("docker", Answers({"output": leak, "returncode": 0})).modules():
                self._returned(home)
                refused = self._settle()
            self.assertEqual(refused["reason"], "handoff_missing")
        with homes() as home, terminal_env(), Terminal("ssh", Answers(
                {"output": "\x1b]133;C\x07OMH_HANDOFF_FILE\x1b]133;D;0\x07\n", "returncode": 0})).modules():
            self._returned(home)
            accepted = self._settle()
        self.assertEqual(accepted["settled"], {"node": "api", "outcome": "accepted"})
        self.assertNotIn("handoff_checked", next(row for row in accepted["nodes"] if row["id"] == "api"))

    def test_a_settle_refused_for_any_other_reason_asks_no_terminal(self) -> None:
        """Mutation: read the backend before `settle`'s own checks, or the reason after it on a remote run."""
        refusals = {}
        answers = Answers(FILE_ANSWER)
        terminal = Terminal("docker", answers)
        with homes() as home, terminal_env(), terminal.modules():
            self._returned(home)
            asked, sent = list(terminal.asked), list(answers.calls)  # the home, read once at define
            refusals["unknown_node"] = call(action="settle", run="feat", node="ghost", outcome="accepted")
            refusals["node_not_out"] = call(action="settle", run="feat", node="docs", outcome="accepted")
            refusals["invalid_reason"] = call(action="settle", run="feat", node="api", outcome="accepted",
                                              reason="x" * (dag_run.MAX_REASON_CHARS + 1))
            start(home, "child-ui", "sa-ui", "Node ui [dag:feat/ui]", now=time.time())
            stop(home, "child-ui", "failed", now=time.time())
            refusals["child_reported_failure"] = call(action="settle", run="feat", node="ui", outcome="accepted")
            call(action="cancel", run="feat")
            refusals["run_cancelled"] = call(action="settle", run="feat", node="api", outcome="accepted")
        self.assertEqual({reason: result.get("reason") for reason, result in refusals.items()},
                         {reason: reason for reason in refusals})
        self.assertEqual((asked, len(sent)), (["default"], 1))
        self.assertEqual((terminal.asked, len(answers.calls), answers.recovered), (asked, 1, 0))
        # A local run keeps main's order: a missing handoff is said before a bad reason.
        with homes() as home, terminal_env():
            self._returned(home)
            local = call(action="settle", run="feat", node="api", outcome="accepted",
                         reason="x" * (dag_run.MAX_REASON_CHARS + 1))
        self.assertEqual(local["reason"], "handoff_missing")

    def test_a_local_or_unread_backend_keeps_the_host_check_and_asks_no_terminal(self) -> None:
        """Mutation: read the backend for a run with no recorded backend, before the host, or for failed."""
        for terminal in (Terminal("local", Answers(FILE_ANSWER)), Terminal("modal", Answers(FILE_ANSWER)), None):
            with self.subTest(backend=terminal and terminal.backend), homes() as home, terminal_env(), (
                    terminal.modules() if terminal else nullcontext()):
                self._returned(home)
                refused = self._settle()
            self.assertEqual(refused["reason"], "handoff_missing")
            if terminal:
                self.assertEqual(terminal.asked, [])
        # Defined before Hermes could be read: the run keeps the host check after the terminal turns readable.
        answers = Answers(FILE_ANSWER)
        with homes() as home, terminal_env():
            self._returned(home)
            with Terminal("docker", answers).modules():
                refused = self._settle()
        self.assertEqual((refused["reason"], answers.calls), ("handoff_missing", []))
        # On this host's path a handoff the host has (a mounted OMH home) is enough, and a failed node asks nothing.
        docker = Terminal("docker", Answers(HOME_UNUSABLE))
        with homes() as home, terminal_env(), docker.modules():
            self._returned(home)
            failed = call(action="settle", run="feat", node="ui", outcome="failed", reason="tests red")
            handoff(home, "feat", "api")
            accepted = self._settle()
        self.assertEqual((failed["status"], accepted["status"], docker.asked), ("ok", "ok", ["default"]))

    def test_local_unset_and_unimportable_write_the_same_bytes(self) -> None:
        """Every way the host check stays: the same results and the same record, byte for byte."""
        def run(terminal: Terminal | None) -> tuple[list[str], bytes]:
            with homes() as home, terminal_env(), (terminal.modules() if terminal else nullcontext()), \
                    patch.object(dag_tool.time, "time", return_value=1_800_000_000.0):
                slots_table(home)
                said = [dag_tool.omh_dag_handler({"action": "define", "run": "feat", "nodes": FEATURE},
                                                 session_id=PARENT)]
                child_started(home, "feat", "api")
                said.append(dag_tool.omh_dag_handler(
                    {"action": "settle", "run": "feat", "node": "api", "outcome": "accepted"}, session_id=PARENT))
                handoff(home, "feat", "api")
                stop(home, "child-api", now=time.time())
                for arguments in ({"action": "settle", "run": "feat", "node": "api", "outcome": "accepted"},
                                  {"action": "settle", "run": "feat", "node": "ui", "outcome": "failed"},
                                  {"action": "status", "run": "feat"}):
                    said.append(dag_tool.omh_dag_handler(arguments, session_id=PARENT))
                record = dag_run.record_path(home.omh, PARENT, "feat").read_bytes()
                # Each run has its own temp home: the paths it names, as given, resolved (on Windows, the long name)
                # and JSON-escaped (a result is JSON), are written as one placeholder.
                roots = {str(home.omh.parent), os.path.realpath(home.omh.parent),
                         str(runtime_paths.default_omh_home().parent)}
            forms = sorted({form for root in roots for form in (json.dumps(root)[1:-1], root)}, key=len, reverse=True)
            for form in forms:
                said = [text.replace(form, "<home>") for text in said]
            return said, record

        unset = run(None)
        self.assertIn("handoff_missing", unset[0][1])
        for terminal in (Terminal("local", Answers(FILE_ANSWER)), Terminal(ValueError("bad config")),
                         Terminal(""), Terminal("modal", Answers(FILE_ANSWER))):
            with self.subTest(backend=terminal.backend):
                self.assertEqual(run(terminal), unset)


class RepairTests(unittest.TestCase):
    """The goal loop: repair nodes stand in for a failed node, at most two cycles for each."""

    def _failed_verify(self, home) -> None:
        slots_table(home)
        call(action="define", run="feat", nodes=[node("api", scope=("a.py",)), node("verify", role="verify", depends_on=("api",))])
        handoff(home, "feat", "api")
        call(action="settle", run="feat", node="api", outcome="accepted")
        call(action="settle", run="feat", node="verify", outcome="failed", reason="2 tests red")

    def test_repair_nodes_resolve_the_failed_node(self) -> None:
        with homes() as home:
            self._failed_verify(home)
            repaired = call(action="repair", run="feat", node="verify", nodes=[
                node("fix", scope=("a.py",), depends_on=("api",)), node("verify2", role="verify", depends_on=("fix",))])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "verify2")
            fixed = call(action="settle", run="feat", node="verify2", outcome="accepted")
            # A failed verification runs again once its repair is in; only that run satisfies it.
            handoff(home, "feat", "verify")
            done = call(action="settle", run="feat", node="verify", outcome="accepted")
        self.assertEqual([c["nodes"] for c in fixed["calls"]], [["verify"]])
        self.assertEqual(repaired["settled"]["repair_nodes"], ["fix", "verify2"])
        # No chat post was ever recorded (a TUI session): the line names no added node, the drawing shows them.
        self.assertNotIn("added", repaired["status_line"])
        self.assertEqual([c["nodes"] for c in repaired["calls"]], [["fix"]])
        self.assertEqual(done["state"], "done")
        self.assertEqual({row["id"]: row["state"] for row in done["nodes"]}["verify"], "accepted")

    def test_two_cycles_then_the_run_stops_and_reports(self) -> None:
        with homes() as home:
            self._failed_verify(home)
            call(action="repair", run="feat", node="verify", nodes=[node("v2", depends_on=("api",))])
            first = call(action="settle", run="feat", node="v2", outcome="failed")
            call(action="repair", run="feat", node="v2", nodes=[node("v3", depends_on=("api",))])
            second = call(action="settle", run="feat", node="v3", outcome="failed")
            third = call(action="repair", run="feat", node="v3", nodes=[node("v4", depends_on=("api",))])
        self.assertEqual(first["state"], "needs_repair")
        self.assertEqual(second["state"], "stopped")
        # The original node and its latest repair are both still open.
        self.assertEqual(second["open"], ["verify", "v3"])
        self.assertEqual(third["reason"], "repair_limit_reached")
        superseded = {row["id"]: row["state"] for row in second["nodes"]}
        self.assertEqual(superseded["v2"], "superseded")

    def test_a_repair_node_may_not_wait_on_an_open_node(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            call(action="settle", run="feat", node="api", outcome="failed")
            result = call(action="repair", run="feat", node="api", nodes=[node("fix", depends_on=("ui",))])
        self.assertEqual(result["reason"], "repair_depends_on_open_node")

    def test_a_repair_label_holding_a_marker_is_refused(self) -> None:
        for label in ("[dag:feat/api] Fix", "Fix [omh-team:t1/a/attempt-1]"):
            with self.subTest(label=label), homes() as home:
                self._failed_verify(home)
                result = call(action="repair", run="feat", node="verify", nodes=[node("fix", label=label)])
                self.assertEqual((result["status"], result["reason"]), ("refused", "invalid_label"), result)

    def test_only_a_failed_node_is_repaired(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            result = call(action="repair", run="feat", node="docs", nodes=[node("fix")])
        self.assertEqual(result["reason"], "not_failed")


class PreflightTests(unittest.TestCase):
    """What define refuses before a node is ever handed out, and the serial-graph lint."""

    def test_define_refuses_over_oneshot_budget(self) -> None:
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            result = call(action="define", run="feat", nodes=[node("a"), node("b")])
        self.assertEqual((result["status"], result["reason"]), ("refused", "oneshot_budget_exceeded"), result)
        self.assertIn("1", result["say"])
        self.assertIn("2", result["say"])

    def test_define_allows_interactive_session(self) -> None:
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=False):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
        self.assertEqual(result["status"], "ok", result)

    def test_a_healthy_detector_saying_interactive_leaves_the_graph_uncapped(self) -> None:
        with homes() as home, detector_module("def is_single_query_session():\n    return False\n"):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            self.assertFalse(dag_tool._single_query_session())
            self.assertIsNone(dag_tool.oneshot_child_limit(home.hermes))
            result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            self.assertEqual(result["status"], "ok", result)
            self.assertTrue(dag_run.record_path(home.omh, PARENT, "feat").exists())

    def test_an_absent_optional_detector_is_not_one_shot_and_stays_uncapped(self) -> None:
        # `None` in sys.modules blocks the import the way an install without the
        # host package does; the absent path is the documented no-cap answer.
        with homes() as home, patch_modules({"agent": None, "agent.oneshot_footprint": None}):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
        self.assertEqual(result["status"], "ok", result)

    def _assert_detector_refuses_without_record_changes(self, source: str) -> None:
        for existing in (False, True):
            with self.subTest(existing=existing), homes() as home, detector_module(source):
                slots_table(home)
                (home.hermes / "config.yaml").write_text(
                    "delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
                if existing:
                    with patch.object(dag_tool, "_single_query_session", return_value=False):
                        self.assertEqual(call(action="define", run="feat", nodes=[node("a")])["status"], "ok")
                path = dag_run.record_path(home.omh, PARENT, "feat")
                before = path.read_bytes() if path.exists() else None
                for operation in (dag_tool._single_query_session, lambda: dag_tool.oneshot_child_limit(home.hermes)):
                    with self.assertRaises(dag_run.DagRefusal) as raised:
                        operation()
                    self.assertEqual(raised.exception.reason, "oneshot_detection_unavailable")
                result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
                self.assertEqual((result["status"], result.get("reason")),
                                 ("refused", "oneshot_detection_unavailable"), result)
                self.assertIn("one-shot", result["say"])
                for secret in ("ModuleNotFoundError", "ImportError", "RuntimeError",
                               "omh_review_missing_detector_dependency", "private failure"):
                    self.assertNotIn(secret, json.dumps(result))
                self.assertEqual(path.exists(), existing)
                self.assertEqual(path.read_bytes() if path.exists() else None, before)

    def test_missing_dependency_during_detector_invocation_refuses_without_record_changes(self) -> None:
        sources = ["def is_single_query_session():\n    import omh_review_missing_detector_dependency\n"]
        # Even a permitted absence name (or no name) from the callable is a failure.
        for missing in ("agent", "agent.oneshot_footprint", None):
            sources.append("def is_single_query_session():\n"
                           f"    raise ModuleNotFoundError('private failure', name={missing!r})\n")
        for source in sources:
            with self.subTest(source=source):
                self._assert_detector_refuses_without_record_changes(source)

    def test_missing_dependency_during_detector_import_refuses_without_record_changes(self) -> None:
        sources = ["import omh_review_missing_detector_dependency\n"]
        # Prefix matches and unnamed ImportErrors do not establish optional absence.
        for missing in ("agent.other_dependency", "agent.oneshot_footprint.dependency", None):
            sources.append(f"raise ModuleNotFoundError('private failure', name={missing!r})\n")
        sources.extend(("raise ImportError('private failure')\n", "raise RuntimeError('private failure')\n", ""))
        for source in sources:
            with self.subTest(source=source):
                self._assert_detector_refuses_without_record_changes(source)

    def test_an_absent_agent_package_stays_uncapped(self) -> None:
        with homes() as home, patch_modules({"agent": None}):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            self.assertFalse(dag_tool._single_query_session())
            self.assertIsNone(dag_tool.oneshot_child_limit(home.hermes))
            result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            self.assertEqual(result["status"], "ok", result)
            self.assertTrue(dag_run.record_path(home.omh, PARENT, "feat").exists())

    def test_an_absent_detector_module_in_a_present_agent_stays_uncapped(self) -> None:
        with homes() as home, detector_module(None):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            self.assertFalse(dag_tool._single_query_session())
            self.assertIsNone(dag_tool.oneshot_child_limit(home.hermes))
            result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            self.assertEqual(result["status"], "ok", result)
            self.assertTrue(dag_run.record_path(home.omh, PARENT, "feat").exists())

    def test_a_healthy_imported_oneshot_detector_enforces_the_budget(self) -> None:
        with homes() as home, detector_module("def is_single_query_session():\n    return True\n"):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            self.assertTrue(dag_tool._single_query_session())
            self.assertEqual(dag_tool.oneshot_child_limit(home.hermes), 1)
            result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            self.assertEqual((result["status"], result.get("reason")),
                             ("refused", "oneshot_budget_exceeded"), result)
            self.assertFalse(dag_run.record_path(home.omh, PARENT, "feat").exists())

    def test_a_broken_installed_detector_refuses_by_name_and_writes_nothing(self) -> None:
        def broken() -> bool:
            raise RuntimeError("host one-shot state is unreadable")

        detector = SimpleNamespace(is_single_query_session=broken)
        with homes() as home, patch_modules({"agent": SimpleNamespace(oneshot_footprint=detector),
                                             "agent.oneshot_footprint": detector}):
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
            result = call(action="define", run="feat", nodes=[node("a"), node("b")])
            written = dag_run.record_path(home.omh, PARENT, "feat").exists()
        self.assertEqual((result["status"], result["reason"]), ("refused", "oneshot_detection_unavailable"), result)
        self.assertIn("one-shot", result["say"])
        self.assertNotIn("host one-shot state is unreadable", result["say"])
        self.assertNotIn("RuntimeError", result["say"])
        self.assertFalse(written, "a refused define must not leave a run record behind")

    def test_zero_limit_is_unlimited_but_invalid_values_follow_the_host_default(self) -> None:
        cases = (("0", "ok"), ("-1", "refused"), ("many", "refused"))
        for raw, status in cases:
            with self.subTest(raw=raw), homes() as home, \
                    patch.object(dag_tool, "_single_query_session", return_value=True):
                (home.hermes / "config.yaml").write_text(
                    f"delegation:\n  oneshot_max_children: {raw}\n", encoding="utf-8")
                result = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            self.assertEqual((result["status"], result.get("reason")),
                             (status, None if status == "ok" else "oneshot_budget_exceeded"), result)
            if status == "refused":
                self.assertIn("at most 2 nodes", result["say"])

    def test_define_refuses_markerless_node(self) -> None:
        with homes():
            result = call(action="define", run="feat", nodes=[node("a", prompt="Do the thing.")])
        self.assertEqual((result["status"], result["reason"]), ("refused", "prompt_markers_missing"), result)
        self.assertIn("a", result["say"])
        self.assertIn("TASK", result["say"])

    def test_partial_markers_stay_lint(self) -> None:
        with homes():
            result = call(action="define", run="feat",
                          nodes=[node("a", prompt="TASK: do it\nDELIVERABLE: a change")])
        self.assertEqual(result["status"], "ok", result)
        self.assertIn("missing_markers:a:SCOPE,VERIFY,STOP_WHEN", result["lint"])

    def test_lint_serial_graph(self) -> None:
        chain = [node("n0")] + [node(f"n{index}", depends_on=(f"n{index - 1}",)) for index in range(1, 5)]
        wide = [node("n0"), node("n1"), node("n2"), node("n3"),
                node("n4", depends_on=("n0", "n1", "n2", "n3"))]
        self.assertIn("serial_graph:5 nodes, critical path 5; most of the graph is one chain, "
                      "so split it into parallel lanes where the work allows.",
                      dag_run.lint([dag_run._validated_node(item) for item in chain]))
        self.assertFalse([finding for finding in dag_run.lint([dag_run._validated_node(item) for item in wide])
                          if finding.startswith("serial_graph")])


def oneshot_config(home, limit: int, *, cap: int = 10) -> None:
    slots_table(home)
    (home.hermes / "config.yaml").write_text(
        f"delegation:\n  oneshot_max_children: {limit}\n  max_concurrent_children: {cap}\n", encoding="utf-8")


def tasks_in(result: dict) -> int:
    return sum(len(item["tasks"]) for item in result.get("calls", []))


class OneShotBudgetTests(unittest.TestCase):
    """The one-shot child budget across define, ready, settle, repair and extend: what this process already spent."""

    def test_define_counts_children_this_session_already_started(self) -> None:
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            oneshot_config(home, 3)
            start(home, "child-other", "sa-other", "Look something up", now=time.time())
            refused = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            defined = call(action="define", run="feat", nodes=[node("a"), node("b")])
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "oneshot_budget_exceeded"), refused)
        self.assertIn("at most 2 nodes", refused["say"])
        self.assertIn("delegation.oneshot_max_children is 3", refused["say"])
        self.assertIn("already started 1", refused["say"])
        self.assertEqual(defined["status"], "ok", defined)
        self.assertEqual(tasks_in(defined), 2)
        self.assertEqual(defined["slots"]["oneshot"], {"limit": 3, "spent": 1, "remaining": 2})

    def test_waves_never_carry_more_tasks_than_the_budget_left(self) -> None:
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            oneshot_config(home, 3)
            defined = call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            child_started(home, "feat", "a")
            child_started(home, "feat", "b")
            # a's child died on a provider error; c's call has not started its child yet, and will take the last one.
            retried = call(action="settle", run="feat", node="a", outcome="failed", provider_error=True)
            again = call(action="ready", run="feat")
            child_started(home, "feat", "c")
            for item in ("b", "c"):
                handoff(home, "feat", item)
            call(action="settle", run="feat", node="b", outcome="accepted")
            left = call(action="settle", run="feat", node="c", outcome="accepted")
            handoff(home, "feat", "a")
            done = call(action="settle", run="feat", node="a", outcome="accepted")
            record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
        self.assertEqual(tasks_in(defined), 3)
        self.assertEqual(retried["settled"]["outcome"], "retry")
        for result in (retried, again):
            self.assertEqual(result["calls"], [], result)
            self.assertEqual(result["held_for_slots"], ["a"])
            self.assertIn("delegation.oneshot_max_children", result["say"])
            self.assertEqual(result["slots"]["oneshot"], {"limit": 3, "spent": 2, "remaining": 1})
        # Nothing else out and no child left: the parent does the node itself, with its handoff path, and settles it.
        self.assertEqual((left["calls"], left["for_parent"]), ([], ["a"]), left)
        self.assertNotIn("held_for_slots", left)
        self.assertIn("yourself", left["say"])
        self.assertIn("delegation.oneshot_max_children is 3", left["say"])
        # The tail only: Windows may spell the temp home in 8.3 short form on one side and long on the other.
        expected = Path(dag_run.node_handoff(record, home.omh, "a"))
        self.assertIn(str(Path(expected.parent.parent.name, expected.parent.name, expected.name)), left["say"])
        self.assertEqual(done["state"], "done", done)
        self.assertEqual(record["nodes"][0]["attempts"][-1]["lane"], "parent")

    def test_a_reoffered_node_costs_a_child_too(self) -> None:
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            oneshot_config(home, 2)
            moment = time.time()
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="define", run="feat", nodes=[node("a"), node("b")])
            start(home, "child-other", "sa-other", "Something else", now=moment)
            # No child ever took the call: both nodes come back once the hand-out is stale, with one child left.
            with patch.object(dag_tool.time, "time", return_value=moment + dag_run.HANDOUT_STALE_SECONDS + 1):
                reoffered = call(action="ready", run="feat")
        self.assertEqual(tasks_in(reoffered), 1, reoffered)
        self.assertEqual(reoffered["held_for_slots"], ["b"])

    def test_a_grandchild_and_a_repeated_start_do_not_count(self) -> None:
        from omh.plugin_bundle.omh import delegation_ledger

        with homes() as home:
            moment = time.time()
            start(home, "child-a", "sa-a", "Top-level", now=moment)
            start(home, "child-a", "sa-a", "Top-level", now=moment)
            start(home, "grand-a", "sa-grand", "Nested", parent="child-a", parent_subagent="sa-a", now=moment)
            self.assertEqual(delegation_ledger.oneshot_children_spawned([PARENT]), 1)
            # Hermes charged the child even when its record cannot be written.
            with patch.object(delegation_ledger, "_update", return_value=False):
                self.assertFalse(start(home, "child-b", "sa-b", "Top-level", now=moment))
            self.assertEqual(delegation_ledger.oneshot_children_spawned([PARENT, "other-session"]), 2)
            self.assertEqual(delegation_ledger.oneshot_children_spawned(["other-session"]), 0)

    def _failed_verify(self, home) -> None:
        call(action="define", run="feat", nodes=[node("api", scope=("a.py",)), node("verify", role="verify", depends_on=("api",))])
        child_started(home, "feat", "api")
        handoff(home, "feat", "api")
        call(action="settle", run="feat", node="api", outcome="accepted")
        child_started(home, "feat", "verify")
        call(action="settle", run="feat", node="verify", outcome="failed", reason="2 tests red")

    def test_repair_and_extend_refuse_more_nodes_than_children_left(self) -> None:
        repair_nodes = [node("fix", scope=("a.py",), depends_on=("api",)), node("verify2", role="verify", depends_on=("fix",))]
        extend_nodes = [node("more", depends_on=("api",)), node("check", depends_on=("more",))]
        for oneshot in (True, False):
            with self.subTest(oneshot=oneshot), homes() as home, \
                    patch.object(dag_tool, "_single_query_session", return_value=oneshot):
                oneshot_config(home, 3)
                self._failed_verify(home)
                path = dag_run.record_path(home.omh, PARENT, "feat")
                before = path.read_bytes()
                repaired = call(action="repair", run="feat", node="verify", nodes=repair_nodes)
                if oneshot:
                    self.assertEqual((repaired["status"], repaired["reason"]), ("refused", "oneshot_budget_exceeded"))
                    self.assertIn("1 more child", repaired["say"])
                    self.assertEqual(path.read_bytes(), before)
                else:
                    self.assertEqual(repaired["settled"]["repair_nodes"], ["fix", "verify2"], repaired)
            with self.subTest(oneshot=oneshot, action="extend"), homes() as home, \
                    patch.object(dag_tool, "_single_query_session", return_value=oneshot):
                oneshot_config(home, 2)
                call(action="define", run="feat", nodes=[node("api", scope=("a.py",))])
                child_started(home, "feat", "api")
                handoff(home, "feat", "api")
                call(action="settle", run="feat", node="api", outcome="accepted")
                path = dag_run.record_path(home.omh, PARENT, "feat")
                before = path.read_bytes()
                extended = call(action="extend", run="feat", node="api", nodes=extend_nodes)
                if oneshot:
                    self.assertEqual((extended["status"], extended["reason"]), ("refused", "oneshot_budget_exceeded"))
                    self.assertEqual(path.read_bytes(), before)
                    one = call(action="extend", run="feat", node="api", nodes=extend_nodes[:1])
                    self.assertEqual((one["status"], tasks_in(one)), ("ok", 1), one)
                else:
                    self.assertEqual(extended["settled"]["extend_nodes"], ["more", "check"], extended)

    def test_interactive_and_unlimited_waves_are_unchanged(self) -> None:
        nodes = [node(f"n{index}", scope=(f"f{index}",)) for index in range(3)]
        for oneshot, limit in ((False, 1), (True, 0)):
            with self.subTest(oneshot=oneshot, limit=limit), homes() as home, \
                    patch.object(dag_tool, "_single_query_session", return_value=oneshot):
                oneshot_config(home, limit, cap=2)
                start(home, "child-other", "sa-other", "Something else", now=time.time())
                result = call(action="define", run="feat", nodes=nodes)
                self.assertEqual(result["status"], "ok", result)
                self.assertNotIn("oneshot", result["slots"])
                self.assertEqual([item["nodes"] for item in result["calls"]], [["n0", "n1"], ["n2"]])
                self.assertNotIn("held_for_slots", result)
                self.assertNotIn("say", result)


class ExtendTests(unittest.TestCase):
    """Work found missing after every node passed: an extend round on the same run, at most two per run."""

    def _done(self, home) -> dict:
        slots_table(home)
        call(action="define", run="feat", nodes=[node("api", scope=("a.py",)),
                                                 node("verify", role="verify", depends_on=("api",), label="Verify the feature")])
        handoff(home, "feat", "api")
        call(action="settle", run="feat", node="api", outcome="accepted")
        handoff(home, "feat", "verify")
        return call(action="settle", run="feat", node="verify", outcome="accepted")

    def test_extend_adds_a_round_to_the_same_run_and_records_where_each_node_came_from(self) -> None:
        with homes() as home:
            done = self._done(home)
            extended = call(action="extend", run="feat", nodes=[
                node("csv", scope=("a.py",), depends_on=("api",)), node("verify2", role="verify", depends_on=("csv",),
                                                                        label="Verify CSV")])
            record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
        self.assertEqual((done["state"], done["extend_rounds_left"]), ("done", 2))
        self.assertIn("extend the run (2 rounds left)", done["say"])
        self.assertEqual(extended["status"], "ok", extended)
        self.assertEqual(extended["state"], "running")
        self.assertEqual(extended["settled"],
                         {"extend_round": 1, "extend_nodes": ["csv", "verify2"], "found_by": "verify"})
        self.assertEqual([c["nodes"] for c in extended["calls"]], [["csv"]])
        self.assertEqual(extended["topology"]["layers"], [["api"], ["verify", "csv"], ["verify2"]])
        self.assertEqual({n["id"]: n["origin"] for n in record["nodes"]},
                         {"api": "define", "verify": "define", "csv": "extend:1", "verify2": "extend:1"})
        self.assertEqual(record["extends"], [["csv", "verify2"]])
        rows = {row["id"]: row for row in extended["nodes"]}
        self.assertEqual((rows["csv"]["origin"], rows["csv"]["found_by"]), ("extend:1", "verify"))
        self.assertNotIn("origin", rows["api"])

    def test_the_whole_run_passes_the_hard_rejects_of_define(self) -> None:
        cases = {
            "unknown_dependency": [node("x", depends_on=("ghost",))],
            "self_dependency": [node("x", depends_on=("x",))],
            "dependency_cycle": [node("x", depends_on=("y",)), node("y", depends_on=("x",))],
            "duplicate_node_id": [node("api")],
            # A finished node's file still needs an edge: the new node then reads that node's handoff.
            "write_scope_overlap": [node("x", scope=("a.py",))],
            "too_many_nodes": [node(f"n{index}") for index in range(dag_run.MAX_NODES - 1)],
            "empty_graph": [],
            "unknown_node": None,
            "invalid_label": [node("x", label="[omh-team:t1/a/attempt-1] More")],
        }
        with homes() as home:
            self._done(home)
            results = {
                reason: call(action="extend", run="feat", nodes=nodes) if nodes is not None
                else call(action="extend", run="feat", node="ghost", nodes=[node("x")])
                for reason, nodes in cases.items()
            }
            unchanged = call(action="status", run="feat")
        for reason, result in results.items():
            self.assertEqual(result.get("reason"), reason, result)
        self.assertEqual((unchanged["state"], len(unchanged["nodes"])), ("done", 2))

    def test_the_new_nodes_are_linted(self) -> None:
        with homes() as home:
            self._done(home)
            markerless = call(action="extend", run="feat", nodes=[node("csv", scope=("b.py",), prompt="just do it")])
            extended = call(action="extend", run="feat", nodes=[node("csv", scope=("b.py",), prompt="TASK: add CSV")])
        self.assertEqual((markerless["status"], markerless["reason"]), ("refused", "prompt_markers_missing"))
        self.assertIn("missing_markers:csv:DELIVERABLE,SCOPE,VERIFY,STOP_WHEN", extended["lint"])
        self.assertIn("verification_misses:csv", extended["lint"])

    def test_two_rounds_then_the_parent_reports_what_is_open(self) -> None:
        with homes() as home:
            self._done(home)
            for number in (1, 2):
                call(action="extend", run="feat", nodes=[node(f"more{number}")])
                handoff(home, "feat", f"more{number}")
                last = call(action="settle", run="feat", node=f"more{number}", outcome="accepted")
            third = call(action="extend", run="feat", nodes=[node("more3")])
        self.assertEqual((last["state"], last["extend_rounds_left"]), ("done", 0))
        self.assertIn("the extend rounds are spent", last["say"])
        self.assertEqual(third["reason"], "extend_limit_reached")
        self.assertIn("report what is still open", third["say"])

    def test_extend_waits_until_every_node_passed(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            running = call(action="extend", run="feat", nodes=[node("x")])
        self.assertEqual(running["reason"], "run_not_done")
        self.assertIn("repair the failed node", running["say"])

    def test_a_new_node_may_wait_only_on_accepted_nodes(self) -> None:
        with homes() as home:
            self._done_after_a_superseded_repair(home)
            refused = call(action="extend", run="feat", nodes=[node("x", depends_on=("v2",))])
            # A superseded repair node's file needs no edge: it never runs again.
            accepted = call(action="extend", run="feat", nodes=[node("y", scope=("b.py",), depends_on=("v3",))])
        self.assertEqual(refused["reason"], "extend_depends_on_open_node")
        self.assertEqual(accepted["status"], "ok", accepted)

    def _done_after_a_superseded_repair(self, home) -> None:
        slots_table(home)
        call(action="define", run="feat", nodes=[node("api", scope=("a.py",)), node("verify", role="verify", depends_on=("api",))])
        handoff(home, "feat", "api")
        call(action="settle", run="feat", node="api", outcome="accepted")
        call(action="settle", run="feat", node="verify", outcome="failed")
        call(action="repair", run="feat", node="verify", nodes=[node("v2", scope=("b.py",), depends_on=("api",))])
        call(action="settle", run="feat", node="v2", outcome="failed")
        call(action="repair", run="feat", node="v2", nodes=[node("v3", scope=("b.py",), depends_on=("api",))])
        handoff(home, "feat", "v3")
        call(action="settle", run="feat", node="v3", outcome="accepted")
        handoff(home, "feat", "verify")
        done = call(action="settle", run="feat", node="verify", outcome="accepted")
        self.assertEqual(done["state"], "done", done)
        self.assertEqual({row["id"]: row["state"] for row in done["nodes"]}["v2"], "superseded")


class LifecycleTests(unittest.TestCase):
    def test_status_finds_the_run_from_a_later_segment(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            later = "20261020_150000_later"
            with patch.object(dag_tool._kanban_board_reader, "conversation_session_ids",
                              return_value={PARENT, later}):
                result = json.loads(dag_tool.omh_dag_handler({"action": "status", "run": "feat"}, session_id=later))
        self.assertEqual((result["status"], result["run"]), ("ok", "feat"), result)

    def test_cancel_ends_the_run(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            result = call(action="cancel", run="feat")
            settle = call(action="settle", run="feat", node="api", outcome="accepted")
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(settle["reason"], "run_cancelled")

    def test_cancel_names_still_running_children(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api"), node("docs")])
            call(action="ready", run="feat")
            child_started(home, "feat", "api")
            result = call(action="cancel", run="feat")
        still = result.get("still_running", [])
        self.assertEqual([row["id"] for row in still], ["api"])
        self.assertEqual(still[0]["subagent_id"], "sa-api")
        self.assertIn("open_for_s", still[0])
        self.assertIn("api as subagent sa-api", result["say"])
        self.assertIn("delegate_task action=stop", result["say"])
        self.assertIn("never settles them", result["say"])

    def test_a_repeated_cancel_still_names_the_running_child(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api"), node("docs")])
            call(action="ready", run="feat")
            child_started(home, "feat", "api")
            call(action="cancel", run="feat")
            again = call(action="cancel", run="feat")
        self.assertEqual([row["subagent_id"] for row in again.get("still_running", [])], ["sa-api"])
        self.assertNotIn("No child is still running", again["say"])

    def test_cancel_without_running_children_says_so(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            result = call(action="cancel", run="feat")
        self.assertNotIn("still_running", result)
        self.assertIn("No child is still running", result["say"])

    def test_the_record_holds_no_child_output(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=FEATURE)
            child_started(home, "feat", "api")
            stop(home, "child-api", now=time.time())
            text = dag_run.record_path(home.omh, PARENT, "feat").read_text(encoding="utf-8")
        self.assertNotIn("SECRET SUMMARY TEXT", text)

    def test_the_ledger_binds_a_child_by_the_last_whole_marker_in_its_goal(self) -> None:
        """Mutation: read only the end or only the start of the goal, or bind on a marker that is not whole."""
        with homes() as home:
            child_started(home, "feat", "api")
            start(home, "child-old", "sa-old", "[dag:feat/ui] Node ui", now=time.time())  # before an update
            start(home, "child-x", "sa-x", "wrong case [dag:feat/API]", now=time.time())
            start(home, "child-c", "sa-c", "Node docs [dag:feat/docs", now=time.time())  # not a whole marker
            # A model that adds text after the marker leaves the binding as it was.
            start(home, "child-y", "sa-y", "Node docs [dag:feat/docs]. Please hurry", now=time.time())
            start(home, "child-z", "sa-z", "Node verify [dag:feat/verify]\n\nExtra instructions from the model",
                  now=time.time())
            children = {child["subagent_id"]: child for child in read_ledger(home.omh, PARENT)["children"]}
        self.assertEqual({subagent_id: children[subagent_id].get("dag") for subagent_id in children}, {
            "sa-api": {"run": "feat", "node": "api"},
            "sa-old": {"run": "feat", "node": "ui"},
            "sa-x": None,
            "sa-c": None,
            "sa-y": {"run": "feat", "node": "docs"},
            "sa-z": {"run": "feat", "node": "verify"},
        })

    def test_a_goal_with_more_than_one_marker_binds_to_the_last(self) -> None:
        """Mutation: take the first marker in `dag_binding`."""
        self.assertEqual(dag_binding("[dag:feat/ui] the button, after [dag:feat/docs] [dag:feat/api]"),
                         {"run": "feat", "node": "api"})
        # A goal from before an update whose label ended with a marker binds to that one, as the end marker did.
        self.assertEqual(dag_binding("[dag:feat/ui] Node ui [dag:feat/api]"), {"run": "feat", "node": "api"})
        self.assertEqual(dag_binding("Node api [dag:feat/api]\n"), {"run": "feat", "node": "api"})
        # Text before and after the marker: both were unbound while only an end or a leading marker counted.
        self.assertEqual(dag_binding("please [dag:feat/api] neither first nor last"), {"run": "feat", "node": "api"})
        self.assertEqual(dag_binding("Node docs [dag:feat/docs] and more"), {"run": "feat", "node": "docs"})
        self.assertEqual(dag_binding("Node api [dag:feat/api"), {})
        # Every line counts: the last marker of the goal, not of its first line.
        self.assertEqual(dag_binding("Node api [dag:feat/api]\nsecond line\nthen [dag:feat/ui]"),
                         {"run": "feat", "node": "ui"})

    def test_a_goal_whose_last_marker_is_a_team_key_binds_no_node(self) -> None:
        """Mutation: read dag markers only, so a team title from before an update that quoted one binds a node."""
        for goal in ("Fix the parser [dag:feat/api] [omh-team:t1/a/attempt-1]",
                     "Fix the parser [dag:feat/api] [omh-team:t1/a/attempt-1]. Please hurry"):
            with self.subTest(goal=goal):
                self.assertEqual(dag_binding(goal), {})
        # A team key before the node's own marker does not hide it, with or without text after the marker.
        self.assertEqual(dag_binding("[omh-team:t1/a/attempt-1] Fix [dag:feat/api]"), {"run": "feat", "node": "api"})
        self.assertEqual(dag_binding("[omh-team:t1/a/attempt-1] Label [dag:feat/x]. Please hurry"),
                         {"run": "feat", "node": "x"})
        # Title from before an update quoting a dag marker, then text after the team key: still the helper's.
        self.assertEqual(dag_binding("Title [dag:feat/api] [omh-team:t1/a/attempt-1]. Please hurry"), {})


NO_HERMES = {"gateway": None, "gateway.status": None}


def hermes_process(started: int) -> dict:
    """Hermes' `gateway.status` liveness probes in a Hermes process that started at ``started``.

    Every pid exists, so the test's own pid stands for each process; a recorded start time other than
    ``started`` is another process, as Hermes' own comparator reads a reused pid.
    """
    status = SimpleNamespace(_pid_exists=lambda pid: True, get_process_start_time=lambda pid: started,
                             start_time_fingerprints_match=lambda recorded, current: abs(current - recorded) <= 200)
    return {"gateway": SimpleNamespace(status=status), "gateway.status": status}


class RestartTests(unittest.TestCase):
    """A Hermes restart ends a node's child and fires no `subagent_stop`.

    Mutation: drop the `lost` mark in `dag_tool._children` or in `derive`, offer a lost node only once it is ten
    minutes stale, or offer it past `MAX_LOST_REOFFERS`.
    """

    def out(self, home, moment: float, *, probes: dict) -> None:
        """Define a one-node run at ``moment`` and start its child in the process ``probes`` stands for."""
        slots_table(home)
        with patch.object(dag_tool.time, "time", return_value=moment), patch_modules(probes):
            call(action="define", run="feat", nodes=[node("api")])
            child_started(home, "feat", "api", now=moment + 1)

    def test_a_node_whose_child_a_restart_ended_is_offered_again_at_once(self) -> None:
        moment = time.time()
        with homes() as home:
            self.out(home, moment, probes=hermes_process(1000))
            self.assertEqual(read_ledger(home.omh, PARENT)["children"][0]["host"],
                             {"pid": os.getpid(), "started": 1000, "machine": host_process.machine()})
            with patch.object(dag_tool.time, "time", return_value=moment + 60), patch_modules(hermes_process(5000)):
                status = call(action="status", run="feat")
                ready = call(action="ready", run="feat")
                start(home, "child-api-2", "sa-api-2", "Node api [dag:feat/api]", now=moment + 61)
                again = call(action="status", run="feat")
            attempts = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))["nodes"][0]["attempts"]
        self.assertEqual(status["nodes"][0]["state"], "handed_out")
        self.assertEqual([c["nodes"] for c in ready["calls"]], [["api"]])
        self.assertEqual(ready["calls"][0]["tasks"][0]["goal"], "Node api [dag:feat/api]")
        self.assertEqual(again["nodes"][0]["state"], "running")
        self.assertEqual([(attempt["n"], attempt["lost"]) for attempt in attempts], [(1, 1)])

    def test_a_child_that_came_back_before_the_restart_is_not_offered_again(self) -> None:
        """Mutation: drop the `"stop" in child` skip in `dag_tool._children`."""
        moment = time.time()
        with homes() as home:
            self.out(home, moment, probes=hermes_process(1000))
            stop(home, "child-api", now=moment + 30)
            with patch.object(dag_tool.time, "time", return_value=moment + 60), patch_modules(hermes_process(5000)):
                ready = call(action="ready", run="feat")
        self.assertEqual((ready["nodes"][0]["state"], ready["calls"]), ("returned", []))

    def test_a_child_that_came_back_under_a_rotated_parent_is_not_offered_again(self) -> None:
        """Hermes files the stop under the parent's current segment, which a rotating compaction made after the start.

        Mutation: drop the stop join in `dag_tool._children` (the node is offered, and its child runs twice).
        """
        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph

        moment = time.time()
        later = "20261020_160000_later"

        def call_in(session: str, **arguments: object) -> dict:
            return json.loads(dag_tool.omh_dag_handler(arguments, session_id=session))

        with homes() as home:
            self.out(home, moment, probes=hermes_process(1000))
            home.session(PARENT, "claude-opus-5-5")
            home.rotate(PARENT, later, at=moment + 10)
            stop(home, "child-api", parent=later, now=moment + 30)  # it came back before the restart
            with patch.object(dag_tool.time, "time", return_value=moment + 60), patch_modules(hermes_process(5000)):
                ready = call_in(later, action="ready", run="feat")
                status = call_in(later, action="status", run="feat")
            graph = build_delegation_graph(home.omh, home.hermes, later, now=moment + 60)
        self.assertEqual((ready["nodes"][0]["state"], ready["calls"]), ("returned", []))
        self.assertEqual(status["nodes"][0]["state"], "returned")
        self.assertEqual(next(node["status"] for node in graph["nodes"] if node.get("dag_node") == "api"), "returned",
                         "omh_dag and the graph read one stop")

    def test_a_child_that_came_back_in_its_own_continuation_is_not_offered_again(self) -> None:
        """Hermes rotated the child itself, so its stop names the continuation, not the session that started.

        Mutation: drop the continuation lookup in `dag_tool._children` (the node is offered, and its child runs twice).
        """
        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph

        moment = time.time()
        with homes() as home:
            self.out(home, moment, probes=hermes_process(1000))
            home.session(PARENT, "claude-opus-5-5")
            home.session("child-api", "glm-5.3-flash", parent=PARENT)
            home.rotate("child-api", "child-api-b", at=moment + 10)
            stop(home, "child-api-b", now=moment + 30)  # it came back before the restart
            with patch.object(dag_tool.time, "time", return_value=moment + 60), patch_modules(hermes_process(5000)):
                ready = call(action="ready", run="feat")
                status = call(action="status", run="feat")
            graph = build_delegation_graph(home.omh, home.hermes, PARENT, now=moment + 60)
        self.assertEqual((ready["nodes"][0]["state"], ready["calls"]), ("returned", []))
        self.assertEqual(status["nodes"][0]["state"], "returned")
        self.assertEqual(next(node["status"] for node in graph["nodes"] if node.get("dag_node") == "api"), "returned",
                         "omh_dag and the graph read one stop")

    def test_a_childs_lineage_is_read_only_when_it_is_about_to_be_lost_beside_an_unjoined_stop(self) -> None:
        """Mutation: read it for every child, or for every lost one (a state.db read on the common path)."""
        moment = time.time()
        with homes() as home:
            self.out(home, moment, probes=hermes_process(1000))
            with patch.object(dag_tool._kanban_board_reader, "conversation_session_ids", return_value=set()) as lineage:
                with patch_modules(hermes_process(1000)):  # still running
                    dag_tool._children(home.omh, [PARENT], home.hermes)
                with patch_modules(hermes_process(5000)):  # a restart ended it, and no stop is unjoined
                    dag_tool._children(home.omh, [PARENT], home.hermes)
                quiet = lineage.call_count
                stop(home, "child-elsewhere", now=moment + 30)  # a stop no start in this ledger names
                with patch_modules(hermes_process(5000)):
                    lost = dag_tool._children(home.omh, [PARENT], home.hermes)
        self.assertEqual((quiet, lineage.call_count), (0, 1))
        self.assertTrue(lost[0]["lost"])

    def test_two_children_under_one_pid_are_asked_about_apart_by_where_it_was_read(self) -> None:
        """Mutation: key the per-call answer by pid and start time only."""
        moment = time.time()
        with homes() as home:
            with patch_modules(hermes_process(1000)):
                with patch.object(host_process, "machine", return_value="linux:other-boot:pid:[4026532999]"):
                    start(home, "child-there", "sa-there", "There [dag:feat/api]", now=moment)
                start(home, "child-here", "sa-here", "Here [dag:feat/ui]", now=moment + 1)
            with patch_modules(hermes_process(5000)):
                lost = {child["child_session_id"]: bool(child.get("lost")) for child in dag_tool._children(home.omh, [PARENT])}
        self.assertEqual(lost, {"child-there": False, "child-here": True})

    def test_a_running_child_and_one_with_no_recorded_process_stay_running(self) -> None:
        moment = time.time()
        for name, started_in, later in (("still running", hermes_process(1000), hermes_process(1000)),
                                        ("started outside Hermes", NO_HERMES, hermes_process(5000))):
            with self.subTest(case=name), homes() as home:
                self.out(home, moment, probes=started_in)
                with patch.object(dag_tool.time, "time", return_value=moment + 6 * 3600), patch_modules(later):
                    ready = call(action="ready", run="feat")
                self.assertEqual((ready["nodes"][0]["state"], ready["calls"]), ("running", []))

    LINE = (f"Hermes restarted while node api ran, {dag_run.MAX_LOST_REOFFERS + 1} times, so it is not offered "
            "again: settle it failed or blocked.")

    def lose_until_spent(self, home, moment: float) -> None:
        """Hermes restarts while each child the node is offered to runs, until the node is not offered again."""
        self.out(home, moment, probes=hermes_process(1000))
        for n in range(dag_run.MAX_LOST_REOFFERS):
            at = moment + 1000 * (n + 1)
            with patch.object(dag_tool.time, "time", return_value=at), patch_modules(hermes_process(5000 * (n + 2))):
                self.assertEqual([c["nodes"] for c in call(action="ready", run="feat")["calls"]], [["api"]])
                start(home, f"child-api-{n}", f"sa-api-{n}", "Node api [dag:feat/api]", now=at + 1)

    def test_past_the_bound_the_parent_settles_a_node_that_keeps_losing_its_child(self) -> None:
        moment = time.time()
        with homes() as home:
            self.lose_until_spent(home, moment)
            with patch.object(dag_tool.time, "time", return_value=moment + 10_000), patch_modules(hermes_process(99_000)):
                spent = call(action="ready", run="feat")
                status = call(action="status", run="feat")
                settled = call(action="settle", run="feat", node="api", outcome="failed", reason="lost to restarts")
        self.assertEqual(spent["calls"], [])
        # Said on every action, `status` included, beside anything else the reply says.
        self.assertEqual((spent["say"], status["say"]), (self.LINE, self.LINE))
        self.assertEqual(settled["nodes"][0]["state"], "failed")
        self.assertNotIn(self.LINE, settled["say"])

    def test_the_settle_line_is_added_to_what_else_the_reply_says(self) -> None:
        """Mutation: let the settle line replace another say (a retry, an export, a full pool)."""
        moment = time.time()
        with homes() as home:
            self.lose_until_spent(home, moment)
            with patch.object(dag_tool.time, "time", return_value=moment + 10_000), patch_modules(hermes_process(99_000)):
                record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
                derived = dag_run.derive(record, dag_tool._children(home.omh, [PARENT]), moment + 10_000)
                said = json.loads(dag_tool._result("ready", record, derived, None, say="Another line."))["say"]
        self.assertEqual(said, f"Another line. {self.LINE}")

    def test_a_cancelled_run_does_not_ask_to_settle_its_lost_node(self) -> None:
        """Mutation: drop the `handed_out` state check from `lost_for_good`."""
        moment = time.time()
        with homes() as home:
            self.lose_until_spent(home, moment)
            with patch.object(dag_tool.time, "time", return_value=moment + 10_000), patch_modules(hermes_process(99_000)):
                cancelled = call(action="cancel", run="feat")
        self.assertEqual(cancelled["nodes"][0]["state"], "cancelled")
        self.assertNotIn(self.LINE, cancelled["say"])

    def test_a_lost_node_waiting_for_a_slot_is_told_to_wait_not_to_settle(self) -> None:
        """Mutation: say a node is not offered again before its losses reach the bound."""
        moment = time.time()
        with homes() as home:
            self.out(home, moment, probes=hermes_process(1000))
            slots_table(home, running=[("busy", os.getpid())])
            home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 1\n")
            with patch.object(dag_tool.time, "time", return_value=moment + 60), patch_modules(hermes_process(5000)):
                ready = call(action="ready", run="feat")
        self.assertEqual((ready["calls"], ready["held_for_slots"]), ([], ["api"]))
        self.assertEqual(ready["say"], "No delegate_task slot is free; end the turn and call ready again after a "
                                       "completion.")


CODING = [
    node("plan", category="unspecified-low", label="Plan the change"),
    node("api", depends_on=("plan",), scope=("src/api.py",)),
    node("ui", depends_on=("plan",), scope=("src/ui.py",)),
    node("review", role="review", depends_on=("plan",), scope=("docs/review.md",), label="Review the plan"),
    node("verify", category="unspecified-high", depends_on=("api", "ui", "review"), label="Verify the feature"),
]


def choose(home, owner: str, *, age: float = 0.0) -> dict:
    """The record the router writes when the person names ``owner``, dated ``age`` seconds ago."""
    from datetime import datetime, timedelta, timezone

    moment = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    state = owner_preference.record_in_message_explicit_naming(
        None, route_family=OWNER_PREFERENCE_ROUTE_FAMILY, selected_owner=owner,
        naming_cue=f"named_executor:{owner}", occurred_at=moment)
    put_record(home, state)
    return state


def put_record(home, state: object) -> None:
    path = home.omh.joinpath(*dag_tool.OWNER_PREFERENCE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


class ExportTests(unittest.TestCase):
    """The coding owner the person already chose takes the coding nodes; everything else stays on delegate_task."""

    def _planned(self, home) -> dict:
        slots_table(home)  # ten free slots: the pool has room, and the coding nodes still go to the owner
        call(action="define", run="feat", goal="ship the export feature", nodes=CODING)
        handoff(home, "feat", "plan")
        return call(action="settle", run="feat", node="plan", outcome="accepted")

    def test_with_a_chosen_owner_coding_nodes_go_to_export_and_the_rest_to_delegate_task(self) -> None:
        with homes() as home:
            choose(home, "codex")
            ready = self._planned(home)
            exported = call(action="export", run="feat", owner="codex")
            payload = json.loads(Path(exported["fanout"]["units_file"]).read_text(encoding="utf-8"))
        self.assertEqual([c["nodes"] for c in ready["calls"]], [["review"]])
        self.assertEqual(ready["export"], {"owner": "codex", "nodes": ["api", "ui"],
                                           "next": {"tool": "omh_dag", "action": "export", "owner": "codex"}})
        self.assertIn("omh_dag action=export owner=codex", ready["say"])
        self.assertEqual(exported["status"], "ok", exported)
        self.assertEqual([unit["unit_id"] for unit in payload["units"]], ["api", "ui"])
        rows = {row["id"]: row["state"] for row in exported["nodes"]}
        self.assertEqual((rows["api"], rows["ui"], rows["verify"]), ("handed_out", "handed_out", "waiting"))

    def test_without_a_record_every_node_runs_on_delegate_task_and_nothing_spawns(self) -> None:
        with homes() as home, patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
            ready = self._planned(home)
            refused = call(action="export", run="feat", owner="codex")
            folder = dag_run.handoff_path(home.omh, PARENT, "feat", "x").parent
            files = sorted(path.name for path in folder.iterdir())
        self.assertEqual(sorted(node_id for c in ready["calls"] for node_id in c["nodes"]), ["api", "review", "ui"])
        self.assertNotIn("export", ready)
        self.assertEqual(refused["reason"], "owner_not_chosen")
        self.assertEqual(files, ["plan.md"])
        popen.assert_not_called()
        run.assert_not_called()

    def test_export_round_trips_into_a_fanout_contract(self) -> None:
        nodes = [node("api", scope=("src/api.py",)), node("ui", scope=("src/ui.py",)),
                 node("docs", depends_on=("api",), scope=("docs/api.md",)),
                 node("verify", role="verify", depends_on=("api", "ui", "docs"))]
        with homes() as home:
            slots_table(home)
            choose(home, "codex")
            defined = call(action="define", run="feat", goal="ship the export feature", nodes=nodes)
            result = call(action="export", run="feat", owner="codex")
            payload = json.loads(Path(result["fanout"]["units_file"]).read_text(encoding="utf-8"))
            goal = Path(result["fanout"]["goal_file"]).read_text(encoding="utf-8")
        self.assertIn("ship the export feature", goal)
        self.assertEqual(defined["calls"], [])
        self.assertEqual(defined["export"]["nodes"], ["api", "ui"])
        self.assertEqual(result["status"], "ok", result)
        # docs waits only on api, which goes in the same batch: the contract keeps the order.
        self.assertEqual([unit["unit_id"] for unit in payload["units"]], ["api", "ui", "docs"])
        contract = build_fanout_contract(goal, payload["units"])
        self.assertEqual(contract["fanout_id"], result["fanout"]["fanout_id"])
        self.assertEqual(contract["merge_plan"]["merge_order"], ["api", "ui", "docs"])
        self.assertEqual({unit["unit_id"]: unit["depends_on"] for unit in contract["units"]},
                         {"api": [], "ui": [], "docs": ["api"]})
        rows = {row["id"]: row["state"] for row in result["nodes"]}
        self.assertEqual(rows["api"], "handed_out")
        self.assertEqual(rows["verify"], "waiting")

    def test_a_second_export_in_one_run_keeps_the_first_exports_files(self) -> None:
        # api goes first; ui waits on a native node, so it goes in a second export once that node passed. The first
        # export's prepare or dispatch may not have run yet: its goal file must still be the one its id was made from.
        nodes = [node("api", scope=("src/api.py",)), node("notes", depends_on=("api",), label="Write the notes"),
                 node("ui", depends_on=("notes",), scope=("src/ui.py",)), node("verify", role="verify", depends_on=("ui",))]
        with homes() as home:
            slots_table(home)
            choose(home, "codex")
            call(action="define", run="feat", goal="ship the export feature", nodes=nodes)
            first = call(action="export", run="feat", owner="codex")
            for node_id in ("api", "notes"):
                handoff(home, "feat", node_id)
                call(action="settle", run="feat", node=node_id, outcome="accepted")
            second = call(action="export", run="feat", owner="codex")
            exports = [
                (result["fanout"], json.loads(Path(result["fanout"]["units_file"]).read_text(encoding="utf-8"))["units"],
                 Path(result["fanout"]["goal_file"]).read_text(encoding="utf-8"))
                for result in (first, second)
            ]
        self.assertEqual([[unit["unit_id"] for unit in units] for _fanout, units, _goal in exports], [["api"], ["ui"]])
        self.assertNotEqual(exports[0][0]["units_file"], exports[1][0]["units_file"])
        self.assertNotEqual(exports[0][0]["goal_file"], exports[1][0]["goal_file"])
        for fanout, units, goal in exports:
            self.assertEqual(build_fanout_contract(goal, units)["fanout_id"], fanout["fanout_id"])
            self.assertIn(fanout["fanout_id"], fanout["units_file"])

    def test_an_exported_node_is_never_handed_to_delegate_task(self) -> None:
        with homes() as home:
            choose(home, "codex")
            self._planned(home)
            moment = time.time()
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="export", run="feat", owner="codex")
            # Past the ten minutes after which a node no child took is offered again: an exported node is not.
            with patch.object(dag_tool.time, "time", return_value=moment + dag_run.HANDOUT_STALE_SECONDS + 1):
                later = call(action="ready", run="feat")
        offered = {node_id for c in later["calls"] for node_id in c["nodes"]}
        self.assertFalse(offered & {"api", "ui"}, later["calls"])
        self.assertNotIn("export", later)

    def test_the_choice_counts_for_a_day_and_never_from_the_future(self) -> None:
        for age, expected in ((23 * 3600 + 59 * 60, "codex"), (24 * 3600 + 60, ""), (-60, "")):
            with self.subTest(age=age), homes() as home:
                choose(home, "codex", age=age)
                self.assertEqual(dag_tool.owner_choice(home.omh, now=time.time()), expected)

    def test_export_reads_the_record_exactly_as_the_router_does(self) -> None:
        from datetime import datetime, timezone

        moment = datetime.now(timezone.utc).isoformat()
        valid = owner_preference.record_in_message_explicit_naming(
            None, route_family=OWNER_PREFERENCE_ROUTE_FAMILY, selected_owner="codex",
            naming_cue="named_executor:codex", occurred_at=moment)
        accepted = owner_preference.record_accepted_explicit_choice(
            None, route_family=OWNER_PREFERENCE_ROUTE_FAMILY, selected_owner="claude-code", occurred_at=moment)

        def changed(state: dict, path: tuple[str, ...], value: object) -> dict:
            copy = json.loads(json.dumps(state))
            target = copy
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return copy

        route = ("routes", OWNER_PREFERENCE_ROUTE_FAMILY)
        states = {
            "valid in_message_naming": valid,
            "valid accepted choice": accepted,
            # The review's four (owner_seam_probe): records the router reads as no choice.
            "raw minimal record": {"schema_version": "coding_owner_preference/v1", "routes": {
                OWNER_PREFERENCE_ROUTE_FAMILY: {"provenance": "in_message_naming", "selected_owner": "codex",
                                                "last_choice_at": moment}}},
            "in_message_naming without a naming cue": changed(valid, (*route, "naming_cue"), ""),
            "owner with a zero count": changed(valid, (*route, "consecutive_accepted_explicit_choices"), 0),
            "privacy boundary broken": changed(valid, ("privacy", "mode"), "full"),
            "no provenance": changed(changed(valid, (*route, "provenance"), ""), (*route, "naming_cue"), ""),
            "secret-shaped owner": changed(valid, (*route, "selected_owner"), "token-codex"),
            "not a mapping": ["codex"],
        }
        for label, state in states.items():
            with self.subTest(label), homes() as home:
                put_record(home, state)
                provenance = owner_preference.explicit_choice_provenance(
                    state if isinstance(state, dict) else None, route_family=OWNER_PREFERENCE_ROUTE_FAMILY)
                router_owner = (state["routes"][OWNER_PREFERENCE_ROUTE_FAMILY]["selected_owner"]
                                if provenance else "")
                self.assertEqual(dag_tool.owner_choice(home.omh, now=time.time()), router_owner)
        self.assertEqual(sum(1 for state in states.values() if owner_preference.explicit_choice_provenance(
            state if isinstance(state, dict) else None, route_family=OWNER_PREFERENCE_ROUTE_FAMILY)), 2)

    def test_the_opaque_reference_check_is_the_routers(self) -> None:
        from omh.plugin_bundle.omh import owner_preference_record as bundle
        from omh.system import metadata_safety as core

        self.assertEqual(bundle.OPAQUE_REFERENCE.pattern, core._OPAQUE_REFERENCE.pattern)
        self.assertEqual(bundle.SENSITIVE_MARKERS, core._SENSITIVE_MARKERS)
        self.assertEqual([(p.pattern, p.flags) for p in bundle.SECRET_VALUE_PATTERNS],
                         [(p.pattern, p.flags) for p in (core._COMMON_SECRET_PREFIX, core._PLATFORM_SECRET_PREFIX,
                                                         core._AWS_ACCESS_KEY, core._GOOGLE_API_KEY)])

    def test_more_than_four_units_need_a_spawn_plan(self) -> None:
        nodes = [node(f"part{index}", scope=(f"src/part{index}.py",)) for index in range(5)]
        plan = {field: "five disjoint files" for field in dag_tool.SPAWN_PLAN_FIELDS}
        with homes() as home:
            slots_table(home)
            choose(home, "codex")
            call(action="define", run="feat", nodes=nodes)
            refused = call(action="export", run="feat", owner="codex")
            exported = call(action="export", run="feat", owner="codex", spawn_plan=plan)
        self.assertEqual(refused["reason"], "spawn_plan_required")
        self.assertEqual(exported["status"], "ok", exported)

    def test_constants_held_against_the_router_and_the_fanout_contract(self) -> None:
        self.assertEqual(dag_tool.OWNER_PREFERENCE_FILE, owner_preference.OWNER_PREFERENCE_PATH_SEGMENTS)
        self.assertEqual(dag_tool.OWNER_PREFERENCE_SCHEMA, owner_preference.OWNER_PREFERENCE_SCHEMA_VERSION)
        self.assertEqual(dag_tool.OWNER_PROVENANCES, owner_preference.OWNER_PREFERENCE_EXPLICIT_CHOICE_PROVENANCES)
        self.assertEqual(dag_tool.OWNER_ROUTE_FAMILY, OWNER_PREFERENCE_ROUTE_FAMILY)
        self.assertEqual(set(dag_tool.EXTERNAL_OWNERS), set(EXTERNAL_CLI_PROFILES))
        self.assertEqual(dag_tool.SPAWN_PLAN_THRESHOLD, FANOUT_SPAWN_PLAN_THRESHOLD)
        self.assertEqual(dag_tool.SPAWN_PLAN_FIELDS, FANOUT_SPAWN_PLAN_FIELDS)


class StateDbTests(unittest.TestCase):
    def test_the_slot_read_is_read_only(self) -> None:
        with homes() as home:
            slots_table(home, running=[("deleg_a", os.getpid())])
            before = home.hermes.joinpath("state.db").read_bytes()
            dag_tool.free_slots(home.hermes)
            self.assertEqual(home.hermes.joinpath("state.db").read_bytes(), before)
            connection = sqlite3.connect(home.hermes / "state.db")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM async_delegations").fetchone()[0], 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()

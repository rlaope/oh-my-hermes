"""The signed metadata-only `cell_trace` of a paired-run Hermes child.

A fake `hermes` serves the arm home the way `tests/test_paired_run_arm_home.py`
does, and its chat writes a Hermes-shaped `state.db` row set with known
counts, tool calls and prompt text. The trace must carry the counts and names
and none of the text, be signed, fail verification when tampered with, and be
null -- never zero -- when the store is missing, locked, or holds no row of
this child.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import textwrap
from typing import Callable, cast
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.hermes_child_dispatch import (  # noqa: E402
    HermesChildObservation,
    HermesChildRequest,
    dispatch_hermes_child,
)
from omh.coding.hermes_child_receipts import (  # noqa: E402
    ReceiptVerificationError,
    load_hermes_child_receipt,
    write_signed_observation,
)
from omh.coding.hermes_child_trace import (  # noqa: E402
    CELL_TRACE_FIELDS,
    CellTrace,
    cell_trace_errors,
    read_hermes_child_trace,
)
from omh.coding.paired_run_arm_home import prepare_arm_home, validate_provider_config  # noqa: E402
from omh.coding.routing_observation import (  # noqa: E402
    authenticate_child_observation,
    build_routing_observation,
    validate_routing_observation,
)

KEY_ENV = "OMH_TEST_PAIRED_PROVIDER_KEY"
SECRET_PROMPT = "CELL-PROMPT-BODY-7f3a fix the roman numeral parser"
SYSTEM_PROMPT = "SYSTEM-PROMPT-BODY-91c2 you are Hermes"
REPLY = "REPLY-BODY-55d0 done"
TOOL_ARGUMENT = "ARGUMENT-BODY-a8e1"

# Shared by the fake child process and the in-process tests.
_WRITER = r'''
import json, sqlite3, time
def write_state(path, session_id, prompt, *, api_calls, tokens, tool_calls, wal=True, system_prompt=None):
    db = sqlite3.connect(path)
    if wal:
        db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS system_prompts (hash TEXT PRIMARY KEY, prompt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL,
        system_prompt TEXT, system_prompt_hash TEXT, api_call_count INTEGER DEFAULT 0,
        input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0,
        cache_write_tokens INTEGER DEFAULT 0, reasoning_tokens INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        role TEXT NOT NULL, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,
        timestamp REAL NOT NULL, api_content TEXT);
    """)
    if system_prompt is not None:
        db.execute("INSERT OR IGNORE INTO system_prompts VALUES (?, ?)", ("h-" + session_id, system_prompt))
    db.execute(
        "INSERT INTO sessions (id, source, started_at, system_prompt, system_prompt_hash, api_call_count, input_tokens,"
        " output_tokens, cache_read_tokens, reasoning_tokens) VALUES (?, 'cli', ?, NULL, ?, ?, ?, ?, ?, ?)",
        (session_id, time.time(), "h-" + session_id if system_prompt is not None else None, api_calls, *tokens),
    )
    now = time.time()
    db.execute("INSERT INTO messages (session_id, role, content, api_content, timestamp) VALUES (?, 'user', ?, ?, ?)",
               (session_id, prompt, prompt + " [injected context]", now))
    for batch in tool_calls:
        calls = [{"id": "c%d" % i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                 for i, (name, args) in enumerate(batch)]
        db.execute("INSERT INTO messages (session_id, role, content, tool_calls, timestamp) VALUES (?, 'assistant', ?, ?, ?)",
                   (session_id, "thinking about it", json.dumps(calls), now))
        for name, _args in batch:
            db.execute("INSERT INTO messages (session_id, role, content, tool_name, timestamp) VALUES (?, 'tool', ?, ?, ?)",
                       (session_id, "tool result body", name, now))
    db.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, 'assistant', ?, ?)",
               (session_id, "REPLY-BODY-55d0 done", now))
    db.commit()
    db.close()
'''

CELL_TOOL_CALLS = [
    [("skill_view", {"name": "omh-app-debugging"})],
    [("read_file", {"path": "ARGUMENT-BODY-a8e1"}), ("search_files", {"pattern": "x"})],
    [("skill_view", {"name": "omh-verification-gate", "file_path": "references/x.md"})],
    [("patch", {"path": "roman.py", "old_string": "ARGUMENT-BODY-a8e1", "new_string": "y"})],
]

_FAKE = r'''
import json, os, subprocess, sys, time
from pathlib import Path
%(writer)s
root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
home = Path(os.environ["HERMES_HOME"])
if args[:2] == ["gateway", "run"]:
    (home / "gateway.pid").write_text(str(os.getpid()))
    while True:
        time.sleep(0.2)
prompt = sys.stdin.read()
if (root / "no-db").exists():
    print("done")
    sys.exit(0)
if "READY" in prompt:
    write_state(home / "state.db", "warmup-session", prompt, api_calls=9, tokens=(900, 90, 0, 0),
                tool_calls=[[("terminal", {"command": "x"})]], system_prompt="warm")
    sys.exit(0)
write_state(home / "state.db", "cell-session", prompt, api_calls=4, tokens=(1200, 300, 800, 0),
            tool_calls=%(calls)s, system_prompt=%(system)r)
print(%(reply)r)
''' % {"writer": _WRITER, "calls": repr(CELL_TOOL_CALLS), "system": SYSTEM_PROMPT, "reply": REPLY}

_NAMESPACE: dict[str, object] = {}
exec(_WRITER, _NAMESPACE)  # noqa: S102 - the same writer the fake child runs
write_state = cast(Callable[..., None], _NAMESPACE["write_state"])

EXPECTED_TOOLS = ["skill_view", "read_file", "search_files", "skill_view", "patch"]


def _route() -> dict[str, object]:
    return {"selected_model": "p/m", "selected_reasoning_effort": "low", "role": "agent_maintainer",
            "executor_profile": "hermes_child", "chain": []}


def _sign(omh_home: Path, terminal: HermesChildObservation, **extra: object) -> Path:
    run_dir = omh_home / "coding" / "hermes-child" / terminal.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = build_routing_observation(
        route=_route(),
        child_dispatch=authenticate_child_observation({"status": terminal.status, "run_id": terminal.run_id}),
        run_id=terminal.run_id,
    )
    payload.update(extra)
    write_signed_observation(run_dir, payload, terminal)
    return run_dir


@unittest.skipIf(os.name == "nt", "POSIX process groups")
class CellTraceDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory(prefix="omh-cell-trace-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(f"#!{sys.executable}\n" + textwrap.dedent(_FAKE).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.parent = self.root / "arms"
        self.parent.mkdir()
        self.env = {"PATH": os.environ.get("PATH", os.defpath), KEY_ENV: "test-key-value"}
        provider = validate_provider_config(
            "claude-proxy", "http://127.0.0.1:8317/v1", "chat_completions", KEY_ENV, env=self.env
        )
        self.arm = prepare_arm_home(
            "variant", provider="claude-proxy", model="claude-sonnet-5-5", reasoning="low",
            hermes=str(self.hermes), provider_config=provider, exposed_skills=("app-debugging",),
            omh_plugin=True, parent=self.parent, ready_seconds=10, warmup_timeout_seconds=10, env=self.env,
        )
        self.addCleanup(self.arm.close)
        self.omh_home = self.root / ".omh"

    def _dispatch(self, **request: object) -> list[HermesChildObservation]:
        events: list[HermesChildObservation] = []
        fields: dict[str, object] = {
            "prompt": SECRET_PROMPT, "model": "claude-sonnet-5-5", "provider": "claude-proxy", "reasoning": "low",
            "parent_run_id": "decision", "run_id": "cell-1", "timeout_seconds": 10, "hermes": str(self.hermes),
            "cwd": self.root, "env": self.env, "allow_parallel": True, "arm_home": self.arm.arm_home,
        }
        fields.update(request)
        dispatch_hermes_child(
            HermesChildRequest(**fields),  # type: ignore[arg-type]
            dispatch_policy="ask_before_dispatch", confirmed=True, observe=events.append,
        )
        return events

    def test_trace_counts_only_this_cells_rows_and_is_signed_without_text(self) -> None:
        events = self._dispatch()
        terminal = events[-1]
        self.assertEqual(terminal.status, "completed")
        self.assertTrue(all(event.cell_trace is None for event in events[:-1]), "only the terminal event carries it")
        trace = terminal.cell_trace
        assert trace is not None
        # The warm-up row (9 calls, terminal) is the home's prior session and stays out.
        self.assertEqual(trace.session_count, 1)
        self.assertEqual(trace.api_call_count, 4)
        self.assertEqual((trace.input_tokens, trace.output_tokens, trace.total_tokens), (1200, 300, 1500))
        self.assertEqual(trace.cache_read_tokens, 800)
        self.assertEqual(trace.tool_names, tuple(EXPECTED_TOOLS))
        self.assertEqual(trace.tool_call_count, 5)
        self.assertEqual(trace.skill_view_count, 2)
        self.assertEqual(trace.skill_view_names, ("omh-app-debugging", "omh-verification-gate"))
        self.assertEqual(trace.system_prompt_chars, len(SYSTEM_PROMPT))
        self.assertEqual(trace.first_request_chars, len(SECRET_PROMPT + " [injected context]"))

        run_dir = _sign(self.omh_home, terminal)
        receipt = load_hermes_child_receipt(self.omh_home, "cell-1")
        self.assertEqual(receipt.cell_trace, trace)
        raw = (run_dir / "observation.json").read_text(encoding="utf-8")
        self.assertEqual(set(json.loads(raw)["cell_trace"]), CELL_TRACE_FIELDS)
        for text in (SECRET_PROMPT, "CELL-PROMPT-BODY", SYSTEM_PROMPT, "SYSTEM-PROMPT-BODY", "REPLY-BODY",
                     TOOL_ARGUMENT, "tool result body", "thinking about it", "roman.py"):
            self.assertNotIn(text, raw)

    def test_tampered_trace_fails_verification(self) -> None:
        run_dir = _sign(self.omh_home, self._dispatch()[-1])
        path = run_dir / "observation.json"
        observation = json.loads(path.read_text())
        observation["cell_trace"]["api_call_count"] = 1
        path.write_text(json.dumps(observation))
        with self.assertRaises(ReceiptVerificationError):
            load_hermes_child_receipt(self.omh_home, "cell-1")

    def test_a_removed_trace_fails_verification(self) -> None:
        run_dir = _sign(self.omh_home, self._dispatch()[-1])
        path = run_dir / "observation.json"
        observation = json.loads(path.read_text())
        del observation["cell_trace"]
        path.write_text(json.dumps(observation))
        with self.assertRaises(ReceiptVerificationError):
            load_hermes_child_receipt(self.omh_home, "cell-1")

    def test_a_caller_trace_never_survives(self) -> None:
        forged = CellTrace(1, 0, 0, 0, 0, 0, 0, 0, 0, (), False, 0, (), None, None).to_record()
        terminal = self._dispatch()[-1]
        _sign(self.omh_home, terminal, cell_trace=forged)
        self.assertEqual(load_hermes_child_receipt(self.omh_home, "cell-1").cell_trace, terminal.cell_trace)
        _sign(self.omh_home, replace(terminal, cell_trace=None), cell_trace=forged)
        self.assertIsNone(load_hermes_child_receipt(self.omh_home, "cell-1").cell_trace)

    def test_a_child_that_wrote_no_row_has_a_null_trace_not_zeros(self) -> None:
        (self.root / "no-db").write_text("1")
        terminal = self._dispatch()[-1]
        self.assertEqual(terminal.status, "completed")
        self.assertIsNone(terminal.cell_trace)
        _sign(self.omh_home, terminal)
        self.assertNotIn("cell_trace", json.loads(
            (self.omh_home / "coding" / "hermes-child" / "cell-1" / "observation.json").read_text()))

    def test_a_child_without_an_arm_home_records_no_trace(self) -> None:
        events = self._dispatch(arm_home=None, run_id="plain-1")
        self.assertIsNone(events[-1].cell_trace)


class CellTraceReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory(prefix="omh-cell-trace-reader-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.db = self.home / "state.db"

    def test_missing_store_is_null(self) -> None:
        self.assertIsNone(read_hermes_child_trace(self.home))

    def test_store_that_is_not_a_database_is_null(self) -> None:
        self.db.write_bytes(b"not a database at all, just bytes" * 10)
        self.assertIsNone(read_hermes_child_trace(self.home))

    def test_store_with_only_excluded_rows_is_null(self) -> None:
        write_state(self.db, "s1", "p", api_calls=2, tokens=(1, 1, 0, 0), tool_calls=[])
        self.assertIsNone(read_hermes_child_trace(self.home, exclude=frozenset({"s1"})))

    def test_locked_store_is_null(self) -> None:
        write_state(self.db, "s1", "p", api_calls=2, tokens=(1, 1, 0, 0), tool_calls=[], wal=False)
        holder = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("UPDATE sessions SET api_call_count = 3")
        self.assertTrue(self.db.with_name("state.db-journal").exists())
        self.assertIsNone(read_hermes_child_trace(self.home))
        holder.execute("ROLLBACK")
        trace = read_hermes_child_trace(self.home)
        assert trace is not None
        self.assertEqual(trace.api_call_count, 2)

    def test_read_creates_no_file_beside_a_closed_wal_store(self) -> None:
        write_state(self.db, "s1", "p", api_calls=1, tokens=(1, 1, 0, 0), tool_calls=[])
        before = sorted(path.name for path in self.home.iterdir())
        self.assertIsNotNone(read_hermes_child_trace(self.home))
        self.assertEqual(sorted(path.name for path in self.home.iterdir()), before)

    def test_missing_messages_table_nulls_only_its_fields(self) -> None:
        db = sqlite3.connect(self.db)
        db.execute("CREATE TABLE sessions (id TEXT, started_at REAL, api_call_count INTEGER, input_tokens INTEGER,"
                   " output_tokens INTEGER)")
        db.execute("INSERT INTO sessions VALUES ('s1', 1.0, 3, 10, 5)")
        db.commit()
        db.close()
        trace = read_hermes_child_trace(self.home)
        assert trace is not None
        self.assertEqual((trace.api_call_count, trace.total_tokens), (3, 15))
        self.assertIsNone(trace.cache_read_tokens)
        self.assertIsNone(trace.tool_names)
        self.assertIsNone(trace.tool_call_count)
        self.assertIsNone(trace.skill_view_names)
        self.assertIsNone(trace.system_prompt_chars)
        self.assertIsNone(trace.first_request_chars)
        self.assertEqual(cell_trace_errors(trace.to_record()), [])

    def test_unsafe_names_are_replaced_and_unparseable_calls_null_the_tool_fields(self) -> None:
        write_state(self.db, "s1", "p", api_calls=1, tokens=(1, 1, 0, 0), tool_calls=[
            [("skill_view", {"name": "sk-live-abcdefghijklmnop"}), ("bad name\nwith body", {})],
            [("skill_view", "not json"), ("terminal", {})],
        ])
        trace = read_hermes_child_trace(self.home)
        assert trace is not None
        self.assertEqual(trace.tool_names, ("skill_view", "unrecognized", "skill_view", "terminal"))
        self.assertEqual(trace.skill_view_names, ("unrecognized", "unrecognized"))
        db = sqlite3.connect(self.db)
        db.execute("UPDATE messages SET tool_calls = '[{broken' WHERE id = (SELECT MIN(id) FROM messages"
                   " WHERE tool_calls IS NOT NULL)")
        db.commit()
        db.close()
        broken = read_hermes_child_trace(self.home)
        assert broken is not None
        self.assertIsNone(broken.tool_names)
        self.assertIsNone(broken.skill_view_count)
        self.assertEqual(broken.api_call_count, 1)

    def test_compression_rotation_rows_are_summed_in_order(self) -> None:
        write_state(self.db, "s1", "p", api_calls=2, tokens=(10, 1, 0, 0), tool_calls=[[("read_file", {})]])
        write_state(self.db, "s2", "p2", api_calls=3, tokens=(20, 2, 0, 0), tool_calls=[[("patch", {})]])
        trace = read_hermes_child_trace(self.home)
        assert trace is not None
        self.assertEqual((trace.session_count, trace.api_call_count, trace.total_tokens), (2, 5, 33))
        self.assertEqual(trace.tool_names, ("read_file", "patch"))
        self.assertEqual(trace.first_request_chars, len("p [injected context]"))


class CellTraceSchemaTests(unittest.TestCase):
    def _observed(self) -> dict[str, object]:
        return build_routing_observation(
            route=_route(),
            child_dispatch=authenticate_child_observation({"status": "completed", "run_id": "r"}),
            run_id="r",
        )

    def _trace(self, **changes: object) -> dict[str, object]:
        record = CellTrace(1, 2, 3, 4, 0, 0, 0, 7, 1, ("read_file",), False, 0, (), None, 12).to_record()
        record.update(changes)
        return record

    def test_valid_trace_is_accepted_on_an_observed_claim_only(self) -> None:
        observed = {**self._observed(), "cell_trace": self._trace()}
        self.assertEqual(validate_routing_observation(observed), [])
        prepared = build_routing_observation(route=_route(), run_id="r")
        prepared["cell_trace"] = self._trace()
        self.assertIn("cell_trace requires an observed claim", validate_routing_observation(prepared))

    def test_shape_refusals(self) -> None:
        cases = (
            self._trace(api_call_count=-1),
            self._trace(input_tokens=True),
            self._trace(session_count=None),
            self._trace(tool_names_truncated=None),
            self._trace(tool_names=["read_file\nprompt body"]),
            self._trace(tool_names=["x"] * 201),
            self._trace(skill_view_names="omh-x"),
            {**self._trace(), "prompt": "body"},
            {key: value for key, value in self._trace().items() if key != "first_request_chars"},
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertTrue(cell_trace_errors(value))
                self.assertTrue(validate_routing_observation({**self._observed(), "cell_trace": value}))


if __name__ == "__main__":
    unittest.main()

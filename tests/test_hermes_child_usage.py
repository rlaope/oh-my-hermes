from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding._hermes_child_usage import (  # noqa: E402
    read_hermes_child_usage,
    summarize_session_rows,
)

# The `sessions` columns the reader names, shaped as Hermes declares them
# (`hermes_state_common.py`); everything else in the real table is irrelevant
# to the read and left out here.
_SESSIONS_DDL = (
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT,"
    " parent_session_id TEXT, started_at REAL NOT NULL, ended_at REAL, title TEXT,"
    " input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,"
    " cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0,"
    " reasoning_tokens INTEGER DEFAULT 0, billing_provider TEXT, estimated_cost_usd REAL,"
    " cost_status TEXT, cost_source TEXT, api_call_count INTEGER DEFAULT 0)"
)
_INSERT = (
    "INSERT INTO sessions (id, source, model, parent_session_id, started_at, title,"
    " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,"
    " billing_provider, estimated_cost_usd, cost_status, cost_source, api_call_count)"
    " VALUES (:id, 'oneshot', :model, :parent, :started_at, 'SECRET_TITLE_MUST_NOT_ESCAPE',"
    " :input, :output, :cache_read, :cache_write, :reasoning, :provider, :cost,"
    " :cost_status, :cost_source, :api_calls)"
)


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "20260925_000000_abc123", "model": "qwen3-coder-next", "parent": None,
        "started_at": 1.0, "input": 11, "output": 7, "cache_read": 3, "cache_write": 0,
        "reasoning": 2, "provider": "qwen", "cost": 0.125, "cost_status": "estimated",
        "cost_source": "official_docs_snapshot", "api_calls": 1,
    }
    row.update(changes)
    return row


class HermesChildUsageReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-hermes-child-usage-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def write_rows(self, *rows: dict[str, object], ddl: str = _SESSIONS_DDL) -> None:
        with closing(sqlite3.connect(self.home / "state.db")) as db, db:
            db.execute(ddl)
            for row in rows:
                db.execute(_INSERT, row)

    def test_one_finished_turn_reads_as_the_usage_file_vocabulary(self) -> None:
        self.write_rows(_row())
        self.assertEqual(
            read_hermes_child_usage(self.home),
            {
                "input_tokens": 11, "output_tokens": 7, "cache_read_tokens": 3,
                "cache_write_tokens": 0, "reasoning_tokens": 2, "total_tokens": 18,
                "api_calls": 1, "estimated_cost_usd": 0.125, "model": "qwen3-coder-next",
                "provider": "qwen", "cost_status": "estimated",
                "cost_source": "official_docs_snapshot",
            },
        )

    def test_absent_unreadable_or_differently_shaped_ledgers_read_as_no_usage(self) -> None:
        cases = {
            "missing": lambda: None,
            "not_a_database": lambda: (self.home / "state.db").write_text("ephemeral", encoding="utf-8"),
            "empty_file": lambda: (self.home / "state.db").write_bytes(b""),
            "no_sessions_table": lambda: self.write_rows(ddl="CREATE TABLE messages (id INTEGER PRIMARY KEY)"),
            "columns_missing": lambda: self.write_rows(
                ddl="CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL)"
            ),
            "no_rows": lambda: self.write_rows(),
        }
        for name, arrange in cases.items():
            with self.subTest(case=name):
                (self.home / "state.db").unlink(missing_ok=True)
                arrange()
                self.assertEqual(read_hermes_child_usage(self.home), {})

    def test_a_child_that_reached_no_provider_has_no_usage_rather_than_zeros(self) -> None:
        # Hermes creates the row at session start; a start it refuses before
        # the first API call leaves every counter at its default. Absent,
        # never zero (AGENTS.md, Reporting Our Own Numbers).
        self.write_rows(_row(input=0, output=0, cache_read=0, reasoning=0, cost=None,
                             cost_status=None, cost_source=None, api_calls=0))
        self.assertEqual(read_hermes_child_usage(self.home), {})

    def test_every_row_in_the_disposable_home_is_summed_and_the_latest_route_wins(self) -> None:
        # A context-compression rotation opens a second row under the first
        # and the later API calls land there; the home belongs to this child
        # alone, so the sum is the child's spend, as the agent's own
        # cumulative counters (the `-z` report's source) would have said.
        self.write_rows(
            _row(id="20260925_000000_parent", started_at=1.0, cost_status="unknown", cost_source="none",
                 cost=0.0, input=100, output=20, api_calls=2),
            _row(id="20260925_000100_child0", parent="20260925_000000_parent", started_at=2.0,
                 input=30, output=5, cache_read=0, reasoning=0, cost=0.5, api_calls=1,
                 model="qwen3-coder-next-rotated", cost_status="estimated",
                 cost_source="provider_models_api"),
        )
        usage = read_hermes_child_usage(self.home)
        self.assertEqual(
            (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"], usage["api_calls"]),
            (130, 25, 155, 3),
        )
        self.assertEqual(usage["estimated_cost_usd"], 0.5)
        self.assertEqual(
            (usage["model"], usage["cost_status"], usage["cost_source"]),
            ("qwen3-coder-next-rotated", "estimated", "provider_models_api"),
        )

    def test_delegate_child_rows_sum_their_counts_but_report_no_cost(self) -> None:
        # Hermes folds a delegate child's cost into the parent's running total,
        # so parent + child rows may count the child twice: the cost is left
        # out (unmeasured), never doubled. Counts are per-row deltas and sum.
        db_rows = (
            _row(id="parent", started_at=1.0, cost=0.75, input=100, output=20, api_calls=2),
            _row(id="child", parent="parent", started_at=2.0, cost=0.5, input=30, output=5, api_calls=1),
        )
        with closing(sqlite3.connect(self.home / "state.db")) as db, db:
            db.execute(_SESSIONS_DDL)
            for row in db_rows:
                db.execute(_INSERT, row)
            db.execute("UPDATE sessions SET source = 'subagent' WHERE id = 'child'")
        usage = read_hermes_child_usage(self.home)
        self.assertEqual((usage["input_tokens"], usage["output_tokens"], usage["api_calls"]), (130, 25, 3))
        for key in ("estimated_cost_usd", "cost_status", "cost_source"):
            self.assertNotIn(key, usage)
        self.assertEqual(usage["model"], "qwen3-coder-next")

    def test_an_excluded_subagent_row_does_not_withhold_the_cell_cost(self) -> None:
        with closing(sqlite3.connect(self.home / "state.db")) as db, db:
            db.execute(_SESSIONS_DDL)
            db.execute(_INSERT, _row(id="old-child", started_at=0.5))
            db.execute(_INSERT, _row(id="cell", started_at=1.0))
            db.execute("UPDATE sessions SET source = 'subagent' WHERE id = 'old-child'")
        usage = read_hermes_child_usage(self.home, exclude=frozenset({"old-child"}))
        self.assertEqual(usage["estimated_cost_usd"], 0.125)

    def test_without_subagent_rows_the_summary_is_unchanged(self) -> None:
        rows = [(11, 7, 3, 0, 2, 1, 0.125, "m", "p", "estimated", "src")]
        self.assertEqual(summarize_session_rows(rows), summarize_session_rows(rows, has_subagents=False))
        self.assertEqual(summarize_session_rows(rows)["estimated_cost_usd"], 0.125)
        withheld = summarize_session_rows(rows, has_subagents=True)
        self.assertEqual(
            {key: value for key, value in summarize_session_rows(rows).items()
             if key not in ("estimated_cost_usd", "cost_status", "cost_source")},
            withheld,
        )

    def test_an_unpriced_route_keeps_hermes_zero_with_the_status_that_explains_it(self) -> None:
        # Hermes stores `COALESCE(estimated_cost_usd, 0) + COALESCE(delta, 0)`
        # per call, so an unpriced route reads 0.0 with `cost_status`
        # `unknown`; both travel, and the renderer already declines to print
        # a bare zero (`_cost_metric` in routing_observation).
        self.write_rows(_row(cost=0.0, cost_status="unknown", cost_source="none"))
        usage = read_hermes_child_usage(self.home)
        self.assertEqual(
            (usage["estimated_cost_usd"], usage["cost_status"], usage["cost_source"]),
            (0.0, "unknown", "none"),
        )

    def test_a_ledger_that_never_priced_carries_no_cost_key(self) -> None:
        self.write_rows(_row(cost=None, cost_status=None, cost_source=None))
        usage = read_hermes_child_usage(self.home)
        self.assertNotIn("estimated_cost_usd", usage)
        self.assertNotIn("cost_status", usage)
        self.assertNotIn("cost_source", usage)
        self.assertEqual(usage["total_tokens"], 18)

    def test_text_columns_are_bounded_and_screened_like_the_usage_file_was(self) -> None:
        self.write_rows(_row(
            model="sk-live-abcdefghijklmnopqrstuvwxyz0123456789",
            provider="p" * 201,
            cost_source="authorization header route",
        ))
        usage = read_hermes_child_usage(self.home)
        self.assertNotIn("model", usage)
        self.assertNotIn("provider", usage)
        self.assertNotIn("cost_source", usage)
        self.assertEqual((usage["cost_status"], usage["total_tokens"]), ("estimated", 18))
        self.assertNotIn("SECRET_TITLE", repr(usage))

    def test_values_that_are_not_counts_or_amounts_are_ignored_not_repaired(self) -> None:
        # Column order of the reader's SELECT: the five token counters,
        # api_call_count, estimated_cost_usd, model, billing_provider,
        # cost_status, cost_source.
        rows = [
            (-5, 7, 3, 0, 2, 1, -0.25, "m", "p", "estimated", "src"),
            (1.5, "7", None, True, 2, 1, math.nan, 7, None, "", "src"),
        ]
        usage = summarize_session_rows(rows)
        self.assertEqual(
            (usage["input_tokens"], usage["output_tokens"], usage["cache_read_tokens"],
             usage["cache_write_tokens"], usage["reasoning_tokens"], usage["api_calls"]),
            (0, 7, 3, 0, 4, 2),
        )
        self.assertNotIn("estimated_cost_usd", usage)
        self.assertEqual((usage["model"], usage["provider"]), ("m", "p"))

    def test_api_call_count_alone_decides_whether_anything_was_measured(self) -> None:
        self.assertEqual(summarize_session_rows([(11, 7, 0, 0, 0, 0, 0.5, "m", "p", "estimated", "s")]), {})
        self.assertEqual(summarize_session_rows([(11, 7, 0, 0, 0, None, 0.5, "m", "p", "estimated", "s")]), {})
        self.assertEqual(summarize_session_rows([]), {})


if __name__ == "__main__":
    unittest.main()

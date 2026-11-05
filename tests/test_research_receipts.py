"""Contracts for fetch receipts: which URLs a session's web tools really opened.

A citation ledger can name a URL the model never opened. `post_tool_call`
sees every web tool result, so it writes one metadata-only
`research_fetch_receipt/v1` line per URL a successful `web_extract`,
`browser_navigate` or `web_search` returned. These pin, through the
registered hook:

* what is recorded (`fetched` for an opened page, `search_listed` for a
  search hit) and what is not (an errored entry, a failed or blocked call,
  every other tool);
* where it goes: the dispatching session's own file, so a child's calls land
  in the child's file;
* what it holds: a `url_key` equal to the grounded-citations normalization,
  and never page text, a title, a query value or the tool arguments;
* that it never raises and stays fast: a busy lock is the 0.1 s telemetry
  wait, and a young file is never read back;
* that a refused write is counted (`receipt_declines` and the session's
  `.refused` sidecar), that a torn last line does not swallow the next
  receipt, and that files untouched for 30 days are pruned.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import research_receipts
from omh.plugin_bundle.omh.awareness_delivery import _awareness_delivery_lock
from omh.plugin_bundle.omh.delegation_ledger import ledger_key
from omh.plugin_bundle.omh.hooks.tool_hooks import post_tool_call
from omh.plugin_bundle.omh.research_receipts import (
    PRUNE_INTERVAL_SECONDS,
    RECEIPT_FIELDS,
    RECEIPT_LINE_FLOOR_BYTES,
    RECEIPT_LINE_LIMIT,
    RECEIPT_LOCK_SECONDS,
    RECEIPT_MAX_AGE_SECONDS,
    RECEIPT_SCHEMA_VERSION,
    prune_receipts,
    receipt_declines,
    receipt_path,
    record_fetch_receipts,
    refusal_path,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research_receipts"
PARENT = "20261104_101010_parent"
CHILD = "20261104_101011_child"
SENTINELS = ("BODY-SAMPLE-SENTINEL", "TITLE-SENTINEL", "SECRET-QUERY-VALUE", "ARGS-SENTINEL")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def oracle_url_key(url: str) -> str:
    """grounded-citations `sources.py` `normalize_url`, copied independently, then sha256."""
    u = (url or "").strip()
    if "#" in u:
        u = u.split("#", 1)[0]
    stripped = u.rstrip("/")
    return hashlib.sha256((stripped or u).encode("utf-8")).hexdigest()


class _ReceiptHomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "omh"
        self.hermes = Path(self._tmp.name) / "hermes"
        self.hermes.mkdir(parents=True)
        env = patch.dict(os.environ, {"OMH_HOME": str(self.home), "HERMES_HOME": str(self.hermes)})
        env.start()
        self.addCleanup(env.stop)
        self._call = 0

    def call(self, tool: str, result: str, *, session: str = PARENT, status: str = "ok", args=None):
        self._call += 1
        return post_tool_call(
            tool_name=tool,
            args={"urls": ["https://example.org/?q=ARGS-SENTINEL"]} if args is None else args,
            result=result,
            status=status,
            session_id=session,
            tool_call_id=f"call-{self._call}",
            turn_id="turn-1",
            duration_ms=12,
            omh_home=str(self.home),
            hermes_home=str(self.hermes),
        )

    def lines(self, session: str = PARENT) -> list[dict]:
        path = receipt_path(self.home, session)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def receipt_dir(self) -> Path:
        return self.home / "runtime" / "research_receipts"


class ReceiptRecordingTests(_ReceiptHomeTest):
    def test_a_three_url_web_extract_writes_three_fetched_lines(self) -> None:
        self.assertIsNone(self.call("web_extract", fixture("web_extract_three.json")))
        lines = self.lines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertEqual(tuple(sorted(line)), tuple(sorted(RECEIPT_FIELDS)))
            self.assertEqual(line["schema_version"], RECEIPT_SCHEMA_VERSION)
            self.assertEqual(line["kind"], "fetched")
            self.assertEqual(line["tool"], "web_extract")
            self.assertEqual(line["session_id"], PARENT)
            self.assertEqual(line["tool_call_id"], "call-1")
            self.assertEqual(line["turn_id"], "turn-1")
            self.assertEqual(len(line["content_sha256"]), 64)
            self.assertGreater(line["content_chars"], 0)
        self.assertEqual(
            [line["url_display"] for line in lines],
            ["https://example.org/paper/one", "https://example.org/paper/two/", "https://docs.example.com/three"],
        )
        mode = stat.S_IMODE(receipt_path(self.home, PARENT).stat().st_mode)
        if os.name != "nt":
            self.assertEqual(mode, 0o600)

    def test_b_an_errored_entry_is_skipped(self) -> None:
        self.call("web_extract", fixture("web_extract_one_error.json"))
        self.assertEqual([line["url_display"] for line in self.lines()], ["https://example.org/ok"])

    def test_c_the_file_holds_no_body_title_query_value_or_args(self) -> None:
        self.call("web_extract", fixture("web_extract_three.json"))
        self.call("web_search", fixture("web_search.json"))
        self.call("browser_navigate", fixture("browser_navigate.json"))
        raw = receipt_path(self.home, PARENT).read_text(encoding="utf-8")
        self.assertEqual(len(self.lines()), 6)
        for sentinel in SENTINELS:
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, raw)
        self.assertNotIn("?", raw)
        self.assertNotIn("#", raw)

    def test_d_other_tools_write_nothing(self) -> None:
        for tool, result in (
            ("delegate_task", json.dumps({"results": [{"url": "https://example.org/x"}]})),
            ("terminal", json.dumps({"output": "https://example.org/x", "exit_code": 0})),
            ("read_file", json.dumps({"content": "https://example.org/x"})),
        ):
            with self.subTest(tool=tool):
                self.call(tool, result)
                self.assertEqual(
                    record_fetch_receipts(
                        tool_name=tool, args={}, result=result, status="ok", session_id=PARENT,
                        tool_call_id="c", turn_id="t", omh_home=str(self.home),
                    ),
                    "not_web_tool",
                )
        self.assertFalse(self.receipt_dir().exists())

    def test_e_a_child_session_writes_the_child_key_file(self) -> None:
        self.call("web_extract", fixture("web_extract_three.json"), session=CHILD)
        self.assertEqual(self.lines(PARENT), [])
        self.assertEqual(len(self.lines(CHILD)), 3)
        self.assertEqual(
            sorted(path.name for path in self.receipt_dir().glob("*.jsonl")), [f"{ledger_key(CHILD)}.jsonl"]
        )
        self.assertTrue(all(line["session_id"] == CHILD for line in self.lines(CHILD)))

    def test_e_a_model_supplied_session_argument_cannot_choose_the_file(self) -> None:
        self.call("web_extract", fixture("web_extract_three.json"), args={"session_id": CHILD})
        self.assertEqual(self.lines(CHILD), [])
        self.assertEqual(len(self.lines(PARENT)), 3)

    def test_f_error_and_blocked_calls_write_nothing(self) -> None:
        for status in ("error", "blocked"):
            with self.subTest(status=status):
                self.call("web_extract", fixture("web_extract_three.json"), status=status)
                self.assertEqual(
                    record_fetch_receipts(
                        tool_name="web_extract", args={}, result=fixture("web_extract_three.json"),
                        status=status, session_id=PARENT, tool_call_id="c", turn_id="t",
                        omh_home=str(self.home),
                    ),
                    "not_ok",
                )
        self.assertFalse(self.receipt_dir().exists())

    def test_g_web_search_writes_search_listed(self) -> None:
        self.call("web_search", fixture("web_search.json"))
        lines = self.lines()
        self.assertEqual([line["kind"] for line in lines], ["search_listed", "search_listed"])
        self.assertEqual([line["url_display"] for line in lines], ["https://example.net/a", "https://example.net/b"])

    def test_browser_navigate_records_the_final_url_as_fetched(self) -> None:
        self.call("browser_navigate", fixture("browser_navigate.json"))
        (line,) = self.lines()
        self.assertEqual((line["kind"], line["url_display"]), ("fetched", "https://example.com/final/landing"))
        self.assertEqual((line["content_sha256"], line["content_chars"]), ("", 0))
        self.assertEqual(
            line["url_key"], oracle_url_key("https://example.com/final/landing?session=SECRET-QUERY-VALUE")
        )

    def test_h_url_key_is_the_sha256_of_the_grounded_citations_normalization(self) -> None:
        self.call("web_extract", fixture("web_extract_three.json"))
        sources = json.loads(fixture("web_extract_three.json"))["results"]
        self.assertEqual([line["url_key"] for line in self.lines()], [oracle_url_key(row["url"]) for row in sources])
        # The query is identity and the fragment and trailing slash are not.
        self.assertEqual(oracle_url_key("https://example.org/paper/two/"), oracle_url_key("https://example.org/paper/two"))
        self.assertNotEqual(
            self.lines()[0]["url_key"], oracle_url_key("https://example.org/paper/one")
        )

    def test_i_a_five_url_call_takes_under_200_ms(self) -> None:
        result = fixture("web_extract_five.json")
        self.call("web_extract", result)  # warm the directory and lock file
        started = time.perf_counter()
        self.call("web_extract", result)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(self.lines()), 10)
        self.assertLess(elapsed, 0.2)

    def test_j_an_unwritable_home_is_refused_without_raising(self) -> None:
        blocked = Path(self._tmp.name) / "not-a-dir"
        blocked.write_text("a file where the home should be\n", encoding="utf-8")
        self.assertEqual(
            record_fetch_receipts(
                tool_name="web_extract", args={}, result=fixture("web_extract_three.json"), status="ok",
                session_id=PARENT, tool_call_id="c", turn_id="t", omh_home=str(blocked),
            ),
            "refused",
        )
        with patch.dict(os.environ, {"OMH_HOME": str(blocked)}):
            self.assertIsNone(
                post_tool_call(
                    tool_name="web_extract", args={}, result=fixture("web_extract_three.json"), status="ok",
                    session_id=PARENT, tool_call_id="c", turn_id="t", omh_home=str(blocked),
                    hermes_home=str(self.hermes),
                )
            )

    def test_the_remaining_labels(self) -> None:
        common = {"args": {}, "status": "ok", "tool_call_id": "c", "turn_id": "t", "omh_home": str(self.home)}
        self.assertEqual(
            record_fetch_receipts(tool_name="web_extract", result="{}", session_id="", **common), "no_session"
        )
        for result in ("not json", json.dumps({"error": "boom"}), json.dumps({"results": [{"error": "x"}]}),
                       json.dumps({"success": False, "data": {"web": [{"url": "https://e.org"}]}})):
            with self.subTest(result=result):
                tool = "web_search" if "success" in result else "web_extract"
                self.assertEqual(
                    record_fetch_receipts(tool_name=tool, result=result, session_id=PARENT, **common), "no_urls"
                )
        self.assertEqual(
            record_fetch_receipts(
                tool_name="browser_navigate", result=json.dumps({"success": False, "url": "https://e.org"}),
                session_id=PARENT, **common,
            ),
            "no_urls",
        )
        self.assertEqual(
            record_fetch_receipts(
                tool_name="web_extract", result=fixture("web_extract_three.json"), session_id=PARENT, **common
            ),
            "recorded",
        )

    def test_the_file_is_bounded_to_the_newest_lines(self) -> None:
        path = receipt_path(self.home, PARENT)
        path.parent.mkdir(parents=True)
        # Receipt-sized lines: the writer only reads a file back once its size could hold the bound.
        pad = "x" * RECEIPT_LINE_FLOOR_BYTES
        path.write_text(
            "".join(json.dumps({"n": n, "pad": pad}) + "\n" for n in range(RECEIPT_LINE_LIMIT - 1)), encoding="utf-8"
        )
        self.call("web_extract", fixture("web_extract_three.json"))
        raw = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw), RECEIPT_LINE_LIMIT)
        self.assertEqual(json.loads(raw[0])["n"], 2)
        self.assertEqual(json.loads(raw[-1])["url_display"], "https://docs.example.com/three")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


    def test_the_shortest_receipt_line_is_longer_than_the_floor(self) -> None:
        """The trim check counts on every line being at least `RECEIPT_LINE_FLOOR_BYTES` long."""
        label = record_fetch_receipts(
            tool_name="browser_navigate", args={}, result=json.dumps({"success": True, "url": "h"}), status="ok",
            session_id="s", tool_call_id="", turn_id="", omh_home=str(self.home),
        )
        self.assertEqual(label, "recorded")
        (line,) = receipt_path(self.home, "s").read_bytes().splitlines(keepends=True)
        self.assertGreater(len(line), RECEIPT_LINE_FLOOR_BYTES)


class ReceiptStoreReviewFixTests(_ReceiptHomeTest):
    def setUp(self) -> None:
        super().setUp()
        saved = dict(receipt_declines)
        receipt_declines.clear()
        self.addCleanup(lambda: (receipt_declines.clear(), receipt_declines.update(saved)))

    def record(self, *, home: Path | None = None, session: str = PARENT) -> str:
        return record_fetch_receipts(
            tool_name="web_extract", args={}, result=fixture("web_extract_three.json"), status="ok",
            session_id=session, tool_call_id="c", turn_id="t", omh_home=str(home or self.home),
        )

    def test_n1_an_unwritable_home_is_refused_and_counted(self) -> None:
        blocked = Path(self._tmp.name) / "not-a-dir"
        blocked.write_text("a file where the home should be\n", encoding="utf-8")
        self.assertEqual(self.record(home=blocked), "refused")
        self.assertEqual(sum(n for key, n in receipt_declines.items() if key.startswith("refused:")), 1)
        # The sidecar cannot be written into a file either; that is counted too, never raised.
        self.assertEqual(sum(n for key, n in receipt_declines.items() if key.startswith("refusal_counter:")), 1)

    def test_n1_a_refused_write_increments_the_session_sidecar(self) -> None:
        path = receipt_path(self.home, PARENT)
        path.parent.mkdir(parents=True)
        path.symlink_to(Path(self._tmp.name) / "elsewhere.jsonl")
        self.assertEqual(self.record(), "refused")
        self.assertEqual(self.record(), "refused")
        self.assertEqual(receipt_declines["refused:OSError"], 2)
        self.assertEqual(refusal_path(self.home, PARENT).read_text(encoding="ascii"), "2\n")
        self.assertFalse((Path(self._tmp.name) / "elsewhere.jsonl").exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(refusal_path(self.home, PARENT).stat().st_mode), 0o600)

    def test_n2_a_busy_lock_refuses_within_the_telemetry_wait(self) -> None:
        self.assertEqual(RECEIPT_LOCK_SECONDS, 0.1)
        path = receipt_path(self.home, PARENT)
        with _awareness_delivery_lock(path, timeout_seconds=0.1):
            started = time.perf_counter()
            label = self.record()
            elapsed = time.perf_counter() - started
        self.assertEqual(label, "refused")
        self.assertEqual(receipt_declines["refused:TimeoutError"], 1)
        self.assertLess(elapsed, 1.0)
        self.assertFalse(path.exists())

    def test_n2_an_append_below_the_bound_never_reads_the_file_back(self) -> None:
        self.assertEqual(self.record(), "recorded")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("read the whole file")):
            self.assertEqual(self.record(), "recorded")
        self.assertEqual(len(self.lines()), 6)

    def test_nit_a_torn_last_line_does_not_swallow_the_next_receipt(self) -> None:
        self.assertEqual(self.record(), "recorded")
        path = receipt_path(self.home, PARENT)
        with path.open("ab") as handle:
            handle.write(b'{"schema_version": "research_fetch_receipt/v1", "kind": "fet')
        self.assertEqual(self.record(), "recorded")
        rows = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 7)
        parsed = []
        for row in rows:
            try:
                parsed.append(json.loads(row))
            except ValueError:
                continue
        self.assertEqual(len(parsed), 6)
        self.assertEqual(parsed[-1]["url_display"], "https://docs.example.com/three")

    def test_n4_files_untouched_for_thirty_days_are_pruned(self) -> None:
        self.assertEqual(RECEIPT_MAX_AGE_SECONDS, 30 * 24 * 3600.0)
        self.assertEqual(self.record(session=PARENT), "recorded")
        self.assertEqual(self.record(session=CHILD), "recorded")
        stale, fresh = receipt_path(self.home, PARENT), receipt_path(self.home, CHILD)
        sidecar = refusal_path(self.home, PARENT)
        sidecar.write_text("3\n", encoding="ascii")
        now = time.time()
        old = now - RECEIPT_MAX_AGE_SECONDS - 60
        os.utime(stale, (old, old))
        os.utime(sidecar, (old, old))
        os.utime(fresh, (now - RECEIPT_MAX_AGE_SECONDS + 3600, now - RECEIPT_MAX_AGE_SECONDS + 3600))
        self.assertEqual(prune_receipts(self.home, now=now), 2)
        self.assertFalse(stale.exists())
        self.assertFalse(sidecar.exists())
        self.assertTrue(fresh.exists())

    def test_n4_a_recorded_write_prunes_at_most_once_an_hour(self) -> None:
        self.assertEqual(PRUNE_INTERVAL_SECONDS, 3600.0)
        self.assertEqual(self.record(session=CHILD), "recorded")
        stale = receipt_path(self.home, CHILD)
        old = time.time() - RECEIPT_MAX_AGE_SECONDS - 60
        os.utime(stale, (old, old))
        with patch.object(research_receipts, "_pruned_at", [time.time()]):
            self.assertEqual(self.record(), "recorded")
            self.assertTrue(stale.exists())  # pruned within the hour already: not again
        with patch.object(research_receipts, "_pruned_at", [0.0]):
            self.assertEqual(self.record(), "recorded")
        self.assertFalse(stale.exists())
        self.assertEqual(len(self.lines()), 6)


if __name__ == "__main__":
    unittest.main()

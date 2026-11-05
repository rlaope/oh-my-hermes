"""Contracts for `omh research receipts verify`: cited sources against fetch receipts.

`sources.py verify` proves a draft cites only ids its grounded-citations
ledger handed out; it cannot prove the URL behind an id was ever opened.
`post_tool_call` writes a `research_fetch_receipt/v1` line for every URL a
session's web tools opened, and this check matches each cited source against
those receipts in the session and in every child its delegation ledger names.
These pin:

* each status (`fetched`, `search_only`, `missing`, `child_unresolved`,
  `not_in_ledger`) from receipts written by the real writer;
* that a session that never delegated (no delegation ledger file) reads
  `missing`, while a ledger that exists but cannot be read never passes
  silently (`child_unresolved`);
* the session tree: earlier compaction segments and their children are
  checked, and an unresolved segment walk is `child_unresolved`;
* the ASCII form Hermes requests a non-ASCII URL in matches its ledger entry,
  and refused receipt writes are reported per session;
* the grounded-citations citation grammar (links, labels and fenced code are
  not citations) and URL identity (an arXiv abstract is not its PDF);
* coverage as an `omh_reported_rate/v1`, with zero citations as `percent: null`;
* the exit code: 0 only when every cited source was fetched, 1 otherwise,
  2 when the check could not run.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands.research import _receipts_verify_exit_code  # noqa: E402
from omh.plugin_bundle.omh.delegation_ledger import LEDGER_SCHEMA_VERSION, ledger_path  # noqa: E402
from omh.plugin_bundle.omh.research_receipts import record_fetch_receipts  # noqa: E402
from omh.quality.reported_rate import reported_rate_shape_errors  # noqa: E402
from omh.plugin_bundle.omh.research_receipts import receipt_path, refusal_path  # noqa: E402
from omh.workflows.research_receipt_check import (  # noqa: E402
    CITATION_RECEIPT_CHECK_SCHEMA_VERSION,
    CLAIM_BOUNDARY,
    check_draft_receipts,
    cited_ids,
    request_normalized_url,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research_receipt_check"
CITATIONS = FIXTURES / "citations.json"
PARENT = "20261104_120000_parent"
CHILD = "20261104_120001_child"
EARLIER = "20261104_110000_earlier"
EARLIER_CHILD = "20261104_110001_earlier_child"
ANCESTORS = "omh.workflows.research_receipt_check.compaction_ancestors"
URL_ONE = "https://example.org/paper/one"
URL_TWO = "https://example.org/paper/two?section=results"


class _ReceiptTree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "omh"
        self.home.mkdir()
        self.hermes = self.root / "hermes"  # no state.db: no rotation happened, the walk resolves empty
        self.hermes.mkdir()
        self._call = 0

    def fetch(self, *urls: str, session: str = PARENT) -> None:
        self._record("web_extract", {"results": [{"url": url, "title": "t", "content": "page text"} for url in urls]}, session)

    def search(self, *urls: str, session: str = PARENT) -> None:
        self._record("web_search", {"success": True, "data": {"web": [{"url": url, "description": "snippet"} for url in urls]}}, session)

    def _record(self, tool: str, result: dict, session: str) -> None:
        self._call += 1
        label = record_fetch_receipts(
            tool_name=tool,
            args={},
            result=json.dumps(result),
            status="ok",
            session_id=session,
            tool_call_id=f"call-{self._call}",
            turn_id="turn-1",
            omh_home=str(self.home),
        )
        self.assertEqual(label, "recorded")

    def delegation_ledger(self, *children: str, session: str = PARENT) -> None:
        """A session's `delegation_ledger/v1`, naming each child the way `subagent_start` records it."""
        path = ledger_path(self.home, session)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "session_id": session,
            "calls": [],
            "children": [
                {"subagent_id": f"sa-{index}", "child_session_id": child, "parent_session_id": session, "started_at": 1.0}
                for index, child in enumerate(children)
            ],
            "updated_at": 1.0,
        }
        path.write_text(json.dumps(record), encoding="utf-8")

    def draft(self, text: str) -> Path:
        path = self.root / f"draft-{self._call}-{len(text)}.md"
        path.write_text(text, encoding="utf-8")
        return path

    def check(self, draft: Path, *, citations: Path = CITATIONS) -> dict:
        return check_draft_receipts(
            omh_home=self.home, hermes_home=self.hermes, session_id=PARENT, citations_path=citations, draft_path=draft
        )

    @staticmethod
    def statuses(payload: dict) -> dict[int, str]:
        return {row["id"]: row["status"] for row in payload["citations"]}


class CitationStatusTests(_ReceiptTree):
    def test_a_two_cited_one_receipt_leaves_the_second_missing(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(payload["schema_version"], CITATION_RECEIPT_CHECK_SCHEMA_VERSION)
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "missing"})
        self.assertEqual(payload["citations"][0]["sessions"], [PARENT])
        self.assertEqual(payload["delegation_ledger"], "read")
        self.assertFalse(payload["all_fetched"])
        self.assertEqual((payload["coverage"]["numerator"], payload["coverage"]["denominator"]), (1, 2))
        self.assertEqual(payload["coverage"]["percent"], 50.0)
        self.assertEqual(_receipts_verify_exit_code(payload), 1)
        self.assertEqual(payload["claim_boundary"], CLAIM_BOUNDARY)

    def test_b_a_child_session_fetch_counts_as_fetched(self) -> None:
        self.delegation_ledger(CHILD)
        self.fetch(URL_ONE)
        self.fetch(URL_TWO, session=CHILD)
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "fetched"})
        self.assertEqual(payload["citations"][1]["sessions"], [CHILD])
        self.assertEqual(payload["sessions_checked"], sorted([PARENT, CHILD]))
        self.assertTrue(payload["all_fetched"])
        self.assertEqual(payload["coverage"]["percent"], 100.0)
        self.assertEqual(_receipts_verify_exit_code(payload), 0)

    def test_c_n6_no_delegation_ledger_file_means_no_child_and_reads_missing(self) -> None:
        """No ledger file: `subagent_start` never ran for this session, so there is no child to miss."""
        self.fetch(URL_ONE)
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(payload["delegation_ledger"], "absent")
        self.assertEqual(payload["delegation_ledgers"], {PARENT: "absent"})
        self.assertEqual(payload["sessions_checked"], [PARENT])
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "missing"})
        self.assertEqual(_receipts_verify_exit_code(payload), 1)

    def test_c_n6_an_unparseable_delegation_ledger_is_child_unresolved(self) -> None:
        path = ledger_path(self.home, PARENT)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.fetch(URL_TWO, session=CHILD)  # opened by a child the parent cannot name without its ledger
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(payload["delegation_ledger"], "unreadable")
        self.assertEqual(self.statuses(payload), {1: "child_unresolved", 2: "child_unresolved"})
        self.assertEqual(_receipts_verify_exit_code(payload), 1)

    def test_c_n6_a_symlinked_or_oversize_delegation_ledger_is_child_unresolved(self) -> None:
        path = ledger_path(self.home, PARENT)
        path.parent.mkdir(parents=True, exist_ok=True)
        target = self.root / "real-ledger.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
        self.assertEqual(self.statuses(self.check(FIXTURES / "draft_two_cited.md")),
                         {1: "child_unresolved", 2: "child_unresolved"})
        path.unlink()
        self.delegation_ledger()
        with patch("omh.plugin_bundle.omh.delegation_ledger.LEDGER_MAX_BYTES", 8):
            payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(payload["delegation_ledger"], "unreadable")
        self.assertEqual(self.statuses(payload), {1: "child_unresolved", 2: "child_unresolved"})
        self.assertEqual(_receipts_verify_exit_code(payload), 1)

    def test_d_zero_citations_is_unmeasured_and_never_passes(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        payload = self.check(FIXTURES / "draft_no_citations.md")
        self.assertEqual(payload["citations"], [])
        self.assertIsNone(payload["coverage"]["percent"])
        self.assertEqual(payload["coverage"]["basis"], "no_observations")
        self.assertFalse(payload["all_fetched"])
        self.assertEqual(_receipts_verify_exit_code(payload), 1)

    def test_e_coverage_is_a_well_formed_reported_rate(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        for draft in ("draft_two_cited.md", "draft_no_citations.md"):
            with self.subTest(draft=draft):
                coverage = self.check(FIXTURES / draft)["coverage"]
                self.assertEqual(reported_rate_shape_errors(coverage), ())
                self.assertEqual(coverage["numerator_of"], ["fetched"])
                self.assertEqual(coverage["denominator_of"], "cited_sources")
                self.assertTrue(coverage["excluded"])

    def test_f_a_search_listed_url_only_is_search_only(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        self.search(URL_TWO)
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "search_only"})
        self.assertEqual(payload["counts"]["search_only"], 1)
        self.assertEqual(_receipts_verify_exit_code(payload), 1)

    def test_f_a_fetch_outranks_an_earlier_search_listing(self) -> None:
        self.delegation_ledger()
        self.search(URL_ONE)
        self.fetch(URL_ONE)
        payload = self.check(self.draft("Method one improves recall here [1].\n"))
        self.assertEqual(self.statuses(payload), {1: "fetched"})

    def test_g_an_id_the_ledger_does_not_hold_is_not_in_ledger(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        payload = self.check(self.draft("One claim [1] and an invented source [3].\n"))
        self.assertEqual(self.statuses(payload), {1: "fetched", 3: "not_in_ledger"})
        self.assertEqual(payload["citations"][1]["url_display"], "")
        self.assertEqual(_receipts_verify_exit_code(payload), 1)

    def test_h_links_labels_and_fenced_code_are_not_citations(self) -> None:
        text = (FIXTURES / "draft_markup.md").read_text(encoding="utf-8")
        self.assertEqual(cited_ids(text), [2])
        self.delegation_ledger()
        self.fetch(URL_TWO)
        payload = self.check(FIXTURES / "draft_markup.md")
        self.assertEqual(self.statuses(payload), {2: "fetched"})
        self.assertEqual(_receipts_verify_exit_code(payload), 0)

    def test_i_an_arxiv_pdf_receipt_does_not_cover_its_abstract_page(self) -> None:
        self.delegation_ledger()
        self.fetch("https://arxiv.org/pdf/2401.00001")
        payload = self.check(self.draft("The abstract states the result [4].\n"))
        self.assertEqual(self.statuses(payload), {4: "missing"})

    def test_ledger_normalization_matches_fragment_and_trailing_slash(self) -> None:
        self.delegation_ledger()
        self.fetch("https://example.org/paper/one/#intro")
        payload = self.check(self.draft("Method one improves recall here [1].\n"))
        self.assertEqual(self.statuses(payload), {1: "fetched"})

    def test_n3_a_receipt_for_the_percent_encoded_form_covers_a_non_ascii_ledger_url(self) -> None:
        url = "https://ko.wikipedia.org/wiki/대한민국"
        encoded = "https://ko.wikipedia.org/wiki/%EB%8C%80%ED%95%9C%EB%AF%BC%EA%B5%AD"
        self.assertEqual(request_normalized_url(url), encoded)
        ledger = self.root / "ko-citations.json"
        ledger.write_text(json.dumps({"version": 1, "sources": [{"id": 1, "url": url, "title": "t"}]}), encoding="utf-8")
        self.fetch(encoded)  # what web_extract reports after normalize_url_for_request
        payload = self.check(self.draft("대한민국 claim [1].\n"), citations=ledger)
        self.assertEqual(self.statuses(payload), {1: "fetched"})
        self.assertEqual(_receipts_verify_exit_code(payload), 0)

    def test_n3_request_normalization_matches_hermes_url_safety(self) -> None:
        """Pinned against `tools/url_safety.normalize_url_for_request` outputs observed in the Hermes venv."""
        cases = {
            "https://bücher.example/a b?q=가 나#프": "https://xn--bcher-kva.example/a%20b?q=%EA%B0%80%20%EB%82%98#%ED%94%84",
            "https:// docs.example/x": "https://docs.example/x",
            "ftp://x/가": "ftp://x/가",
            "https://example.org/paper/one": "https://example.org/paper/one",
            "https://example.org/a%20b": "https://example.org/a%20b",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(request_normalized_url(raw), expected)

    def test_n3_a_redirect_target_never_covers_the_url_that_redirected(self) -> None:
        self.fetch("https://example.org/paper/one-final")
        payload = self.check(self.draft("Method one improves recall here [1].\n"))
        self.assertEqual(self.statuses(payload), {1: "missing"})
        self.assertIn("redirect", payload["claim_boundary"])

    def test_n1_refused_receipt_writes_are_reported_per_session(self) -> None:
        self.delegation_ledger(CHILD)
        self.fetch(URL_ONE)
        blocked = receipt_path(self.home, CHILD)
        blocked.symlink_to(self.root / "elsewhere.jsonl")
        label = record_fetch_receipts(
            tool_name="web_extract", args={}, result=json.dumps({"results": [{"url": URL_TWO, "content": "x"}]}),
            status="ok", session_id=CHILD, tool_call_id="c", turn_id="t", omh_home=str(self.home),
        )
        self.assertEqual(label, "refused")
        blocked.unlink()  # the store recovered; the refusal still shows
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(payload["receipt_refusals"], {CHILD: 1, PARENT: 0})
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "missing"})
        self.assertEqual(_receipts_verify_exit_code(payload), 1)
        refusal_path(self.home, PARENT).write_text("not a number\n", encoding="ascii")
        self.assertEqual(self.check(FIXTURES / "draft_two_cited.md")["receipt_refusals"][PARENT], None)

    def test_n5_earlier_compaction_segments_and_their_children_are_checked(self) -> None:
        self.delegation_ledger()
        self.delegation_ledger(EARLIER_CHILD, session=EARLIER)
        self.fetch(URL_ONE, session=EARLIER)  # fetched before the rotation moved the conversation to PARENT
        self.fetch(URL_TWO, session=EARLIER_CHILD)
        with patch(ANCESTORS, return_value={"status": "resolved", "ancestors": [EARLIER]}) as walk:
            payload = self.check(FIXTURES / "draft_two_cited.md")
        walk.assert_called_once_with(str(self.hermes), PARENT)
        self.assertEqual(payload["segments"], [PARENT, EARLIER])
        self.assertTrue(payload["segments_resolved"])
        self.assertEqual(payload["delegation_ledgers"], {EARLIER: "read", PARENT: "read"})
        self.assertEqual(payload["sessions_checked"], sorted([PARENT, EARLIER, EARLIER_CHILD]))
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "fetched"})
        self.assertEqual(payload["citations"][1]["sessions"], [EARLIER_CHILD])
        self.assertEqual(_receipts_verify_exit_code(payload), 0)

    def test_n5_an_unresolved_segment_walk_with_no_match_is_child_unresolved(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        answer = {"status": "unverified", "reason": "state_db_unavailable", "ancestors": []}
        with patch(ANCESTORS, return_value=answer):
            payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertFalse(payload["segments_resolved"])
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "child_unresolved"})
        self.assertEqual(_receipts_verify_exit_code(payload), 1)
        with patch(ANCESTORS, side_effect=OSError("state.db")):
            payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertFalse(payload["segments_resolved"])
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "child_unresolved"})

    def test_n5_no_state_db_resolves_with_the_session_alone(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual((payload["segments"], payload["segments_resolved"]), ([PARENT], True))

    def test_unparseable_and_foreign_receipt_lines_are_skipped(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        path = self.home / "runtime" / "research_receipts"
        (receipt,) = list(path.glob("*.jsonl"))
        with receipt.open("a", encoding="utf-8") as handle:
            handle.write("{torn\n")
            handle.write(json.dumps({"schema_version": "other/v1", "kind": "fetched", "url_key": "x"}) + "\n")
        payload = self.check(FIXTURES / "draft_two_cited.md")
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "missing"})


class ReceiptsVerifyCliTests(_ReceiptTree):
    def run_verify(self, draft: Path, *extra: str, env: dict | None = None) -> tuple[int, str, str]:
        argv = ["--omh-home", str(self.home), "--hermes-home", str(self.hermes), "research", "receipts", "verify",
                "--citations", str(CITATIONS), "--draft", str(draft), *extra]
        with patch.dict(os.environ, env or {}, clear=False):
            if env is None:
                os.environ.pop("HERMES_SESSION_ID", None)
            return run_cli(argv)

    def test_j_end_to_end_missing_then_all_fetched(self) -> None:
        self.delegation_ledger(CHILD)
        self.fetch(URL_ONE)
        status, stdout, stderr = self.run_verify(FIXTURES / "draft_two_cited.md", "--session", PARENT, "--json")
        self.assertEqual(status, 1, stderr)
        payload = json.loads(stdout)
        self.assertEqual(self.statuses(payload), {1: "fetched", 2: "missing"})
        self.assertEqual(payload["session_id"], PARENT)

        self.fetch(URL_TWO, session=CHILD)
        status, stdout, stderr = self.run_verify(FIXTURES / "draft_two_cited.md", "--session", PARENT, "--json")
        self.assertEqual(status, 0, stderr)
        self.assertTrue(json.loads(stdout)["all_fetched"])

    def test_j_session_defaults_to_hermes_session_id(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE, URL_TWO)
        status, stdout, stderr = self.run_verify(FIXTURES / "draft_two_cited.md", "--json", env={"HERMES_SESSION_ID": PARENT})
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["session_id"], PARENT)
        self.assertEqual(payload["session_source"], "env")
        self.assertNotIn("session_override", payload)
        self.assertEqual(stderr, "")

    def test_j_n5_a_session_flag_other_than_hermes_session_id_is_recorded_and_noted(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE, URL_TWO)
        status, stdout, stderr = self.run_verify(
            FIXTURES / "draft_two_cited.md", "--session", PARENT, "--json", env={"HERMES_SESSION_ID": CHILD}
        )
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual((payload["session_source"], payload.get("session_override")), ("flag", True))
        self.assertIn("not this command's HERMES_SESSION_ID", stderr)
        status, stdout, stderr = self.run_verify(
            FIXTURES / "draft_two_cited.md", "--session", PARENT, "--json", env={"HERMES_SESSION_ID": PARENT}
        )
        payload = json.loads(stdout)
        self.assertEqual(payload["session_source"], "flag")
        self.assertNotIn("session_override", payload)
        self.assertEqual(stderr, "")

    def test_j_no_session_is_a_usage_error(self) -> None:
        status, _stdout, stderr = self.run_verify(FIXTURES / "draft_two_cited.md", "--json")
        self.assertEqual(status, 2)
        self.assertIn("HERMES_SESSION_ID", stderr)

    def test_j_unreadable_inputs_exit_two(self) -> None:
        bad_ledger = self.root / "ledger.json"
        bad_ledger.write_text("[]", encoding="utf-8")
        cases = (
            ["--citations", str(self.root / "absent.json")],
            ["--citations", str(bad_ledger)],
        )
        for override in cases:
            with self.subTest(override=override[1]):
                argv = ["--omh-home", str(self.home), "research", "receipts", "verify",
                        *override, "--draft", str(FIXTURES / "draft_two_cited.md"), "--session", PARENT]
                status, _stdout, stderr = run_cli(argv)
                self.assertEqual(status, 2)
                self.assertTrue(stderr.startswith("omh: "), stderr)
        status, _stdout, _stderr = self.run_verify(self.root / "absent.md", "--session", PARENT)
        self.assertEqual(status, 2)

    def test_j_text_output_names_coverage_and_boundary(self) -> None:
        self.delegation_ledger()
        self.fetch(URL_ONE)
        argv = ["--omh-home", str(self.home), "--hermes-home", str(self.hermes), "research", "receipts", "verify",
                "--citations", str(CITATIONS), "--draft", str(FIXTURES / "draft_two_cited.md"), "--session", PARENT]
        status, stdout, stderr = run_cli(argv, output_json=False)
        self.assertEqual(status, 1, stderr)
        self.assertIn("fetched coverage: 50.0% — 1/2 cited_sources (fetched)", stdout)
        self.assertIn("[2] missing https://example.org/paper/two", stdout)
        self.assertNotIn("section=results", stdout)
        self.assertIn(CLAIM_BOUNDARY, stdout)


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()

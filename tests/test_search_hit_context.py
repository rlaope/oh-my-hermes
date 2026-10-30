"""Search hit context: lines around each hit of a small ``search_files`` result.

The host's redactor (``agent.redact``) is stood in by a module installed in
``sys.modules`` for each test, the way Hermes provides it at runtime; without
it the pass must do nothing.
"""

from __future__ import annotations

import json
import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.hooks.result_transforms import transform_tool_result
from omh.plugin_bundle.omh.search_hit_context import (
    MATCHES_FORMAT,
    MAX_ADDED_CHARS,
    MAX_FILES,
    MAX_HITS,
    enrich_search_hits,
)

DENSE_FORMAT = (
    "path-grouped: each file path on its own line, followed by indented "
    "'<line>: <content>' rows for matches in that file"
)


def _redact(text: str, *, file_read: bool = False, secret_file: bool = False, **_: object) -> str:
    """A stand-in for Hermes's redactor: masks one token, and a whole PEM-shaped block onto one line."""
    assert file_read
    if "-----BEGIN KEY-----" in text and "-----END KEY-----" in text:
        start, end = text.index("-----BEGIN KEY-----"), text.index("-----END KEY-----") + len("-----END KEY-----")
        text = text[:start] + "[REDACTED PRIVATE KEY]" + text[end:]
    return text.replace("sk-live-123", "«redacted»")


def _host_redact_module() -> types.ModuleType:
    module = types.ModuleType("agent.redact")
    module.redact_sensitive_text = _redact  # type: ignore[attr-defined]
    module._is_secret_file_arg = lambda path: path.endswith(".env")  # type: ignore[attr-defined]
    return module


def _dense(groups: dict[str, list[tuple[int, str]]]) -> str:
    rows = []
    for path, hits in groups.items():
        rows.append(path)
        rows.extend(f"  {line}: {content.rstrip()}" for line, content in hits)
    return "\n".join(rows)


def _result(groups: dict[str, list[tuple[int, str]]], **extra: object) -> str:
    total = sum(len(hits) for hits in groups.values())
    if total < 5:
        payload: dict[str, object] = {"total_count": total, "matches": [
            {"path": path, "line": line, "content": content}
            for path, hits in groups.items() for line, content in hits]}
    else:
        payload = {"total_count": total, "matches_format": DENSE_FORMAT, "matches_text": _dense(groups)}
    payload.update(extra)
    return json.dumps(payload)


PRICING = (
    '"""Fee arithmetic."""\n'
    "\n"
    "\n"
    "def compute_fee(amount_cents: int, rate_bp: int) -> int:\n"
    '    """Fee in cents for an amount at a rate in basis points."""\n'
    "    return amount_cents * rate_bp // 10000\n"
)
BILLING = (
    "from benchapp.pricing import compute_fee\n"
    "\n"
    "\n"
    "def bill_total(amount_cents: int) -> int:\n"
    "    return amount_cents + compute_fee(amount_cents, 125)\n"
)


class SearchHitContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "pricing.py").write_text(PRICING, encoding="utf-8")
        (self.root / "src" / "billing.py").write_text(BILLING, encoding="utf-8")
        modules = mock.patch.dict(sys.modules, {"agent.redact": _host_redact_module()})
        modules.start()
        self.addCleanup(modules.stop)
        cwd = mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.root)})
        cwd.start()
        self.addCleanup(cwd.stop)

    def enrich(self, result: str, **args: object) -> dict | None:
        out = enrich_search_hits(tool_name="search_files", args={"pattern": "compute_fee", **args}, result=result)
        return None if out is None else json.loads(out)

    def small(self) -> str:
        return _result({
            "./src/billing.py": [(1, "from benchapp.pricing import compute_fee"),
                                 (5, "    return amount_cents + compute_fee(amount_cents, 125)")],
            "./src/pricing.py": [(4, "def compute_fee(amount_cents: int, rate_bp: int) -> int:")],
        })

    def test_small_result_gains_the_lines_around_each_hit(self) -> None:
        out = self.enrich(self.small())
        self.assertIsNotNone(out)
        self.assertEqual(out["total_count"], 3)
        self.assertEqual(out["matches_format"], MATCHES_FORMAT)
        self.assertNotIn("matches", out)
        self.assertEqual(out["matches_text"], "\n".join([
            "./src/billing.py",
            "  1: from benchapp.pricing import compute_fee",
            "  2-",
            "  3-",
            "  4- def bill_total(amount_cents: int) -> int:",
            "  5:     return amount_cents + compute_fee(amount_cents, 125)",
            "./src/pricing.py",
            "  3-",
            "  4: def compute_fee(amount_cents: int, rate_bp: int) -> int:",
            '  5-     """Fee in cents for an amount at a rate in basis points."""',
            "  6-     return amount_cents * rate_bp // 10000",
        ]))

    def test_dense_result_keeps_host_keys_and_hit_rows(self) -> None:
        lines = "\n".join(f"VALUE_{n} = {n}" for n in range(1, 41)) + "\n"
        (self.root / "src" / "values.py").write_text(lines, encoding="utf-8")
        hits = [(n, f"VALUE_{n} = {n}") for n in (2, 3, 20, 38, 40)]
        out = self.enrich(_result({"./src/values.py": hits}, _omitted="1 result(s) omitted"))
        self.assertEqual(out["_omitted"], "1 result(s) omitted")
        rows = out["matches_text"].split("\n")
        for line, content in hits:
            self.assertIn(f"  {line}: {content}", rows)
        # Overlapping windows merge; a gap is one "..." row; nothing past the last line.
        self.assertEqual(rows[:7], ["./src/values.py", "  1- VALUE_1 = 1", "  2: VALUE_2 = 2", "  3: VALUE_3 = 3",
                                    "  4- VALUE_4 = 4", "  5- VALUE_5 = 5", "  6- VALUE_6 = 6"])
        self.assertEqual(rows[7], "  ...")
        self.assertEqual(rows[-3:], ["  38: VALUE_38 = 38", "  39- VALUE_39 = 39", "  40: VALUE_40 = 40"])

    def test_broad_or_partial_results_pass_through(self) -> None:
        many = _result({f"./src/f{n}.py": [(1, "x")] for n in range(MAX_FILES + 1)})
        self.assertIsNone(self.enrich(many))
        (self.root / "src" / "many.py").write_text("x\n" * (MAX_HITS + 1), encoding="utf-8")
        self.assertIsNone(self.enrich(_result({"./src/many.py": [(n, "x") for n in range(1, MAX_HITS + 2)]})))
        self.assertIsNone(self.enrich(self.small().replace('"total_count"', '"truncated": true, "total_count"')))
        self.assertIsNone(self.enrich(json.dumps({"error": "Search failed: x", "total_count": 0})))
        self.assertIsNone(self.enrich(json.dumps({"total_count": 0})))

    def test_a_call_that_chose_its_own_shape_is_left_alone(self) -> None:
        self.assertIsNone(self.enrich(self.small(), context=2))
        self.assertIsNone(self.enrich(self.small(), output_mode="files_only"))
        self.assertIsNone(self.enrich(self.small(), target="files"))
        self.assertIsNone(enrich_search_hits(tool_name="read_file", args={}, result=self.small()))
        self.assertIsNotNone(self.enrich(self.small(), context=0))

    def test_a_hit_that_no_longer_matches_the_disk_leaves_the_result_alone(self) -> None:
        (self.root / "src" / "pricing.py").write_text("# moved\n" + PRICING, encoding="utf-8")
        self.assertIsNone(self.enrich(self.small()))

    def test_a_path_that_does_not_resolve_leaves_the_result_alone(self) -> None:
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.root / "elsewhere")}):
            self.assertIsNone(self.enrich(self.small()))

    def test_no_host_redactor_means_no_enrichment(self) -> None:
        with mock.patch.dict(sys.modules, {"agent.redact": None}):
            self.assertIsNone(self.enrich(self.small()))

    def test_added_lines_are_redacted_by_the_host(self) -> None:
        (self.root / "src" / "keys.py").write_text("KEY = 'sk-live-123'\nfrom x import fee\n", encoding="utf-8")
        out = self.enrich(_result({"./src/keys.py": [(2, "from x import fee")]}))
        self.assertIn("  1- KEY = '«redacted»'", out["matches_text"])
        self.assertNotIn("sk-live-123", out["matches_text"])

    def test_redaction_that_changes_the_line_count_leaves_the_result_alone(self) -> None:
        body = "-----BEGIN KEY-----\nabc\n-----END KEY-----\nfee = 1\n"
        (self.root / "src" / "pem.py").write_text(body, encoding="utf-8")
        self.assertIsNone(self.enrich(_result({"./src/pem.py": [(4, "fee = 1")]})))

    def test_added_text_over_the_cap_leaves_the_result_alone(self) -> None:
        long_line = "y" * 499
        (self.root / "src" / "wide.py").write_text("\n".join(["hit"] + [long_line] * 3) * 6 + "\n", encoding="utf-8")
        hits = [(1 + 4 * n, "hit") for n in range(6)]
        self.assertGreater(6 * 3 * 500, MAX_ADDED_CHARS)
        self.assertIsNone(self.enrich(_result({"./src/wide.py": hits})))

    def test_crlf_files_and_absolute_paths(self) -> None:
        path = self.root / "src" / "crlf.py"
        path.write_bytes(b"a = 1\r\nfee = 2\r\nb = 3\r\n")
        out = self.enrich(_result({str(path): [(2, "fee = 2\r")]}))
        self.assertEqual(out["matches_text"].split("\n"), [str(path), "  1- a = 1", "  2: fee = 2", "  3- b = 3"])

    def test_the_composed_seam_enriches_and_leaves_broad_results_byte_identical(self) -> None:
        composed = transform_tool_result(tool_name="search_files", args={"pattern": "compute_fee"},
                                         result=self.small(), session_id="", tool_call_id="")
        self.assertEqual(json.loads(composed)["matches_format"], MATCHES_FORMAT)
        broad = _result({f"./src/f{n}.py": [(1, "x")] for n in range(MAX_FILES + 1)})
        passed = transform_tool_result(tool_name="search_files", args={"pattern": "x"},
                                       result=broad, session_id="", tool_call_id="")
        self.assertIn(passed, (None, broad))


if __name__ == "__main__":
    unittest.main()

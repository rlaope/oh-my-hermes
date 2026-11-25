#!/usr/bin/env python3
"""Offline, counts-only residual PII and secret scanner for omh-data-share-review.

Zero third-party dependencies, zero network calls. Prints counts per class and the
SHA-256 of the scanned file bytes, never raw matched values.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

SCHEMA_VERSION = "residual_scan/v1"
MAX_SCAN_BYTES = 50 * 1024 * 1024  # 50 MiB safety cap

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3,4}[\s.-]\d{4}(?!\w)"
)
_US_SSN_RE = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_KR_RRN_RE = re.compile(r"\b\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-[1-4]\d{6}\b")
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)
_VENDOR_KEY_RE = re.compile(
    r"(?:"
    r"\bsk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{16,}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bAIza[0-9A-Za-z_-]{30,}\b"
    r"|\bxox[baprs]-[0-9A-Za-z-]{10,}\b"
    r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
    r")"
)
_ABS_PATH_RE = re.compile(
    r"(?:/Users/[A-Za-z0-9._@-]+/[^\s\"'`,;)]+|/home/[A-Za-z0-9._@-]+/[^\s\"'`,;)]+|[A-Za-z]:\\Users\\[^\s\"'`,;)]+)"
)
_SECRET_CONTEXT_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|passwd|bearer|auth)[\s\"'`:=]+([A-Za-z0-9+/_=-]{24,})"
)


def _luhn_valid(digits: str) -> bool:
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    total = 0
    for idx, ch in enumerate(reversed(digits)):
        val = int(ch)
        if idx % 2 == 1:
            val *= 2
            if val > 9:
                val -= 9
        total += val
    return total % 10 == 0


def _shannon_entropy(token: str) -> float:
    if not token:
        return 0.0
    counts = Counter(token)
    length = len(token)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def scan_text_counts(text: str) -> dict[str, int]:
    """Return per-class hit counts for `text`; never returns matched substrings."""
    counts: Counter[str] = Counter()
    counts["email"] = len(_EMAIL_RE.findall(text))
    counts["phone"] = len(_PHONE_RE.findall(text))
    counts["national_id"] = len(_US_SSN_RE.findall(text)) + len(_KR_RRN_RE.findall(text))
    card_hits = 0
    for match in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", match.group(0))
        if _luhn_valid(digits):
            card_hits += 1
    counts["credit_card"] = card_hits
    counts["ipv4"] = len(_IPV4_RE.findall(text))
    counts["vendor_secret"] = len(_VENDOR_KEY_RE.findall(text))
    counts["absolute_local_path"] = len(_ABS_PATH_RE.findall(text))
    entropy_hits = 0
    for match in _SECRET_CONTEXT_RE.finditer(text):
        candidate = match.group(1)
        if _shannon_entropy(candidate) >= 4.0:
            entropy_hits += 1
    counts["high_entropy_secret"] = entropy_hits
    return {key: int(counts[key]) for key in sorted(counts)}


def _scan_csv_columns(text: str) -> dict[str, dict[str, int]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return {}
    per_col: dict[str, Counter[str]] = {}
    for row in reader:
        for field, value in row.items():
            if field is None or not value:
                continue
            hits = scan_text_counts(str(value))
            nonzero = {k: v for k, v in hits.items() if v > 0}
            if nonzero:
                per_col.setdefault(str(field), Counter()).update(nonzero)
    return {col: dict(sorted(counter.items())) for col, counter in sorted(per_col.items())}


def _walk_json_fields(node: Any, prefix: str, acc: dict[str, Counter[str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _walk_json_fields(value, path, acc)
    elif isinstance(node, list):
        for item in node:
            _walk_json_fields(item, prefix or "[]", acc)
    elif isinstance(node, str):
        hits = scan_text_counts(node)
        nonzero = {k: v for k, v in hits.items() if v > 0}
        if nonzero:
            acc.setdefault(prefix or "<root>", Counter()).update(nonzero)


def scan_file(path: Path, *, free_text_sampled: bool = False) -> dict[str, object]:
    """Scan a local file and emit a metadata-only `residual_scan/v1` record."""
    raw = path.read_bytes()
    if len(raw) > MAX_SCAN_BYTES:
        raise ValueError(f"file exceeds maximum scan size ({MAX_SCAN_BYTES} bytes)")
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")
    counts = scan_text_counts(text)
    suffix = path.suffix.lower()
    fields_with_hits: dict[str, dict[str, int]] = {}
    detected_format = "text"
    if suffix == ".csv":
        detected_format = "csv"
        fields_with_hits = _scan_csv_columns(text)
    elif suffix in {".json", ".jsonl", ".ndjson"}:
        detected_format = suffix.lstrip(".")
        acc: dict[str, Counter[str]] = {}
        try:
            if suffix == ".json":
                _walk_json_fields(json.loads(text), "", acc)
            else:
                for line in text.splitlines():
                    if line.strip():
                        _walk_json_fields(json.loads(line), "", acc)
            fields_with_hits = {k: dict(sorted(v.items())) for k, v in sorted(acc.items())}
        except json.JSONDecodeError:
            detected_format = "text"

    total_hits = sum(counts.values())
    if total_hits > 0:
        verdict = "not_redacted"
    elif free_text_sampled:
        verdict = "redacted"
    else:
        verdict = "needs_free_text_sample"

    return {
        "schema_version": SCHEMA_VERSION,
        "scan_method": "offline_stdlib_residual_scan_v1",
        "file_name": path.name,
        "format": detected_format,
        "file_bytes": len(raw),
        "line_count": len(text.splitlines()),
        "sha256": digest,
        "free_text_sampled": bool(free_text_sampled),
        "counts_by_class": counts,
        "total_hits": total_hits,
        "fields_with_hits": fields_with_hits,
        "verdict": verdict,
        "claim_boundary": (
            "Counts-only offline regex/Luhn/entropy residual scan of the exact file bytes. "
            "No matched values are emitted, nothing is uploaded, and lawful sharing authority "
            "is not determined here."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline counts-only PII/secret residual scanner for omh-data-share-review."
    )
    parser.add_argument("--input", required=True, help="Local file path to scan (CSV, JSON, JSONL, or text).")
    parser.add_argument(
        "--free-text-sampled",
        action="store_true",
        help="Confirm a human/reviewer also inspected a sample of free-text fields.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)
    try:
        target = Path(args.input).expanduser().resolve()
        if not target.is_file():
            raise FileNotFoundError("input path does not exist or is not a regular file")
        payload = scan_file(target, free_text_sampled=bool(args.free_text_sampled))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        error_payload = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        print(json.dumps(error_payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"residual_scan/v1 verdict={payload['verdict']} total_hits={payload['total_hits']} sha256={payload['sha256']}")
        for cls, count in payload["counts_by_class"].items():
            if count:
                print(f"  - {cls}: {count}")
    return 0 if payload["total_hits"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Corpus loading, verdict extraction and per-run grading.

Nothing here calls a model. A run is graded from the reviewer's final text
alone, so a recorded fixture and a live run go through the same code.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

BASE = Path(__file__).resolve().parents[1]
CORPUS_ROOT = BASE / "corpus"

KINDS = ("trap", "control")
EXPECTED_FOR_KIND = {"trap": "clean", "control": "bug"}
CASE_KEYS = {"id", "kind", "language", "expected", "why"}
CONTROL_KEYS = CASE_KEYS | {"bug_location"}
LOCATION_WINDOW = 3
RECORDS_SCHEMA = "review-false-alarms/records/v1"
ARMS = ("omh-on", "omh-off")

# Outcomes. A trap ends `clean_ok` or `false_alarm`; a control ends `hit`,
# `miss_clean` (said clean) or `miss_location` (said bug, wrong place). Either
# kind can end `no_verdict`, which is never folded into clean.
TRAP_OUTCOMES = ("clean_ok", "false_alarm", "no_verdict")
CONTROL_OUTCOMES = ("hit", "miss_clean", "miss_location", "no_verdict")

_VERDICT_LINE = re.compile(r"^VERDICT:\s*(?P<body>.*?)\s*$")
_BUG_BODY = re.compile(r"^bug\s+(?P<path>\S+?):(?P<line>[1-9][0-9]*)$")
_PATH_PREFIXES = ("./", "context/", "a/", "b/")


class CorpusError(ValueError):
    """A case directory that does not follow the corpus schema."""


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    language: str
    expected: str
    why: str
    bug_path: str | None
    bug_line: int | None
    directory: Path


@dataclass(frozen=True)
class Verdict:
    """`kind` is `clean`, `bug` or `none`; `none` carries the reason."""

    kind: str
    path: str | None = None
    line: int | None = None
    reason: str | None = None


def case_from_record(record: Mapping[str, Any], directory: Path) -> Case:
    """Validate one case.json object; raise CorpusError naming the field."""

    if not isinstance(record, Mapping):
        raise CorpusError(f"{directory.name}: case.json is not an object")
    kind = record.get("kind")
    if kind not in KINDS:
        raise CorpusError(f"{directory.name}: kind must be one of {KINDS}, got {kind!r}")
    wanted = CONTROL_KEYS if kind == "control" else CASE_KEYS
    if set(record) != wanted:
        raise CorpusError(
            f"{directory.name}: keys {sorted(record)} differ from {sorted(wanted)}"
        )
    for key in ("id", "language", "why"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise CorpusError(f"{directory.name}: {key} must be a non-empty string")
    if record["id"] != directory.name:
        raise CorpusError(f"{directory.name}: id {record['id']!r} differs from the directory name")
    if record["expected"] != EXPECTED_FOR_KIND[kind]:
        raise CorpusError(
            f"{directory.name}: a {kind} expects {EXPECTED_FOR_KIND[kind]!r}, got {record['expected']!r}"
        )
    bug_path = bug_line = None
    if kind == "control":
        location = record["bug_location"]
        if not isinstance(location, Mapping) or set(location) != {"path", "line"}:
            raise CorpusError(f"{directory.name}: bug_location must be {{path, line}}")
        if not isinstance(location["path"], str) or not location["path"]:
            raise CorpusError(f"{directory.name}: bug_location.path must be a non-empty string")
        if type(location["line"]) is not int or location["line"] < 1:
            raise CorpusError(f"{directory.name}: bug_location.line must be a positive integer")
        bug_path, bug_line = location["path"], location["line"]
    return Case(
        id=record["id"],
        kind=kind,
        language=record["language"],
        expected=record["expected"],
        why=record["why"],
        bug_path=bug_path,
        bug_line=bug_line,
        directory=directory,
    )


def load_case(directory: Path) -> Case:
    for required in ("case.json", "diff.patch", "context"):
        if not (directory / required).exists():
            raise CorpusError(f"{directory.name}: missing {required}")
    record = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    return case_from_record(record, directory)


def load_corpus(root: Path = CORPUS_ROOT) -> dict[str, Case]:
    cases = {}
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        case = load_case(directory)
        cases[case.id] = case
    return cases


def normalize_path(path: str) -> str:
    path = path.strip().strip("`'\"").replace("\\", "/")
    changed = True
    while changed:
        changed = False
        for prefix in _PATH_PREFIXES:
            if path.startswith(prefix):
                path = path[len(prefix):]
                changed = True
    return path


def _unwrap(line: str) -> str:
    """Drop the markdown a model wraps a line in: emphasis, code ticks, a list bullet."""

    line = line.strip()
    if line.startswith(("- ", "* ", "> ")):
        line = line[2:].strip()
    return line.strip("*_`").strip()


def extract_verdict(output: str | None) -> Verdict:
    """The verdict on the reply's last non-empty line, or `none` and why.

    The contract is that the reply *ends* with the verdict line. A verdict
    earlier in the text followed by more prose is not accepted, because the
    reviewer may have changed its mind after writing it.
    """

    if not output or not output.strip():
        return Verdict("none", reason="empty_output")
    lines = [line for line in output.splitlines() if line.strip()]
    while lines and _unwrap(lines[-1]) in ("", "```"):
        lines.pop()
    if not lines:
        return Verdict("none", reason="empty_output")
    match = _VERDICT_LINE.match(_unwrap(lines[-1]))
    if not match:
        return Verdict("none", reason="no_verdict_line")
    body = match.group("body").strip().strip("*_`").strip()
    if body.casefold() == "clean":
        return Verdict("clean")
    bug = _BUG_BODY.match(body)
    if bug:
        return Verdict("bug", path=normalize_path(bug.group("path")), line=int(bug.group("line")))
    return Verdict("none", reason="garbled_verdict")


def grade(case: Case, verdict: Verdict) -> str:
    if verdict.kind == "none":
        return "no_verdict"
    if case.kind == "trap":
        return "clean_ok" if verdict.kind == "clean" else "false_alarm"
    if verdict.kind == "clean":
        return "miss_clean"
    if (
        verdict.path == normalize_path(case.bug_path or "")
        and verdict.line is not None
        and abs(verdict.line - (case.bug_line or 0)) <= LOCATION_WINDOW
    ):
        return "hit"
    return "miss_location"


def load_records(path: Path) -> list[dict[str, Any]]:
    """Read a records file (a recorded fixture or a live run's output)."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping) or data.get("schema") != RECORDS_SCHEMA:
        raise ValueError(f"{path}: not a {RECORDS_SCHEMA} file")
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(f"{path}: records must be a list")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"{path}: record {index} is not an object")
        if record.get("arm") not in ARMS:
            raise ValueError(f"{path}: record {index} has unknown arm {record.get('arm')!r}")
        if not isinstance(record.get("case"), str):
            raise ValueError(f"{path}: record {index} has no case id")
        if type(record.get("run")) is not int:
            raise ValueError(f"{path}: record {index} has no integer run")
        if record.get("output") is not None and not isinstance(record.get("output"), str):
            raise ValueError(f"{path}: record {index} output must be text or null")
    return [dict(record) for record in records]


def grade_records(cases: Mapping[str, Case], records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    graded = []
    seen = set()
    for record in records:
        key = (record["arm"], record["case"], record["run"])
        if key in seen:
            raise ValueError(f"duplicate record for arm {key[0]}, case {key[1]}, run {key[2]}")
        seen.add(key)
        case = cases.get(record["case"])
        if case is None:
            raise ValueError(f"record names unknown case {record['case']!r}")
        verdict = extract_verdict(record.get("output"))
        graded.append(
            {
                "arm": record["arm"],
                "case": case.id,
                "kind": case.kind,
                "run": record["run"],
                "verdict": verdict.kind,
                "verdict_reason": verdict.reason,
                "outcome": grade(case, verdict),
            }
        )
    return graded

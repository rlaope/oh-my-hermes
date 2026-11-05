"""Deterministic two-reviewer title/abstract screening for systematic reviews.

Three steps, each a pure local file operation (no network, no model call):

* ``freeze`` writes ``screening_protocol/v1``: the person's criteria text and
  ordered exclusion codes, hashed, write-once.
* ``prepare`` writes one set of task files per reviewer (``A`` and ``B``),
  each holding the criteria verbatim, the ordered codes, the records in a
  reviewer-specific seeded order and the answer grammar, plus a
  ``screening_manifest/v1`` naming every file by sha256. A task file never
  holds the other reviewer's answers or name.
* ``merge`` reads both reviewers' answer lines and decides each record:
  both INCLUDE -> include; both EXCLUDE -> exclude with the earlier code in
  protocol order; one INCLUDE and one EXCLUDE, or any UNSURE -> conflict; a
  reviewer with no line, contradictory lines or an unknown code -> pending,
  never a silent exclude. Adjudication lines resolve conflicts only.

The merge payload carries ids and codes, never titles, abstracts or answer
text. Agreement is ``agreement_stats/v1`` over records both reviewers decided
include/exclude: agreement between two reviewers, not accuracy. Reviewers
running the same model are not independent and the payload says so.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

from ..quality.agreement_stats import agreement_stats
from ..system.local_store import utc_now

PROTOCOL_SCHEMA_VERSION = "screening_protocol/v1"
MANIFEST_SCHEMA_VERSION = "screening_manifest/v1"
MERGE_SCHEMA_VERSION = "screening_merge/v1"

PROTOCOL_FILE = "protocol.json"
MANIFEST_FILE = "manifest.json"
TASKS_DIR = "tasks"
REVIEWERS = ("A", "B")

CRITERIA_CHAR_LIMIT = 20000
CODE_COUNT_MAX = 20
RECORD_ID_CHAR_LIMIT = 200
BATCH_SIZE_DEFAULT = 25
BATCH_SIZE_MAX = 500

INCLUDE = "include"
EXCLUDE = "exclude"
UNSURE = "unsure"
CONFLICT = "conflict"
PENDING = "pending"

PENDING_MISSING = "missing"
PENDING_CONTRADICTORY = "contradictory_lines"
PENDING_UNKNOWN_CODE = "unknown_code"

INDEPENDENCE_NOT_OBSERVED = "not_observed"
INDEPENDENCE_SAME_MODEL = "same_model"
INDEPENDENCE_DIFFERENT_MODELS = "different_models"
WARNING_BROKEN_INDEPENDENCE = "broken_independence"
WARNING_SAME_ANSWERS_FILE = "same_answers_file"

# Observation classes merge drops before agreement is computed.
EXCLUDED_RECORDS_WITH_UNSURE = "records_with_unsure"
EXCLUDED_PENDING_RECORDS = "pending_records"

CLAIM_BOUNDARY = (
    "AI screening is decision support, not a review team's decision; the team verifies every "
    "decision. Agreement is between two reviewers, not accuracy against a human gold set."
)

_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
_RECORD_ID_PATTERN = re.compile(r"\S+")
# The fixed answer grammar: keywords are case-insensitive, the id is compared exactly.
_ANSWER_LINE = re.compile(
    r"^\s*RECORD\s+(\S+)\s*:\s*(?:(INCLUDE|UNSURE)|EXCLUDE\s+(\S+))\s*$",
    re.IGNORECASE,
)


class ScreeningInputError(ValueError):
    """An input the screening step refuses; the CLI maps it to exit 2."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_text(path: Path, what: str) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ScreeningInputError(f"cannot read {what} {path}: {exc.strerror or exc}") from exc
    try:
        return data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise ScreeningInputError(f"{what} {path} is not UTF-8") from exc


def _read_json(path: Path, what: str) -> Any:
    text = _read_text(path, what)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScreeningInputError(f"{what} {path} is not valid JSON (line {exc.lineno})") from exc


def _write_new(path: Path, text: str, what: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise ScreeningInputError(f"{what} {path} already exists; it is write-once") from exc


def _protocol_digest(criteria: str, codes: list[dict[str, str]]) -> str:
    return _sha256_bytes(_canonical_json({"criteria": criteria, "codes": codes}))


def _validated_codes(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= CODE_COUNT_MAX:
        raise ScreeningInputError(f"codes must be a JSON list of 1..{CODE_COUNT_MAX} {{code, label}} objects")
    codes: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != {"code", "label"}:
            raise ScreeningInputError(f"codes entry {index} must be an object with exactly 'code' and 'label'")
        code, label = item["code"], item["label"]
        if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
            raise ScreeningInputError(
                f"codes entry {index}: code must be 1-32 letters, digits, '_', '.' or '-', starting alphanumeric"
            )
        if not isinstance(label, str) or not label.strip():
            raise ScreeningInputError(f"codes entry {index}: label must be a non-empty string")
        if code in seen:
            raise ScreeningInputError(f"codes entry {index}: code {code} is repeated; codes must be unique")
        seen.add(code)
        codes.append({"code": code, "label": label.strip()})
    return codes


def freeze_protocol(*, criteria_path: Path, codes_path: Path, out_dir: Path) -> dict[str, Any]:
    """Write ``out_dir/protocol.json`` once; refuse when it already exists."""
    criteria = _read_text(criteria_path, "criteria file")
    if not criteria.strip():
        raise ScreeningInputError("criteria file is empty")
    if len(criteria) > CRITERIA_CHAR_LIMIT:
        raise ScreeningInputError(f"criteria file holds {len(criteria)} characters; the limit is {CRITERIA_CHAR_LIMIT}")
    codes = _validated_codes(_read_json(codes_path, "codes file"))
    protocol_path = out_dir / PROTOCOL_FILE
    if protocol_path.exists():
        raise ScreeningInputError(f"{protocol_path} already exists; a frozen protocol is write-once")
    protocol = {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "criteria": criteria,
        "criteria_sha256": _sha256_bytes(criteria.encode("utf-8")),
        "codes": codes,
        "protocol_sha256": _protocol_digest(criteria, codes),
        "frozen_at": utc_now(),
    }
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ScreeningInputError(f"cannot create {out_dir}: {exc.strerror or exc}") from exc
    _write_new(protocol_path, json.dumps(protocol, indent=2, sort_keys=True, ensure_ascii=False) + "\n", "protocol")
    return protocol


def load_protocol(screening_dir: Path) -> dict[str, Any]:
    """Read ``protocol.json`` and refuse one edited after freeze."""
    protocol = _read_json(screening_dir / PROTOCOL_FILE, "protocol")
    if not isinstance(protocol, dict) or protocol.get("schema_version") != PROTOCOL_SCHEMA_VERSION:
        raise ScreeningInputError(f"{screening_dir / PROTOCOL_FILE} is not a {PROTOCOL_SCHEMA_VERSION} file")
    criteria = protocol.get("criteria")
    if not isinstance(criteria, str):
        raise ScreeningInputError("protocol criteria is missing")
    codes = _validated_codes(protocol.get("codes"))
    if protocol.get("protocol_sha256") != _protocol_digest(criteria, codes):
        raise ScreeningInputError("protocol.json does not match its protocol_sha256; it was edited after freeze")
    return protocol


def _read_records(records_path: Path) -> tuple[list[dict[str, str]], str]:
    try:
        data = records_path.read_bytes()
    except OSError as exc:
        raise ScreeningInputError(f"cannot read records file {records_path}: {exc.strerror or exc}") from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ScreeningInputError(f"records file {records_path} is not UTF-8") from exc
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    # Split on "\n" only: str.splitlines would also split on U+2028, U+0085 and
    # other separators that are legal raw characters inside a JSON string.
    for line_number, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScreeningInputError(f"records line {line_number} is not valid JSON") from exc
        if not isinstance(row, dict):
            raise ScreeningInputError(f"records line {line_number} is not a JSON object")
        record_id = row.get("id")
        if (
            not isinstance(record_id, str)
            or not _RECORD_ID_PATTERN.fullmatch(record_id)
            or len(record_id) > RECORD_ID_CHAR_LIMIT
        ):
            raise ScreeningInputError(
                f"records line {line_number}: id must be a non-empty string of up to "
                f"{RECORD_ID_CHAR_LIMIT} characters without whitespace"
            )
        if record_id in seen:
            raise ScreeningInputError(f"records line {line_number}: id {record_id} is repeated; ids must be unique")
        seen.add(record_id)
        record = {"id": record_id}
        for field in ("title", "abstract"):
            value = row.get(field, "")
            if not isinstance(value, str):
                raise ScreeningInputError(f"records line {line_number}: {field} must be a string")
            record[field] = value
        records.append(record)
    if not records:
        raise ScreeningInputError("records file holds no records")
    return records, _sha256_bytes(data)


def reviewer_order(record_ids: list[str], *, seed: int, reviewer: str) -> list[str]:
    """The reviewer's seeded record order: reproducible, and different per reviewer."""
    order = list(record_ids)
    random.Random(f"systematic-review:{seed}:{reviewer}").shuffle(order)
    return order


def _task_text(
    protocol: dict[str, Any],
    records: list[dict[str, str]],
    *,
    reviewer: str,
    batch: int,
    batch_count: int,
) -> str:
    codes = protocol["codes"]
    lines = [
        f"# Screening task: reviewer {reviewer}, batch {batch} of {batch_count}",
        "",
        f"Protocol sha256: {protocol['protocol_sha256']}",
        "",
        "Screen each record below against the criteria. Judge only the record's title and abstract.",
        "",
        "## Criteria (verbatim)",
        "",
        protocol["criteria"].rstrip("\n"),
        "",
        "## Exclusion codes, in the order they are applied",
        "",
    ]
    lines.extend(f"{index}. {code['code']}: {code['label']}" for index, code in enumerate(codes, start=1))
    lines.extend(
        [
            "",
            "## Answer format",
            "",
            "Write exactly one line per record, in one of these three forms and nothing else on the line:",
            "",
            "```text",
            "RECORD <id>: INCLUDE",
            "RECORD <id>: EXCLUDE <code>",
            "RECORD <id>: UNSURE",
            "```",
            "",
            "Use the record id exactly as written. When several exclusion codes apply, give the first one",
            "in the order above. Answer UNSURE when the title and abstract do not settle the decision.",
            "A record with no line, two different lines, or a code not listed above is not decided.",
            "",
            "## Records",
        ]
    )
    for record in records:
        lines.extend(
            [
                "",
                f"### RECORD {record['id']}",
                "",
                f"Title: {record['title']}",
                "",
                f"Abstract: {record['abstract']}",
            ]
        )
    return "\n".join(lines) + "\n"


def prepare_tasks(*, screening_dir: Path, records_path: Path, seed: int, batch_size: int = BATCH_SIZE_DEFAULT) -> dict[str, Any]:
    """Write per-reviewer task files and ``manifest.json``; refuse an existing ``tasks/``."""
    if not 1 <= batch_size <= BATCH_SIZE_MAX:
        raise ScreeningInputError(f"--batch-size must be between 1 and {BATCH_SIZE_MAX}")
    protocol = load_protocol(screening_dir)
    records, records_sha256 = _read_records(records_path)
    tasks_dir = screening_dir / TASKS_DIR
    manifest_path = screening_dir / MANIFEST_FILE
    if tasks_dir.exists():
        raise ScreeningInputError(f"{tasks_dir} already exists; prepare writes task files once")
    if manifest_path.exists():
        raise ScreeningInputError(f"{manifest_path} already exists; prepare writes the manifest once")
    by_id = {record["id"]: record for record in records}
    record_ids = [record["id"] for record in records]
    batch_count = (len(records) + batch_size - 1) // batch_size
    try:
        tasks_dir.mkdir()
    except OSError as exc:
        raise ScreeningInputError(f"cannot create {tasks_dir}: {exc.strerror or exc}") from exc
    batches: list[dict[str, Any]] = []
    for reviewer in REVIEWERS:
        reviewer_dir = tasks_dir / reviewer
        reviewer_dir.mkdir()
        order = reviewer_order(record_ids, seed=seed, reviewer=reviewer)
        for index in range(batch_count):
            batch_ids = order[index * batch_size : (index + 1) * batch_size]
            text = _task_text(
                protocol,
                [by_id[record_id] for record_id in batch_ids],
                reviewer=reviewer,
                batch=index + 1,
                batch_count=batch_count,
            )
            task_path = reviewer_dir / f"batch-{index + 1:03d}.md"
            _write_new(task_path, text, "task file")
            batches.append(
                {
                    "reviewer": reviewer,
                    "batch": index + 1,
                    "path": task_path.relative_to(screening_dir).as_posix(),
                    "sha256": _sha256_bytes(text.encode("utf-8")),
                    "record_ids": batch_ids,
                }
            )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "records_sha256": records_sha256,
        "seed": seed,
        "batch_size": batch_size,
        "record_count": len(record_ids),
        "record_ids": record_ids,
        "batches": batches,
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    _write_new(manifest_path, json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", "manifest")
    return manifest


def _manifest_digest(manifest: dict[str, Any]) -> str:
    return _sha256_bytes(_canonical_json({key: value for key, value in manifest.items() if key != "manifest_sha256"}))


def _load_manifest(screening_dir: Path, protocol: dict[str, Any]) -> list[str]:
    manifest = _read_json(screening_dir / MANIFEST_FILE, "manifest")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ScreeningInputError(f"{screening_dir / MANIFEST_FILE} is not a {MANIFEST_SCHEMA_VERSION} file")
    if manifest.get("manifest_sha256") != _manifest_digest(manifest):
        raise ScreeningInputError("manifest.json does not match its manifest_sha256; it was edited after prepare")
    if manifest.get("protocol_sha256") != protocol["protocol_sha256"]:
        raise ScreeningInputError("manifest.json was prepared against a different protocol")
    record_ids = manifest.get("record_ids")
    if (
        not isinstance(record_ids, list)
        or not record_ids
        or not all(isinstance(record_id, str) for record_id in record_ids)
        or len(set(record_ids)) != len(record_ids)
    ):
        raise ScreeningInputError("manifest.json record_ids must be a non-empty list of unique strings")
    batches = manifest.get("batches")
    if not isinstance(batches, list) or not all(isinstance(batch, dict) for batch in batches):
        raise ScreeningInputError("manifest.json batches must be a list of objects")
    for reviewer in REVIEWERS:
        batch_ids = [
            record_id
            for batch in batches
            if batch.get("reviewer") == reviewer
            for record_id in (batch.get("record_ids") if isinstance(batch.get("record_ids"), list) else [])
        ]
        if sorted(batch_ids) != sorted(record_ids) or manifest.get("record_count") != len(record_ids):
            raise ScreeningInputError(
                f"manifest.json record_ids no longer match the records prepare gave reviewer {reviewer}"
            )
    return record_ids


def _answer_files(path: Path, what: str) -> list[Path]:
    if path.is_dir():
        files = sorted(child for child in path.glob("*.md") if child.is_file())
        if not files:
            raise ScreeningInputError(f"{what} {path} holds no *.md files; answer files in a directory must end in .md")
        return files
    if path.is_file():
        return [path]
    raise ScreeningInputError(f"{what} {path} is neither a file nor a directory")


def _answer_lines(path: Path, what: str) -> list[tuple[str, str, str]]:
    """``(record_id, decision, code)`` for every line matching the fixed grammar."""
    parsed: list[tuple[str, str, str]] = []
    for answer_file in _answer_files(path, what):
        for line in _read_text(answer_file, what).split("\n"):
            match = _ANSWER_LINE.match(line)
            if match is None:
                continue
            record_id, keyword, code = match.group(1), match.group(2), match.group(3)
            if keyword is None:
                parsed.append((record_id, EXCLUDE, code))
            else:
                parsed.append((record_id, keyword.lower(), ""))
    return parsed


def _same_answers(answers_a: Path, answers_b: Path) -> bool:
    """True when A and B name the same path, or files with identical bytes."""
    if answers_a.resolve() == answers_b.resolve():
        return True

    def contents(path: Path) -> list[bytes]:
        out: list[bytes] = []
        for answer_file in _answer_files(path, "answers"):
            try:
                out.append(answer_file.read_bytes())
            except OSError as exc:
                raise ScreeningInputError(f"cannot read answers {answer_file}: {exc.strerror or exc}") from exc
        return out

    return contents(answers_a) == contents(answers_b)


def _reviewer_decisions(
    lines: list[tuple[str, str, str]], record_ids: set[str], codes: set[str]
) -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, int]]:
    """Per reviewer: decided records, pending reasons, and line counts."""
    seen: dict[str, set[tuple[str, str]]] = {}
    unknown_record = 0
    for record_id, decision, code in lines:
        if record_id not in record_ids:
            unknown_record += 1
            continue
        seen.setdefault(record_id, set()).add((decision, code))
    decided: dict[str, tuple[str, str]] = {}
    pending: dict[str, str] = {}
    for record_id in record_ids:
        answers = seen.get(record_id)
        if not answers:
            pending[record_id] = PENDING_MISSING
        elif len(answers) > 1:
            pending[record_id] = PENDING_CONTRADICTORY
        else:
            decision, code = next(iter(answers))
            if decision == EXCLUDE and code not in codes:
                pending[record_id] = PENDING_UNKNOWN_CODE
            else:
                decided[record_id] = (decision, code)
    counts = {"matched_lines": len(lines), "unknown_record_lines": unknown_record}
    return decided, pending, counts


def _adjudication_decisions(
    path: Path, conflicts: set[str], codes: set[str]
) -> dict[str, tuple[str, str]]:
    resolved: dict[str, tuple[str, str]] = {}
    for record_id, decision, code in _answer_lines(path, "adjudication"):
        if decision == UNSURE:
            raise ScreeningInputError(f"adjudication for record {record_id} is UNSURE; adjudication must decide")
        if record_id not in conflicts:
            raise ScreeningInputError(f"adjudication names record {record_id}, which is not a conflict")
        if decision == EXCLUDE and code not in codes:
            raise ScreeningInputError(f"adjudication for record {record_id} uses a code the protocol does not list")
        previous = resolved.get(record_id)
        if previous is not None and previous != (decision, code):
            raise ScreeningInputError(f"adjudication holds two different decisions for record {record_id}")
        resolved[record_id] = (decision, code)
    return resolved


def parse_reviewer_models(text: str) -> dict[str, str]:
    """``A=x,B=y`` -> ``{"A": "x", "B": "y"}``; both reviewers are required."""
    models: dict[str, str] = {}
    for part in text.split(","):
        reviewer, sep, model = part.partition("=")
        reviewer, model = reviewer.strip(), model.strip()
        if not sep or reviewer not in REVIEWERS or not model or reviewer in models:
            raise ScreeningInputError("--reviewer-models must be A=<model>,B=<model>")
        models[reviewer] = model
    if set(models) != set(REVIEWERS):
        raise ScreeningInputError("--reviewer-models must be A=<model>,B=<model>")
    return models


def merge_answers(
    *,
    screening_dir: Path,
    answers_a: Path,
    answers_b: Path,
    adjudication: Path | None = None,
    reviewer_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Merge both reviewers' answers into ``screening_merge/v1``."""
    protocol = load_protocol(screening_dir)
    record_ids = _load_manifest(screening_dir, protocol)
    code_order = [code["code"] for code in protocol["codes"]]
    codes = set(code_order)
    id_set = set(record_ids)
    decided_a, pending_a, lines_a = _reviewer_decisions(_answer_lines(answers_a, "answers for A"), id_set, codes)
    decided_b, pending_b, lines_b = _reviewer_decisions(_answer_lines(answers_b, "answers for B"), id_set, codes)

    final: dict[str, tuple[str, str]] = {}
    pending: list[dict[str, Any]] = []
    code_disagreements: list[str] = []
    pairs: list[tuple[bool, bool]] = []
    with_unsure = 0
    for record_id in record_ids:
        if record_id in pending_a or record_id in pending_b:
            reasons = {reviewer: reason for reviewer, reason in (("A", pending_a.get(record_id)), ("B", pending_b.get(record_id))) if reason}
            pending.append({"id": record_id, "reviewers": reasons})
            final[record_id] = (PENDING, "")
            continue
        (a_decision, a_code), (b_decision, b_code) = decided_a[record_id], decided_b[record_id]
        if UNSURE in (a_decision, b_decision):
            with_unsure += 1
        else:
            pairs.append((a_decision == INCLUDE, b_decision == INCLUDE))
        if a_decision == b_decision == INCLUDE:
            final[record_id] = (INCLUDE, "")
        elif a_decision == b_decision == EXCLUDE:
            final[record_id] = (EXCLUDE, min(a_code, b_code, key=code_order.index))
            if a_code != b_code:
                code_disagreements.append(record_id)
        else:
            final[record_id] = (CONFLICT, "")

    conflicts = {record_id for record_id, (decision, _code) in final.items() if decision == CONFLICT}
    adjudicated: list[str] = []
    if adjudication is not None:
        resolved = _adjudication_decisions(adjudication, conflicts, codes)
        for record_id in record_ids:
            if record_id in resolved:
                final[record_id] = resolved[record_id]
                adjudicated.append(record_id)

    excluded_by_code = {code: 0 for code in code_order}
    for decision, code in final.values():
        if decision == EXCLUDE:
            excluded_by_code[code] += 1
    conflict_ids = [record_id for record_id in record_ids if final[record_id][0] == CONFLICT]

    warnings: list[str] = []
    if reviewer_models is None:
        independence = INDEPENDENCE_NOT_OBSERVED
    elif reviewer_models["A"].casefold() == reviewer_models["B"].casefold():
        independence = INDEPENDENCE_SAME_MODEL
        warnings.append(WARNING_BROKEN_INDEPENDENCE)
    else:
        independence = INDEPENDENCE_DIFFERENT_MODELS
    if _same_answers(answers_a, answers_b):
        warnings.append(WARNING_SAME_ANSWERS_FILE)

    return {
        "schema_version": MERGE_SCHEMA_VERSION,
        "protocol_sha256": protocol["protocol_sha256"],
        "counts": {
            "records": len(record_ids),
            "included": sum(1 for decision, _code in final.values() if decision == INCLUDE),
            "excluded": sum(excluded_by_code.values()),
            "excluded_by_code": excluded_by_code,
            "conflicts": len(conflict_ids),
            "adjudicated": len(adjudicated),
            "pending": len(pending),
        },
        "records": [
            {"id": record_id, "decision": final[record_id][0], "code": final[record_id][1]} for record_id in record_ids
        ],
        "conflict_ids": conflict_ids,
        "adjudicated_ids": adjudicated,
        "pending": pending,
        "code_disagreements": code_disagreements,
        "answer_lines": {"A": lines_a, "B": lines_b},
        "agreement": agreement_stats(
            pairs, excluded={EXCLUDED_RECORDS_WITH_UNSURE: with_unsure, EXCLUDED_PENDING_RECORDS: len(pending)}
        ),
        "reviewer_independence": independence,
        "reviewer_models": reviewer_models,
        "warnings": warnings,
        "claim_boundary": CLAIM_BOUNDARY,
    }


__all__ = [
    "CLAIM_BOUNDARY",
    "MANIFEST_SCHEMA_VERSION",
    "MERGE_SCHEMA_VERSION",
    "PROTOCOL_SCHEMA_VERSION",
    "ScreeningInputError",
    "freeze_protocol",
    "load_protocol",
    "merge_answers",
    "parse_reviewer_models",
    "prepare_tasks",
    "reviewer_order",
]

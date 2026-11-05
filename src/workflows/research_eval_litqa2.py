"""Score the research workflow on LitQA2: deterministic task files in, graded rates out.

`prepare` turns a pinned LitQA2 JSONL export into a frozen evaluation set: the
export's sha256 must match the digest the caller names, a seeded sample picks
the questions, and each one becomes a task file holding only the question,
lettered options and the answer-line instruction. Which letter is right lives
in ``answer_key.json`` beside them, never in a task file. `grade` reads one
answer file per task and arm, extracts the final ``ANSWER: <letter>`` line by
a fixed rule, and reports accuracy, precision, unsure and unanswered rates as
``omh_reported_rate/v1`` payloads, plus how many cited sources each arm's
``citation_receipt_check/v1`` payloads say were really fetched.

The dataset is read from wherever the caller keeps it and is never copied:
task files carry no dataset id, source, key passage or canary, and the grade
payload carries no answer text. Stdlib only; no network.

The score is about one biology literature-QA benchmark. The two arms are
Hermes subagents in one profile told apart only by their instruction, not
paired-run signed receipts.
"""
from __future__ import annotations

import ast
import hashlib
import json
import random
import re
import string
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ..quality.reported_rate import reported_rate, reported_rate_shape_errors
from .research_receipt_check import CITATION_RECEIPT_CHECK_SCHEMA_VERSION, COVERAGE_EXCLUDED

KEY_SCHEMA_VERSION: Final = "research_eval_litqa2_key/v1"
MANIFEST_SCHEMA_VERSION: Final = "research_eval_litqa2_manifest/v1"
PREPARE_SCHEMA_VERSION: Final = "research_eval_litqa2_prepare/v1"
GRADE_SCHEMA_VERSION: Final = "research_eval_litqa2_grade/v1"

ARM_BASELINE: Final = "baseline"
ARM_RESEARCH: Final = "research"
ARMS: Final = (ARM_BASELINE, ARM_RESEARCH)
ARM_INSTRUCTIONS: Final = {
    ARM_BASELINE: "Answer the question below. Use whatever tools you would normally use. Do not load any skill.",
    ARM_RESEARCH: (
        "Answer the question below using the ulw-research workflow: load skill_view(name='ulw-research') and "
        "grounded-citations, research the literature with web tools, keep a citation ledger and a short draft "
        "with [n] citations, then run `omh research receipts verify` on them."
    ),
}
UNSURE_OPTION: Final = "Insufficient information to answer this question"
ANSWER_INSTRUCTION: Final = "Finish with one final line exactly of the form `ANSWER: <letter>`."
CLAIM_BOUNDARY: Final = (
    "Scores one biology literature-QA benchmark (LitQA2). Both arms are Hermes subagents in one profile, "
    "told apart only by their instruction; these are not paired-run signed receipts. Options are shown as the "
    "dataset gives them, so a row whose distractors repeat a sentence shows that sentence twice; only the ideal "
    "answer's letter scores as correct."
)

OUTCOME_CORRECT: Final = "correct"
OUTCOME_INCORRECT: Final = "incorrect"
OUTCOME_UNSURE: Final = "unsure"
OUTCOME_UNANSWERED: Final = "unanswered"
OUTCOME_MISSING: Final = "missing"
OUTCOMES: Final = (OUTCOME_CORRECT, OUTCOME_INCORRECT, OUTCOME_UNSURE, OUTCOME_UNANSWERED, OUTCOME_MISSING)
RECEIPT_NOT_OBSERVED: Final = "not_observed"
RECEIPT_OBSERVED: Final = "observed"
NO_RECEIPT_CHECK: Final = "no_receipt_check"

DATA_BYTE_LIMIT: Final = 16 * 1024 * 1024
ANSWER_BYTE_LIMIT: Final = 64 * 1024
KEY_BYTE_LIMIT: Final = 4_000_000
RECEIPT_CHECK_BYTE_LIMIT: Final = 4_000_000
LETTERS: Final = string.ascii_uppercase

_ANSWER_LINE_RE: Final = re.compile(r"^\s*\**\s*ANSWER\s*\**\s*:\s*(.*)$", re.IGNORECASE)
_ANSWER_STRIP: Final = string.whitespace + "*()."
_TASK_ID_RE: Final = re.compile(r"^q\d{2,}$")


class LitQA2InputError(ValueError):
    """An input that cannot be read or does not have the shape this command needs (exit 2)."""


class LitQA2DigestError(ValueError):
    """The data file's sha256 is not the digest the caller pinned (exit 1)."""


def _read_bytes(path: Path, *, label: str, limit: int) -> bytes:
    try:
        if not path.is_file():
            raise LitQA2InputError(f"{label} not found: {path}")
        if path.stat().st_size > limit:
            raise LitQA2InputError(f"{label} is larger than {limit} bytes: {path}")
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise LitQA2InputError(f"{label} is unreadable ({type(exc).__name__}): {path}") from exc
    if len(raw) > limit:
        raise LitQA2InputError(f"{label} is larger than {limit} bytes: {path}")
    return raw


def _read_text(path: Path, *, label: str, limit: int) -> str:
    raw = _read_bytes(path, label=label, limit=limit)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LitQA2InputError(f"{label} is not UTF-8: {path}") from exc


def _read_json(path: Path, *, label: str, limit: int) -> Any:
    text = _read_text(path, label=label, limit=limit)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LitQA2InputError(f"{label} is not JSON: {path}") from exc


def _parse_distractors(value: object, line_number: int) -> list[str]:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
            raise LitQA2InputError(f"row {line_number}: distractors is not a list literal") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise LitQA2InputError(f"row {line_number}: distractors must be a list of non-empty strings")
    return list(value)


def parse_rows(text: str) -> list[dict[str, Any]]:
    """``{id, question, ideal, distractors}`` per JSONL row; ``row N`` in an error is the 1-based line."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Split on LF only: str.splitlines() also breaks on U+2028 and friends, which JSON strings may hold.
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise LitQA2InputError(f"row {line_number}: not a JSON object") from exc
        if not isinstance(record, dict):
            raise LitQA2InputError(f"row {line_number}: not a JSON object")
        for field in ("id", "question", "ideal"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                raise LitQA2InputError(f"row {line_number}: missing {field}")
        if record["id"] in seen:
            raise LitQA2InputError(f"row {line_number}: duplicate id")
        seen.add(record["id"])
        rows.append({
            "id": record["id"],
            "question": record["question"],
            "ideal": record["ideal"],
            "distractors": _parse_distractors(record.get("distractors"), line_number),
        })
    return rows


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def build_task(row: Mapping[str, Any], *, task_id: str, seed: int) -> dict[str, Any]:
    """The task file bytes and its key entry; the option order is ``Random(f"{seed}:{id}")``."""
    options = [row["ideal"], *row["distractors"], UNSURE_OPTION]
    if len(options) > len(LETTERS):
        raise LitQA2InputError(f"task {task_id}: more than {len(LETTERS)} options")
    order = list(range(len(options)))
    random.Random(f"{seed}:{row['id']}").shuffle(order)
    correct = LETTERS[order.index(0)]
    unsure = LETTERS[order.index(len(options) - 1)]
    lines = [f"# LitQA2 task {task_id}", "", _lf(row["question"]).strip(), ""]
    lines.extend(f"{LETTERS[slot]}. {_lf(options[index]).strip()}" for slot, index in enumerate(order))
    lines.extend(["", ANSWER_INSTRUCTION, ""])
    body = "\n".join(lines).encode("utf-8")
    return {
        "body": body,
        "key": {
            "task_id": task_id,
            "dataset_id": row["id"],
            "correct": correct,
            "unsure": unsure,
            "option_count": len(options),
            "task_sha256": hashlib.sha256(body).hexdigest(),
        },
    }


def sample_rows(rows: Sequence[Mapping[str, Any]], *, sample: int, seed: int) -> list[Mapping[str, Any]]:
    if sample < 1 or sample > len(rows):
        raise LitQA2InputError(f"--sample must be between 1 and the {len(rows)} rows in the data")
    ordered = sorted(rows, key=lambda row: row["id"])
    return random.Random(f"{seed}:sample").sample(ordered, sample)


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def prepare_litqa2(*, data_path: Path, sha256: str, sample: int, seed: int, out_dir: Path) -> dict[str, Any]:
    """Check the digest, sample, and write ``tasks/``, ``answer_key.json`` and ``manifest.json`` into an empty DIR.

    Nothing is written until every check passed: a digest mismatch raises
    `LitQA2DigestError`, every other refusal `LitQA2InputError`.
    """
    raw = _read_bytes(data_path, label="data file", limit=DATA_BYTE_LIMIT)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != sha256.strip().lower():
        raise LitQA2DigestError(f"data file sha256 is {digest}, not the pinned {sha256.strip()}: {data_path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LitQA2InputError(f"data file is not UTF-8: {data_path}") from exc
    chosen = sample_rows(parse_rows(text), sample=sample, seed=seed)
    width = max(2, len(str(sample)))
    tasks = [build_task(row, task_id=f"q{index:0{width}d}", seed=seed) for index, row in enumerate(chosen, start=1)]
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise LitQA2InputError(f"output directory is not empty: {out_dir}")
    identity = {"data_sha256": digest, "seed": seed, "sample": sample, "arms": list(ARMS)}
    key = {"schema_version": KEY_SCHEMA_VERSION, **identity, "tasks": [task["key"] for task in tasks]}
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        **identity,
        "task_files": [
            {"task_id": task["key"]["task_id"], "path": f"tasks/{task['key']['task_id']}.md",
             "sha256": task["key"]["task_sha256"]}
            for task in tasks
        ],
        "arm_instructions": dict(ARM_INSTRUCTIONS),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    try:
        (out_dir / "tasks").mkdir(parents=True, exist_ok=True)
        for task in tasks:
            (out_dir / "tasks" / f"{task['key']['task_id']}.md").write_bytes(task["body"])
        (out_dir / "answer_key.json").write_bytes(_json_bytes(key))
        (out_dir / "manifest.json").write_bytes(_json_bytes(manifest))
    except OSError as exc:
        raise LitQA2InputError(f"cannot write the output directory ({type(exc).__name__}): {out_dir}") from exc
    return {
        "schema_version": PREPARE_SCHEMA_VERSION,
        "out_dir": str(out_dir),
        "task_count": len(tasks),
        "data_sha256": digest,
        "seed": seed,
        "sample": sample,
    }


def extract_answer(text: str, option_count: int) -> str | None:
    """The letter on the last ``ANSWER:`` line, or None when that line holds no single in-range letter."""
    value = None
    for line in text.splitlines():
        match = _ANSWER_LINE_RE.match(line)
        if match:
            value = match.group(1)
    if value is None:
        return None
    value = value.strip(_ANSWER_STRIP)
    # ASCII only: 'ı'.upper() is 'I' and 'ſ'.upper() is 'S', which would read a non-letter as an option.
    if len(value) != 1 or not value.isascii() or value.upper() not in LETTERS:
        return None
    letter = value.upper()
    return letter if LETTERS.index(letter) < option_count else None


def outcome_for(letter: str | None, task: Mapping[str, Any]) -> str:
    if letter is None:
        return OUTCOME_UNANSWERED
    if letter == task["correct"]:
        return OUTCOME_CORRECT
    if letter == task["unsure"]:
        return OUTCOME_UNSURE
    return OUTCOME_INCORRECT


def _is_option_letter(value: object, option_count: int) -> bool:
    """One letter among the first ``option_count``; a substring test would admit ``""`` and ``"AB"``."""
    return isinstance(value, str) and value in set(LETTERS[:option_count])


def read_key(path: Path) -> dict[str, Any]:
    key = _read_json(path, label="answer key", limit=KEY_BYTE_LIMIT)
    if not isinstance(key, dict) or key.get("schema_version") != KEY_SCHEMA_VERSION:
        raise LitQA2InputError(f"answer key is not {KEY_SCHEMA_VERSION}: {path}")
    if key.get("arms") != list(ARMS):
        raise LitQA2InputError(f"answer key arms must be {list(ARMS)}: {path}")
    tasks = key.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise LitQA2InputError(f"answer key has no tasks: {path}")
    seen: set[str] = set()
    for task in tasks:
        count = task.get("option_count") if isinstance(task, dict) else None
        valid = (
            isinstance(task, dict)
            and isinstance(task.get("task_id"), str) and _TASK_ID_RE.match(task["task_id"])
            and task["task_id"] not in seen
            and isinstance(count, int) and not isinstance(count, bool) and 2 <= count <= len(LETTERS)
            and _is_option_letter(task.get("correct"), count)
            and _is_option_letter(task.get("unsure"), count)
            and task.get("correct") != task.get("unsure")
        )
        if not valid:
            raise LitQA2InputError(f"answer key has a malformed task entry: {path}")
        seen.add(task["task_id"])
    return key


def parse_receipt_check_args(values: Sequence[str] | None) -> dict[str, Path]:
    """``ARM=DIR`` pairs; an unknown or repeated arm is a usage error."""
    parsed: dict[str, Path] = {}
    for value in values or ():
        arm, sep, directory = value.partition("=")
        if not sep or arm not in ARMS or not directory:
            raise LitQA2InputError(f"--receipt-checks takes ARM=DIR with ARM one of {', '.join(ARMS)}: {value}")
        if arm in parsed:
            raise LitQA2InputError(f"--receipt-checks names arm {arm} twice")
        parsed[arm] = Path(directory).expanduser()
    return parsed


def receipt_coverage(directory: Path, task_ids: Sequence[str]) -> dict[str, Any]:
    """Summed fetched / cited counts over the arm's ``citation_receipt_check/v1`` payloads, one per task."""
    if not directory.is_dir():
        raise LitQA2InputError(f"receipt-check directory not found: {directory}")
    numerator = denominator = read = absent = 0
    numerator_of: list[str] | None = None
    for task_id in task_ids:
        path = directory / f"{task_id}.json"
        if not path.exists():
            absent += 1
            continue
        payload = _read_json(path, label="receipt check", limit=RECEIPT_CHECK_BYTE_LIMIT)
        if not isinstance(payload, dict) or payload.get("schema_version") != CITATION_RECEIPT_CHECK_SCHEMA_VERSION:
            raise LitQA2InputError(f"receipt check is not {CITATION_RECEIPT_CHECK_SCHEMA_VERSION}: {path}")
        coverage = payload.get("coverage")
        if reported_rate_shape_errors(coverage) or coverage["numerator"] > coverage["denominator"]:
            raise LitQA2InputError(f"receipt check coverage is not a well-formed reported rate: {path}")
        numerator += coverage["numerator"]
        denominator += coverage["denominator"]
        numerator_of = numerator_of or list(coverage["numerator_of"])
        read += 1
    rate = reported_rate(
        numerator=numerator,
        denominator=denominator,
        numerator_of=numerator_of or ["fetched"],
        denominator_of="cited_sources",
        excluded=[*COVERAGE_EXCLUDED, NO_RECEIPT_CHECK],
    )
    return {"status": RECEIPT_OBSERVED, "rate": rate.to_payload(), "tasks_checked": read, NO_RECEIPT_CHECK: absent}


def _arm_metrics(counts: Mapping[str, int], total: int) -> dict[str, Any]:
    sure = counts[OUTCOME_CORRECT] + counts[OUTCOME_INCORRECT]
    return {
        "counts": dict(counts),
        "accuracy": reported_rate(
            numerator=counts[OUTCOME_CORRECT], denominator=total,
            numerator_of=[OUTCOME_CORRECT], denominator_of="key_tasks",
        ).to_payload(),
        "precision": reported_rate(
            numerator=counts[OUTCOME_CORRECT], denominator=sure,
            numerator_of=[OUTCOME_CORRECT], denominator_of="sure_answers",
            excluded=[OUTCOME_UNSURE, OUTCOME_UNANSWERED, OUTCOME_MISSING],
        ).to_payload(),
        "unsure_rate": reported_rate(
            numerator=counts[OUTCOME_UNSURE], denominator=total,
            numerator_of=[OUTCOME_UNSURE], denominator_of="key_tasks",
        ).to_payload(),
        "unanswered_rate": reported_rate(
            numerator=counts[OUTCOME_UNANSWERED] + counts[OUTCOME_MISSING], denominator=total,
            numerator_of=[OUTCOME_UNANSWERED, OUTCOME_MISSING], denominator_of="key_tasks",
        ).to_payload(),
    }


def grade_litqa2(*, key_path: Path, answers_dir: Path, receipt_checks: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """The ``research_eval_litqa2_grade/v1`` payload: outcomes and letters, never answer text."""
    key = read_key(key_path)
    if not answers_dir.is_dir():
        raise LitQA2InputError(f"answers directory not found: {answers_dir}")
    tasks = key["tasks"]
    task_ids = [task["task_id"] for task in tasks]
    outcomes: list[dict[str, Any]] = []
    by_arm: dict[str, dict[str, str]] = {arm: {} for arm in ARMS}
    for task in tasks:
        for arm in ARMS:
            path = answers_dir / arm / f"{task['task_id']}.md"
            if not path.exists():
                outcome, letter = OUTCOME_MISSING, None
            else:
                letter = extract_answer(_read_text(path, label="answer file", limit=ANSWER_BYTE_LIMIT),
                                        task["option_count"])
                outcome = outcome_for(letter, task)
            by_arm[arm][task["task_id"]] = outcome
            outcomes.append({"task_id": task["task_id"], "arm": arm, "outcome": outcome, "extracted": letter})
    receipt_dirs = dict(receipt_checks or {})
    arms: dict[str, Any] = {}
    for arm in ARMS:
        counts = {name: sum(1 for value in by_arm[arm].values() if value == name) for name in OUTCOMES}
        metrics = _arm_metrics(counts, len(tasks))
        metrics["receipt_coverage"] = (
            receipt_coverage(receipt_dirs[arm], task_ids) if arm in receipt_dirs else {"status": RECEIPT_NOT_OBSERVED}
        )
        arms[arm] = metrics
    both = [(by_arm[ARM_BASELINE][tid] == OUTCOME_CORRECT, by_arm[ARM_RESEARCH][tid] == OUTCOME_CORRECT)
            for tid in task_ids]
    missing = sum(1 for row in outcomes if row["outcome"] == OUTCOME_MISSING)
    return {
        "schema_version": GRADE_SCHEMA_VERSION,
        "key": {
            "schema_version": KEY_SCHEMA_VERSION,
            "data_sha256": key.get("data_sha256"),
            "seed": key.get("seed"),
            "sample": key.get("sample"),
            "arms": list(ARMS),
            "task_count": len(tasks),
        },
        "arms": arms,
        "paired": {
            "both_correct": sum(1 for base, res in both if base and res),
            "research_only": sum(1 for base, res in both if res and not base),
            "baseline_only": sum(1 for base, res in both if base and not res),
            "neither": sum(1 for base, res in both if not base and not res),
        },
        "outcomes": outcomes,
        "missing_answers": missing,
        "complete": missing == 0,
        "claim_boundary": CLAIM_BOUNDARY,
    }


__all__ = [
    "ANSWER_INSTRUCTION",
    "ARMS",
    "ARM_INSTRUCTIONS",
    "CLAIM_BOUNDARY",
    "GRADE_SCHEMA_VERSION",
    "KEY_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "OUTCOMES",
    "PREPARE_SCHEMA_VERSION",
    "UNSURE_OPTION",
    "LitQA2DigestError",
    "LitQA2InputError",
    "build_task",
    "extract_answer",
    "grade_litqa2",
    "outcome_for",
    "parse_receipt_check_args",
    "parse_rows",
    "prepare_litqa2",
    "read_key",
    "receipt_coverage",
    "sample_rows",
]

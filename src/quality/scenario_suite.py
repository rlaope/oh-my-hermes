"""Shared shape for the scenario suites under `benchmarks/<suite>/v1`.

Two suites use it today: `automation-intent/v1` (does a plain-language request
become the right prepared automation, or correctly none) and
`orchestration/v1` (does the parent hand coding to the named owner, in the
right repository, citing only observed links, within a word budget). Each
suite owns its scenario schema and its grader; this module owns what they
share:

- **Two splits, kept apart by structure.** A suite's corpus is two files,
  `corpus/tuning.json` and `corpus/held-out.json`. Every command defaults to
  the tuning split; the held-out split is read only when it is named. A
  held-out report carries totals only, never a per-category rate or which
  scenario failed or why, so a held-out run cannot be read back into skill
  text one scenario at a time. `split_isolation_errors` refuses shared ids or shared request
  text between the two.
- **Observation classes.** An observation is either `observed` (the arm ran
  and its decision is graded) or an infrastructure failure, one of
  `INFRASTRUCTURE_FAILURE_CLASSES`. Infrastructure failures and scenarios
  with no observation at all are excluded from every denominator, by name,
  and counted; they are never graded as passes or as failures.
- **Rates.** Every rate is `omh_reported_rate/v1` with a Wilson 95% interval
  beside it. An empty denominator is `percent: null` with basis
  `no_observations`, and the interval is null too.
- **Headline identity.** A report's `headline` names the arm, the corpus and
  split, the corpus digest, the selection rule, and the observations artifact
  and its digest. With nothing graded it says `prepared_not_observed`.

Grading is deterministic and structural. No grader here calls a model, and
this module starts no process: the opt-in live arm in each lane's `bench.py`
spawns `omh coding hermes-child dispatch --confirm-dispatch`, the
Hermes-native child boundary, and this module only builds its argument
vector, its prompt, and the observation the lane records from its result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .reported_rate import format_reported_rate, reported_rate

CORPUS_SCHEMA_VERSION = "omh_scenario_corpus/v1"
OBSERVATIONS_SCHEMA_VERSION = "omh_scenario_observations/v1"
REPORT_SCHEMA_VERSION = "omh_scenario_suite_report/v1"

TUNING_SPLIT = "tuning"
HELD_OUT_SPLIT = "held_out"
SPLITS = (TUNING_SPLIT, HELD_OUT_SPLIT)
# The split a command reads when none is named. Held-out is never a default.
DEFAULT_SPLIT = TUNING_SPLIT
SPLIT_FILES = {TUNING_SPLIT: "tuning.json", HELD_OUT_SPLIT: "held-out.json"}
# The share of a suite's scenarios the held-out split holds, as a closed range.
HELD_OUT_SHARE_RANGE = (0.2, 0.3)
# A held-out report needs at least this share of the split graded (not
# excluded). Padding a file with infrastructure failures around one graded
# scenario would otherwise let the totals name that scenario's verdict.
HELD_OUT_MIN_GRADED_NUMERATOR, HELD_OUT_MIN_GRADED_DENOMINATOR = 3, 4

OBSERVED = "observed"
INFRASTRUCTURE_FAILURE = "infrastructure_failure"
OBSERVATION_STATUSES = (OBSERVED, INFRASTRUCTURE_FAILURE)
# The arm did not run, ran out of time, or its transport failed before it
# wrote a decision. None of these says anything about the decision, so each
# is excluded from the denominator by name rather than graded.
INFRASTRUCTURE_FAILURE_CLASSES = ("arm_did_not_run", "timeout", "transport_error")
# The two groups a tuning report splits scenarios into.
REQUEST_DERIVABLE_GROUP = "request_derivable"
SKILL_RULE_GROUP = "skill_rule"
GROUPS = (REQUEST_DERIVABLE_GROUP, SKILL_RULE_GROUP)
# A scenario of the split with no observation in the file at all.
NOT_OBSERVED = "not_observed"
EXCLUDED_CLASSES = (*INFRASTRUCTURE_FAILURE_CLASSES, NOT_OBSERVED)

OBSERVATION_KEYS = frozenset({"scenario_id", "status", "infrastructure_failure", "reason", "decision", "evidence_links"})
# An infrastructure failure keeps a short reason for diagnosis: the child's
# terminal status and why no decision was read. Never the prompt or stderr.
MAX_REASON_CHARS = 200
RUN_KEYS = frozenset({"execution_path", "arm_kind", "model", "provider", "reasoning", "skill_digest"})
SCENARIO_ID_LIMIT = 80

# The file a live arm writes in its workspace. The child boundary reports
# metadata and never the model's text, so this file is the whole interface
# between a run and its grade.
DECISION_FILENAME = ".omh-scenario-decision.json"
MAX_DECISION_FILE_BYTES = 256 * 1024
MAX_PROMPT_BYTES = 262_144

# z for a two-sided 95% interval.
WILSON_Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class Failure:
    """One structural check a decision did not meet."""

    check: str
    expected: object
    observed: object

    def to_payload(self) -> dict[str, object]:
        return {"check": self.check, "expected": self.expected, "observed": self.observed}


Grader = Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[Failure, ...]]
ScenarioErrors = Callable[[Mapping[str, Any]], list[str]]


class ScenarioSuiteError(ValueError):
    """A corpus, observations file or request that the suite refuses to read."""


def canonical_digest(value: object) -> str:
    """sha256 over sorted-keys compact ASCII JSON, so line endings never move it."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def normalize_split(name: str) -> str:
    """Accept the CLI spelling `held-out` for the `held_out` split."""
    split = str(name).strip().replace("-", "_")
    if split not in SPLITS:
        raise ScenarioSuiteError(f"unknown split: {name!r}; expected one of {', '.join(SPLITS)}")
    return split


def split_path(lane: Path, split: str) -> Path:
    return Path(lane) / "corpus" / SPLIT_FILES[normalize_split(split)]


def read_json_document(path: Path, *, limit: int = 8 * 1024 * 1024) -> Any:
    """Read one bounded UTF-8 JSON file, or refuse it by name."""
    target = Path(path)
    try:
        with target.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise ScenarioSuiteError(f"not readable: {target}: {exc}") from exc
    if len(raw) > limit:
        raise ScenarioSuiteError(f"exceeds the {limit}-byte cap: {target}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScenarioSuiteError(f"not readable JSON: {target}: {exc}") from exc


def load_split(lane: Path, split: str = DEFAULT_SPLIT) -> dict[str, Any]:
    """Load one split of a suite's corpus; the held-out file is read only when named."""
    name = normalize_split(split)
    document = read_json_document(split_path(lane, name))
    if not isinstance(document, dict) or document.get("split") != name:
        raise ScenarioSuiteError(f"{split_path(lane, name)} is not the {name} split")
    return document


def corpus_errors(
    corpus: Mapping[str, Any],
    *,
    suite: str,
    split: str,
    categories: Sequence[str],
    id_prefix: str,
    scenario_errors: ScenarioErrors,
) -> list[str]:
    """Why one split file is not a well-formed corpus of this suite."""
    errors: list[str] = []
    expected_keys = {"schema_version", "suite", "split", "scenarios"}
    if set(corpus) != expected_keys:
        errors.append(f"corpus keys must be exactly {sorted(expected_keys)}")
    if corpus.get("schema_version") != CORPUS_SCHEMA_VERSION:
        errors.append(f"schema_version must be {CORPUS_SCHEMA_VERSION}")
    if corpus.get("suite") != suite:
        errors.append(f"suite must be {suite}")
    if corpus.get("split") != split:
        errors.append(f"split must be {split}")
    scenarios = corpus.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("scenarios must be a non-empty list")
        return errors
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        where = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{where} must be an object")
            continue
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id.startswith(id_prefix) or len(scenario_id) > SCENARIO_ID_LIMIT:
            errors.append(f"{where}.id must be a string starting with {id_prefix!r}, at most {SCENARIO_ID_LIMIT} characters")
        elif scenario_id in seen:
            errors.append(f"{where}.id {scenario_id} is duplicated")
        else:
            seen.add(scenario_id)
        if scenario.get("category") not in categories:
            errors.append(f"{where}.category must be one of {', '.join(categories)}")
        for field in ("request", "why"):
            value = scenario.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{where}.{field} must be a non-empty string")
        errors.extend(f"{where}: {error}" for error in scenario_errors(scenario))
    return errors


def _request_key(text: object) -> str:
    return " ".join(str(text).casefold().split())


def split_isolation_errors(
    tuning: Mapping[str, Any],
    held_out: Mapping[str, Any],
    *,
    categories: Sequence[str],
) -> list[str]:
    """Why the two splits do not stay apart.

    The splits share no id and no request text (compared case- and
    whitespace-insensitively), every category appears in both, and the
    held-out split holds roughly a quarter of the suite.
    """
    errors: list[str] = []
    tuning_rows = [row for row in tuning.get("scenarios", []) if isinstance(row, dict)]
    held_rows = [row for row in held_out.get("scenarios", []) if isinstance(row, dict)]
    shared_ids = sorted({row.get("id") for row in tuning_rows} & {row.get("id") for row in held_rows})
    if shared_ids:
        errors.append(f"ids in both splits: {', '.join(str(item) for item in shared_ids)}")
    tuning_requests = {_request_key(row.get("request")) for row in tuning_rows}
    shared_requests = sorted(row.get("id") for row in held_rows if _request_key(row.get("request")) in tuning_requests)
    if shared_requests:
        errors.append(f"held-out requests repeated in tuning: {', '.join(str(item) for item in shared_requests)}")
    for name, rows in (("tuning", tuning_rows), ("held_out", held_rows)):
        present = {row.get("category") for row in rows}
        missing = [category for category in categories if category not in present]
        if missing:
            errors.append(f"{name} split has no scenario in: {', '.join(missing)}")
    total = len(tuning_rows) + len(held_rows)
    low, high = HELD_OUT_SHARE_RANGE
    if total and not low <= len(held_rows) / total <= high:
        errors.append(f"held-out split holds {len(held_rows)} of {total} scenarios, outside {low:.0%}-{high:.0%}")
    return errors


def wilson_interval(successes: int, trials: int, *, z: float = WILSON_Z_95) -> dict[str, float] | None:
    """Wilson score interval for a binomial proportion, in percent.

    Returns None over an empty denominator: no interval exists for a rate that
    was never measured.
    """
    if successes < 0 or trials < 0 or successes > trials:
        raise ValueError("wilson interval needs 0 <= successes <= trials")
    if trials == 0:
        return None
    proportion = successes / trials
    z2 = z * z
    centre = proportion + z2 / (2 * trials)
    margin = z * math.sqrt(proportion * (1 - proportion) / trials + z2 / (4 * trials * trials))
    denominator = 1 + z2 / trials
    low = max(0.0, (centre - margin) / denominator)
    high = min(1.0, (centre + margin) / denominator)
    return {"low": round(low * 100, 1) + 0.0, "high": round(high * 100, 1) + 0.0, "confidence": 0.95}


def rate_with_interval(
    *,
    numerator: int,
    denominator: int,
    numerator_of: Sequence[str],
    denominator_of: str,
    excluded: Sequence[str],
) -> dict[str, object]:
    """An `omh_reported_rate/v1` payload with its Wilson 95% interval beside it."""
    rate = reported_rate(
        numerator=numerator,
        denominator=denominator,
        numerator_of=list(numerator_of),
        denominator_of=denominator_of,
        excluded=list(excluded),
    )
    return {
        "rate": rate.to_payload(),
        "wilson_95": wilson_interval(numerator, denominator),
        "line": format_reported_rate(rate),
    }


def observations_errors(document: object, *, suite: str, split: str) -> list[str]:
    """Why an observations file is not one this suite and split can grade."""
    if not isinstance(document, dict):
        return ["observations file must be a JSON object"]
    errors: list[str] = []
    expected = {"schema_version", "suite", "split", "arm", "observations"}
    if not expected <= set(document) <= expected | {"run"}:
        errors.append(f"observations keys must be {sorted(expected)} plus optional run")
    if document.get("schema_version") != OBSERVATIONS_SCHEMA_VERSION:
        errors.append(f"schema_version must be {OBSERVATIONS_SCHEMA_VERSION}")
    if document.get("suite") != suite:
        errors.append(f"suite must be {suite}")
    if document.get("split") != split:
        errors.append(f"split must be {split}; a file recorded on one split is never graded against the other")
    arm = document.get("arm")
    if not isinstance(arm, str) or not arm.strip():
        errors.append("arm must name the arm that produced these observations")
    run = document.get("run", {})
    if not isinstance(run, dict) or not set(run) <= RUN_KEYS or not all(isinstance(value, str) for value in run.values()):
        errors.append(f"run must be an object of strings with keys from {sorted(RUN_KEYS)}")
    rows = document.get("observations")
    if not isinstance(rows, list):
        errors.append("observations must be a list")
        return errors
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"observations[{index}]"
        if not isinstance(row, dict) or not set(row) <= OBSERVATION_KEYS:
            errors.append(f"{where} must be an object with keys from {sorted(OBSERVATION_KEYS)}")
            continue
        scenario_id = row.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            errors.append(f"{where}.scenario_id must be a string")
        elif scenario_id in seen:
            errors.append(f"{where}.scenario_id {scenario_id} is observed twice")
        else:
            seen.add(scenario_id)
        status = row.get("status")
        if status not in OBSERVATION_STATUSES:
            errors.append(f"{where}.status must be one of {', '.join(OBSERVATION_STATUSES)}")
        elif status == INFRASTRUCTURE_FAILURE:
            if row.get("infrastructure_failure") not in INFRASTRUCTURE_FAILURE_CLASSES:
                errors.append(f"{where}.infrastructure_failure must be one of {', '.join(INFRASTRUCTURE_FAILURE_CLASSES)}")
            if "decision" in row:
                errors.append(f"{where} is an infrastructure failure and must carry no decision")
            reason = row.get("reason", "")
            if not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS:
                errors.append(f"{where}.reason must be a string of at most {MAX_REASON_CHARS} characters")
        else:
            if "infrastructure_failure" in row or "reason" in row:
                errors.append(f"{where} is observed and must not name an infrastructure failure or reason")
            if not isinstance(row.get("decision"), dict):
                errors.append(f"{where}.decision must be an object")
        links = row.get("evidence_links", [])
        if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
            errors.append(f"{where}.evidence_links must be a list of strings")
    return errors


def _count_rate(
    passed: int,
    graded: int,
    excluded_counts: Mapping[str, int],
    *,
    denominator_of: str,
) -> dict[str, object]:
    return rate_with_interval(
        numerator=passed,
        denominator=graded,
        numerator_of=["passed"],
        denominator_of=denominator_of,
        excluded=[name for name in EXCLUDED_CLASSES if excluded_counts.get(name)],
    )


def build_suite_report(
    *,
    suite: str,
    corpus: Mapping[str, Any],
    observations: Mapping[str, Any],
    grade: Grader,
    categories: Sequence[str],
    artifact: str,
) -> dict[str, Any]:
    """Grade one observations file against one split and report it.

    Refuses an observation of a scenario this split does not hold, so a
    tuning file cannot be graded as held-out evidence or the reverse.
    """
    split = str(corpus.get("split"))
    errors = observations_errors(observations, suite=suite, split=split)
    if errors:
        raise ScenarioSuiteError("; ".join(errors))
    scenarios = [row for row in corpus["scenarios"] if isinstance(row, dict)]
    by_id = {str(row["id"]): row for row in scenarios}
    rows = {str(row["scenario_id"]): row for row in observations["observations"]}
    unknown = sorted(set(rows) - set(by_id))
    if unknown:
        raise ScenarioSuiteError(f"observations name scenarios the {split} split does not hold: {', '.join(unknown)}")
    if split == HELD_OUT_SPLIT:
        # A partial held-out file, or one padded with infrastructure failures,
        # would let its totals name one scenario's verdict.
        if set(rows) != set(by_id):
            raise ScenarioSuiteError(
                f"a held-out report needs an observation (graded or infrastructure failure) of every one of its "
                f"{len(by_id)} scenarios; this file has {len(rows)}"
            )
        graded_rows = sum(1 for row in rows.values() if row["status"] == OBSERVED)
        if graded_rows * HELD_OUT_MIN_GRADED_DENOMINATOR < len(by_id) * HELD_OUT_MIN_GRADED_NUMERATOR:
            raise ScenarioSuiteError(
                f"a held-out report needs at least {HELD_OUT_MIN_GRADED_NUMERATOR}/{HELD_OUT_MIN_GRADED_DENOMINATOR} "
                f"of its {len(by_id)} scenarios graded; this file grades {graded_rows}. Rerun the whole split."
            )

    outcomes: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        row = rows.get(scenario_id)
        group = SKILL_RULE_GROUP if scenario.get("skill_rule") else REQUEST_DERIVABLE_GROUP
        base = {"scenario_id": scenario_id, "category": scenario["category"], "group": group}
        if row is None:
            outcomes.append({**base, "outcome": NOT_OBSERVED})
        elif row["status"] == INFRASTRUCTURE_FAILURE:
            outcomes.append({**base, "outcome": row["infrastructure_failure"]})
        else:
            failures = grade(scenario, row)
            outcomes.append({
                **base,
                "outcome": "failed" if failures else "passed",
                "failures": [failure.to_payload() for failure in failures],
            })

    def tally(selected: list[dict[str, Any]]) -> dict[str, Any]:
        excluded_counts = {name: sum(1 for item in selected if item["outcome"] == name) for name in EXCLUDED_CLASSES}
        passed = sum(1 for item in selected if item["outcome"] == "passed")
        graded = sum(1 for item in selected if item["outcome"] in {"passed", "failed"})
        return {
            "scenarios": len(selected),
            "graded": graded,
            "passed": passed,
            "failed": graded - passed,
            "excluded_counts": excluded_counts,
            "pass_rate": _count_rate(passed, graded, excluded_counts, denominator_of=f"graded {split} scenarios"),
        }

    overall = tally(outcomes)
    observed = overall["graded"] > 0
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite": suite,
        "split": split,
        "arm": observations["arm"],
        "run": dict(observations.get("run", {})),
        "headline": {
            "status": "observed" if observed else "prepared_not_observed",
            "arm": observations["arm"],
            "corpus": suite,
            "split": split,
            "corpus_digest": canonical_digest(corpus),
            "selection_rule": (
                f"{len(rows)} of the {len(by_id)} scenarios in the {split} split observed, one observation each; "
                f"{', '.join(EXCLUDED_CLASSES)} excluded from the denominator by name"
            ),
            "artifact": artifact,
            "artifact_digest": canonical_digest(observations),
            "pass_rate": overall["pass_rate"],
        },
        "totals": overall,
        "claim_boundary": (
            "A rate describes this arm on this split of this corpus at this revision. It is a structural "
            "grade of prepared decisions, not evidence that an automation ran, a handoff executed, or a "
            "reply was delivered, and it says nothing about any other model, prompt or corpus."
        ),
    }
    if split == HELD_OUT_SPLIT:
        # Totals only. A held-out category holds a scenario or two, so a
        # per-category rate would name which one failed, and which held-out
        # scenario failed, and why, is exactly what tuning skill text against
        # the held-out split would need.
        report["scenario_detail"] = "withheld_for_held_out_split"
    else:
        report["per_category"] = {
            category: tally([item for item in outcomes if item["category"] == category]) for category in categories
        }
        # Which numbers measure the skill text: a skill_rule scenario's
        # expectation rests on a rule only the skill text states, so only the
        # skill-text arm can derive it; any arm can derive the rest from the
        # request alone.
        report["per_group"] = {group: tally([item for item in outcomes if item["group"] == group]) for group in GROUPS}
        report["scenarios"] = outcomes
    return report


def summary_lines(report: Mapping[str, Any]) -> list[str]:
    """A short text view of a report: the headline, then one line per category."""
    headline = report["headline"]
    lines = [
        f"{report['suite']} [{report['split']}] arm={report['arm']} status={headline['status']}",
        f"  overall: {headline['pass_rate']['line']}",
    ]
    interval = headline["pass_rate"]["wilson_95"]
    if interval:
        lines.append(f"  wilson 95%: {interval['low']}%-{interval['high']}%")
    for group, block in report.get("per_group", {}).items():
        lines.append(f"  [{group}]: {block['pass_rate']['line']}")
    for category, block in report.get("per_category", {}).items():
        lines.append(f"  {category}: {block['pass_rate']['line']}")
    return lines


def prompt_view(scenario: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """The part of a scenario an arm may see: never `expect` or `why`."""
    return {key: scenario[key] for key in keys if key in scenario}


def scenario_prompt(
    *,
    suite_instructions: str,
    decision_contract: str,
    view: Mapping[str, Any],
    skill_texts: Sequence[tuple[str, str]] = (),
) -> str:
    """One scenario's prompt for a live arm.

    `skill_texts` is the `skill-text` arm's inlined guidance, as (path, text)
    pairs read from the checkout; the `bare` arm passes none. A prompt over
    the byte budget is refused rather than cut, because a cut prompt would be
    graded as the arm's decision about a scenario it never fully saw.
    """
    parts = [suite_instructions.strip(), ""]
    if skill_texts:
        parts.append("The following OMH skill guidance applies. Follow it.")
        for path, text in skill_texts:
            parts.extend([f"--- {path} ---", text.strip(), f"--- end {path} ---"])
        parts.append("")
    parts.extend([
        "Scenario (JSON):",
        json.dumps(view, indent=2, sort_keys=True, ensure_ascii=False),
        "",
        decision_contract.strip(),
        "",
        f"Write your decision as one JSON object to the file {DECISION_FILENAME} in the current working "
        "directory. Write nothing else there, do not run any command, and do not create, edit or "
        "remove any real job, branch, or remote object: this is an evaluation and only the file counts.",
    ])
    prompt = "\n".join(parts) + "\n"
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ScenarioSuiteError(f"scenario prompt exceeds the {MAX_PROMPT_BYTES}-byte budget")
    return prompt


def skill_texts_digest(skill_texts: Sequence[tuple[str, str]]) -> str:
    """Digest of the inlined guidance, with line endings normalized."""
    return canonical_digest([[path, text.replace("\r\n", "\n")] for path, text in skill_texts])


def child_dispatch_argv(
    executable: str,
    *,
    hermes_executable: str,
    workspace: Path,
    model: str,
    provider: str,
    reasoning: str,
    parent_run_id: str,
    run_id: str,
    timeout: int,
) -> list[str]:
    """The Hermes-native child boundary command a lane's live arm runs.

    The prompt goes on the child's stdin, never on argv; the command refuses
    without `--confirm-dispatch`.
    """
    return [
        executable, "coding", "hermes-child", "dispatch", "--confirm-dispatch",
        "--model", model, "--provider", provider, "--reasoning", reasoning,
        "--parent-run-id", parent_run_id, "--run-id", run_id,
        "--hermes", hermes_executable, "--cwd", str(workspace),
        "--timeout", str(timeout), "--json",
    ]


def read_decision_file(workspace: Path) -> tuple[dict[str, Any] | None, str]:
    """The decision an arm wrote, or why there is none.

    A reason names the file only, never its directory: it is stored on the
    observation, and the workspace path can carry a home directory.
    """
    target = Path(workspace) / DECISION_FILENAME
    if not target.exists():
        return None, f"{DECISION_FILENAME} was not written"
    try:
        with target.open("rb") as handle:
            raw = handle.read(MAX_DECISION_FILE_BYTES + 1)
    except OSError as exc:
        return None, f"{DECISION_FILENAME} is not readable ({type(exc).__name__})"
    if len(raw) > MAX_DECISION_FILE_BYTES:
        return None, f"{DECISION_FILENAME} exceeds the {MAX_DECISION_FILE_BYTES}-byte cap"
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, f"{DECISION_FILENAME} is not readable UTF-8 JSON"
    if not isinstance(document, dict):
        return None, f"{DECISION_FILENAME} is not a JSON object"
    return document, ""


def child_status(stdout: str) -> str:
    """The child's terminal status from `hermes-child dispatch --json`, or ''."""
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    # `routing_observation/v1` keeps the terminal status at the top level.
    status = payload.get("status")
    return status if isinstance(status, str) else ""


def observation_from_dispatch(
    scenario_id: str,
    *,
    launched: bool,
    timed_out: bool,
    stdout: str,
    decision: Mapping[str, Any] | None,
    decision_keys: Sequence[str],
    evidence_links: Sequence[str] = (),
    reason: str = "",
) -> dict[str, Any]:
    """Classify one live dispatch into an observation row.

    - The outer wait or the child itself timed out: `timeout`.
    - The child ended `failed` or `cancelled` without writing a decision:
      `transport_error`.
    - The `omh` command could not start, or reported no `completed` child and
      no decision was written (a refusal, a non-terminal status):
      `arm_did_not_run`.
    - Otherwise the arm ran: its decision, narrowed to `decision_keys`, is
      graded. A child that completed and wrote no decision is graded on an
      empty decision and fails; it ran, so that is a result, not an outage.

    `evidence_links` are the scenario's own evidence links, set by the
    harness. A link the model wrote into its decision file never becomes
    evidence.
    """
    status = child_status(stdout) if launched else ""
    head = f"child status {status or 'none'}" if launched else "the omh command could not start"
    diagnosis = "; ".join(part for part in (head, reason.strip()) if part)[:MAX_REASON_CHARS]

    def failure(kind: str) -> dict[str, Any]:
        return {"scenario_id": scenario_id, "status": INFRASTRUCTURE_FAILURE, "infrastructure_failure": kind, "reason": diagnosis}

    if timed_out or status == "timed_out":
        return failure("timeout")
    if decision is None and status in {"failed", "cancelled"}:
        return failure("transport_error")
    # Only a child that reported `completed`, or one that wrote a decision, ran.
    # A refusal, a non-terminal status or no status at all started nothing.
    if not launched or (decision is None and status != "completed"):
        return failure("arm_did_not_run")
    narrowed = {key: decision[key] for key in decision_keys if decision is not None and key in decision}
    row: dict[str, Any] = {"scenario_id": scenario_id, "status": OBSERVED, "decision": narrowed}
    if evidence_links:
        row["evidence_links"] = list(evidence_links)
    return row


def new_observations_document(*, suite: str, split: str, arm: str, run: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": OBSERVATIONS_SCHEMA_VERSION,
        "suite": suite,
        "split": normalize_split(split),
        "arm": arm,
        "run": dict(run),
        "observations": [],
    }


def write_json(path: Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def string_list(value: object) -> list[str] | None:
    """The value as a list of strings, or None when it is not one."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "DECISION_FILENAME",
    "DEFAULT_SPLIT",
    "EXCLUDED_CLASSES",
    "HELD_OUT_SPLIT",
    "INFRASTRUCTURE_FAILURE",
    "INFRASTRUCTURE_FAILURE_CLASSES",
    "NOT_OBSERVED",
    "OBSERVATIONS_SCHEMA_VERSION",
    "OBSERVED",
    "REPORT_SCHEMA_VERSION",
    "SPLITS",
    "SPLIT_FILES",
    "TUNING_SPLIT",
    "Failure",
    "ScenarioSuiteError",
    "build_suite_report",
    "canonical_digest",
    "child_dispatch_argv",
    "child_status",
    "corpus_errors",
    "load_split",
    "new_observations_document",
    "normalize_split",
    "observation_from_dispatch",
    "observations_errors",
    "prompt_view",
    "rate_with_interval",
    "read_decision_file",
    "read_json_document",
    "scenario_prompt",
    "skill_texts_digest",
    "split_isolation_errors",
    "split_path",
    "string_list",
    "summary_lines",
    "wilson_interval",
]

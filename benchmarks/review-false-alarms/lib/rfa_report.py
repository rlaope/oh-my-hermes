"""Per-arm summary and the markdown table both numbers are read from."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from rfa_grading import ARMS

MIN_RUNS = 3


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _flips(outcomes_by_run: Mapping[int, str]) -> int:
    """Adjacent runs (in run order) whose outcome differs."""

    ordered = [outcomes_by_run[run] for run in sorted(outcomes_by_run)]
    return sum(1 for before, after in zip(ordered, ordered[1:]) if before != after)


def summarize(graded: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_arm: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in graded:
        by_arm[row["arm"]].append(row)
    summary = {}
    for arm in ARMS:
        rows = by_arm.get(arm, [])
        if not rows:
            continue
        traps = [row for row in rows if row["kind"] == "trap"]
        controls = [row for row in rows if row["kind"] == "control"]
        false_alarms = sum(1 for row in traps if row["outcome"] == "false_alarm")
        hits = sum(1 for row in controls if row["outcome"] == "hit")
        per_case: dict[str, dict[int, str]] = defaultdict(dict)
        for row in rows:
            per_case[row["case"]][row["run"]] = row["outcome"]
        flips = {case: _flips(outcomes) for case, outcomes in sorted(per_case.items())}
        runs_per_case = {case: len(outcomes) for case, outcomes in per_case.items()}
        summary[arm] = {
            "trap_runs": len(traps),
            "false_alarms": false_alarms,
            "false_alarm_rate": _rate(false_alarms, len(traps)),
            "control_runs": len(controls),
            "hits": hits,
            "hit_rate": _rate(hits, len(controls)),
            "no_verdict": sum(1 for row in rows if row["outcome"] == "no_verdict"),
            "no_verdict_traps": sum(1 for row in traps if row["outcome"] == "no_verdict"),
            "no_verdict_controls": sum(1 for row in controls if row["outcome"] == "no_verdict"),
            "miss_location": sum(1 for row in controls if row["outcome"] == "miss_location"),
            "flips": flips,
            "flip_total": sum(flips.values()),
            "cases_with_flips": sum(1 for count in flips.values() if count),
            "min_runs_per_case": min(runs_per_case.values()),
        }
    return summary


def verdict_on_win_rule(summary: Mapping[str, Mapping[str, Any]]) -> str:
    """The two-sided rule: fewer false alarms on traps AND no fewer hits on controls."""

    on, off = summary.get("omh-on"), summary.get("omh-off")
    if not on or not off:
        return "not decided: both arms are needed"
    rates = (on["false_alarm_rate"], off["false_alarm_rate"], on["hit_rate"], off["hit_rate"])
    if any(rate is None for rate in rates):
        return "not decided: an arm has no trap runs or no control runs"
    on_fa, off_fa, on_hit, off_hit = rates
    if min(on["min_runs_per_case"], off["min_runs_per_case"]) < MIN_RUNS:
        prefix = f"noise (fewer than {MIN_RUNS} runs per case); "
    else:
        prefix = ""
    if on_fa < off_fa and on_hit >= off_hit:
        return prefix + "omh-on wins: fewer false alarms, hit rate held"
    if on_fa < off_fa:
        return prefix + "no win: fewer false alarms, but fewer controls hit"
    if on_hit < off_hit:
        return prefix + "no win: false alarms not lower, and fewer controls hit"
    return prefix + "no win: false alarms not lower"


def _percent(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)"


def markdown_table(summary: Mapping[str, Mapping[str, Any]]) -> str:
    lines = [
        "| arm | false-alarm rate (traps) | hit rate (controls) | no_verdict | wrong location | cases with flips | flips |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, row in summary.items():
        lines.append(
            f"| {arm} | {_percent(row['false_alarms'], row['trap_runs'])} "
            f"| {_percent(row['hits'], row['control_runs'])} "
            f"| {row['no_verdict']} (traps {row['no_verdict_traps']}, controls {row['no_verdict_controls']}) "
            f"| {row['miss_location']} "
            f"| {row['cases_with_flips']} | {row['flip_total']} |"
        )
    lines.append("")
    lines.append(f"Win rule: {verdict_on_win_rule(summary)}")
    return "\n".join(lines)


def per_case_table(graded: Iterable[Mapping[str, Any]]) -> str:
    """One row per case, each arm's outcomes in run order."""

    cells: dict[str, dict[str, dict[int, str]]] = defaultdict(lambda: defaultdict(dict))
    kinds: dict[str, str] = {}
    for row in graded:
        cells[row["case"]][row["arm"]][row["run"]] = row["outcome"]
        kinds[row["case"]] = row["kind"]
    arms = [arm for arm in ARMS if any(arm in by_arm for by_arm in cells.values())]
    lines = [
        "| case | kind | " + " | ".join(arms) + " |",
        "| --- | --- | " + " | ".join("---" for _ in arms) + " |",
    ]
    for case in sorted(cells, key=lambda name: (kinds[name], name)):
        outcomes = [
            ", ".join(cells[case][arm][run] for run in sorted(cells[case][arm])) or "-"
            for arm in arms
        ]
        lines.append(f"| {case} | {kinds[case]} | " + " | ".join(outcomes) + " |")
    return "\n".join(lines)

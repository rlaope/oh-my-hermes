#!/usr/bin/env python3
# ─── How to run ───
# python tools/test_sharding/aggregate.py --plan plan.json \
#   --quarantine tools/test_sharding/quarantine.json --results-dir results/ \
#   --lanes linux-3.11,linux-3.12,windows-3.12 \
#   --lane-plan windows-3.12=plan-windows.json
"""Fail-closed, lane-aware reconciliation for deterministic unittest shards."""

from __future__ import annotations

import argparse
import collections
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.test_sharding import JsonValue, ShardingError
from tools.test_sharding.plan import MAX_DURATION_SECONDS, load_quarantine

MAX_TIMING_ENTRIES: Final = 50_000
TOP_SLOWEST: Final = 10
QUARANTINE_KEY: Final = -1


@dataclass(frozen=True, slots=True)
class ShardResult:
    """One validated lane-local shard execution result."""

    lane: str
    kind: str
    shard: int
    planned: tuple[str, ...]
    executed: tuple[str, ...]
    skipped: tuple[str, ...]
    failures: tuple[str, ...]
    errors: tuple[str, ...]
    durations: dict[str, float]

    def accounted(self) -> tuple[str, ...]:
        return tuple(sorted(self.executed + self.skipped + self.failures + self.errors))


def _string_list(payload: dict[str, JsonValue], key: str, source: Path) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ShardingError(f"result {source.name} has a malformed {key} list")
    return tuple(sorted(value))


def load_result(path: Path) -> ShardResult:
    """Parse one untrusted result file into the aggregate's typed boundary."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardingError(f"result file is not readable JSON: {path.name}") from exc
    if (
        not isinstance(payload, dict)
        or isinstance(payload.get("version"), bool)
        or not isinstance(payload.get("version"), int)
        or payload.get("version") != 1
    ):
        raise ShardingError(f"result {path.name} must be a version-1 JSON object")
    lane = payload.get("lane")
    kind = payload.get("kind")
    shard = payload.get("shard")
    if not isinstance(lane, str) or not lane.strip():
        raise ShardingError(f"result {path.name} has a malformed lane")
    match kind, shard:
        case "shard", bool():
            raise ShardingError(f"result {path.name} has a malformed shard index")
        case "shard", int() as index if index >= 0:
            shard_key = index
        case "quarantine", None:
            shard_key = QUARANTINE_KEY
        case "shard", _:
            raise ShardingError(f"result {path.name} has a malformed shard index")
        case "quarantine", _:
            raise ShardingError(f"result {path.name} quarantine must not carry a shard")
        case _:
            raise ShardingError(f"result {path.name} has an unknown kind: {kind}")
    durations = payload.get("durations")
    if not isinstance(durations, dict) or not all(
        isinstance(test_id, str)
        and not isinstance(seconds, bool)
        and isinstance(seconds, int | float)
        and math.isfinite(seconds)
        for test_id, seconds in durations.items()
    ):
        raise ShardingError(f"result {path.name} has malformed durations")
    return ShardResult(
        lane=lane,
        kind=kind,
        shard=shard_key,
        planned=_string_list(payload, "planned", path),
        executed=_string_list(payload, "executed", path),
        skipped=_string_list(payload, "skipped", path),
        failures=_string_list(payload, "failures", path),
        errors=_string_list(payload, "errors", path),
        durations={test_id: min(max(float(seconds), 0.0), MAX_DURATION_SECONDS) for test_id, seconds in durations.items()},
    )


def load_plan(path: Path) -> dict[int, tuple[str, ...]]:
    """Parse and internally reconcile the static plan before trusting results."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardingError(f"plan file is not readable JSON: {path}") from exc
    if (
        not isinstance(payload, dict)
        or isinstance(payload.get("version"), bool)
        or not isinstance(payload.get("version"), int)
        or payload.get("version") != 1
    ):
        raise ShardingError("plan file must be a version-1 JSON object")
    shards, quarantine, counts = payload.get("shards"), payload.get("quarantine"), payload.get("counts")
    shard_count = payload.get("shard_count")
    if (
        not isinstance(shards, dict)
        or not isinstance(quarantine, list)
        or not all(isinstance(test_id, str) for test_id in quarantine)
        or isinstance(shard_count, bool)
        or not isinstance(shard_count, int)
        or not isinstance(counts, dict)
        or set(counts) != {"discovered", "sharded", "quarantined"}
        or any(isinstance(count, bool) or not isinstance(count, int) for count in counts.values())
    ):
        raise ShardingError("plan file is malformed")
    parsed: dict[int, tuple[str, ...]] = {}
    for key, value in shards.items():
        if not isinstance(key, str) or not key.isdecimal() or not isinstance(value, list) or not all(isinstance(test_id, str) for test_id in value):
            raise ShardingError(f"plan shard {key} is malformed")
        parsed[int(key)] = tuple(sorted(value))
    assigned = [test_id for shard in parsed.values() for test_id in shard] + sorted(quarantine)
    if (
        len(assigned) != len(set(assigned))
        or counts["discovered"] != len(assigned)
        or counts["sharded"] != len(assigned) - len(quarantine)
        or counts["quarantined"] != len(quarantine)
    ):
        raise ShardingError("plan counts do not match an exact-once assignment")
    if set(parsed) != set(range(len(parsed))) or shard_count != len(parsed):
        raise ShardingError("plan shard indexes are not contiguous from zero")
    parsed[QUARANTINE_KEY] = tuple(sorted(quarantine))
    return parsed


def parse_lanes(raw: str) -> tuple[str, ...]:
    """Parse the required lane set, rejecting empty or duplicate identities."""

    lanes = tuple(part.strip() for part in raw.split(","))
    if not lanes or any(not lane for lane in lanes) or len(lanes) != len(set(lanes)):
        raise ShardingError("lanes must be a non-empty, unique comma-separated set")
    return lanes


def lane_plans(default: dict[int, tuple[str, ...]], lanes: tuple[str, ...], overrides: dict[str, dict[int, tuple[str, ...]]]) -> dict[str, dict[int, tuple[str, ...]]]:
    """Bind each lane to the plan it ran, and prove every plan covers one suite.

    A lane may run a different shard count (Windows is the long pole), but every
    plan must assign the same discovered IDs and the same serial quarantine, or
    the lanes would not be measuring the same suite.
    """

    unknown = sorted(set(overrides) - set(lanes))
    if unknown:
        raise ShardingError(f"lane plan given for a lane that is not required: {unknown[0]}")
    plans = {lane: overrides.get(lane, default) for lane in lanes}
    baseline_ids = sorted(test_id for tests in default.values() for test_id in tests)
    for lane, plan in plans.items():
        if plan[QUARANTINE_KEY] != default[QUARANTINE_KEY] or sorted(test_id for tests in plan.values() for test_id in tests) != baseline_ids:
            raise ShardingError(f"plan for {lane} does not cover the same tests and quarantine as the default plan")
    return plans


def parse_lane_plan(raw: str) -> tuple[str, Path]:
    """Parse one LANE=PATH override, rejecting an empty lane or path."""

    lane, separator, path = raw.partition("=")
    if not separator or not lane.strip() or not path.strip():
        raise ShardingError(f"lane plan must be LANE=PATH: {raw}")
    return lane.strip(), Path(path.strip())


def reconcile(plans: dict[str, dict[int, tuple[str, ...]]], results: list[ShardResult]) -> list[str]:
    """Prove each lane executes every ID of its own plan once and no lane is absent."""

    lanes = tuple(plans)
    indexed: dict[tuple[str, int], ShardResult] = {}
    for result in results:
        key = (result.lane, result.shard)
        if result.lane not in lanes:
            raise ShardingError(f"unexpected result lane: {result.lane}")
        if key in indexed:
            raise ShardingError(f"duplicate result for {result.lane} shard {result.shard}")
        indexed[key] = result
    expected_keys = {(lane, shard) for lane in lanes for shard in plans[lane]}
    unexpected = set(indexed) - expected_keys
    if unexpected:
        lane, shard = sorted(unexpected)[0]
        raise ShardingError(f"unexpected result for {lane} shard {shard}")
    all_durations: dict[str, float] = {}
    executed = skipped = 0
    for lane in lanes:
        for shard, planned in plans[lane].items():
            label = "quarantine" if shard == QUARANTINE_KEY else f"shard {shard}"
            result = indexed.get((lane, shard))
            if result is None:
                raise ShardingError(f"missing result for {lane} {label}")
            if result.planned != planned or result.accounted() != planned or len(result.accounted()) != len(set(result.accounted())):
                raise ShardingError(f"result for {lane} {label} does not account for every planned test")
            if result.failures or result.errors:
                raise ShardingError(f"{lane} {label} reports {len(result.failures)} failures, {len(result.errors)} errors")
            if not set(result.durations).issubset(result.executed):
                raise ShardingError(f"{lane} {label} reports durations for unexecuted tests")
            all_durations.update({test_id: max(all_durations.get(test_id, 0.0), seconds) for test_id, seconds in result.durations.items()})
            executed += len(result.executed)
            skipped += len(result.skipped)
    expected = plans[lanes[0]]
    discovered = sum(len(tests) for tests in expected.values())
    quarantined = len(expected[QUARANTINE_KEY])
    lines = [f"test sharding aggregate: reconciled {discovered} tests in {len(lanes)} lanes (performance data only; not test, review, or merge evidence)", f"counts: discovered-per-lane={discovered} sharded-per-lane={discovered - quarantined} quarantined-per-lane={quarantined} executed-total={executed} skipped-total={skipped}"]
    for lane in lanes:
        lane_results = [indexed[lane, shard] for shard in plans[lane]]
        lines.append(f"{lane} ({len(plans[lane]) - 1} shards): {sum(len(result.executed) for result in lane_results)} executed, {sum(len(result.skipped) for result in lane_results)} skipped, {sum(sum(result.durations.values()) for result in lane_results):.1f}s cumulative")
    slowest = sorted(all_durations.items(), key=lambda item: (-item[1], item[0]))[:TOP_SLOWEST]
    lines.append("slowest tests (performance data):")
    lines.extend(f"  {seconds:.2f}s  {test_id}" for test_id, seconds in slowest)
    modules: collections.Counter[str] = collections.Counter()
    for test_id, seconds in all_durations.items():
        modules[test_id.split(".")[0]] += seconds
    lines.append("slowest modules (performance data):")
    lines.extend(f"  {seconds:.1f}s  {module}" for module, seconds in sorted(modules.items(), key=lambda item: (-item[1], item[0]))[:TOP_SLOWEST])
    return lines


def write_timings(path: Path, results: list[ShardResult], live: set[str]) -> None:
    """Persist bounded, live-only timing history for the next cache restore."""

    durations: dict[str, float] = {}
    for result in results:
        for test_id, seconds in result.durations.items():
            if test_id in live:
                durations[test_id] = max(durations.get(test_id, 0.0), seconds)
    kept = sorted(durations, key=lambda test_id: (-durations[test_id], test_id))[:MAX_TIMING_ENTRIES]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "durations": {test_id: durations[test_id] for test_id in sorted(kept)}}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--quarantine", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--lanes", required=True)
    parser.add_argument("--lane-plan", action="append", default=[], help="LANE=PATH: a lane that ran its own plan (repeatable)")
    parser.add_argument("--timings-out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Aggregate all configured lanes and fail closed on every discrepancy."""

    args = _parser().parse_args(argv)
    try:
        load_quarantine(args.quarantine)
        overrides: dict[str, dict[int, tuple[str, ...]]] = {}
        for raw in args.lane_plan:
            lane, path = parse_lane_plan(raw)
            if lane in overrides:
                raise ShardingError(f"duplicate lane plan for {lane}")
            overrides[lane] = load_plan(path)
        plans = lane_plans(load_plan(args.plan), parse_lanes(args.lanes), overrides)
        paths = sorted(args.results_dir.glob("*.json"))
        if not paths:
            raise ShardingError(f"no shard results found in {args.results_dir}")
        results = [load_result(path) for path in paths]
        lines = reconcile(plans, results)
        if args.timings_out is not None:
            write_timings(args.timings_out, results, {test_id for plan in plans.values() for tests in plan.values() for test_id in tests})
    except ShardingError as exc:
        print(f"test sharding aggregate: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

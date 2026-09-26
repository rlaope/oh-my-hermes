#!/usr/bin/env python3
# ─── How to run ───
# python tools/test_sharding/plan.py --shards 2 --shard0-offset 25 \
#   --durations tools/test_sharding/timings.json \
#   --quarantine tools/test_sharding/quarantine.json --out plan.json
"""Build a deterministic, static unittest shard plan without importing tests."""

from __future__ import annotations

import argparse
import collections
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.test_sharding import JsonValue, ShardingError
from tools.test_sharding.static_inventory import discover_inventory

MAX_DURATION_SECONDS: Final = 3600.0
DEFAULT_DURATION_SECONDS: Final = 1.0
DATE_LENGTH: Final = 10


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    """One owned, justified serial-quarantine selector."""

    match: str
    owner: str
    reason: str
    added: str


@dataclass(frozen=True, slots=True)
class PlanningInputs:
    """All trusted, already-parsed inputs to deterministic planning."""

    inventory: tuple[str, ...]
    durations: dict[str, float]
    quarantine: tuple[QuarantineEntry, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    """The exact-once assignment of every statically discovered test ID."""

    shards: tuple[tuple[str, ...], ...]
    quarantine: tuple[str, ...]

    def payload(self) -> dict[str, JsonValue]:
        sharded = sum(len(shard) for shard in self.shards)
        return {
            "version": 1,
            "shard_count": len(self.shards),
            "shards": {str(index): list(shard) for index, shard in enumerate(self.shards)},
            "quarantine": list(self.quarantine),
            "counts": {
                "discovered": sharded + len(self.quarantine),
                "sharded": sharded,
                "quarantined": len(self.quarantine),
            },
        }


def load_timings(path: Path) -> dict[str, float]:
    """Parse bounded duration history; only test IDs remain meaningful later."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardingError(f"timings file is not readable JSON: {path}") from exc
    if (
        not isinstance(payload, dict)
        or isinstance(payload.get("version"), bool)
        or not isinstance(payload.get("version"), int)
        or payload.get("version") != 1
    ):
        raise ShardingError("timings file must be a version-1 JSON object")
    durations = payload.get("durations")
    if not isinstance(durations, dict):
        raise ShardingError("timings file must carry a durations object")
    parsed: dict[str, float] = {}
    for test_id, seconds in durations.items():
        if (
            not isinstance(test_id, str)
            or isinstance(seconds, bool)
            or not isinstance(seconds, int | float)
            or not math.isfinite(seconds)
        ):
            raise ShardingError("timings durations must map test IDs to finite numbers")
        parsed[test_id] = min(max(float(seconds), 0.0), MAX_DURATION_SECONDS)
    return parsed


def load_quarantine(path: Path) -> tuple[QuarantineEntry, ...]:
    """Parse quarantine metadata and refuse entries without ownership."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShardingError(f"quarantine file is not readable JSON: {path}") from exc
    if (
        not isinstance(payload, dict)
        or isinstance(payload.get("version"), bool)
        or not isinstance(payload.get("version"), int)
        or payload.get("version") != 1
    ):
        raise ShardingError("quarantine file must be a version-1 JSON object")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ShardingError("quarantine file must carry an entries list")
    parsed: list[QuarantineEntry] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ShardingError("quarantine entries must be JSON objects")
        values = tuple(entry.get(key) for key in ("match", "owner", "reason", "added"))
        if not all(isinstance(value, str) for value in values):
            raise ShardingError("quarantine entries require match/owner/reason/added strings")
        match, owner, reason, added = values
        if not match.strip() or not owner.strip() or not reason.strip():
            raise ShardingError(f"quarantine entry {match or '<unknown>'} needs owner and reason")
        if len(added) != DATE_LENGTH or added[4:5] != "-" or added[7:8] != "-":
            raise ShardingError(f"quarantine entry {match} must record added as YYYY-MM-DD")
        parsed.append(QuarantineEntry(match, owner, reason, added))
    return tuple(parsed)


def expand_quarantine(entries: tuple[QuarantineEntry, ...], inventory: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve selectors statically and reject stale quarantine metadata."""

    selected: set[str] = set()
    for entry in entries:
        matches = {test_id for test_id in inventory if test_id == entry.match or test_id.startswith(entry.match + ".")}
        if not matches:
            raise ShardingError(f"stale quarantine entry matches no discovered test: {entry.match}")
        selected.update(matches)
    return tuple(sorted(selected))


def lpt_partition(durations: dict[str, float], shard_count: int, seeds: tuple[float, ...] = ()) -> list[list[str]]:
    """Use deterministic longest-processing-time-first balancing.

    ``seeds`` is load a shard already carries before any test is placed (work
    the job runs besides its shard list); missing entries are zero.
    """

    if shard_count < 1:
        raise ShardingError("shard count must be at least 1")
    if len(seeds) > shard_count:
        raise ShardingError("more shard seeds than shards")
    loads = [*seeds, *([0.0] * (shard_count - len(seeds)))]
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    for test_id in sorted(durations, key=lambda identifier: (-durations[identifier], identifier)):
        target = min(range(shard_count), key=lambda index: (loads[index], index))
        shards[target].append(test_id)
        loads[target] += durations[test_id]
    return [sorted(shard) for shard in shards]


def count_partition(test_ids: list[str], shard_count: int) -> list[list[str]]:
    """Expose the deterministic count-only baseline used by balance tests."""

    if shard_count < 1:
        raise ShardingError("shard count must be at least 1")
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    for test_id in test_ids:
        shards[min(range(shard_count), key=lambda index: (len(shards[index]), index))].append(test_id)
    return [sorted(shard) for shard in shards]


def build_plan(inputs: PlanningInputs, shard_count: int, shard0_offset: float = 0.0) -> Plan:
    """Assign all IDs once, using measured durations or a stable median fallback.

    Two known loads are seeded before balancing. ``shard0_offset`` is the
    declared seconds of non-test gates that shard 0's job runs after its tests.
    The serial quarantine runs in the last shard's job, after that shard's
    tests, so its duration is seeded onto the last shard, which the balance
    then leaves with the lightest share of parallel tests.
    """

    if not math.isfinite(shard0_offset) or shard0_offset < 0:
        raise ShardingError("shard 0 offset must be a finite, non-negative number of seconds")

    inventory = tuple(sorted(inputs.inventory))
    quarantined = expand_quarantine(inputs.quarantine, inventory)
    remaining = [test_id for test_id in inventory if test_id not in set(quarantined)]
    known = [inputs.durations[test_id] for test_id in remaining if test_id in inputs.durations]
    fallback = statistics.median(known) if known else DEFAULT_DURATION_SECONDS
    seeds = [0.0] * max(shard_count, 1)
    seeds[0] += shard0_offset
    seeds[-1] += sum(inputs.durations.get(test_id, fallback) for test_id in quarantined)
    shards = tuple(tuple(shard) for shard in lpt_partition({test_id: inputs.durations.get(test_id, fallback) for test_id in remaining}, shard_count, tuple(seeds)))
    assigned = [test_id for shard in shards for test_id in shard] + list(quarantined)
    tally = collections.Counter(assigned)
    if sorted(assigned) != list(inventory) or any(count > 1 for count in tally.values()):
        raise ShardingError("shard assignment is not exact-once")
    return Plan(shards, quarantined)


def write_plan(plan: Plan, out: Path) -> None:
    """Write canonical JSON so identical inputs have byte-identical output."""

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan.payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--shard0-offset", type=float, default=0.0, help="declared seconds of non-test gates shard 0's job also runs")
    parser.add_argument("--durations", type=Path, required=True)
    parser.add_argument("--quarantine", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start-dir", type=Path, default=Path("tests"))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the static planner boundary and report its deterministic counts."""

    args = _parser().parse_args(argv)
    try:
        plan = build_plan(PlanningInputs(discover_inventory(args.start_dir), load_timings(args.durations), load_quarantine(args.quarantine)), args.shards, args.shard0_offset)
        write_plan(plan, args.out)
    except ShardingError as exc:
        print(f"test sharding: {exc}", file=sys.stderr)
        return 2
    print(f"test sharding: planned {plan.payload()['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

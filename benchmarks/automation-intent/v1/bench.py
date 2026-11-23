#!/usr/bin/env python3
"""Automation-intent scenario suite: does a request become the right automation?

The commands, gates and live path are in `benchmarks/scenario_suite_bench.py`,
shared by every scenario-suite lane. `validate` and `grade` are offline and
free; `run` spends money and refuses without `--allow-paid-live`,
`--max-paid-calls` and `--confirm`.
"""

from __future__ import annotations

from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parents[1]))

import scenario_suite_bench as runner  # noqa: E402

from omh.quality import automation_intent_grading as suite  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    return runner.main(argv, suite=suite, lane=BASE, grade=suite.grade_automation_intent, parent_run_id="automation-intent")


if __name__ == "__main__":
    raise SystemExit(main())

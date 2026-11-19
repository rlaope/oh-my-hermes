"""The one-shot Hermes harness for a live run.

Imported only by `bench.py run --live`. A dry run never reaches this module's
subprocess call; the tests check the argv it builds without starting Hermes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Any

from rfa_grading import Case

# The task text both arms receive, byte for byte. It states the task and the
# answer format and nothing else: no caution, no hint that some changes are
# correct, no mention of false alarms. The arm difference is whether OMH is
# loaded in the Hermes profile, never this text.
REVIEW_PROMPT = (
    "Review a code change. The unified diff is in diff.patch in the current "
    "directory, and the files as they are after the change are under context/ "
    "(you may read any of them).\n"
    "Decide whether the change introduces a bug.\n"
    "End your reply with exactly one line in one of these two forms, and "
    "nothing after it:\n"
    "VERDICT: clean\n"
    "VERDICT: bug <path>:<line>\n"
    "where <path> is the file's path relative to context/ and <line> is the "
    "line number of the bug in that file after the change."
)

DEFAULT_TOOLSETS = "file"
DEFAULT_TIMEOUT = 600
REFUSED_PROVIDERS = frozenset({"og"})


def stage_workspace(case: Case, root: Path) -> Path:
    """Copy one case's diff and context into a fresh directory.

    case.json stays behind: it holds the answer.
    """

    workspace = root / case.id
    workspace.mkdir(parents=True)
    shutil.copy2(case.directory / "diff.patch", workspace / "diff.patch")
    shutil.copytree(case.directory / "context", workspace / "context")
    return workspace


def oneshot_argv(
    *,
    hermes_executable: str,
    profile: str | None,
    workspace: Path,
    usage_file: Path,
    provider: str | None,
    model: str | None,
    toolsets: str,
    ignore_rules: bool,
) -> list[str]:
    """`hermes -z` for one review. Provider and model are passed only when set,
    so an unset flag means the profile's own default model."""

    argv = [hermes_executable]
    if profile:
        argv += ["-p", profile]
    argv += ["-z", REVIEW_PROMPT, "--in", str(workspace), "--usage-file", str(usage_file)]
    argv += ["--toolsets", toolsets]
    if provider:
        argv += ["--provider", provider]
    if model:
        argv += ["--model", model]
    if ignore_rules:
        argv.append("--ignore-rules")
    return argv


def review_once(
    case: Case,
    *,
    hermes_executable: str,
    profile: str | None,
    provider: str | None,
    model: str | None,
    toolsets: str,
    ignore_rules: bool,
    timeout: int,
) -> dict[str, Any]:
    """One live review. Returns the reply text and what the run cost."""

    with TemporaryDirectory(prefix="omh-rfa-") as scratch:
        root = Path(scratch)
        workspace = stage_workspace(case, root / "work")
        usage_file = root / "usage.json"
        argv = oneshot_argv(
            hermes_executable=hermes_executable,
            profile=profile,
            workspace=workspace,
            usage_file=usage_file,
            provider=provider,
            model=model,
            toolsets=toolsets,
            ignore_rules=ignore_rules,
        )
        environment = dict(os.environ)
        environment["TERMINAL_CWD"] = str(workspace)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"output": None, "exit_code": None, "failure": "timeout",
                    "seconds": round(time.monotonic() - started, 3), "usage": None}
        seconds = round(time.monotonic() - started, 3)
        try:
            usage = json.loads(usage_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            usage = None
    return {
        "output": completed.stdout,
        "exit_code": completed.returncode,
        "failure": None if completed.returncode == 0 else "nonzero_exit",
        "seconds": seconds,
        "usage": usage,
    }

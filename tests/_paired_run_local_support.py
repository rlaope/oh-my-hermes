"""Local executable and Git fixtures for paired-run CLI tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import time

root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
# A paired-run arm's harness-owned gateway: ready once gateway.pid exists.
if args[:2] == ["gateway", "run"]:
    home = Path(os.environ["HERMES_HOME"])
    with (root / "gateways.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": args, "hermes_home": str(home), "pid": os.getpid(),
                                 "env_names": sorted(os.environ)}) + "\n")
    (home / "gateway.pid").write_text(str(os.getpid()), encoding="utf-8")
    while True:
        time.sleep(0.2)
# Mirrors the installed Hermes CLI: only `chat --query-file -` reads stdin;
# `-z/--oneshot PROMPT` takes its prompt from argv (#1824).
if args[:3] == ["chat", "--query-file", "-"]:
    prompt = sys.stdin.read()
elif "--oneshot" in args:
    prompt = args[args.index("--oneshot") + 1]
else:
    raise SystemExit("no Hermes query transport in argv")
# One file per call: the arms run at the same time, and on Windows two processes appending to one
# file can lose a line (the C runtime seeks to the end and then writes; it is not an atomic append).
calls = root / "calls"
calls.mkdir(exist_ok=True)
(calls / f"{time.time_ns()}-{os.getpid()}.json").write_text(
    json.dumps({"argv": args, "prompt": prompt, "hermes_home": os.environ.get("HERMES_HOME", "")}),
    encoding="utf-8")
print("completed")
"""


def read_calls(root: Path) -> list[dict[str, object]]:
    """The fake Hermes' chat calls, oldest first (one JSON file per call)."""
    folder = root / "calls"
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.json"), key=lambda f: tuple(int(n) for n in f.stem.split("-")))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()

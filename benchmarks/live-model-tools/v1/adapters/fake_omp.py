#!/usr/bin/env python3
"""Offline stand-in for `omp -p --mode json`, for the omp harness tests only.

It parses the argv the adapter builds, makes the reference `C-SCOPE-TRAP` fix in the
`--cwd` workspace, writes the answer file and prints an omp-shaped JSON event stream.
`FAKE_OMP_MODE` picks a failure: `exit` (exit 1 after one call), `hang` (sleep past the
adapter timeout), `silent` (exit 0 with no assistant message).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def assistant(text: str, tool: str | None, usage: dict) -> dict:
    content = [{"type": "text", "text": text}] if text else []
    if tool:
        content.append({"type": "toolCall", "id": "t1", "name": tool, "arguments": {}})
    return {"type": "message_end", "message": {"role": "assistant", "content": content, "usage": usage,
                                                 "stopReason": "toolUse" if tool else "stop"}}


def main(argv: list[str]) -> int:
    mode = os.environ.get("FAKE_OMP_MODE", "ok")
    flags: dict[str, str] = {}
    args = argv[1:]
    for index, value in enumerate(args):
        if value.startswith("--") and index + 1 < len(args):
            flags[value] = args[index + 1]
    required = {"--mode": "json", "--thinking": None, "--model": None, "--cwd": None, "--max-time": None}
    for flag, expected in required.items():
        if flag not in flags or (expected is not None and flags[flag] != expected):
            print(f"fake omp: bad {flag}", file=sys.stderr)
            return 2
    if "-p" not in args or "--no-title" not in args:
        print("fake omp: not print mode", file=sys.stderr)
        return 2
    workspace = Path(flags["--cwd"])
    prompt = args[-1]
    record = os.environ.get("FAKE_OMP_PROMPT_DIGEST")
    if record:
        Path(record).write_text(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), encoding="utf-8")
    emit({"type": "session", "id": "fake-omp-session", "cwd": str(workspace)})
    emit({"type": "agent_start"})
    usage = {"input": 10, "output": 5, "cacheRead": 100, "cacheWrite": 20, "totalTokens": 135,
             "cost": {"total": 0}}
    if mode == "silent":
        return 0
    emit(assistant("", "read", usage))
    if mode == "hang":
        time.sleep(30)
    if mode == "exit":
        print("fake omp: provider error", file=sys.stderr)
        return 1
    units = workspace / "src/benchapp/units.py"
    units.write_text(units.read_text(encoding="utf-8").replace('{"s": 60,', '{"s": 1,'), encoding="utf-8")
    emit(assistant("", "edit", usage))
    answer = {"changed_paths": ["src/benchapp/units.py"]}
    (workspace / ".omh-benchmark-answer.json").write_text(json.dumps(answer), encoding="utf-8")
    emit(assistant(json.dumps(answer), None, usage))
    emit({"type": "agent_end", "messages": []})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""The `omp` harness: one oh-my-pi print-mode run in the benchmark workspace.

This path exists to compare another coding harness against OMH on the same pinned
instances and the same controller-only validators. It sends the `baseline` condition
prompt (the bare task and completion contract, no OMH calibration, no edit rule naming
Hermes tool names) and leaves omp at its own defaults otherwise.

omp runs as `omp -p --mode json`: one JSON event per stdout line. The adapter reads the
stream in memory and keeps scalar metrics only (token counts, tool-call counts by tool
name, wall time, exit code); the prompt, the events and stderr are never persisted.
omp keeps its own session transcript under its own home, outside the benchmark.

The process is bounded twice: omp's `--max-time` stops the session, and the adapter's
timeout kills the process group it started (its own child, never anything else).
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Iterable

from omh_live import MAX_PROMPT_BYTES, _platform_argv, prompt_digest, prompt_for_condition, task_digest

# Only the bare contract: every other condition carries OMH calibration or the OMH unit head.
OMP_CONDITIONS = ("baseline",)
# omp `--thinking` levels; the manifest's `effort` is passed through when it is one of these.
OMP_THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
ANSWER_KEY = "changed_paths"
# Seconds past omp's own `--max-time` before the adapter kills the process group it started.
_GRACE_SECONDS = 60


def omp_argv(
    executable: str,
    *,
    model: str,
    provider: str,
    effort: str,
    workspace: Path,
    prompt: str,
    max_time: int,
) -> list[str]:
    """Print mode with JSON events; the prompt is the one positional message.

    `--no-title` skips the side request omp makes to name a session: it is not part of
    the task and would be billed outside the main loop. Nothing else is switched off.
    """
    if effort not in OMP_THINKING_LEVELS:
        raise ValueError(f"omp effort must be one of: {', '.join(OMP_THINKING_LEVELS)}")
    if prompt.startswith("@"):
        raise ValueError("an omp message starting with @ is read as a file reference")
    return [
        executable,
        "-p",
        "--mode",
        "json",
        "--no-title",
        "--model",
        f"{provider}/{model}",
        "--thinking",
        effort,
        "--max-time",
        str(max_time),
        "--cwd",
        str(workspace),
        prompt,
    ]


def _text_of(message: dict[str, Any]) -> str:
    parts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def summarize_omp_events(lines: Iterable[str]) -> dict[str, Any]:
    """Scalar metrics from an `omp --mode json` event stream.

    Tokens are summed over every assistant `message_end` (each carries that call's
    usage); `total` counts input, output and both cache directions, as Hermes's
    `total_tokens` does. A line that is not JSON is counted, never kept.
    """
    tokens: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    cost = 0.0
    calls = 0
    session_id: str | None = None
    last_text = ""
    last_stop: str | None = None
    errors = 0
    non_json = 0
    agent_end = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            non_json += 1
            continue
        if not isinstance(event, dict):
            non_json += 1
            continue
        kind = event.get("type")
        if kind == "session" and isinstance(event.get("id"), str):
            session_id = session_id or event["id"]
        elif kind == "agent_end":
            agent_end = True
        elif kind == "message_end":
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            calls += 1
            usage = message.get("usage") or {}
            for source, target in (("input", "input"), ("output", "output"), ("cacheRead", "cache_read"),
                                   ("cacheWrite", "cache_write"), ("totalTokens", "total")):
                value = usage.get(source)
                if isinstance(value, int) and not isinstance(value, bool):
                    tokens[target] += value
            usage_cost = usage.get("cost")
            if isinstance(usage_cost, dict) and isinstance(usage_cost.get("total"), (int, float)):
                cost += float(usage_cost["total"])
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "toolCall" and isinstance(block.get("name"), str):
                    tools[block["name"]] += 1
            if message.get("stopReason") == "error" or message.get("errorMessage"):
                errors += 1
            last_stop = message.get("stopReason") if isinstance(message.get("stopReason"), str) else None
            text = _text_of(message)
            if text:
                last_text = text
    return {
        "session_id": session_id,
        "assistant_calls": calls,
        "tokens": {key: tokens.get(key, 0) for key in ("input", "output", "cache_read", "cache_write", "total")},
        "cost_usd": round(cost, 6),
        "tool_calls": sum(tools.values()),
        "tool_counts": dict(sorted(tools.items())),
        "last_stop_reason": last_stop,
        "error_messages": errors,
        "final_text_has_answer_key": ANSWER_KEY in last_text,
        "agent_end": agent_end,
        "non_json_lines": non_json,
    }


def _classify(summary: dict[str, Any], exit_code: int, stderr: str) -> str:
    normalized = stderr.casefold()
    if any(marker in normalized for marker in ("unauthorized", "401", "forbidden", "403", "no api key", "login")):
        return "authentication_failed"
    if any(marker in normalized for marker in ("rate limit", "429", "too many requests", "usage limit")):
        return "rate_limited"
    if "model" in normalized and ("not found" in normalized or "unknown" in normalized):
        return "model_unavailable"
    if summary["error_messages"]:
        return "provider_error"
    return "process_crash"


def _failed(prompt: str, route: dict[str, str], condition: str, kind: str, classification: str,
            summary: dict[str, Any] | None, exit_code: int | None, wall: float) -> dict[str, Any]:
    receipt: dict[str, Any] = {"classification": classification, "kind": kind}
    if exit_code is not None:
        receipt["exit_code"] = exit_code
    tokens = summary["tokens"]["total"] if summary and summary["assistant_calls"] else None
    return {
        "schema_version": "omh_live_model_trial/v1",
        "execution_path": "omp",
        "condition": condition,
        "task_digest": task_digest(prompt),
        "prompt_digest": prompt_digest(prompt),
        "route": route,
        "observation": {"status": "failed", "tools": summary["tool_calls"] if summary else None,
                        "tokens": tokens, "cost_usd": summary["cost_usd"] if summary else None},
        "failure_receipt": receipt,
        "session_id": summary["session_id"] if summary else None,
        "harness_metrics": _metrics(summary, exit_code, wall),
    }


def _metrics(summary: dict[str, Any] | None, exit_code: int | None, wall: float) -> dict[str, Any]:
    metrics: dict[str, Any] = {"wall_seconds": round(wall, 3), "exit_code": exit_code}
    if summary:
        metrics.update({key: summary[key] for key in (
            "assistant_calls", "tokens", "tool_counts", "last_stop_reason", "error_messages",
            "final_text_has_answer_key", "agent_end", "non_json_lines")})
    return metrics


def omp_environment() -> dict[str, str]:
    """The caller's environment minus every opt-in flag of the Hermes arms.

    The omp launcher given as `--omp-executable` is expected to rebuild its own
    environment (an isolated HOME, no inherited keys); this only keeps the OMH
    flags of other arms from reaching it.
    """
    environment = dict(os.environ)
    for key in ("OMH_HASHLINE_TOOLS", "OMH_LSP_TOOLS", "OMH_IMPACT_CHECK", "TERMINAL_CWD"):
        environment.pop(key, None)
    return environment


def run_omp_trial(
    *,
    omp_executable: str,
    workspace: Path,
    task: str,
    model: str,
    provider: str,
    effort: str,
    condition: str,
    timeout: int,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Run omp once; keep only scalar metrics. `timeout` bounds omp's own `--max-time` too."""
    if not confirmed:
        raise ValueError("explicit paid-live confirmation is required at the effect boundary")
    if condition not in OMP_CONDITIONS:
        raise ValueError("the omp harness sends only the baseline condition (no OMH calibration)")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer from 1 to 3600 seconds")
    if len(task.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_BYTES} bytes")
    prompt = prompt_for_condition(task, {}, condition)
    route = {"selected_model": model, "selected_reasoning_effort": effort, "model_family": provider}
    argv = omp_argv(omp_executable, model=model, provider=provider, effort=effort,
                    workspace=workspace, prompt=prompt, max_time=timeout)
    started = time.time()
    process = subprocess.Popen(_platform_argv(argv), cwd=workspace, env=omp_environment(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout + _GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        # Our own child and its process group only.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        summary = summarize_omp_events(stdout.splitlines())
        return _failed(prompt, route, condition, "timeout", "timeout", summary, None, time.time() - started)
    wall = time.time() - started
    summary = summarize_omp_events(stdout.splitlines())
    if process.returncode != 0:
        return _failed(prompt, route, condition, "process_exit", _classify(summary, process.returncode, stderr),
                       summary, process.returncode, wall)
    if not summary["assistant_calls"]:
        return _failed(prompt, route, condition, "usage_telemetry", "usage_unavailable", summary,
                       process.returncode, wall)
    return {
        "schema_version": "omh_live_model_trial/v1",
        "execution_path": "omp",
        "condition": condition,
        "task_digest": task_digest(prompt),
        "prompt_digest": prompt_digest(prompt),
        "route": route,
        "observation": {
            "status": "completed",
            "tools": summary["tool_calls"],
            "tokens": summary["tokens"]["total"],
            "cost_usd": summary["cost_usd"],
        },
        "failure_receipt": None,
        "session_id": summary["session_id"],
        "harness_metrics": _metrics(summary, process.returncode, wall),
    }

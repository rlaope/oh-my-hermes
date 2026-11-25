"""Prompt-cache report over a Hermes profile's ``state.db``, opened read-only.

``omh cache`` answers why a profile's prompt cache goes cold: how much of each
session source's input was served from cache, how long people pause between
messages, and, per cron job, where its cache writes came from. Nothing here
sends a model request or writes anything; the database is opened with
``mode=ro`` and every column is probed before it is read, like
``delegation_graph``'s usage reader.

The cron write split classifies each model run's write against an estimate of
the job's stable prefix, ``P`` = the smallest write any of the job's model runs
made in the window (a run writes at least its prefix when the cache is cold):

- cold: ``min(write, P)`` of a run that starts more than an hour after the
  job's previous model run (or is its first in the window). The 1h cache tier
  has expired by then, so this write is unavoidable at the run's cadence.
- churn: ``min(write, P)`` of a run within an hour of the previous one whose
  ``system_prompt_hash`` changed. The prefix was still warm but the prompt
  moved, so the write is fixable by keeping the prompt stable.
- other: everything else, ``write - min(write, P)`` of every run plus the
  prefix part of a warm, unchanged run (in-run growth such as tool loops).
"""

from __future__ import annotations

import re
import sqlite3
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

# Hermes `agent/prompt_caching.py` MACHINE_PACED_SOURCES: every other source is paced by a person.
MACHINE_PACED_SOURCES = frozenset(
    {
        "subagent", "cron", "oneshot", "webhook", "kanban", "api", "api_server", "tool", "batch",
        "curator", "a2a", "msgraph_webhook", "gateway_hygiene",
    }
)
COLD_GAP_SECONDS = 3600
GAP_BUCKETS = ("<5m", "5-60m", ">1h")
LINE_LIMIT = 160
JOB_SEPARATOR = " · "
_SECRET = re.compile(
    r"(?i)(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[abpr]-[A-Za-z0-9\-]{8,}"
    r"|\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+|[A-Za-z0-9+/_\-]{40,})"
)


class CacheReportError(RuntimeError):
    """The profile has no readable ``state.db`` or it lacks the ``sessions`` table."""


def _connect(state_db: Path, *, timeout: float = 0.25) -> sqlite3.Connection:
    if not state_db.is_file():
        raise CacheReportError(f"no state.db at {state_db}")
    try:
        return sqlite3.connect(f"file:{quote(str(state_db))}?mode=ro", uri=True, timeout=timeout)
    except sqlite3.Error as exc:
        raise CacheReportError(f"cannot open {state_db} read-only: {exc}") from exc


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _col(columns: set[str], name: str, fallback: str = "NULL") -> str:
    return name if name in columns else fallback


def job_key(title: str | None) -> str:
    """The cron job a session belongs to: its title before ``' · '``, ``'?'`` when the title has none."""
    if not title or JOB_SEPARATOR not in title:
        return "?"
    return title.split(JOB_SEPARATOR, 1)[0]


def redact_line(line: str, limit: int = LINE_LIMIT) -> str:
    """One prompt line safe to print: secret-shaped runs masked, then cut to ``limit`` characters."""
    masked = _SECRET.sub("[redacted]", line.strip())
    return masked if len(masked) <= limit else masked[: limit - 1] + "…"


def _share(read: int, total: int) -> float | None:
    return round(read / total, 4) if total else None


def build_cache_report(hermes_home: str | Path, *, days: float = 7, now: float | None = None) -> dict[str, Any]:
    clock = time.time() if now is None else now
    since = clock - float(days) * 86400
    connection = _connect(Path(hermes_home) / "state.db")
    try:
        columns = _columns(connection, "sessions")
        if "source" not in columns or "started_at" not in columns:
            raise CacheReportError("state.db has no sessions table with source/started_at")
        report: dict[str, Any] = {
            "window": {"days": days, "since": since, "until": clock},
            "sources": _read_share_by_source(connection, columns, since),
            "idle_gaps": _idle_gaps(connection, since),
        }
        report["cron"] = _cron(connection, columns, since)
        report["suggestions"] = suggestions(report["cron"]["split"])
        return report
    except sqlite3.Error as exc:
        raise CacheReportError(f"state.db read failed: {exc}") from exc
    finally:
        connection.close()


def _read_share_by_source(connection: sqlite3.Connection, columns: set[str], since: float) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""SELECT source, COUNT(*), SUM(COALESCE({_col(columns, 'input_tokens', '0')}, 0)),
                   SUM(COALESCE({_col(columns, 'cache_read_tokens', '0')}, 0)),
                   SUM(COALESCE({_col(columns, 'cache_write_tokens', '0')}, 0))
            FROM sessions WHERE started_at >= ? GROUP BY source""",
        (since,),
    ).fetchall()
    out = []
    for source, count, uncached, read, write in rows:
        uncached, read, write = int(uncached or 0), int(read or 0), int(write or 0)
        out.append(
            {
                "source": source or "?",
                "sessions": int(count),
                "input_tokens": uncached,
                "cache_read_tokens": read,
                "cache_write_tokens": write,
                "read_share": _share(read, uncached + read + write),
                "human": (source or "") not in MACHINE_PACED_SOURCES,
            }
        )
    out.sort(key=lambda item: -(item["input_tokens"] + item["cache_read_tokens"] + item["cache_write_tokens"]))
    return out


def _idle_gaps(connection: sqlite3.Connection, since: float) -> dict[str, Any]:
    """Seconds between consecutive user messages inside each human-paced session started in the window."""
    buckets = dict.fromkeys(GAP_BUCKETS, 0)
    if not {"session_id", "role", "timestamp"} <= _columns(connection, "messages"):
        return {"buckets": buckets, "gaps": 0}
    machine = ",".join("?" * len(MACHINE_PACED_SOURCES))
    rows = connection.execute(
        f"""SELECT m.session_id, m.timestamp FROM messages m JOIN sessions s ON s.id = m.session_id
            WHERE s.started_at >= ? AND COALESCE(s.source, '') NOT IN ({machine}) AND m.role = 'user'
            ORDER BY m.session_id, m.timestamp""",
        (since, *sorted(MACHINE_PACED_SOURCES)),
    )
    previous: tuple[Any, float] | None = None
    for session_id, stamp in rows:
        if stamp is None:
            continue
        stamp = float(stamp)
        if previous is not None and previous[0] == session_id:
            gap = stamp - previous[1]
            buckets["<5m" if gap < 300 else "5-60m" if gap <= COLD_GAP_SECONDS else ">1h"] += 1
        previous = (session_id, stamp)
    return {"buckets": buckets, "gaps": sum(buckets.values())}


def _cron(connection: sqlite3.Connection, columns: set[str], since: float) -> dict[str, Any]:
    rows = connection.execute(
        f"""SELECT {_col(columns, 'title')}, started_at, COALESCE({_col(columns, 'message_count', '0')}, 0),
                   COALESCE({_col(columns, 'cache_write_tokens', '0')}, 0), {_col(columns, 'system_prompt_hash')},
                   {_col(columns, 'id')}
            FROM sessions WHERE source = 'cron' AND started_at >= ? ORDER BY started_at""",
        (since,),
    ).fetchall()
    jobs: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        jobs[job_key(row[0])].append(row)
    totals = {"cold": 0, "churn": 0, "other": 0}
    table = []
    churn_pairs: dict[str, tuple[str, str]] = {}
    for key, runs in jobs.items():
        model = [run for run in runs if int(run[2] or 0) > 0]
        write = sum(int(run[3] or 0) for run in runs)
        gaps = [float(b[1]) - float(a[1]) for a, b in zip(model, model[1:])]
        split = {"cold": 0, "churn": 0, "other": 0}
        prefix = min((int(run[3] or 0) for run in model), default=0)
        for index, run in enumerate(model):
            run_write = int(run[3] or 0)
            first = min(run_write, prefix)
            if index == 0 or gaps[index - 1] > COLD_GAP_SECONDS:
                split["cold"] += first
            elif run[4] != model[index - 1][4]:
                split["churn"] += first
                churn_pairs[key] = (model[index - 1][4], run[4])
            else:
                split["other"] += first
            split["other"] += run_write - first
        for name in totals:
            totals[name] += split[name]
        table.append(
            {
                "job": key,
                "runs": len(runs),
                "model_runs": len(model),
                "write_tokens": write,
                "median_gap_minutes": round(statistics.median(gaps) / 60, 1) if gaps else None,
                "prompt_hashes": len({run[4] for run in model}),
                "prefix_estimate": prefix,
                "split": split,
            }
        )
    table.sort(key=lambda item: (-item["write_tokens"], item["job"]))
    total_write = sum(item["write_tokens"] for item in table)
    split_out = {
        name: {"tokens": tokens, "share": _share(tokens, total_write)} for name, tokens in totals.items()
    }
    churn = None
    ranked = sorted((item for item in table if item["split"]["churn"]), key=lambda item: -item["split"]["churn"])
    if ranked:
        top = ranked[0]["job"]
        churn = {"job": top, **_first_difference(connection, columns, *churn_pairs[top])}
    return {
        "sessions": len(rows),
        "model_runs": sum(item["model_runs"] for item in table),
        "write_tokens": total_write,
        "jobs": table,
        "split": split_out,
        "top_churn": churn,
    }


def _prompt(connection: sqlite3.Connection, columns: set[str], digest: str | None) -> str | None:
    if not digest:
        return None
    if {"hash", "prompt"} <= _columns(connection, "system_prompts"):
        row = connection.execute("SELECT prompt FROM system_prompts WHERE hash = ?", (digest,)).fetchone()
        if row and row[0]:
            return str(row[0])
    if "system_prompt" in columns and "system_prompt_hash" in columns:
        row = connection.execute(
            "SELECT system_prompt FROM sessions WHERE system_prompt_hash = ? AND system_prompt IS NOT NULL LIMIT 1",
            (digest,),
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    return None


def _first_difference(connection: sqlite3.Connection, columns: set[str], old: str, new: str) -> dict[str, Any]:
    before, after = _prompt(connection, columns, old), _prompt(connection, columns, new)
    result: dict[str, Any] = {"from_hash": (old or "")[:8], "to_hash": (new or "")[:8]}
    if before is None or after is None:
        return {**result, "line": None, "before": None, "after": None}
    a, b = before.splitlines(), after.splitlines()
    index = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return {
        **result,
        "line": index + 1,
        "before": redact_line(a[index]) if index < len(a) else None,
        "after": redact_line(b[index]) if index < len(b) else None,
    }


def suggestions(split: dict[str, dict[str, Any]]) -> list[str]:
    """One to three plain next steps, largest write class first."""
    advice = {
        "cold": "Most cron cache writes are cold starts after more than an hour idle; the cache cannot stay warm at "
        "that cadence, so run fewer or batched jobs, or shrink the prompt each run rebuilds.",
        "churn": "Some runs rewrote a still-warm prefix because the system prompt changed between them; keep "
        "volatile lines (dates, memory usage headers, skill lists) out of the prompt or at its end.",
        "other": "Much of the write is growth inside a run (tool loops, long tool output); trim tool output and "
        "the turns per run.",
    }
    ranked = [name for name in sorted(split, key=lambda name: -split[name]["tokens"]) if split[name]["tokens"]]
    return [advice[name] for name in ranked] or ["No cron cache writes in this window; nothing to change."]


def main_read_share(hermes_home: str | Path, *, hours: float = 24, now: float | None = None) -> dict[str, Any] | None:
    """Cache read share of the main sessions (human-paced, no parent) active in the last ``hours``; the HUD's field.

    One aggregate query over at most 500 recent sessions, through the effective-activity index when the column
    exists. Returns None when the window has no input. The read never waits on a lock (``timeout=0``): a writer
    holding state.db makes it raise ``sqlite3.OperationalError`` at once, which the HUD takes as "leave it out".
    """
    since = (time.time() if now is None else now) - hours * 3600
    connection = _connect(Path(hermes_home) / "state.db", timeout=0)
    try:
        columns = _columns(connection, "sessions")
        activity = "COALESCE(last_activity_at, started_at)" if "last_activity_at" in columns else "started_at"
        parent = "AND parent_session_id IS NULL" if "parent_session_id" in columns else ""
        machine = ",".join("?" * len(MACHINE_PACED_SOURCES))
        row = connection.execute(
            f"""SELECT COUNT(*), SUM(u), SUM(r), SUM(w) FROM (
                    SELECT COALESCE(input_tokens, 0) u, COALESCE(cache_read_tokens, 0) r,
                           COALESCE(cache_write_tokens, 0) w
                    FROM sessions WHERE {activity} >= ? AND COALESCE(source, '') NOT IN ({machine}) {parent}
                    ORDER BY {activity} DESC LIMIT 500)""",
            (since, *sorted(MACHINE_PACED_SOURCES)),
        ).fetchone()
    finally:
        connection.close()
    count, uncached, read, write = (int(value or 0) for value in row)
    share = _share(read, uncached + read + write)
    if share is None:
        return None
    return {"window_hours": hours, "sessions": count, "read_share": share}


def _n(value: int) -> str:
    return f"{value:,}"


def _pct(share: float | None) -> str:
    return "-" if share is None else f"{share * 100:.1f}%"


def render_cache_report(report: dict[str, Any]) -> str:
    window = report["window"]
    fmt = "%Y-%m-%d %H:%M %Z"
    lines = [
        f"omh cache · last {window['days']:g}d ({time.strftime(fmt, time.localtime(window['since']))} → "
        f"{time.strftime(fmt, time.localtime(window['until']))}) · state.db read-only",
        "",
        "Read share by source (cache read / all input tokens)",
    ]
    for item in report["sources"]:
        lines.append(
            f"  {item['source']:<10} {_pct(item['read_share']):>6}  sessions {item['sessions']:>4}  "
            f"read {_n(item['cache_read_tokens'])}  write {_n(item['cache_write_tokens'])}"
        )
    gaps = report["idle_gaps"]["buckets"]
    lines += ["", "Idle gaps between user messages (human sources): " + " · ".join(f"{k} {gaps[k]}" for k in GAP_BUCKETS)]
    cron = report["cron"]
    lines += [
        "",
        f"Cron: {_n(cron['sessions'])} sessions · {cron['model_runs']} model runs · write {_n(cron['write_tokens'])}",
    ]
    for item in cron["jobs"]:
        gap = "-" if item["median_gap_minutes"] is None else f"{item['median_gap_minutes']:g}m"
        lines.append(
            f"  {item['job'][:40]:<40} runs {item['runs']:>3}  model {item['model_runs']:>3}  "
            f"write {_n(item['write_tokens']):>10}  median gap {gap:>7}  prompts {item['prompt_hashes']}"
        )
    split = cron["split"]
    lines += [
        "",
        "Write split: " + " · ".join(f"{name} {_n(split[name]['tokens'])} ({_pct(split[name]['share'])})" for name in split),
        "  cold  = prefix write of a run more than 1h after the job's previous run (cache expired; unavoidable)",
        "  churn = prefix write of a run within 1h whose system prompt hash changed (fixable)",
        "  other = growth inside runs plus warm unchanged prefixes; prefix = the job's smallest run write",
    ]
    churn = cron["top_churn"]
    if churn:
        lines += ["", f"Top churn job {churn['job']}: {churn['from_hash']} → {churn['to_hash']}"]
        if churn["line"] is None:
            lines.append("  (system prompt text not stored)")
        else:
            lines += [f"  first differing line {churn['line']}:", f"  - {churn['before'] or ''}", f"  + {churn['after'] or ''}"]
    lines += ["", "Suggestions:"] + [f"  {i}. {text}" for i, text in enumerate(report["suggestions"], 1)]
    return "\n".join(lines)

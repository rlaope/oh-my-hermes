#!/usr/bin/env python3
"""Settled-state monitor for one GitHub pull request, for a Hermes cron monitor job.

Hermes runs this as a cron job's `--monitor-script`, with no arguments, from
`<profile>/scripts/`, before the agent on every tick. Hermes hashes the exact
stdout bytes: unchanged output suppresses the agent run, changed output wakes
it with a diff. So the output names only the PR's settled state, never a time
or a running count of anything still in progress:

    pr-watch: <watch> <owner>/<repo>#<pr>
    state=open head=<sha12> conflict=no
    checks=fail passed=5 failed=2 pending=0
    reviews=1 decision=none
    fix_rounds_used=1 fix_round_cap=2
    next=fix_round round=2

`next` is one of `wait` (checks still running), `fix_round` (checks failed and
the cap has room), `hand_to_person` (cap reached, a merge conflict, changes
requested, or failed checks whose round count cannot be read), `report` (checks
passed, none exist, or an approval) and `stop_watch` (merged, closed, or the
deadline passed). While checks run, and after the deadline, only the header and
the `next` line print, so a push during a run and the passing ticks after the
deadline keep the same bytes; after the deadline nothing is read.

Fix rounds are counted from evidence, not memory: the first head whose checks
the monitor saw settle as failed is kept in its state file, and every commit
the PR's own commit list holds after that head is one round used. When that
head is no longer in the list (history rewritten), the count is unreadable and
`next=hand_to_person reason=fix_rounds_unreadable`.

Installed as `<profile>/scripts/pr_watch_<watch>.py`; the file name names the
watch, whose config is `<profile>/pr_watch/<watch>.json` and whose state is
`<profile>/pr_watch/<watch>.state.json`. `--config PATH` selects a config
directly (manual runs, tests).

Read-only toward the forge: one fixed `gh pr view <pr> --repo <owner>/<repo>
--json ...` per tick, no shell, the repository and number validated before
they reach the argv, a 30 s timeout, stdin closed, output capped. It uses the
gh CLI's own sign-in and never reads or prints a token. Stdlib only, so it runs
on Hermes' own interpreter.

Exit codes: 0 state printed, 3 config error, 4 gh missing, failed or timed
out, 5 gh output unreadable, 6 state file not writable. On a nonzero exit
Hermes reports the monitor source as failed and keeps the last output's hash.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_GH = 4
EXIT_GH_OUTPUT = 5
EXIT_STATE = 6

SCRIPT_PREFIX = "pr_watch_"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
MAX_FIX_ROUND_CAP = 2
GH_TIMEOUT_S = 30
MAX_GH_OUTPUT = 8 * 1024 * 1024

FAILED_CONCLUSIONS = frozenset({"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"})
PENDING_CONTEXT_STATES = frozenset({"PENDING", "EXPECTED"})
FAILED_CONTEXT_STATES = frozenset({"FAILURE", "ERROR"})
DECISIONS = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "REVIEW_REQUIRED": "required"}
PR_STATES = {"OPEN": "open", "CLOSED": "closed", "MERGED": "merged"}


class ConfigError(Exception):
    pass


class GhError(Exception):
    def __init__(self, code: int, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------- config


def parse_deadline(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ConfigError("deadline must be a UTC time such as 2026-11-23T14:00:00Z")
    try:
        stamp = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ConfigError("deadline must be a UTC time such as 2026-11-23T14:00:00Z") from None
    return stamp.replace(tzinfo=dt.timezone.utc)


def load_config(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise ConfigError(f"config unreadable: {path}: {exc.__class__.__name__}") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ConfigError("name must match [a-z0-9][a-z0-9_-]{0,63}")
    repo = raw.get("repo")
    if not isinstance(repo, str) or not REPO_RE.match(repo) or ".." in repo:
        raise ConfigError("repo must be owner/name")
    pr = raw.get("pr")
    if not isinstance(pr, int) or isinstance(pr, bool) or not 1 <= pr <= 10**9:
        raise ConfigError("pr must be a positive pull request number")
    cap = raw.get("fix_round_cap", MAX_FIX_ROUND_CAP)
    if not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= MAX_FIX_ROUND_CAP:
        raise ConfigError(f"fix_round_cap must be an integer from 0 to {MAX_FIX_ROUND_CAP}")
    return {"name": name, "repo": repo, "pr": pr, "fix_round_cap": cap, "deadline": parse_deadline(raw.get("deadline"))}


def resolve_config(arg: str | None) -> tuple[Path, str | None]:
    """(config path, watch name from the script file or None)."""
    if arg:
        return Path(arg), None
    script = Path(sys.argv[0])
    env_home = os.environ.get("HERMES_HOME")
    home = Path(env_home) if env_home else script.resolve().parent.parent
    stem = script.stem
    if not stem.startswith(SCRIPT_PREFIX) or len(stem) == len(SCRIPT_PREFIX):
        raise ConfigError(f"install this file as scripts/{SCRIPT_PREFIX}<watch>.py or pass --config")
    name = stem[len(SCRIPT_PREFIX):]
    return home / "pr_watch" / f"{name}.json", name


# ---------------------------------------------------------------- forge read


def read_pr(repo: str, pr: int) -> dict:
    """One read-only `gh pr view`; the argv is fixed apart from the validated repository and number."""
    try:
        done = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo, "--json",
             "state,headRefOid,mergeable,reviewDecision,latestReviews,statusCheckRollup,commits"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=GH_TIMEOUT_S, check=False,
        )
    except FileNotFoundError:
        raise GhError(EXIT_GH, "gh_not_found") from None
    except subprocess.TimeoutExpired:
        raise GhError(EXIT_GH, "gh_timeout") from None
    except OSError as exc:
        raise GhError(EXIT_GH, f"gh_not_started:{exc.__class__.__name__}") from None
    if done.returncode != 0:
        raise GhError(EXIT_GH, f"gh_exit_{done.returncode}")
    if len(done.stdout) > MAX_GH_OUTPUT:
        raise GhError(EXIT_GH_OUTPUT, "gh_output_too_large")
    try:
        data = json.loads(done.stdout)
    except ValueError:
        raise GhError(EXIT_GH_OUTPUT, "gh_output_not_json") from None
    if not isinstance(data, dict):
        raise GhError(EXIT_GH_OUTPUT, "gh_output_not_an_object")
    return data


# ---------------------------------------------------------------- settled state


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def check_counts(rollup: object) -> tuple[int, int, int]:
    """(passed, failed, pending) over the PR head's check runs and status contexts."""
    passed = failed = pending = 0
    for item in _list(rollup):
        item = _dict(item)
        if _text(item.get("__typename")) == "StatusContext" or ("state" in item and "status" not in item):
            state = _text(item.get("state")).upper()
            if not state or state in PENDING_CONTEXT_STATES:
                pending += 1
            elif state in FAILED_CONTEXT_STATES:
                failed += 1
            else:
                passed += 1
            continue
        status, conclusion = _text(item.get("status")).upper(), _text(item.get("conclusion")).upper()
        if status != "COMPLETED" or not conclusion:
            pending += 1
        elif conclusion in FAILED_CONCLUSIONS:
            failed += 1
        else:
            passed += 1
    return passed, failed, pending


def checks_verdict(passed: int, failed: int, pending: int) -> str:
    if pending:
        return "pending"
    if failed:
        return "fail"
    return "pass" if passed else "none"


def commit_oids(commits: object) -> list[str]:
    return [oid for oid in (_text(_dict(c).get("oid")).lower() for c in _list(commits)) if SHA_RE.match(oid)]


def fix_rounds_used(first_failed_head: str | None, oids: list[str]) -> int | None:
    """Commits after the first failed head, from the PR's own commit list; None when that head is gone."""
    if not first_failed_head:
        return 0
    if first_failed_head not in oids:
        return None
    return len(oids) - oids.index(first_failed_head) - 1


def decide(pr_state: str, conflict: bool, checks: str, decision: str, used: int | None, cap: int) -> tuple[str, str]:
    """(next, detail) for the settled state; order matters: an ended PR first, then what blocks a fix."""
    if pr_state in ("merged", "closed"):
        return "stop_watch", f"reason={pr_state}"
    if conflict:
        return "hand_to_person", "reason=merge_conflict"
    if checks == "pending":
        return "wait", "reason=checks_running"
    if checks == "fail":
        if used is None:
            return "hand_to_person", "reason=fix_rounds_unreadable"
        if used >= cap:
            return "hand_to_person", "reason=fix_round_cap"
        return "fix_round", f"round={used + 1}"
    if decision == "changes_requested":
        return "hand_to_person", "reason=changes_requested"
    if decision == "approved":
        return "report", "reason=approved"
    return "report", f"reason=checks_{checks}"


def summarize(cfg: dict, data: dict, state: dict) -> tuple[list[str], dict]:
    """The stable output lines and the state to keep, from one `gh pr view` reply."""
    pr_state = PR_STATES.get(_text(data.get("state")).upper(), "unknown")
    head = _text(data.get("headRefOid")).lower()
    head = head if SHA_RE.match(head) else ""
    conflict = _text(data.get("mergeable")).upper() == "CONFLICTING"
    passed, failed, pending = check_counts(data.get("statusCheckRollup"))
    checks = checks_verdict(passed, failed, pending)
    decision = DECISIONS.get(_text(data.get("reviewDecision")).upper(), "none")
    reviews = len(_list(data.get("latestReviews")))
    kept = dict(state)
    first_failed = _text(kept.get("first_failed_head")).lower()
    first_failed = first_failed if SHA_RE.match(first_failed) else None
    if checks == "fail" and first_failed is None and head:
        first_failed = head
        kept["first_failed_head"] = head
    used = fix_rounds_used(first_failed, commit_oids(data.get("commits")))
    nxt, detail = decide(pr_state, conflict, checks, decision, used, cfg["fix_round_cap"])
    header = f"pr-watch: {cfg['name']} {cfg['repo']}#{cfg['pr']}"
    if nxt == "wait":
        # A push while checks run changes the head but settles nothing: keep the bytes the same.
        return [header, f"next={nxt} {detail}"], kept
    lines = [
        header,
        f"state={pr_state} head={head[:12] or 'unknown'} conflict={'yes' if conflict else 'no'}",
        f"checks={checks} passed={passed} failed={failed} pending={pending}",
        f"reviews={reviews} decision={decision}",
        f"fix_rounds_used={'unreadable' if used is None else used} fix_round_cap={cfg['fix_round_cap']}"
        + (f" first_failed_head={first_failed[:12]}" if first_failed else ""),
        f"next={nxt} {detail}",
    ]
    return lines, kept


# ---------------------------------------------------------------- main


def _read_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run(argv: list[str], now: dt.datetime | None = None, reader=read_pr) -> int:
    parser = argparse.ArgumentParser(description="Settled-state monitor for one GitHub pull request.")
    parser.add_argument("--config", help="watch config JSON (default: from this file's name)")
    args = parser.parse_args(argv)
    try:
        config_path, expected = resolve_config(args.config)
        cfg = load_config(config_path)
        if expected is not None and cfg["name"] != expected:
            raise ConfigError(f"config name {cfg['name']!r} does not match the script's watch {expected!r}")
    except ConfigError as exc:
        print(f"pr-watch: error reason=config detail={exc}", file=sys.stderr)
        return EXIT_CONFIG
    header = f"pr-watch: {cfg['name']} {cfg['repo']}#{cfg['pr']}"
    if (now or dt.datetime.now(dt.timezone.utc)) >= cfg["deadline"]:
        print(header)
        print("next=stop_watch reason=deadline")
        return EXIT_OK
    try:
        data = reader(cfg["repo"], cfg["pr"])
    except GhError as exc:
        print(f"pr-watch: error reason={exc.detail} watch={cfg['name']}", file=sys.stderr)
        return exc.code
    state_path = config_path.with_name(config_path.stem + ".state.json")
    state = _read_state(state_path)
    lines, kept = summarize(cfg, data, state)
    if kept != state:
        try:
            _write_state(state_path, kept)
        except OSError as exc:
            print(f"pr-watch: error reason=state detail={exc.__class__.__name__}", file=sys.stderr)
            return EXIT_STATE
    print("\n".join(lines))
    return EXIT_OK


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())

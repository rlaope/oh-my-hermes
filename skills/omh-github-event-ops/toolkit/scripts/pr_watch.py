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
    fix_rounds_used=1 fix_round_cap=2 first_failed_head=<sha12>
    next=fix_round round=2

`next` is one of `fix_round` (checks failed and the cap has room),
`hand_to_person` (cap reached, a merge conflict, changes requested, or failed
checks whose round count cannot be read), `report` (checks passed, none exist,
or an approval), `stop_watch` (merged, closed, or the deadline passed) and
`wait` (nothing has settled yet in this watch).

Unsettled is not a change. While a check is queued or running, while GitHub
reports mergeability as UNKNOWN (it recomputes after every push), while the PR
or its head cannot be read, and on the first tick a new head shows no checks at
all, the script prints this watch's last settled block again, byte for byte,
or `next=wait reason=unsettled` before anything settled. So a push, a CI run
starting, or a mergeability recompute wakes nobody; only a new settled state
does.

Fix rounds are counted from evidence, never memory, and the count only grows.
The PR's state file keeps the first head the monitor saw with checks settled as
failed, every distinct head it observed after that head, and the highest count
it ever printed. Rounds used is the largest of that stored count, the number of
heads observed after the first failed head (an amend and force-push is a new
head), and the number of commits the PR's commit list holds after that head.
The commit list is read only when it ends at the current head and holds the
first failed head; otherwise (history rewritten, a list cut at GitHub's first
100 commits, a stale list) it is unreadable, and failed checks hand the fix to
a person.

The state is per pull request, not per watch: `<profile>/pr_watch/state/
<owner>/<name>/pr-<n>.json`, kept when a watch is removed, so a new watch on
the same PR keeps the count. Every watch on that PR shares it under one lock
file beside it: a tick reads, changes and writes it only while holding the lock
(through a temporary file of its own and one atomic replace). A tick that
cannot get the lock within 20 seconds repeats its watch's last block, reads
nothing and writes nothing: no change and no alert. A state file that exists
but cannot be read is never overwritten: the watch stops with
`next=stop_watch reason=state_unreadable path=<file>`, the same bytes every
tick, and reads nothing from GitHub, so a person checks it. A tick that holds
the lock and still cannot open the file (permission denied, a folder in its
place) exits 6, which Hermes delivers as an alert.

Each watch ends at most 24 hours after its first tick, whatever its `deadline`
says. The first tick is kept per watch name, so a later watch on the same PR
takes a new name.

Installed as `<profile>/scripts/pr_watch_<watch>.py`; the file name names the
watch, whose config is `<profile>/pr_watch/<watch>.json`. `--config PATH`
selects a config directly (manual runs, tests).

Read-only toward the forge: one fixed `gh pr view <pr> --repo <owner>/<repo>
--json ...` per tick, no shell, the repository and number validated before
they reach the argv, a 30 s timeout, stdin closed, output capped. It uses the
gh CLI's own sign-in and never reads or prints a token. Stdlib only, so it runs
on Hermes' own interpreter.

Exit codes: 0 state printed, 3 config error, 4 gh missing, failed or timed
out, 5 gh output unreadable, 6 state file not writable. On a nonzero exit
Hermes reports the monitor source as failed (and delivers that as an alert) and
keeps the last output's hash.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
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
MAX_WATCH_SECONDS = 24 * 3600
MAX_HEADS_KEPT = 8
MAX_WATCHES_KEPT = 10
GH_TIMEOUT_S = 30
MAX_GH_OUTPUT = 8 * 1024 * 1024
WAIT_LINE = "next=wait reason=unsettled"
LOCK_WAIT_S = 20.0
LOCK_STALE_S = 120.0
# Names Windows refuses as a file or folder, whatever the extension.
RESERVED_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                            *(f"lpt{i}" for i in range(1, 10))})

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
    if not isinstance(repo, str) or not REPO_RE.match(repo) or ".." in repo or repo.endswith("/."):
        raise ConfigError("repo must be owner/name")
    pr = raw.get("pr")
    if not isinstance(pr, int) or isinstance(pr, bool) or not 1 <= pr <= 10**9:
        raise ConfigError("pr must be a positive pull request number")
    cap = raw.get("fix_round_cap", MAX_FIX_ROUND_CAP)
    if not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= MAX_FIX_ROUND_CAP:
        raise ConfigError(f"fix_round_cap must be an integer from 0 to {MAX_FIX_ROUND_CAP}")
    deadline = raw.get("deadline")
    return {"name": name, "repo": repo, "pr": pr, "fix_round_cap": cap, "deadline": parse_deadline(deadline),
            "watch_key": name}


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


def _safe_part(part: str) -> str:
    """A path component every platform accepts: a trailing dot or a Windows device name is hex-encoded.

    The `~` prefix is a character `REPO_RE` refuses in an owner or a name, so an encoded part can never
    be some other repository's real name.
    """
    if part.endswith(".") or part.split(".", 1)[0] in RESERVED_NAMES:
        return "~" + part.encode("utf-8").hex()
    return part


def state_path(config_path: Path, cfg: dict) -> Path:
    """The PR's own state file, shared by every watch on that PR."""
    owner, name = cfg["repo"].lower().split("/", 1)
    return config_path.parent / "state" / _safe_part(owner) / _safe_part(name) / f"pr-{cfg['pr']}.json"


# ---------------------------------------------------------------- forge read


def read_pr(repo: str, pr: int) -> dict:
    """One read-only `gh pr view`; the argv is fixed apart from the validated repository and number."""
    try:
        done = subprocess.run(
            ["gh", "pr", "view", str(pr), "--repo", repo, "--json",
             "state,headRefOid,mergeable,reviewDecision,reviews,statusCheckRollup,commits"],
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
    except (ValueError, RecursionError):
        raise GhError(EXIT_GH_OUTPUT, "gh_output_not_json") from None
    if not isinstance(data, dict):
        raise GhError(EXIT_GH_OUTPUT, "gh_output_not_an_object")
    return data


# ---------------------------------------------------------------- state


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_watch(entry: object) -> bool:
    entry = _dict(entry)
    settled = entry.get("settled", [])
    return (_is_count(entry.get("started")) and isinstance(settled, list)
            and all(isinstance(line, str) and "\n" not in line for line in settled))


def read_state(path: Path) -> tuple[dict, str]:
    """(state, status): `ok` (a missing file is an empty state), `unreadable`, or `io_error` (try again)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, "ok"
    except OSError:
        return {}, "io_error"
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return {}, "unreadable"
    if not isinstance(data, dict):
        return {}, "unreadable"
    first = data.get("first_failed_head")
    heads = data.get("heads_after", [])
    watches = data.get("watches", {})
    valid = (
        (first is None or (isinstance(first, str) and SHA_RE.match(first)))
        and isinstance(heads, list) and all(isinstance(h, str) and SHA_RE.match(h) for h in heads)
        and _is_count(data.get("rounds_floor", 0))
        and (data.get("empty_head") is None or (isinstance(data["empty_head"], str) and SHA_RE.match(data["empty_head"])))
        and isinstance(watches, dict) and all(_valid_watch(v) for v in watches.values())
    )
    return (data, "ok") if valid else ({}, "unreadable")


def write_state(path: Path, data: dict) -> None:
    """Write through a temporary file of this tick's own (mode 600), then one atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, sort_keys=True) + "\n")
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: a reader still has the file open
                if attempt == 2:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def take_lock(lock: Path) -> bool:
    """The PR's lock, so two watches on one PR never interleave read, modify and write."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
            continue
        os.close(fd)
        return True


def watch_entry(state: dict, key: str, now: dt.datetime) -> dict:
    """This watch's entry, started at its first tick; only the newest few watches are kept."""
    watches = dict(_dict(state.get("watches")))
    entry = dict(_dict(watches.get(key))) or {"started": int(now.timestamp()), "settled": []}
    watches[key] = entry
    if len(watches) > MAX_WATCHES_KEPT:
        newest = sorted(watches, key=lambda k: watches[k]["started"], reverse=True)[:MAX_WATCHES_KEPT]
        watches = {k: watches[k] for k in newest}
    state["watches"] = watches
    return entry


# ---------------------------------------------------------------- settled state


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


def submitted_reviews(reviews: object) -> int:
    """Every submitted review, so a second review by the same person is a change too."""
    return sum(1 for r in _list(reviews) if _text(_dict(r).get("state")).upper() not in ("", "PENDING"))


def count_rounds(state: dict, head: str, oids: list[str]) -> int | None:
    """Rounds used, never lower than before; None when the commit list cannot be read for it."""
    first = state.get("first_failed_head")
    if not first:
        return 0
    if head and head != first and head not in state["heads_after"]:
        state["heads_after"] = (state["heads_after"] + [head])[-MAX_HEADS_KEPT:]
    listed = bool(oids) and oids[-1] == head and first in oids
    committed = len(oids) - oids.index(first) - 1 if listed else 0
    used = max(state.get("rounds_floor", 0), len(state["heads_after"]), committed)
    state["rounds_floor"] = used
    return used if listed else None


def decide(pr_state: str, conflict: bool, checks: str, decision: str, used: int | None, cap: int,
           readable: bool) -> tuple[str, str]:
    """(next, detail) for a settled state: an ended PR first, then what makes the fix a person's."""
    if pr_state in ("merged", "closed"):
        return "stop_watch", f"reason={pr_state}"
    if conflict:
        return "hand_to_person", "reason=merge_conflict"
    if decision == "changes_requested":
        return "hand_to_person", "reason=changes_requested"
    if checks == "fail":
        if used is not None and used >= cap:
            return "hand_to_person", "reason=fix_round_cap"
        if used is None or not readable:
            return "hand_to_person", "reason=fix_rounds_unreadable"
        return "fix_round", f"round={used + 1}"
    if decision == "approved":
        return "report", "reason=approved"
    return "report", f"reason=checks_{checks}"


def observe(cfg: dict, data: dict, state: dict, readable: bool) -> list[str] | None:
    """The settled block for one `gh pr view` reply, or None when nothing has settled."""
    pr_state = PR_STATES.get(_text(data.get("state")).upper(), "unknown")
    head = _text(data.get("headRefOid")).lower()
    head = head if SHA_RE.match(head) else ""
    mergeable = _text(data.get("mergeable")).upper()
    conflict = mergeable == "CONFLICTING"
    passed, failed, pending = check_counts(data.get("statusCheckRollup"))
    checks = checks_verdict(passed, failed, pending)
    decision = DECISIONS.get(_text(data.get("reviewDecision")).upper(), "none")
    reviews = submitted_reviews(data.get("reviews"))
    oids = commit_oids(data.get("commits"))
    state.setdefault("heads_after", [])

    ended = pr_state in ("merged", "closed")
    settled = ended or (pr_state == "open" and bool(head) and (conflict or (
        mergeable != "UNKNOWN" and checks != "pending" and (checks != "none" or state.get("empty_head") == head))))
    if not ended and checks == "none" and head and state.get("empty_head") != head:
        state["empty_head"] = head  # no checks yet on a new head: CI may not have registered them
    if readable and checks == "fail" and settled and not state.get("first_failed_head") and head:
        state["first_failed_head"] = head
    used = count_rounds(state, head, oids) if readable and head else None
    if not readable or (state.get("first_failed_head") and used is None):
        used_text, used_value = "unreadable", (state.get("rounds_floor") if readable else None)
    else:
        used_text, used_value = str(used), used
    if not settled:
        return None
    nxt, detail = decide(pr_state, conflict, checks, decision, used_value, cfg["fix_round_cap"],
                         readable and used is not None)
    first = state.get("first_failed_head")
    return [
        f"state={pr_state} head={head[:12] or 'unknown'} conflict={'yes' if conflict else 'no'}",
        f"checks={checks} passed={passed} failed={failed} pending={pending}",
        f"reviews={reviews} decision={decision}",
        f"fix_rounds_used={used_text} fix_round_cap={cfg['fix_round_cap']}"
        + (f" first_failed_head={first[:12]}" if first else ""),
        f"next={nxt} {detail}",
    ]


# ---------------------------------------------------------------- main


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
    now = now or dt.datetime.now(dt.timezone.utc)
    header = f"pr-watch: {cfg['name']} {cfg['repo']}#{cfg['pr']}"
    path = state_path(config_path, cfg)
    lock = path.with_name(path.name + ".lock")
    try:
        locked = take_lock(lock)
    except OSError as exc:
        print(f"pr-watch: error reason=state detail={exc.__class__.__name__} path={path}", file=sys.stderr)
        return EXIT_STATE
    try:
        code, lines = tick(cfg, path, now, reader, locked)
    finally:
        if locked:
            try:
                lock.unlink()
            except OSError:
                pass
    if lines:
        print("\n".join([header, *lines]))
    return code


def tick(cfg: dict, path: Path, now: dt.datetime, reader, locked: bool) -> tuple[int, list[str]]:
    """(exit code, lines after the header) for one tick. Only a tick holding the PR's lock reads gh or writes."""
    loaded, status = read_state(path)  # a lockless read is whole: every write is one atomic replace
    if status == "unreadable":
        # Fails loudly and stops: the count cannot be trusted, so nothing is read and nothing is overwritten.
        # The path is on stdout, the same bytes every tick: Hermes shows a monitor's stdout, not its stderr.
        print(f"pr-watch: error reason=state_unreadable path={path}", file=sys.stderr)
        return EXIT_OK, [f"next=stop_watch reason=state_unreadable path={path}"]
    state = json.loads(json.dumps(loaded))
    entry = watch_entry(state, cfg["watch_key"], now)
    deadline = min(cfg["deadline"], dt.datetime.fromtimestamp(entry["started"] + MAX_WATCH_SECONDS, dt.timezone.utc))
    if now >= deadline:
        lines = ["next=stop_watch reason=deadline"]
    elif locked and status == "io_error":
        # Holding the lock and still unable to read (permission denied, a folder at the path) is not
        # contention: fail the tick, so Hermes delivers the error instead of a wait that never ends.
        print(f"pr-watch: error reason=state_io_error path={path}", file=sys.stderr)
        return EXIT_STATE, []
    elif not locked or status == "io_error":
        # Another watch on this PR holds the lock: this tick repeats this watch's last block, which is no
        # change and no alert, and the next tick reads the PR.
        print(f"pr-watch: note reason=state_busy path={path}", file=sys.stderr)
        return EXIT_OK, entry["settled"] or [WAIT_LINE]
    else:
        try:
            data = reader(cfg["repo"], cfg["pr"])
        except GhError as exc:
            print(f"pr-watch: error reason={exc.detail} watch={cfg['name']}", file=sys.stderr)
            return exc.code, []
        block = observe(cfg, data, state, True)
        if block is not None:
            entry["settled"] = block
        lines = entry["settled"] or [WAIT_LINE]
    if locked and status == "ok" and state != loaded:
        try:
            write_state(path, state)
        except OSError as exc:
            print(f"pr-watch: error reason=state detail={exc.__class__.__name__} path={path}", file=sys.stderr)
            return EXIT_STATE, []
    return EXIT_OK, lines


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())

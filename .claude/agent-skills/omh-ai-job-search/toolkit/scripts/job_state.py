#!/usr/bin/env python3
"""Offline vacancy identity and evidence-bound state. Explicit invocation only."""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import unicodedata
from urllib.parse import unquote, urlsplit, urlunsplit


INPUT_LIMIT = 2 * 1024 * 1024
STATE_LIMIT = 16 * 1024 * 1024
AVAILABILITY = ("unknown", "open", "closed")
STATES = ("none", "draft", "submitted", "interviewing", "offered", "accepted", "rejected", "withdrawn")
JOB_FIELDS = {"source_namespace", "posting_id", "original_url", "canonical_url", "title", "company",
              "location", "remote_scope", "posted_at", "deadline", "application_url", "availability", "receipt_ids"}
SOURCE_FIELDS = {"receipt_id", "kind", "source_url", "retrieved_at", "status", "freshness", "evidence_ref", "error"}
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
TOKEN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
JOB_ID = r"job-[0-9a-f]{64}"
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class Refusal(Exception):
    def __init__(self, code, message, exit_code=2):
        self.code, self.message, self.exit_code = code, message, exit_code
        super().__init__(message)


def require(condition, code="invalid_schema", message="Invalid document structure"):
    if not condition:
        raise Refusal(code, message)


def limit(condition):
    require(condition, "limit_exceeded", "Document exceeds a declared finite limit")


def fields(value, expected):
    require(type(value) is dict and set(value) == set(expected))


def text(value, maximum=4096, nullable=False, multiline=False):
    if value is None and nullable:
        return
    require(type(value) is str, "invalid_type", "Expected a string or explicitly permitted null")
    limit(len(value) <= maximum)
    require(bool(value.strip()), "invalid_value", "Expected nonempty text")
    require(not any((ord(c) < 32 and not (multiline and c in "\t\n")) or ord(c) == 127 for c in value),
            "invalid_value", "Control characters are not permitted")
    require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), "invalid_value", "Invalid Unicode text")


def token(value, pattern=TOKEN):
    text(value)
    require(re.fullmatch(pattern, value) is not None, "invalid_value", "Invalid identifier syntax")


def choice(value, options):
    require(type(value) is str and value in options, "invalid_value", "Unsupported enumerated value")


def timestamp(value):
    text(value)
    match = re.fullmatch(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
                         r"(?:\.([0-9]+))?(Z|([+-])([0-9]{2}):([0-9]{2}))", value)
    if match is None:
        raise Refusal("invalid_timestamp", "Timestamp must be an aware ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(match[1])
    except ValueError:
        raise Refusal("invalid_timestamp", "Invalid calendar timestamp") from None
    # Python 3.14 reads T24:00:00 as the next midnight; 3.11-3.13 refuse it.
    # Requiring an exact round trip refuses it on every supported interpreter.
    require(parsed.isoformat() == match[1], "invalid_timestamp", "Invalid calendar timestamp")
    offset_hour, offset_minute = int(match[5] or 0), int(match[6] or 0)
    require(offset_hour < 24 and offset_minute < 60,
            "invalid_timestamp", "Invalid timezone offset")
    offset = (offset_hour * 60 + offset_minute) * 60
    if match[4] == "-":
        offset = -offset
    # Integer UTC seconds avoid datetime rollover at year bounds. Canonical
    # decimal digits compare exactly, including beyond microseconds or Decimal
    # context precision; stripping only trailing zeros preserves equality.
    seconds = parsed.toordinal() * 86400 + parsed.hour * 3600 + parsed.minute * 60 + parsed.second - offset
    return seconds, (match[2] or "").rstrip("0")


def calendar(value):
    if value is None:
        return
    text(value)
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None, "invalid_date", "Date must be YYYY-MM-DD or null")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise Refusal("invalid_date", "Invalid calendar date") from None


def component(value):
    require(bool(value) and value not in {".", ".."} and not value.endswith((".", " "))
            and not any(c in value for c in '\\:<>"|?*')
            and not any(ord(c) < 32 or ord(c) == 127 for c in value)
            and value.split(".")[0].upper() not in RESERVED,
            "unsafe_path", "Unsafe portable path component")


def reference(value):
    text(value, 240)
    require(not value.startswith("/"), "unsafe_path", "Evidence reference must be relative")
    for part in value.split("/"):
        component(part)
        require(re.fullmatch(r"[A-Za-z0-9._-]+", part) is not None,
                "unsafe_path", "Invalid evidence reference component")


def normal_url(value):
    text(value)
    require(not any(c.isspace() for c in value) and not re.search(r"%(?![0-9a-fA-F]{2})", value)
            and "\\" not in value, "invalid_url", "Invalid URL syntax")
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
        require(parts.scheme.lower() in {"http", "https"} and bool(host) and parts.username is None
                and parts.password is None and not parts.netloc.endswith(":"), "invalid_url", "Invalid HTTP(S) URL authority")
        if ":" in host:
            ipaddress.IPv6Address(host)
            authority = "[" + host.lower() + "]"
        else:
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", host):
                ipaddress.IPv4Address(host)
            ascii_host = host.encode("idna").decode("ascii")
            require(len(ascii_host) <= 253 and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in ascii_host.rstrip(".").split(".")), "invalid_url", "Invalid hostname")
            authority = host.lower()
        require(port is None or 1 <= port <= 65535, "invalid_url", "Invalid URL port")
        scheme = parts.scheme.lower()
        if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
            authority += ":" + parts.netloc.rsplit(":", 1)[1]
        query = "&".join(pair for pair in parts.query.split("&")
                         if unquote(pair.split("=", 1)[0]).lower() not in TRACKING)
        # urlunsplit discards empty delimiters; preserve explicit identity fragments.
        result = urlunsplit((scheme, authority, parts.path, query, parts.fragment))
        if "?" in value.split("#", 1)[0] and not parts.query:
            result = result.split("#", 1)[0] + "?" + ("#" + parts.fragment if "#" in value else "")
        if "#" in value and "#" not in result:
            result += "#"
        return result
    except (ValueError, UnicodeError):
        raise Refusal("invalid_url", "Invalid HTTP(S) URL") from None


def job_key(job):
    if job["posting_id"] is not None:
        key = "id:" + job["source_namespace"] + ":" + job["posting_id"]
    else:
        key = "url:" + normal_url(job["canonical_url"] or job["original_url"])
    return "job-" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def unique_strings(value, maximum, nonempty=False):
    require(type(value) is list, "invalid_type", "Expected an array")
    limit(len(value) <= maximum)
    require(not nonempty or bool(value))
    for item in value:
        text(item)
    require(len(set(value)) == len(value), "invalid_value", "Duplicate array item")


def source_check(source):
    fields(source, SOURCE_FIELDS)
    token(source["receipt_id"])
    choice(source["kind"], ("search", "snippet", "employer", "original", "user_provided"))
    if source["source_url"] is None:
        require(source["kind"] == "user_provided", "invalid_url", "Only user_provided may have null source URL")
    else:
        normal_url(source["source_url"])
    timestamp(source["retrieved_at"])
    choice(source["status"], ("ok", "empty", "blocked", "error"))
    choice(source["freshness"], ("verified", "unverified"))
    reference(source["evidence_ref"])
    if source["status"] in {"blocked", "error"}:
        text(source["error"], 2048, multiline=True)
    else:
        require(source["error"] is None)
    if source["freshness"] == "verified":
        require(source["kind"] in {"employer", "original"} and source["status"] == "ok")
    if source["status"] == "empty":
        require(source["kind"] == "search")


def job_check(job, sources):
    fields(job, JOB_FIELDS)
    token(job["source_namespace"], r"[a-z0-9][a-z0-9.-]{0,127}")
    text(job["posting_id"], 256, nullable=True)
    normalized = normal_url(job["original_url"])
    if job["canonical_url"] is not None:
        normal_url(job["canonical_url"])
        require(job["canonical_url"] == normalized, "identity_conflict", "Canonical URL must equal normalized original URL")
    for name in ("title", "company", "location", "remote_scope"):
        text(job[name], 512, nullable=name in {"location", "remote_scope"})
    for name in ("posted_at", "deadline"):
        calendar(job[name])
    if job["application_url"] is not None:
        normal_url(job["application_url"])
    choice(job["availability"], AVAILABILITY)
    unique_strings(job["receipt_ids"], 20, True)
    for receipt_id in job["receipt_ids"]:
        token(receipt_id)
        require(receipt_id in sources, "invalid_reference", "Job receipt is missing from this capture set")
        require(sources[receipt_id]["status"] == "ok", "invalid_reference", "Unsuccessful source cannot support a job")
    if job["availability"] != "unknown":
        require(any(sources[r]["freshness"] == "verified" for r in job["receipt_ids"]),
                "invalid_evidence_type", "Availability requires verified employer/original evidence")


def batch_check(value):
    fields(value, {"schema", "jobs", "sources"})
    require(value["schema"] == "ai_job_search_captures/v1")
    require(type(value["jobs"]) is list and type(value["sources"]) is list, "invalid_type", "Expected capture arrays")
    limit(len(value["jobs"]) <= 100 and len(value["sources"]) <= 200)
    sources = {}
    for source in value["sources"]:
        source_check(source)
        require(source["receipt_id"] not in sources, "invalid_value", "Duplicate receipt ID in batch")
        sources[source["receipt_id"]] = source
    for job in value["jobs"]:
        job_check(job, sources)
    return value


def duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "invalid_json", "Duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    try:
        # Bound depth before the decoder can recurse; quoted brackets are data.
        depth, quoted, escaped = 0, False, False
        for char in raw.decode("utf-8"):
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                limit(depth <= 12)
            elif char in "]}":
                depth -= 1
        value = json.loads(raw, object_pairs_hook=duplicate_keys,
                           parse_constant=lambda _: require(False, "invalid_json", "Nonfinite JSON number"))
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal("invalid_json", "Invalid UTF-8 JSON document") from None
    stack = [(value, ())]
    while stack:
        item, path = stack.pop()
        if type(item) is str:
            limit(len(item) <= 4096)
            require("\x00" not in item and not any(0xD800 <= ord(c) <= 0xDFFF for c in item),
                    "invalid_value", "Invalid Unicode text")
        elif type(item) is dict:
            if path not in {("jobs",), ("sources",)}:
                limit(len(item) <= 32)
            for key, child in item.items():
                limit(len(key) <= 4096)
                stack.append((child, path + (key,)))
        elif type(item) is list:
            stack.extend((child, path + (i,)) for i, child in enumerate(item))
    require(type(value) is dict)
    return value


def require_supported_platform():
    require(bool(getattr(os, "O_NOFOLLOW", 0)) and bool(getattr(os, "O_DIRECTORY", 0))
            and all(fn in os.supports_dir_fd for fn in (os.open, os.stat, os.unlink, os.rename))
            and os.stat in os.supports_follow_symlinks,
            "unsupported_platform", "Required POSIX no-follow/dir-fd primitives unavailable; Windows is unsupported")


def safe_path(value):
    require(type(value) is str and bool(value), "unsafe_path", "An explicit path is required")
    require("\\" not in value, "unsafe_path", "Backslash paths are unsupported")
    for part in value.split("/"):
        if part not in {"", "."}:
            component(part)
    path = Path(os.path.abspath(value))
    for ancestor in (*reversed(path.parents), path):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), "unsafe_path", "Symlink paths are forbidden")
        if ancestor != path:
            require(stat.S_ISDIR(info.st_mode), "unsafe_path", "Path ancestor must be a directory")
    return path


def read_bytes(path, maximum, missing=False):
    safe_path(str(path))
    require(hasattr(os, "O_NOFOLLOW"), "unsafe_path", "Required no-follow primitive unavailable")
    try:
        if path.exists():
            require(stat.S_ISREG(path.lstat().st_mode), "unsafe_path", "Expected a regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if missing:
            return None
        raise Refusal("io_error", "Input file is unavailable", 4) from None
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), "unsafe_path", "Expected a regular file")
        limit(os.fstat(fd).st_size <= maximum)
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(maximum + 1)
        limit(len(raw) <= maximum)
        return raw
    finally:
        if fd is not None:
            os.close(fd)


def outcome(jobs, sources):
    receipts = list(sources)
    if not receipts:
        return "not_observed"
    failures = sum(s["status"] in {"blocked", "error"} for s in receipts)
    if failures == len(receipts):
        return "blocked"
    if failures:
        return "partial"
    searches = [s for s in receipts if s["kind"] == "search"]
    if not jobs and searches and all(s["status"] == "empty" for s in searches):
        return "empty"
    return "results" if jobs else "not_observed"


def verified(jobs):
    return sum(j["availability"] in {"open", "closed"} for j in jobs)


def empty_state():
    return {"schema": "ai_job_search_state/v1", "revision": 0, "jobs": {}, "sources": {}}


def observation_time(job, sources):
    return max(timestamp(sources[r]["retrieved_at"]) for r in job["receipt_ids"])


def comparable(job):
    result = {k: v for k, v in job.items() if k not in {"original_url", "canonical_url", "receipt_ids"}}
    result["url"] = normal_url(job["original_url"])
    return result


def observe(entry, job, sources):
    if job not in entry["observations"]:
        if entry["observations"]:
            old_time = observation_time(entry["job"], sources)
            new_time = observation_time(job, sources)
            require(new_time != old_time or comparable(job) == comparable(entry["job"]),
                    "identity_conflict", "Equal-time job observations disagree")
            # Equal-time contradictions with older observations must also refuse.
            for previous in entry["observations"]:
                require(observation_time(previous, sources) != new_time or comparable(previous) == comparable(job),
                        "identity_conflict", "Equal-time job observations disagree")
            if new_time > old_time:
                entry["job"] = copy.deepcopy(job)
        else:
            entry["job"] = copy.deepcopy(job)
        entry["observations"].append(copy.deepcopy(job))
    if job["original_url"] not in entry["original_urls"]:
        entry["original_urls"].append(job["original_url"])
    for receipt in job["receipt_ids"]:
        if receipt not in entry["receipt_ids"]:
            entry["receipt_ids"].append(receipt)


def new_entry():
    return {"job": None, "original_urls": [], "receipt_ids": [], "observations": [],
            "application_state": "none", "history": []}


EDGES = {
    ("none", "draft"): {"draft_artifact"},
    **{(s, "submitted"): {"user_report", "submission_receipt"} for s in ("none", "draft")},
    ("submitted", "interviewing"): {"user_report", "employer_notice"},
    **{(s, "offered"): {"user_report", "employer_notice"} for s in ("submitted", "interviewing")},
    **{(s, "rejected"): {"user_report", "employer_notice"} for s in ("submitted", "interviewing", "offered")},
    ("offered", "accepted"): {"user_decision"},
    **{(s, "withdrawn"): {"user_decision"} for s in ("draft", "submitted", "interviewing", "offered")},
}
EVENT_FIELDS = {"event_id", "from_state", "to_state", "evidence_type", "evidence_ref", "occurred_at", "corrects_event"}


def event_check(event, current, prior):
    fields(event, EVENT_FIELDS)
    require(event["event_id"] == f"event-{len(prior) + 1:06d}", "invalid_history", "Invalid event sequence")
    choice(event["from_state"], STATES)
    choice(event["to_state"], STATES)
    require(event["from_state"] == current, "invalid_history", "Broken transition chain")
    text(event["evidence_type"])
    reference(event["evidence_ref"])
    timestamp(event["occurred_at"])
    if event["evidence_type"] == "user_correction":
        token(event["corrects_event"], r"event-[0-9]{6}")
        corrected = next((e for e in prior if e["event_id"] == event["corrects_event"]), None)
        require(corrected is not None, "invalid_history", "Correction must identify a prior event of this job")
        require(event["evidence_ref"] != corrected["evidence_ref"], "invalid_evidence_type", "Correction requires its own evidence reference")
    else:
        require(event["corrects_event"] is None, "invalid_history", "Only user_correction may correct an event")
        allowed = EDGES.get((current, event["to_state"]), set())
        require(bool(allowed), "invalid_transition", "Unsupported application transition")
        require(event["evidence_type"] in allowed, "invalid_evidence_type", "Evidence type does not support this transition")


def event_payload(event):
    return {k: event[k] for k in ("to_state", "evidence_type", "evidence_ref", "occurred_at", "corrects_event")}


def history_check(entry):
    choice(entry["application_state"], STATES)
    require(type(entry["history"]) is list, "invalid_type", "Expected history array")
    limit(len(entry["history"]) <= 100)
    current, prior = "none", []
    for event in entry["history"]:
        event_check(event, current, prior)
        require(not prior or event_payload(event) != event_payload(prior[-1]), "invalid_history", "Duplicate final transition in history")
        current = event["to_state"]
        prior.append(event)
    require(entry["application_state"] == current, "invalid_history", "Current progress disagrees with history")


def transition_state(state, args):
    require(args.job_id in state["jobs"], "invalid_reference", "Job does not exist in this workspace")
    proposed = copy.deepcopy(state)
    entry = proposed["jobs"][args.job_id]
    event = {"event_id": f"event-{len(entry['history']) + 1:06d}",
             "from_state": entry["application_state"], "to_state": args.state,
             "evidence_type": args.evidence_type, "evidence_ref": args.evidence_ref,
             "occurred_at": args.occurred_at, "corrects_event": args.corrects_event}
    if entry["history"] and event_payload(event) == event_payload(entry["history"][-1]):
        return proposed, entry["history"][-1]["event_id"], False
    event_check(event, entry["application_state"], entry["history"])
    entry["history"].append(event)
    entry["application_state"] = args.state
    return proposed, event["event_id"], True


def state_check(value):
    fields(value, {"schema", "revision", "jobs", "sources"})
    require(value["schema"] == "ai_job_search_state/v1")
    require(type(value["revision"]) is int and value["revision"] >= 0, "invalid_type", "Invalid state revision")
    limit(value["revision"] <= 2147483647)
    require(type(value["jobs"]) is dict and type(value["sources"]) is dict)
    limit(len(value["jobs"]) <= 2000 and len(value["sources"]) <= 4000)
    for receipt_id, source in value["sources"].items():
        source_check(source)
        require(receipt_id == source["receipt_id"], "invalid_reference", "Stored receipt key mismatch")
    observations = 0
    for job_id, entry in value["jobs"].items():
        token(job_id, JOB_ID)
        fields(entry, {"job", "original_urls", "receipt_ids", "observations", "application_state", "history"})
        job_check(entry["job"], value["sources"])
        require(job_key(entry["job"]) == job_id, "identity_conflict", "Stored job key mismatch")
        unique_strings(entry["original_urls"], 100, True)
        unique_strings(entry["receipt_ids"], 200, True)
        for url in entry["original_urls"]:
            normal_url(url)
        require(type(entry["observations"]) is list and bool(entry["observations"]))
        observations += len(entry["observations"])
        limit(observations <= 10000)
        rebuilt = new_entry()
        for observation in entry["observations"]:
            job_check(observation, value["sources"])
            require(job_key(observation) == job_id, "identity_conflict", "Observation identity mismatch")
            require(observation not in rebuilt["observations"], "invalid_value", "Duplicate stored observation")
            observe(rebuilt, observation, value["sources"])
        for key in ("job", "original_urls", "receipt_ids"):
            require(entry[key] == rebuilt[key], "invalid_schema", "Stored observation projection mismatch")
        history_check(entry)
    return value


def read_state(workspace):
    raw = read_bytes(workspace / "state.json", STATE_LIMIT, missing=True)
    return (empty_state() if raw is None else state_check(decode(raw))), raw


def reconcile(state, batch):
    proposed = copy.deepcopy(state)
    for source in batch["sources"]:
        old = proposed["sources"].get(source["receipt_id"])
        require(old is None or old == source, "identity_conflict", "Existing receipt ID has different content")
        proposed["sources"][source["receipt_id"]] = copy.deepcopy(source)
    inserted, updated = set(), set()
    for job in batch["jobs"]:
        job_id = job_key(job)
        if job_id not in proposed["jobs"]:
            proposed["jobs"][job_id] = new_entry()
            inserted.add(job_id)
        previous = copy.deepcopy(proposed["jobs"][job_id])
        observe(proposed["jobs"][job_id], job, proposed["sources"])
        if previous != proposed["jobs"][job_id] and job_id not in inserted:
            updated.add(job_id)
    return proposed, sorted(inserted), sorted(updated)


def duplicates(state):
    groups = {}
    for job_id, entry in state["jobs"].items():
        job = entry["job"]
        key = tuple(unicodedata.normalize("NFC", job[k]).casefold().strip() for k in ("company", "title"))
        groups.setdefault(key, []).append(job_id)
    pairs = []
    for ids in groups.values():
        ids.sort()
        pairs.extend([a, b] for i, a in enumerate(ids) for b in ids[i + 1:])
    return sorted(pairs)


def counts(state):
    jobs = [entry["job"] for entry in state["jobs"].values()]
    return {"revision": state["revision"], "job_count": len(jobs), "source_count": len(state["sources"]),
            "verified_job_count": verified(jobs)}


def make_workspace(workspace):
    for part in (*reversed(workspace.parents), workspace):
        if not part.exists():
            part.mkdir(mode=0o700)
    safe_path(str(workspace))
    require(workspace.is_dir(), "unsafe_path", "Workspace must be a directory")


@contextmanager
def writer(workspace):
    require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
            and all(fn in os.supports_dir_fd for fn in (os.open, os.stat, os.unlink, os.rename))
            and os.stat in os.supports_follow_symlinks,
            "unsafe_path", "Required safe-write primitives unavailable")
    make_workspace(workspace)
    directory = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    lock_stat = None
    lease = {"directory": directory, "lock_stat": None, "committed": False}
    try:
        lock_path = workspace / ".job-state.lock"
        safe_path(str(lock_path))
        if lock_path.exists():
            existing_lock = lock_path.lstat()
            require(stat.S_ISREG(existing_lock.st_mode) and existing_lock.st_nlink == 1,
                    "unsafe_path", "Existing lock must be a regular unlinked file")
        try:
            lock_fd = os.open(".job-state.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=directory)
        except FileExistsError:
            raise Refusal("writer_conflict", "Workspace writer lock already exists", 3) from None
        lock_stat = os.fstat(lock_fd)
        lease["lock_stat"] = lock_stat
        yield lease
    finally:
        try:
            if lock_fd is not None:
                os.close(lock_fd)
            if lock_stat is not None:
                try:
                    current = os.stat(".job-state.lock", dir_fd=directory, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (lock_stat.st_dev, lock_stat.st_ino):
                        os.unlink(".job-state.lock", dir_fd=directory)
                except FileNotFoundError:
                    pass
        except OSError:
            # Atomic replacement is the commit point. A cleanup failure cannot
            # honestly turn a completed mutation into a claimed rollback/exit 4.
            # Leave an owned stale lock rather than breaking another writer's lock.
            if not lease["committed"]:
                raise
        finally:
            try:
                os.close(directory)
            except OSError:
                if not lease["committed"]:
                    raise


def commit(workspace, state, previous, lease):
    directory, lock_stat = lease["directory"], lease["lock_stat"]
    state_check(state)
    raw = (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    limit(len(raw) <= STATE_LIMIT)
    state_check(decode(raw))
    name = ".job-state-" + secrets.token_hex(16) + ".tmp"
    fd = None
    temporary_stat = None
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        temporary_stat = os.fstat(fd)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        safe_path(str(workspace / "state.json"))
        safe_path(str(workspace / name))
        current = os.stat(".job-state.lock", dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
            raise Refusal("writer_conflict", "Writer lock ownership changed", 3)
        actual = read_bytes(workspace / "state.json", STATE_LIMIT, missing=True)
        if (actual is None) != (previous is None) or (actual is not None and hashlib.sha256(actual).digest() != hashlib.sha256(previous).digest()):
            raise Refusal("writer_conflict", "State changed during this operation", 3)
        current_temp = os.stat(name, dir_fd=directory, follow_symlinks=False)
        require(stat.S_ISREG(current_temp.st_mode) and current_temp.st_nlink == 1
                and (current_temp.st_dev, current_temp.st_ino) == (temporary_stat.st_dev, temporary_stat.st_ino),
                "unsafe_path", "Temporary file ownership changed")
        os.replace(name, "state.json", src_dir_fd=directory, dst_dir_fd=directory)
        lease["committed"] = True
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_stat is not None:
            try:
                current_temp = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (current_temp.st_dev, current_temp.st_ino) == (temporary_stat.st_dev, temporary_stat.st_ino):
                    os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass
            except OSError:
                if not lease["committed"]:
                    raise


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refusal("invalid_arguments", "Invalid command arguments; use --help")


def main(argv=None):
    try:
        parser = Parser(description=__doc__, allow_abbrev=False)
        sub = parser.add_subparsers(dest="command", required=True)
        validate = sub.add_parser("validate", allow_abbrev=False)
        validate.add_argument("--input", required=True)
        merge = sub.add_parser("merge", allow_abbrev=False)
        merge.add_argument("--input", required=True)
        merge.add_argument("--workspace", required=True)
        summary = sub.add_parser("summary", allow_abbrev=False)
        summary.add_argument("--workspace", required=True)
        transition = sub.add_parser("transition", allow_abbrev=False)
        for flag in ("workspace", "job-id", "state", "evidence-type", "evidence-ref", "occurred-at"):
            transition.add_argument("--" + flag, required=True)
        transition.add_argument("--corrects-event", default=None)
        args = parser.parse_args(argv)
        require_supported_platform()
        value = None
        if args.command in {"validate", "merge"}:
            value = batch_check(decode(read_bytes(safe_path(args.input), INPUT_LIMIT)))
        if args.command == "transition":
            token(args.job_id, JOB_ID)
            choice(args.state, STATES)
            text(args.evidence_type)
            reference(args.evidence_ref)
            timestamp(args.occurred_at)
            if args.corrects_event is not None:
                token(args.corrects_event, r"event-[0-9]{6}")
        if args.command in {"validate", "merge"}:
            # Validate reconciliation as well as every record, before workspace writes.
            proposed_batch, _, _ = reconcile(empty_state(), value)
            state_check(proposed_batch)
        if args.command == "validate":
            result = {"job_count": len(value["jobs"]), "source_count": len(value["sources"]),
                      "verified_job_count": verified(value["jobs"]),
                      "source_outcome": outcome(value["jobs"], value["sources"])}
        elif args.command == "summary":
            workspace = safe_path(args.workspace)
            state, _ = read_state(workspace)
            entries = state["jobs"]
            result = {**counts(state),
                      "availability_counts": {s: sum(e["job"]["availability"] == s for e in entries.values()) for s in AVAILABILITY},
                      "application_counts": {s: sum(e["application_state"] == s for e in entries.values()) for s in STATES},
                      "source_outcome": outcome(entries, state["sources"].values()),
                      "possible_duplicates": duplicates(state),
                      "next_action_job_ids": sorted(k for k, e in entries.items() if e["application_state"] in
                                                    {"none", "draft", "submitted", "interviewing", "offered"})}
        else:
            workspace = safe_path(args.workspace)
            if args.command == "transition":
                require(workspace.exists(), "invalid_reference", "Job does not exist in this workspace")
            with writer(workspace) as lease:
                state, old = read_state(workspace)
                if args.command == "merge":
                    proposed, inserted, updated = reconcile(state, value)
                    changed = proposed != state
                else:
                    proposed, event_id, changed = transition_state(state, args)
                if changed:
                    proposed["revision"] += 1
                    commit(workspace, proposed, old, lease)
                if args.command == "merge":
                    result = {**counts(proposed), "inserted_job_ids": inserted, "updated_job_ids": updated,
                              "possible_duplicates": duplicates(proposed),
                              "source_outcome": outcome(value["jobs"], value["sources"])}
                else:
                    result = {"revision": proposed["revision"], "job_id": args.job_id,
                              "application_state": proposed["jobs"][args.job_id]["application_state"],
                              "event_id": event_id, "changed": changed}
        print(json.dumps({"schema": "ai_job_search_result/v1", "command": args.command, "ok": True, **result}, sort_keys=True))
        return 0
    except Refusal as error:
        print(json.dumps({"schema": "ai_job_search_error/v1", "ok": False,
                          "error": {"code": error.code, "message": error.message}}, sort_keys=True), file=sys.stderr)
        return error.exit_code
    except OSError:
        print(json.dumps({"schema": "ai_job_search_error/v1", "ok": False,
                          "error": {"code": "io_error", "message": "Local I/O operation failed"}}, sort_keys=True), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())

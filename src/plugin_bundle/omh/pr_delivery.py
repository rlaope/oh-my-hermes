"""The PR delivery grant: whether this profile's bot may publish its own work unattended.

Owner-approved, 2026-11-23 (`docs/IMPLEMENTATION-BOUNDARIES.md`). A bot that
works with nobody to answer a confirmation (a webhook run, a one-shot run, a
scheduled run) may, once the person turns this grant on for its profile, do
exactly four externally visible things: push a new branch under the grant's
branch prefix, open a pull request from it, push fix commits to a pull
request it opened, and comment on a pull request it opened. Merging,
force-pushing, pushing to the default branch, and anything on a pull request
the bot did not open stay a person's, grant or no grant.

What this module owns, and nothing else:

* where the grant lives and how it is read. One file per Hermes profile under
  ``<omh_home>/runtime/pr_delivery/``, named by a digest of the profile's
  Hermes home and naming that home inside, so two profiles that share one OMH
  home never share a grant. A missing, unreadable, malformed or foreign file,
  a wrong schema version, a scope other than the fixed one, or an invalid
  branch prefix all read as OFF. There is no other default.
* the record of which pull requests this bot opened. The gate's
  ``post_tool_call`` half writes one line per ``gh pr create`` that the grant
  allowed and whose own output named the new pull request's URL; the model
  never writes it (`evidence_store_guard` refuses a file-tool write into the
  store, and the gate refuses a shell command that names it).

Nothing here turns the grant on. The one writer is the person's
``omh capability-policy pr-delivery on`` (`src/commands/pr_delivery.py`), and
`tests/test_pr_delivery_grant.py` holds that no other module in `src/` calls
it. Stdlib only, and no module-level ``omh.*`` import: this file ships in the
plugin bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

GRANT_SCHEMA_VERSION: Final = "omh_pr_delivery_grant/v1"
OPENED_PR_SCHEMA_VERSION: Final = "omh_pr_delivery_opened_pr/v1"
GRANT_STATUS_SCHEMA_VERSION: Final = "omh_pr_delivery_grant_status/v1"
# Under `<omh_home>/runtime/`, beside the other stores only OMH's own code
# writes; `evidence_store_guard.EVIDENCE_STORES` names it.
STORE_DIRNAME: Final = "pr_delivery"
GRANT_FILE_PREFIX: Final = "grant-"
OPENED_FILE_PREFIX: Final = "opened-"

TURN_ON_COMMAND: Final = "omh capability-policy pr-delivery on"
TURN_OFF_COMMAND: Final = "omh capability-policy pr-delivery off"
SHOW_COMMAND: Final = "omh capability-policy pr-delivery show"

# The fixed scope, recorded in every grant and compared on every read: a file
# whose scope says anything else is not this grant and reads as off.
ALLOWED_ACTIONS: Final[tuple[str, ...]] = (
    "push a new branch under the grant's branch prefix, never the default branch",
    "open a pull request from that branch",
    "push fix commits to a pull request this bot opened",
    "comment on a pull request this bot opened",
)
NEVER_ALLOWED_ACTIONS: Final[tuple[str, ...]] = (
    "merge a pull request, on the forge or by pushing a merge to the default branch",
    "force-push, or delete a remote branch",
    "push to the default branch",
    "act on a pull request this bot did not open, or change repository settings",
)

DEFAULT_BRANCH_PREFIX: Final = "bot/"
# One path segment and a slash: `bot/`, `omh-bot/`. A prefix is the bot's
# branch namespace, so it must never be able to name a whole branch.
_BRANCH_PREFIX: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}/$")
_RESERVED_PREFIXES: Final = frozenset({"refs/", "heads/", "tags/", "remotes/", "head/"})

# A PR URL exactly as `gh pr create` prints it on success.
PR_URL: Final = re.compile(r"^https://([A-Za-z0-9.-]+)/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]{0,9})$")
MAX_GRANT_BYTES: Final = 16_384
# POSIX owner and mode bits. On Windows they say nothing, so the file is read
# as recorded there (`docs/PR-DELIVERY-GRANT.md`, Windows).
MODE_BITS_MEAN_SOMETHING: Final = os.name == "posix"
MAX_OPENED_RECORDS: Final = 500
MAX_OPENED_BYTES: Final = 1_048_576


def valid_branch_prefix(value: object) -> bool:
    text = str(value or "")
    return bool(_BRANCH_PREFIX.match(text)) and text.lower() not in _RESERVED_PREFIXES


def profile_key(hermes_home: str | Path) -> str:
    """The profile's identity as stored: its Hermes home, made absolute and real."""
    return os.path.realpath(os.path.expanduser(str(hermes_home)))


def _digest(hermes_home: str | Path) -> str:
    return hashlib.sha256(profile_key(hermes_home).encode("utf-8")).hexdigest()[:16]


def store_dir(omh_home: str | Path) -> Path:
    return Path(omh_home).expanduser() / "runtime" / STORE_DIRNAME


def grant_path(omh_home: str | Path, hermes_home: str | Path) -> Path:
    return store_dir(omh_home) / f"{GRANT_FILE_PREFIX}{_digest(hermes_home)}.json"


def opened_prs_path(omh_home: str | Path, hermes_home: str | Path) -> Path:
    return store_dir(omh_home) / f"{OPENED_FILE_PREFIX}{_digest(hermes_home)}.jsonl"


def _load_object(path: Path) -> tuple[dict | None, str]:
    """(document, reason): a document only when the file is a readable JSON object.

    On POSIX the file must also belong to the user running OMH and be
    writable by nobody else; on Windows the mode bits say nothing, so this
    check does not apply there.
    """
    try:
        info = path.stat()
        if info.st_size > MAX_GRANT_BYTES:
            return None, "grant_file_too_large"
        if MODE_BITS_MEAN_SOMETHING and (info.st_uid != os.getuid() or info.st_mode & 0o022):
            return None, "grant_file_not_private"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "no_grant_recorded"
    except (OSError, ValueError, UnicodeDecodeError):
        return None, "grant_file_unreadable"
    if not isinstance(raw, dict):
        return None, "grant_file_malformed"
    return raw, ""


def evaluate_grant(document: Mapping[str, object] | None, hermes_home: str | Path) -> tuple[bool, str]:
    """(on, reason) for one loaded grant document. Every doubt answers off."""
    if document is None:
        return False, "no_grant_recorded"
    if document.get("schema_version") != GRANT_SCHEMA_VERSION:
        return False, "grant_schema_unknown"
    if document.get("hermes_home") != profile_key(hermes_home):
        return False, "grant_names_another_profile"
    if list(document.get("allowed_actions") or ()) != list(ALLOWED_ACTIONS):
        return False, "grant_scope_changed"
    if list(document.get("never_allowed_actions") or ()) != list(NEVER_ALLOWED_ACTIONS):
        return False, "grant_scope_changed"
    if not valid_branch_prefix(document.get("branch_prefix")):
        return False, "grant_branch_prefix_invalid"
    if document.get("state") != "on":
        return False, "grant_turned_off"
    return True, "granted"


def read_grant(omh_home: str | Path, hermes_home: str | Path) -> dict[str, object]:
    """This profile's grant as the gate and the read-only surfaces see it.

    Never raises: a path that cannot be built is a grant that cannot be read,
    and that is off.
    """
    try:
        path = grant_path(omh_home, hermes_home)
    except (OSError, RuntimeError, ValueError):
        return _status(False, "grant_path_unresolvable", None, "")
    document, reason = _load_object(path)
    on, verdict = evaluate_grant(document, hermes_home) if document is not None else (False, reason)
    return _status(on, verdict, document, str(path))


def _status(on: bool, reason: str, document: Mapping[str, object] | None, path: str) -> dict[str, object]:
    recorded = document or {}
    return {
        "schema_version": GRANT_STATUS_SCHEMA_VERSION,
        "state": "on" if on else "off",
        "reason": reason,
        "branch_prefix": str(recorded.get("branch_prefix") or "") if on else "",
        "granted_at": str(recorded.get("granted_at") or "") if on else "",
        "allowed_actions": list(ALLOWED_ACTIONS) if on else [],
        "never_allowed_actions": list(NEVER_ALLOWED_ACTIONS),
        "turn_on_command": TURN_ON_COMMAND,
        "turn_off_command": TURN_OFF_COMMAND,
        "who_may_change_it": "only the person, at their own terminal; never the bot",
        "path": path,
    }


def branch_prefix(grant: Mapping[str, object]) -> str:
    """The grant's prefix when on; the default otherwise, for messages only."""
    value = str(grant.get("branch_prefix") or "")
    return value if grant.get("state") == "on" and valid_branch_prefix(value) else DEFAULT_BRANCH_PREFIX


def recorded_grants(omh_home: str | Path) -> list[dict[str, object]]:
    """Every profile's grant recorded in this OMH home, for `omh doctor`.

    Each row is judged against the profile its file names, the same way that
    profile's own gate would judge it; an unreadable file is listed as off.
    """
    rows: list[dict[str, object]] = []
    try:
        paths = sorted(store_dir(omh_home).glob(f"{GRANT_FILE_PREFIX}*.json"))
    except OSError:
        return rows
    for path in paths:
        document, reason = _load_object(path)
        home = str((document or {}).get("hermes_home") or "")
        if document is None or not home:
            rows.append({"hermes_home": home, "state": "off", "reason": reason or "grant_file_malformed",
                         "branch_prefix": "", "granted_at": "", "path": str(path)})
            continue
        on, verdict = evaluate_grant(document, home)
        if on and path.name != grant_path(omh_home, home).name:
            on, verdict = False, "grant_file_misnamed"
        rows.append({
            "hermes_home": home,
            "state": "on" if on else "off",
            "reason": verdict,
            "branch_prefix": str(document.get("branch_prefix") or "") if on else "",
            "granted_at": str(document.get("granted_at") or "") if on else "",
            "path": str(path),
        })
    return rows


def parse_pr_url(text: str) -> tuple[str, int] | None:
    """(`host/owner/name` lowercased, number) for a PR URL, else None."""
    match = PR_URL.match(text.strip())
    if match is None:
        return None
    host, owner, name, number = match.groups()
    return f"{host}/{owner}/{name}".lower(), int(number)


def _opened_rows(omh_home: str | Path, hermes_home: str | Path) -> list[dict]:
    try:
        path = opened_prs_path(omh_home, hermes_home)
        if path.stat().st_size > MAX_OPENED_BYTES:
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-MAX_OPENED_RECORDS:]
    except (OSError, RuntimeError, ValueError, UnicodeDecodeError):
        return []
    rows: list[dict] = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("schema_version") == OPENED_PR_SCHEMA_VERSION:
            rows.append(row)
    return rows


def opened_prs(omh_home: str | Path, hermes_home: str | Path) -> frozenset[tuple[str, int]]:
    """(`host/owner/name`, number) of every PR this profile's gate recorded as opened."""
    found = (parse_pr_url(str(row.get("url") or "")) for row in _opened_rows(omh_home, hermes_home))
    return frozenset(parsed for parsed in found if parsed is not None)


def opened_count(omh_home: str | Path, hermes_home: str | Path, session_id: str) -> int:
    """How many PRs the gate recorded as opened by this session: the per-run cap reads it."""
    return sum(1 for row in _opened_rows(omh_home, hermes_home) if row.get("session_id") == session_id)


def append_opened_pr(
    omh_home: str | Path, hermes_home: str | Path, *, url: str, head_branch: str, session_id: str
) -> bool:
    """Record one PR the gate saw `gh pr create` open under the grant. Never raises."""
    parsed = parse_pr_url(url)
    if parsed is None:
        return False
    row = {
        "schema_version": OPENED_PR_SCHEMA_VERSION,
        "url": url.strip(),
        "repository": parsed[0],
        "number": parsed[1],
        "head_branch": head_branch,
        "session_id": session_id,
        "observed_from": "the output of the gh pr create call the grant allowed",
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    line = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    try:
        path = opened_prs_path(omh_home, hermes_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)
    except (OSError, RuntimeError, ValueError):
        return False
    return True

#!/usr/bin/env python3
"""Change monitor for Notion, Linear, Jira and Sentry, for a Hermes cron monitor job.

Hermes runs this as a cron job's `--monitor-script`, with no arguments, from
`<profile>/scripts/`, before the agent on every tick. Hermes hashes the exact
stdout bytes: unchanged output suppresses the agent run (no model call),
changed output wakes the agent with a diff. So the output holds only ids and
the platform's own timestamps, sorted, never a fetch time or a body:

    monitor: notion watch=<name>
    database <db-id> row <row-id> edited=<last_edited_time>
    page <page-id> edited=<last_edited_time>

    monitor: linear watch=<name>      (open issues assigned to the key's user)
    issue ENG-12

    monitor: jira watch=<name>        (issues the JQL selects, by key)
    issue OPS-7

    monitor: sentry watch=<name>      (newest issues the query selects)
    issue 4501 short=WEB-3F first_seen=2026-11-24T08:00:00Z

Installed as `<profile>/scripts/api_watch_<watch>.py`; the file name names the
watch, whose config is `<profile>/monitors/<watch>.json`. `--config PATH`
selects a config directly (manual runs, tests).

The credential comes only from the environment, by one fixed name per
platform (NOTION_API_KEY, LINEAR_API_KEY, JIRA_EMAIL with JIRA_API_TOKEN,
SENTRY_AUTH_TOKEN). It is sent only to that platform's own API host, fixed
here (api.notion.com, api.linear.app, <site>.atlassian.net, sentry.io or
de.sentry.io), over HTTPS, with redirects refused, a 15 s socket timeout, 30 s
at most for a whole reply, and a capped reply. It is never printed, logged or written. Every request is a read: GETs,
plus Notion's database query and Linear's GraphQL query, which are reads sent
as POST. Nothing is written anywhere; the only output is stdout and stderr.

Failure is never a change, and never silent:
- A missing, malformed or rejected credential, a page or project that is not
  found or not shared, a refused request, or a config error prints one fixed
  line, `error reason=<reason>`, and exits 0. Hermes sees that line change
  once, wakes the agent once to report it, and stays quiet while it holds.
- A network error or timeout (`network`), HTTP 429 or a Linear rate limit
  (`platform_busy`), 5xx (`server_error`), a redirect, or a reply it cannot
  read prints nothing on stdout and one `unreachable reason=<reason>` line on
  stderr, and exits 1. Hermes treats that as a failed monitor source: no
  change, no agent run, the stored hash kept. It alerts the job's failure
  target on the first failed tick and holds back repeats of the same failure
  for `cron.failure_repeat_alert_hours` (6 by default); a tick that succeeds
  closes the incident. The reason words avoid the ones Hermes reads as a model
  provider's failure (rate limit, timed out, quota), so the alert does not
  blame the model.

`api_base` in the config (tests only) replaces the host and is refused unless
it is plain HTTP on a loopback address; requests to it skip any proxy.
Stdlib only, so it runs on Hermes' own interpreter.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

EXIT_OK = 0
EXIT_UNREACHABLE = 1

SCRIPT_PREFIX = "api_watch_"
CONFIG_DIR = "monitors"
KINDS = ("notion", "linear", "jira", "sentry")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TOKEN_RE = re.compile(r"^[\x21-\x7e]{1,4096}$")
EMAIL_RE = re.compile(r"^[^\s@:]{1,128}@[^\s@:]{1,253}$")
NOTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
NOTION_OUT_ID_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$")
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$")
LINEAR_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,16}-\d{1,9}$")
JIRA_SITE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}-\d{1,9}$")
SENTRY_ORG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")
SENTRY_ID_RE = re.compile(r"^\d{1,20}$")
SENTRY_SHORT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

TIMEOUT_S = 15
DEADLINE_S = 30
MAX_BODY = 1024 * 1024
NOTION_VERSION = "2022-06-28"
DEFAULT_JQL = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
DEFAULT_SENTRY_QUERY = "is:unresolved"
HOSTS = {
    "notion": "https://api.notion.com",
    "linear": "https://api.linear.app",
    "sentry:us": "https://sentry.io",
    "sentry:de": "https://de.sentry.io",
}
TOKEN_KEYS = {
    "notion": ("NOTION_API_KEY",),
    "linear": ("LINEAR_API_KEY",),
    "jira": ("JIRA_EMAIL", "JIRA_API_TOKEN"),
    "sentry": ("SENTRY_AUTH_TOKEN",),
}
LINEAR_QUERY = (
    "query($first: Int!) { viewer { assignedIssues(first: $first, orderBy: updatedAt, "
    "filter: { state: { type: { nin: [\"completed\", \"canceled\"] } } }) { nodes { identifier } } } }"
)


class ConfigError(Exception):
    pass


class Persistent(Exception):
    """A failure that holds until a person fixes it: one fixed line, exit 0."""

    def __init__(self, reason: str, key: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.key = key


class Transient(Exception):
    """A failure that may pass on its own: nothing on stdout, exit 1."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - refuse every redirect
        return None


# ---------------------------------------------------------------- config


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _int(raw: dict, key: str, default: int, low: int, high: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"{key} must be a whole number from {low} to {high}")
    return value


def _text(raw: dict, key: str, default: str, limit: int) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or CONTROL_RE.search(value):
        raise ConfigError(f"{key} must be one line of at most {limit} characters")
    return value.strip()


def _notion_ids(raw: dict, key: str, limit: int) -> list[str]:
    values = raw.get(key, [])
    if not isinstance(values, list) or len(values) > limit:
        raise ConfigError(f"{key} must be a list of at most {limit} Notion ids")
    ids = []
    for value in values:
        compact = value.replace("-", "").lower() if isinstance(value, str) else ""
        if not NOTION_ID_RE.fullmatch(compact):
            raise ConfigError(f"{key} holds a value that is not a 32-character Notion id")
        ids.append(compact)
    return sorted(set(ids))


def load_config(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ConfigError("config file not readable") from None
    except ValueError:
        raise ConfigError("config file is not JSON") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ConfigError("name must match [a-z0-9][a-z0-9_-]{0,63}")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ConfigError("kind must be one of " + ", ".join(KINDS))
    cfg: dict = {"name": name, "kind": kind}
    if kind == "notion":
        cfg["pages"] = _notion_ids(raw, "pages", 10)
        cfg["databases"] = _notion_ids(raw, "databases", 5)
        if not cfg["pages"] and not cfg["databases"]:
            raise ConfigError("name at least one Notion page or database")
        cfg["rows"] = _int(raw, "rows", 20, 1, 100)
        base = HOSTS["notion"]
    elif kind == "linear":
        cfg["limit"] = _int(raw, "limit", 50, 1, 100)
        base = HOSTS["linear"]
    elif kind == "jira":
        site = raw.get("site")
        if not isinstance(site, str) or not JIRA_SITE_RE.fullmatch(site):
            raise ConfigError("site must be the <site> of <site>.atlassian.net")
        cfg["jql"] = _text(raw, "jql", DEFAULT_JQL, 500)
        cfg["limit"] = _int(raw, "limit", 50, 1, 100)
        base = f"https://{site}.atlassian.net"
    else:
        org = raw.get("org")
        if not isinstance(org, str) or not SENTRY_ORG_RE.fullmatch(org):
            raise ConfigError("org must be the organization slug")
        region = raw.get("region", "us")
        if region not in ("us", "de"):
            raise ConfigError("region must be us or de")
        projects = raw.get("project_ids", [])
        if (not isinstance(projects, list) or len(projects) > 10
                or any(isinstance(p, bool) or not isinstance(p, int) or not 0 < p < 10**15 for p in projects)):
            raise ConfigError("project_ids must be a list of at most 10 numeric project ids")
        cfg.update(org=org, project_ids=sorted(set(projects)), query=_text(raw, "query", DEFAULT_SENTRY_QUERY, 200),
                   limit=_int(raw, "limit", 10, 1, 100))
        base = HOSTS[f"sentry:{region}"]
    override = raw.get("api_base")
    cfg["loopback"] = False
    if override is not None:
        parts = urlsplit(override) if isinstance(override, str) else None
        if parts is None or parts.scheme != "http" or not _is_loopback_host(parts.hostname or ""):
            raise ConfigError("api_base is for tests and must be http:// on a loopback host")
        base, cfg["loopback"] = override.rstrip("/"), True
    cfg["base"] = base
    return cfg


def resolve_config(arg: str | None) -> tuple[Path, str | None]:
    """(config path, watch name from the script's file name or None)."""
    if arg:
        return Path(arg), None
    script = Path(sys.argv[0])
    env_home = os.environ.get("HERMES_HOME", "").strip()
    home = Path(env_home) if env_home else script.resolve().parent.parent
    stem = script.stem
    if not stem.startswith(SCRIPT_PREFIX) or len(stem) == len(SCRIPT_PREFIX):
        raise ConfigError(f"install this file as scripts/{SCRIPT_PREFIX}<watch>.py or pass --config")
    name = stem[len(SCRIPT_PREFIX):]
    return home / CONFIG_DIR / f"{name}.json", name


def read_credentials(kind: str) -> list[str]:
    values = []
    for key in TOKEN_KEYS[kind]:
        value = os.environ.get(key, "").strip()
        if not value:
            raise Persistent("no_token", key)
        if not (EMAIL_RE if key == "JIRA_EMAIL" else TOKEN_RE).fullmatch(value):
            raise Persistent("bad_token", key)
        values.append(value)
    return values


# ---------------------------------------------------------------- HTTP


class Client:
    def __init__(self, cfg: dict, authorization: str):
        handlers: list = [_NoRedirect()]
        if cfg["loopback"]:
            handlers.append(ProxyHandler({}))
        self._opener = build_opener(*handlers)
        self._base = cfg["base"]
        self._authorization = authorization
        self.requests = 0

    def call(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None,
             headers: dict | None = None) -> object:
        url = self._base + path + ("?" + urlencode(params, doseq=True) if params else "")
        sent = {"Authorization": self._authorization, "Accept": "application/json",
                "User-Agent": "omh-monitor-watch/1", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body, sort_keys=True).encode("utf-8")
            sent["Content-Type"] = "application/json"
        req = Request(url, data=data, method=method, headers=sent)
        self.requests += 1
        deadline = time.monotonic() + DEADLINE_S
        try:
            try:
                resp = self._opener.open(req, timeout=TIMEOUT_S)
            except HTTPError as exc:
                resp = exc  # a 4xx or 5xx: its status and body are read like any reply
            with resp:
                status, raw = resp.status, _read_bounded(resp, deadline)
        except (URLError, OSError):
            # A timeout and a refused or dropped connection are one outage: one reason, so Hermes
            # opens one incident for it, not one per symptom.
            raise Transient("network") from None
        except Exception:  # noqa: BLE001 - http.client's malformed-reply errors (BadStatusLine, ...)
            # urllib re-raises http.client.HTTPException subclasses as they are, and importing
            # http.client here to name them would widen this client's surface; the class is not
            # printed, so the reply reads as unreadable and nothing from it reaches stderr.
            raise Transient("bad_response") from None
        if status == 429:
            raise Transient("platform_busy")
        if status >= 500:
            raise Transient("server_error")
        if 300 <= status < 400:
            raise Transient("redirect_refused")
        if len(raw) > MAX_BODY:
            raise Transient("reply_too_large")
        try:
            parsed = json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, ValueError):
            parsed = None
        if status == 401:
            raise Persistent("token_rejected")
        if status == 403:
            raise Persistent("forbidden")
        if status == 404:
            raise Persistent("not_found")
        if status >= 400:
            if _linear_error_code(parsed, "RATELIMITED"):
                raise Transient("platform_busy")
            if _linear_error_code(parsed, "AUTHENTICATION_ERROR"):
                raise Persistent("token_rejected")
            raise Persistent("request_rejected")
        if parsed is None:
            raise Transient("bad_response")
        return parsed


def _linear_error_code(parsed: object, code: str) -> bool:
    """Whether a GraphQL error in the reply carries `extensions.code == code` (Linear's error shape)."""
    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    if not isinstance(errors, list):
        return False
    for error in errors:
        extensions = error.get("extensions") if isinstance(error, dict) else None
        if isinstance(extensions, dict) and extensions.get("code") == code:
            return True
    return False


def _read_bounded(stream, deadline: float) -> bytes:
    """At most MAX_BODY + 1 bytes, read in pieces until DEADLINE_S has passed since the request."""
    chunks, size = [], 0
    while size <= MAX_BODY:
        if time.monotonic() > deadline:
            raise TimeoutError("reply took too long")
        piece = stream.read1(65_536) if hasattr(stream, "read1") else stream.read(65_536)
        if not piece:
            break
        chunks.append(piece)
        size += len(piece)
    return b"".join(chunks)


def _authorization(kind: str, credentials: list[str]) -> str:
    if kind == "jira":
        pair = f"{credentials[0]}:{credentials[1]}".encode("utf-8")
        return "Basic " + base64.b64encode(pair).decode("ascii")
    if kind == "linear":
        return credentials[0]  # a Linear personal API key is sent as is, without a scheme
    return "Bearer " + credentials[0]


# ---------------------------------------------------------------- platforms


def _stamp(value: object) -> str | None:
    return value if isinstance(value, str) and STAMP_RE.fullmatch(value) else None


def read_notion(client: Client, cfg: dict) -> list[str]:
    lines = []
    headers = {"Notion-Version": NOTION_VERSION}
    for page in cfg["pages"]:
        data = client.call("GET", f"/v1/pages/{page}", headers=headers)
        page_id, edited = (data.get("id"), _stamp(data.get("last_edited_time"))) if isinstance(data, dict) else ("", None)
        if not isinstance(page_id, str) or not NOTION_OUT_ID_RE.fullmatch(page_id) or edited is None:
            raise Transient("bad_response")
        gone = data.get("archived") is True or data.get("in_trash") is True
        lines.append(f"page {page_id} " + ("archived" if gone else f"edited={edited}"))
    for database in cfg["databases"]:
        data = client.call("POST", f"/v1/databases/{database}/query", headers=headers, body={
            "page_size": cfg["rows"], "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        })
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise Transient("bad_response")
        rows = []
        for row in results:
            row_id = row.get("id") if isinstance(row, dict) else None
            edited = _stamp(row.get("last_edited_time")) if isinstance(row, dict) else None
            if isinstance(row_id, str) and NOTION_OUT_ID_RE.fullmatch(row_id) and edited:
                rows.append(f"database {database} row {row_id} edited={edited}")
        if results and not rows:
            raise Transient("bad_response")
        lines.extend(rows or [f"database {database} rows=0"])
    return sorted(lines)


def read_linear(client: Client, cfg: dict) -> list[str]:
    data = client.call("POST", "/graphql", body={"query": LINEAR_QUERY, "variables": {"first": cfg["limit"]}})
    if _linear_error_code(data, "RATELIMITED"):
        raise Transient("platform_busy")
    if _linear_error_code(data, "AUTHENTICATION_ERROR"):
        raise Persistent("token_rejected")
    if isinstance(data, dict) and data.get("errors"):
        raise Persistent("request_rejected")
    try:
        nodes = data["data"]["viewer"]["assignedIssues"]["nodes"]
    except (KeyError, TypeError):
        raise Transient("bad_response") from None
    if not isinstance(nodes, list):
        raise Transient("bad_response")
    keys = sorted({n["identifier"] for n in nodes
                   if isinstance(n, dict) and isinstance(n.get("identifier"), str)
                   and LINEAR_KEY_RE.fullmatch(n["identifier"])})
    if nodes and not keys:
        raise Transient("bad_response")
    lines = [f"issue {key}" for key in keys] or ["issues=0"]
    if len(nodes) >= cfg["limit"]:
        lines.append("limit_reached=yes")
    return lines


def read_jira(client: Client, cfg: dict) -> list[str]:
    data = client.call("GET", "/rest/api/3/search/jql", params={
        "jql": cfg["jql"], "fields": "id", "maxResults": cfg["limit"],
    })
    issues = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(issues, list):
        raise Transient("bad_response")
    keys = sorted({i["key"] for i in issues
                   if isinstance(i, dict) and isinstance(i.get("key"), str) and JIRA_KEY_RE.fullmatch(i["key"])})
    if issues and not keys:
        raise Transient("bad_response")
    lines = [f"issue {key}" for key in keys] or ["issues=0"]
    if len(issues) >= cfg["limit"] or data.get("isLast") is False:
        lines.append("limit_reached=yes")
    return lines


def read_sentry(client: Client, cfg: dict) -> list[str]:
    params = {"query": cfg["query"], "sort": "new", "limit": cfg["limit"], "statsPeriod": "14d"}
    if cfg["project_ids"]:
        params["project"] = [str(p) for p in cfg["project_ids"]]
    data = client.call("GET", f"/api/0/organizations/{quote(cfg['org'])}/issues/", params=params)
    if not isinstance(data, list):
        raise Transient("bad_response")
    rows = []
    for issue in data:
        if not isinstance(issue, dict):
            continue
        issue_id, short, first = issue.get("id"), issue.get("shortId"), _stamp(issue.get("firstSeen"))
        if (isinstance(issue_id, str) and SENTRY_ID_RE.fullmatch(issue_id) and isinstance(short, str)
                and SENTRY_SHORT_RE.fullmatch(short) and first):
            rows.append((int(issue_id), f"issue {issue_id} short={short} first_seen={first}"))
    if data and not rows:
        raise Transient("bad_response")
    return [line for _key, line in sorted(set(rows))] or ["issues=0"]


READERS = {"notion": read_notion, "linear": read_linear, "jira": read_jira, "sentry": read_sentry}


# ---------------------------------------------------------------- main


def _emit(lines: list[str]) -> None:
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Change monitor for a Hermes cron monitor job.")
    parser.add_argument("--config", help="watch config JSON (default: from this file's name)")
    args = parser.parse_args(argv)
    kind, name = "api", "?"
    try:
        config_path, expected = resolve_config(args.config)
        if expected is not None:
            name = expected
        cfg = load_config(config_path)
        kind = cfg["kind"]
        if expected is not None and cfg["name"] != expected:
            raise ConfigError("config name does not match the script's watch name")
        name = cfg["name"]
    except ConfigError as exc:
        _emit([f"monitor: {kind} watch={name}", "error reason=config"])
        print(f"monitor: config error: {exc}", file=sys.stderr)
        return EXIT_OK
    header = f"monitor: {kind} watch={name}"
    try:
        client = Client(cfg, _authorization(kind, read_credentials(kind)))
        lines = READERS[kind](client, cfg)
    except Persistent as exc:
        _emit([header, f"error reason={exc.reason}" + (f" key={exc.key}" if exc.key else "")])
        return EXIT_OK
    except Transient as exc:
        print(f"{header} unreachable reason={exc.reason}", file=sys.stderr)
        return EXIT_UNREACHABLE
    _emit([header, *lines])
    return EXIT_OK


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.exit(run(sys.argv[1:]))

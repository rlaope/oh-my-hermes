"""The monitor-recipe scripts against fakes: a loopback API, a fake skill CLI, a temporary vault.

`src/skills/monitor_watch_toolkit/scripts/*.py` are companion data that a
Hermes cron job runs as its `--monitor-script`, on Hermes' interpreter. These
tests run them the same way, as child processes, against a server on
127.0.0.1, a stand-in `google_api.py`, and a folder in a temporary directory;
nothing reaches a real service. Hermes compares the exact stdout bytes, so the
tests compare bytes too: unchanged state must print the same bytes, a real
change must not, and a failure must never look like either.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import unittest
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "src/skills/monitor_watch_toolkit"
API = KIT / "scripts/api_watch.py"
GOOGLE = KIT / "scripts/google_watch.py"
VAULT = KIT / "scripts/vault_watch.py"
TOKEN = "FAKE-monitor-token-9c41e7"  # synthetic; must never be echoed
EMAIL = "someone@example.com"
CREDENTIAL_NAMES = ("NOTION_API_KEY", "LINEAR_API_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN", "SENTRY_AUTH_TOKEN")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeApi:
    """A loopback HTTP server whose replies come from `self.route(method, path, query, body) -> (status, body)`."""

    def __init__(self):
        self.requests: list[dict] = []
        self.route: Callable[..., tuple[int, object]] = lambda method, path, query, body: (404, {})
        api = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, method: str):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                query = parse_qs(parts.query)
                api.requests.append({"method": method, "path": parts.path, "query": query, "body": body,
                                     "headers": dict(self.headers.items())})
                status, reply = api.route(method, parts.path, query, body)
                data = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
                self.send_response(status)
                if status in (301, 302):
                    self.send_header("Location", api.base + "/elsewhere")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self._answer("GET")

            def do_POST(self):  # noqa: N802
                self._answer("POST")

            def log_message(self, format, *args):  # noqa: A002 - silence the server log
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_NAMES and k not in ("HERMES_HOME", "OBSIDIAN_VAULT_PATH")}
    env.update(extra)
    return env


def _run(script: Path, args: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, encoding="utf-8",
                          env=env, cwd=cwd, timeout=60, stdin=subprocess.DEVNULL, check=False)


class ApiWatchTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def config(self, **cfg) -> Path:
        cfg.setdefault("name", "watch-1")
        cfg.setdefault("api_base", self.api.base)
        path = self.dir / "watch.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path

    def watch(self, env: dict[str, str] | None = None, **cfg) -> subprocess.CompletedProcess:
        done = _run(API, ["--config", str(self.config(**cfg))], env if env is not None else _env(
            NOTION_API_KEY=TOKEN, LINEAR_API_KEY=TOKEN, JIRA_EMAIL=EMAIL, JIRA_API_TOKEN=TOKEN, SENTRY_AUTH_TOKEN=TOKEN))
        self.assertNotIn(TOKEN, done.stdout + done.stderr)
        return done

    # ------------------------------------------------------------ Notion

    def notion_routes(self, pages: dict[str, str], rows: list[dict]):
        def route(method, path, query, body):
            if method == "GET" and path.startswith("/v1/pages/"):
                page = path.rsplit("/", 1)[-1]
                if page not in pages:
                    return 404, {"object": "error", "code": "object_not_found"}
                dashed = f"{page[:8]}-{page[8:12]}-{page[12:16]}-{page[16:20]}-{page[20:]}"
                return 200, {"object": "page", "id": dashed, "last_edited_time": pages[page], "archived": False,
                             "properties": {"title": "Private roadmap text"}}
            if method == "POST" and path.endswith("/query"):
                return 200, {"object": "list", "results": rows, "has_more": False}
            return 404, {}
        self.api.route = route

    def test_notion_prints_ids_and_edit_times_sorted_and_sends_the_key_as_bearer(self):
        page, database = "a" * 32, "b" * 32
        rows = [{"id": "22222222-2222-2222-2222-222222222222", "last_edited_time": "2026-11-24T09:00:00.000Z",
                 "properties": {"Name": "Secret row title"}},
                {"id": "11111111-1111-1111-1111-111111111111", "last_edited_time": "2026-11-24T08:00:00.000Z"}]
        self.notion_routes({page: "2026-11-24T07:00:00.000Z"}, rows)
        done = self.watch(kind="notion", pages=[page], databases=[database], rows=5)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, "\n".join([
            "monitor: notion watch=watch-1",
            f"database {database} row 11111111-1111-1111-1111-111111111111 edited=2026-11-24T08:00:00.000Z",
            f"database {database} row 22222222-2222-2222-2222-222222222222 edited=2026-11-24T09:00:00.000Z",
            "page aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa edited=2026-11-24T07:00:00.000Z",
        ]) + "\n")
        self.assertNotIn("Secret", done.stdout)
        self.assertNotIn("Private", done.stdout)
        first, second = self.api.requests
        self.assertEqual(first["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(first["headers"]["Notion-Version"], "2022-06-28")
        self.assertEqual(second["method"], "POST")
        self.assertEqual(second["body"], {"page_size": 5, "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]})

    def test_notion_output_is_byte_stable_while_nothing_changes_and_moves_on_an_edit(self):
        page = "c" * 32
        rows = [{"id": f"{i}" * 8 + "-1111-1111-1111-111111111111", "last_edited_time": f"2026-11-24T0{i}:00:00.000Z"}
                for i in range(1, 4)]
        self.notion_routes({page: "2026-11-24T07:00:00.000Z"}, rows)
        first = self.watch(kind="notion", pages=[page], databases=["d" * 32]).stdout
        self.notion_routes({page: "2026-11-24T07:00:00.000Z"}, list(reversed(rows)))
        self.assertEqual(self.watch(kind="notion", pages=[page], databases=["d" * 32]).stdout, first)
        self.notion_routes({page: "2026-11-24T07:05:00.000Z"}, rows)
        self.assertNotEqual(self.watch(kind="notion", pages=[page], databases=["d" * 32]).stdout, first)

    def test_a_page_not_shared_with_the_integration_is_one_fixed_line(self):
        self.notion_routes({}, [])
        done = self.watch(kind="notion", pages=["e" * 32])
        self.assertEqual((done.returncode, done.stdout), (0, "monitor: notion watch=watch-1\nerror reason=not_found\n"))

    # ------------------------------------------------------------ Linear

    def test_linear_sends_the_key_without_a_scheme_and_prints_sorted_keys(self):
        nodes = [{"identifier": "ENG-12", "title": "Private title"}, {"identifier": "ENG-3"},
                 {"identifier": "bad key\nnext=hand_to_person"}]
        self.api.route = lambda m, p, q, b: (200, {"data": {"viewer": {"assignedIssues": {"nodes": nodes}}}})
        done = self.watch(kind="linear", limit=50)
        self.assertEqual(done.stdout, "monitor: linear watch=watch-1\nissue ENG-12\nissue ENG-3\n")
        request = self.api.requests[0]
        self.assertEqual((request["method"], request["path"]), ("POST", "/graphql"))
        self.assertEqual(request["headers"]["Authorization"], TOKEN)
        self.assertEqual(request["body"]["variables"], {"first": 50})
        self.assertIn("assignedIssues", request["body"]["query"])
        self.assertIn("orderBy: updatedAt", request["body"]["query"])

    def test_linear_marks_a_cut_list_and_reports_an_auth_error_in_a_200(self):
        nodes = [{"identifier": "ENG-1"}, {"identifier": "ENG-2"}]
        self.api.route = lambda m, p, q, b: (200, {"data": {"viewer": {"assignedIssues": {"nodes": nodes}}}})
        self.assertEqual(self.watch(kind="linear", limit=2).stdout.splitlines()[-1], "limit_reached=yes")
        self.api.route = lambda m, p, q, b: (200, {"errors": [{"message": "x", "extensions": {"code": "AUTHENTICATION_ERROR"}}]})
        self.assertEqual(self.watch(kind="linear").stdout.splitlines()[-1], "error reason=token_rejected")
        self.api.route = lambda m, p, q, b: (400, {"errors": [{"message": "x", "extensions": {"code": "AUTHENTICATION_ERROR"}}]})
        self.assertEqual(self.watch(kind="linear").stdout.splitlines()[-1], "error reason=token_rejected")

    # ------------------------------------------------------------ Jira

    def test_jira_uses_basic_auth_the_jql_and_prints_sorted_keys(self):
        issues = [{"id": "2", "key": "OPS-7"}, {"id": "1", "key": "OPS-10"}, {"id": "3", "key": "<b>x</b>"}]
        self.api.route = lambda m, p, q, b: (200, {"issues": issues, "isLast": True})
        done = self.watch(kind="jira", site="example", jql="assignee = currentUser()")
        self.assertEqual(done.stdout, "monitor: jira watch=watch-1\nissue OPS-10\nissue OPS-7\n")
        request = self.api.requests[0]
        self.assertEqual(request["path"], "/rest/api/3/search/jql")
        self.assertEqual(request["query"]["jql"], ["assignee = currentUser()"])
        self.assertTrue(request["headers"]["Authorization"].startswith("Basic "))
        self.assertEqual(self.watch(kind="jira", site="example").stdout.count("issue "), 2)
        self.assertEqual(self.api.requests[-1]["query"]["jql"],
                         ["assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"])

    def test_jira_needs_both_names_and_reports_invalid_jql_as_refused(self):
        done = self.watch(env=_env(JIRA_API_TOKEN=TOKEN), kind="jira", site="example")
        self.assertEqual(done.stdout.splitlines()[-1], "error reason=no_token key=JIRA_EMAIL")
        self.assertEqual(self.api.requests, [])
        self.api.route = lambda m, p, q, b: (400, {"errorMessages": ["bad jql"]})
        self.assertEqual(self.watch(kind="jira", site="example").stdout.splitlines()[-1], "error reason=request_rejected")

    # ------------------------------------------------------------ Sentry

    def test_sentry_reads_the_newest_issues_and_sorts_them_by_id(self):
        issues = [{"id": "4502", "shortId": "WEB-3G", "firstSeen": "2026-11-24T08:05:00.123456Z", "title": "Private",
                   "count": "17", "lastSeen": "2026-11-24T09:00:00Z"},
                  {"id": "999", "shortId": "WEB-1", "firstSeen": "2026-11-20T08:00:00Z", "count": "3"}]
        self.api.route = lambda m, p, q, b: (200, issues)
        done = self.watch(kind="sentry", org="example-org", project_ids=[42])
        self.assertEqual(done.stdout, "\n".join([
            "monitor: sentry watch=watch-1",
            "issue 999 short=WEB-1 first_seen=2026-11-20T08:00:00Z",
            "issue 4502 short=WEB-3G first_seen=2026-11-24T08:05:00.123456Z",
        ]) + "\n")
        request = self.api.requests[0]
        self.assertEqual(request["path"], "/api/0/organizations/example-org/issues/")
        self.assertEqual({k: v for k, v in request["query"].items()},
                         {"query": ["is:unresolved"], "sort": ["new"], "limit": ["10"], "statsPeriod": ["14d"],
                          "project": ["42"]})
        self.assertEqual(request["headers"]["Authorization"], f"Bearer {TOKEN}")
        # The volatile fields (count, lastSeen) are not in the output: a new event on an old issue wakes nobody.
        issues[0]["count"], issues[0]["lastSeen"] = "18", "2026-11-24T09:05:00Z"
        self.assertEqual(self.watch(kind="sentry", org="example-org", project_ids=[42]).stdout, done.stdout)

    # ------------------------------------------------------------ failures

    def test_a_missing_or_malformed_credential_sends_nothing_and_is_one_fixed_line(self):
        done = self.watch(env=_env(), kind="sentry", org="example-org")
        self.assertEqual((done.returncode, done.stdout),
                         (0, "monitor: sentry watch=watch-1\nerror reason=no_token key=SENTRY_AUTH_TOKEN\n"))
        done = self.watch(env=_env(SENTRY_AUTH_TOKEN="has a space " + TOKEN), kind="sentry", org="example-org")
        self.assertEqual(done.stdout.splitlines()[-1], "error reason=bad_token key=SENTRY_AUTH_TOKEN")
        self.assertEqual(self.api.requests, [])

    def test_refusals_are_fixed_lines_and_the_same_refusal_prints_the_same_bytes(self):
        for status, reason in ((401, "token_rejected"), (403, "forbidden"), (404, "not_found"), (422, "request_rejected")):
            self.api.route = lambda m, p, q, b, status=status: (status, {"detail": f"secret {TOKEN} detail"})
            first = self.watch(kind="sentry", org="example-org")
            second = self.watch(kind="sentry", org="example-org")
            self.assertEqual((first.returncode, first.stdout),
                             (0, f"monitor: sentry watch=watch-1\nerror reason={reason}\n"), status)
            self.assertEqual(second.stdout, first.stdout)

    def test_transient_failures_print_nothing_on_stdout_and_exit_1(self):
        for status, reason in ((429, "platform_busy"), (500, "server_error"), (503, "server_error"),
                               (302, "redirect_refused")):
            self.api.route = lambda m, p, q, b, status=status: (status, {})
            done = self.watch(kind="linear")
            self.assertEqual((done.returncode, done.stdout), (1, ""), status)
            self.assertEqual(done.stderr.strip(), f"monitor: linear watch=watch-1 unreachable reason={reason}")
        self.assertNotIn("/elsewhere", [r["path"] for r in self.api.requests])
        self.api.route = lambda m, p, q, b: (200, b"not json")
        done = self.watch(kind="linear")
        self.assertEqual((done.returncode, done.stdout, done.stderr.strip()),
                         (1, "", "monitor: linear watch=watch-1 unreachable reason=bad_response"))
        self.api.route = lambda m, p, q, b: (200, {"data": {"viewer": None}})
        self.assertEqual(self.watch(kind="linear").returncode, 1)

    def test_a_linear_rate_limit_is_transient_on_200_and_400(self):
        limited = {"errors": [{"message": "x", "extensions": {"code": "RATELIMITED"}}]}
        for status in (200, 400):
            self.api.route = lambda m, p, q, b, status=status: (status, limited)
            done = self.watch(kind="linear")
            self.assertEqual((done.returncode, done.stdout, done.stderr.strip()),
                             (1, "", "monitor: linear watch=watch-1 unreachable reason=platform_busy"), status)

    def test_a_list_with_items_but_no_readable_id_is_a_failure_not_an_empty_list(self):
        cases = (
            ({"kind": "linear"}, {"data": {"viewer": {"assignedIssues": {"nodes": [{"id": "uuid-only"}]}}}}),
            ({"kind": "jira", "site": "example"}, {"issues": [{"id": "10001"}], "isLast": True}),
            ({"kind": "sentry", "org": "example-org"}, [{"id": "12", "title": "no short id"}]),
            ({"kind": "notion", "databases": ["b" * 32]}, {"results": [{"id": "x"}]}),
        )
        for cfg, reply in cases:
            self.api.route = lambda m, p, q, b, reply=reply: (200, reply)
            done = self.watch(**cfg)
            self.assertEqual((done.returncode, done.stdout), (1, ""), cfg)
            self.assertIn("reason=bad_response", done.stderr, cfg)
        self.api.route = lambda m, p, q, b: (200, {"issues": [], "isLast": True})
        self.assertEqual(self.watch(kind="jira", site="example").stdout.splitlines()[-1], "issues=0")

    def test_the_transient_reasons_never_read_as_a_model_provider_failure(self):
        """Hermes classifies a monitor job's failure text with its provider classifier; keep these words out."""
        import ast
        words = set()
        for script in (API, GOOGLE):
            for node in ast.walk(ast.parse(script.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Transient"
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    words.add(node.args[0].value)
        self.assertEqual(words, {"network", "platform_busy", "server_error", "redirect_refused", "reply_too_large",
                                 "bad_response", "cli_failed"})
        for word in words:
            for banned in ("rate", "limit", "too_many", "throttl", "timed", "timeout", "quota", "overload"):
                self.assertNotIn(banned, word)

    def test_a_malformed_status_line_is_bad_response_without_a_traceback(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def answer():
            conn, _ = server.accept()
            with conn:
                # Read the whole request (headers, then the Content-Length body of the GraphQL POST) before
                # replying. One recv() can return the headers alone; closing a socket with request bytes still
                # unread makes Windows send RST instead of FIN, and the client then reports `network`, not
                # the `bad_response` this test is about (seen on test-windows in two CI runs).
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                head, _, body = data.partition(b"\r\n\r\n")
                length = 0
                for line in head.split(b"\r\n")[1:]:
                    name, _, value = line.partition(b":")
                    if name.strip().lower() == b"content-length":
                        length = int(value.strip())
                while len(body) < length:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    body += chunk
                conn.sendall(b"GARBAGE\r\n\r\n")
        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        try:
            done = self.watch(kind="linear", api_base=f"http://127.0.0.1:{port}")
        finally:
            thread.join(5)
            server.close()
        self.assertEqual((done.returncode, done.stdout, done.stderr.strip()),
                         (1, "", "monitor: linear watch=watch-1 unreachable reason=bad_response"))

    def test_a_reply_that_drips_is_cut_at_the_deadline(self):
        module = _load(API, "api_watch_deadline_check")
        module.DEADLINE_S, module.TIMEOUT_S = 1, 5
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        stop = threading.Event()

        def drip():
            conn, _ = server.accept()
            with conn:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n")
                while not stop.wait(0.3):
                    try:
                        conn.sendall(b" ")
                    except OSError:
                        return
        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        try:
            client = module.Client({"base": f"http://127.0.0.1:{port}", "loopback": True}, "Bearer x")
            with self.assertRaises(module.Transient) as caught:
                client.call("GET", "/slow")
        finally:
            stop.set()
            thread.join(5)
            server.close()
        self.assertEqual(caught.exception.reason, "network")

    def test_a_closed_port_is_a_network_failure_not_a_change(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        done = self.watch(kind="notion", pages=["f" * 32], api_base=f"http://127.0.0.1:{port}")
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn("unreachable reason=network", done.stderr)

    def test_config_errors_are_one_fixed_line(self):
        for cfg in ({"kind": "trello"}, {"kind": "notion"}, {"kind": "notion", "pages": ["not-an-id"]},
                    {"kind": "jira", "site": "evil.example.com/x"}, {"kind": "sentry", "org": "x", "region": "eu"},
                    {"kind": "linear", "api_base": "https://api.linear.app.example.net"},
                    {"kind": "linear", "api_base": "http://10.0.0.8:80"}, {"kind": "linear", "limit": 0},
                    {"kind": "jira", "site": "example", "jql": "a\nb"}):
            done = self.watch(**cfg)
            self.assertEqual(done.returncode, 0, cfg)
            self.assertEqual(done.stdout.splitlines()[-1], "error reason=config", cfg)
        self.assertEqual(self.api.requests, [])

    def test_hosts_are_fixed_and_a_config_cannot_move_the_credential(self):
        module = _load(API, "api_watch_under_test")
        hosts = {}
        for cfg in ({"kind": "notion", "pages": ["a" * 32]}, {"kind": "linear"}, {"kind": "jira", "site": "acme"},
                    {"kind": "sentry", "org": "acme"}, {"kind": "sentry", "org": "acme", "region": "de"}):
            path = self.dir / "cfg.json"
            path.write_text(json.dumps({"name": "w", **cfg}), encoding="utf-8")
            loaded = module.load_config(path)
            hosts[(cfg["kind"], cfg.get("region", ""))] = (loaded["base"], loaded["loopback"])
        self.assertEqual(hosts, {
            ("notion", ""): ("https://api.notion.com", False),
            ("linear", ""): ("https://api.linear.app", False),
            ("jira", ""): ("https://acme.atlassian.net", False),
            ("sentry", ""): ("https://sentry.io", False),
            ("sentry", "de"): ("https://de.sentry.io", False),
        })
        self.assertEqual(module.TOKEN_KEYS, {"notion": ("NOTION_API_KEY",), "linear": ("LINEAR_API_KEY",),
                                             "jira": ("JIRA_EMAIL", "JIRA_API_TOKEN"),
                                             "sentry": ("SENTRY_AUTH_TOKEN",)})

    def test_installed_copy_finds_its_config_from_its_file_name(self):
        home = self.dir / "profile"
        (home / "scripts").mkdir(parents=True)
        (home / "monitors").mkdir()
        shutil.copy(API, home / "scripts/api_watch_my-linear.py")
        nodes = [{"identifier": "ENG-1"}]
        self.api.route = lambda m, p, q, b: (200, {"data": {"viewer": {"assignedIssues": {"nodes": nodes}}}})
        (home / "monitors/my-linear.json").write_text(json.dumps(
            {"name": "my-linear", "kind": "linear", "api_base": self.api.base}), encoding="utf-8")
        done = _run(home / "scripts/api_watch_my-linear.py", [], _env(HERMES_HOME=str(home), LINEAR_API_KEY=TOKEN))
        self.assertEqual(done.stdout, "monitor: linear watch=my-linear\nissue ENG-1\n")
        (home / "monitors/my-linear.json").write_text(json.dumps({"name": "other", "kind": "linear"}), encoding="utf-8")
        done = _run(home / "scripts/api_watch_my-linear.py", [], _env(HERMES_HOME=str(home), LINEAR_API_KEY=TOKEN))
        self.assertEqual(done.stdout, "monitor: linear watch=my-linear\nerror reason=config\n")


FAKE_GOOGLE_API = '''
import json, os, sys, time
from pathlib import Path
Path(os.environ["FAKE_GOOGLE_ARGV"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
if os.environ.get("FAKE_GOOGLE_SLEEP"):
    time.sleep(float(os.environ["FAKE_GOOGLE_SLEEP"]))
if os.environ.get("FAKE_GOOGLE_STDERR"):
    print(os.environ["FAKE_GOOGLE_STDERR"], file=sys.stderr)
sys.stdout.write(os.environ.get("FAKE_GOOGLE_REPLY", "[]"))
sys.exit(int(os.environ.get("FAKE_GOOGLE_EXIT", "0")))
'''


class GoogleWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "profile"
        self.cli = self.home / "skills/productivity/google-workspace/scripts/google_api.py"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text(FAKE_GOOGLE_API, encoding="utf-8")
        (self.home / "google_token.json").write_text('{"token": "' + TOKEN + '"}', encoding="utf-8")
        self.argv_file = Path(self.tmp.name) / "argv.json"

    def watch(self, reply: object = (), now: str = "2026-11-24T09:00:00+00:00", **extra) -> subprocess.CompletedProcess:
        cfg = {"name": "w", **extra.pop("cfg")}
        path = Path(self.tmp.name) / "watch.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        env = _env(HERMES_HOME=str(self.home), FAKE_GOOGLE_ARGV=str(self.argv_file),
                   FAKE_GOOGLE_REPLY=reply if isinstance(reply, str) else json.dumps(list(reply)), **extra)
        done = _run(GOOGLE, ["--config", str(path), "--now", now], env)
        self.assertNotIn(TOKEN, done.stdout + done.stderr)
        return done

    def argv(self) -> list[str]:
        return json.loads(self.argv_file.read_text(encoding="utf-8"))

    def test_gmail_runs_one_fixed_search_and_prints_only_sorted_ids(self):
        messages = [{"id": "18c2f0a1b2c3d4e6", "threadId": "t", "from": "Boss <boss@example.com>",
                     "subject": "Private subject", "snippet": "private snippet", "labels": ["UNREAD"]},
                    {"id": "18c2f0a1b2c3d4e5", "subject": "Another"}, {"id": "not hex\nmessage x"}]
        done = self.watch(messages, cfg={"kind": "gmail", "query": "-in:chats from:boss@example.com", "limit": 7})
        self.assertEqual((done.returncode, done.stdout), (0, "\n".join([
            "monitor: gmail watch=w", "matched=2", "message 18c2f0a1b2c3d4e5", "message 18c2f0a1b2c3d4e6"]) + "\n"))
        self.assertEqual(self.argv(), ["gmail", "search", "--max", "7", "--", "-in:chats from:boss@example.com"])
        for private in ("Boss", "Private", "private", "Another"):
            self.assertNotIn(private, done.stdout)
        again = self.watch(list(reversed(messages)), cfg={"kind": "gmail", "query": "-in:chats from:boss@example.com", "limit": 7})
        self.assertEqual(again.stdout, done.stdout)

    def test_calendar_wakes_for_each_event_entering_the_lead_window(self):
        cfg = {"kind": "calendar", "lead_minutes": 15}
        events = [
            {"id": "evta", "summary": "Private standup", "start": "2026-11-24T18:10:00+09:00", "status": "confirmed"},
            {"id": "evtb", "summary": "Later", "start": "2026-11-24T10:00:00Z"},
            {"id": "allday", "summary": "Holiday", "start": "2026-11-24"},
            {"id": "gone", "summary": "Cancelled", "start": "2026-11-24T09:12:00Z", "status": "cancelled"},
            {"id": "old", "start": "2026-11-23T12:00:00Z"},
            {"id": "older", "start": "2026-11-23T08:00:00Z"},
        ]
        before = self.watch(events, now="2026-11-24T08:50:00+00:00", cfg=cfg)
        self.assertEqual(before.stdout, "monitor: calendar watch=w\nevent old start=2026-11-23T12:00:00Z\n")
        self.assertEqual(self.argv(), ["calendar", "list", "--start", "2026-11-23T08:50:00Z", "--end",
                                       "2026-11-24T09:05:00Z", "--max", "100", "--calendar", "primary"])
        entered = self.watch(events, now="2026-11-24T09:00:00+00:00", cfg=cfg)
        self.assertEqual(entered.stdout, "monitor: calendar watch=w\nevent old start=2026-11-23T12:00:00Z\n"
                                         "event evta start=2026-11-24T18:10:00+09:00\n")
        self.assertNotIn("Private", entered.stdout)
        # Still inside the window a tick later: the same bytes, no wake.
        self.assertEqual(self.watch(events, now="2026-11-24T09:05:00+00:00", cfg=cfg).stdout, entered.stdout)
        # It starts: it replaces the earlier started event, one change the prompt answers [SILENT].
        started = self.watch(events, now="2026-11-24T09:20:00+00:00", cfg=cfg)
        self.assertEqual(started.stdout, "monitor: calendar watch=w\nevent evta start=2026-11-24T18:10:00+09:00\n")
        self.assertEqual(self.watch(events, now="2026-11-24T09:40:00+00:00", cfg=cfg).stdout, started.stdout)
        nxt = self.watch(events, now="2026-11-24T09:46:00+00:00", cfg=cfg)
        self.assertEqual(nxt.stdout, "monitor: calendar watch=w\nevent evta start=2026-11-24T18:10:00+09:00\n"
                                     "event evtb start=2026-11-24T10:00:00Z\n")
        self.assertEqual(self.watch([], cfg=cfg).stdout, "monitor: calendar watch=w\nevent none\n")

    def test_two_events_entering_in_one_tick_and_one_added_ahead_each_get_a_line(self):
        cfg = {"kind": "calendar", "lead_minutes": 15}
        both = [{"id": "aaa", "start": "2026-11-24T10:00:00Z"}, {"id": "bbb", "start": "2026-11-24T10:02:00Z"}]
        done = self.watch(both, now="2026-11-24T09:47:00+00:00", cfg=cfg)
        self.assertEqual(done.stdout.splitlines()[1:], ["event aaa start=2026-11-24T10:00:00Z",
                                                        "event bbb start=2026-11-24T10:02:00Z"])
        shown = self.watch([{"id": "late", "start": "2026-11-24T10:00:00Z"}], now="2026-11-24T09:50:00+00:00", cfg=cfg)
        added = self.watch([{"id": "late", "start": "2026-11-24T10:00:00Z"},
                            {"id": "early", "start": "2026-11-24T09:55:00Z"}], now="2026-11-24T09:50:00+00:00", cfg=cfg)
        self.assertNotEqual(added.stdout, shown.stdout)
        self.assertIn("event early start=2026-11-24T09:55:00Z", added.stdout)

    def test_a_reply_with_items_but_no_readable_id_is_a_failure_not_nothing(self):
        done = self.watch([{"identifier": "x"}], cfg={"kind": "gmail", "query": "is:starred"})
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn("reason=bad_response", done.stderr)
        done = self.watch([{"eventId": "x", "start": "2026-11-24T09:05:00Z"}], cfg={"kind": "calendar"})
        self.assertEqual((done.returncode, done.stdout), (1, ""))

    def test_events_with_the_same_start_print_together_in_id_order(self):
        events = [{"id": "zz", "start": "2026-11-24T09:05:00Z"}, {"id": "aa", "start": "2026-11-24T09:05:00Z"}]
        done = self.watch(events, cfg={"kind": "calendar"})
        self.assertEqual(done.stdout.splitlines()[1:], ["event aa start=2026-11-24T09:05:00Z",
                                                        "event zz start=2026-11-24T09:05:00Z"])

    def test_start_reads_every_shape_google_calendar_sends(self):
        import datetime as dt
        module = _load(GOOGLE, "google_watch_start_check")
        utc = dt.timezone.utc
        self.assertEqual(module._start("2026-11-24T10:00:00+09:00"), dt.datetime(2026, 11, 24, 1, tzinfo=utc))
        self.assertEqual(module._start("2026-11-24T01:00:00Z"), dt.datetime(2026, 11, 24, 1, tzinfo=utc))
        self.assertEqual(module._start("2026-11-24T01:00:00z"), dt.datetime(2026, 11, 24, 1, tzinfo=utc))
        self.assertEqual(module._start("2026-11-24T01:00:00.250Z"),
                         dt.datetime(2026, 11, 24, 1, 0, 0, 250000, tzinfo=utc))
        self.assertEqual(module._start("2026-11-24T00:00:00-05:00"), dt.datetime(2026, 11, 24, 5, tzinfo=utc))
        for unreadable in ("2026-11-24",              # all-day: a date, not a start time
                           "2026-11-24T10:00:00",     # no offset names no instant
                           "2026-11-24T24:00:00Z",    # hour 24, refused on every Python
                           "2026-11-24T24:00:00+09:00", "2026-11-24T25:00:00Z", "not a time", "", None, 1700000000,
                           "2026-11-24T10:00:00Z\nevent x"):
            with self.subTest(value=unreadable):
                self.assertIsNone(module._start(unreadable))

    def test_an_hour_24_start_is_left_out_not_moved_to_the_next_day(self):
        events = [{"id": "odd", "start": "2026-11-24T24:00:00Z"}, {"id": "real", "start": "2026-11-24T09:05:00Z"}]
        done = self.watch(events, cfg={"kind": "calendar"})
        self.assertEqual(done.stdout, "monitor: calendar watch=w\nevent real start=2026-11-24T09:05:00Z\n")

    def test_no_skill_or_no_sign_in_is_one_fixed_line_and_runs_nothing(self):
        (self.home / "google_token.json").unlink()
        done = self.watch(cfg={"kind": "gmail", "query": "is:starred"})
        self.assertEqual(done.stdout, "monitor: gmail watch=w\nerror reason=not_signed_in\n")
        self.assertFalse(self.argv_file.exists())
        self.cli.unlink()
        done = self.watch(cfg={"kind": "calendar"})
        self.assertEqual(done.stdout, "monitor: calendar watch=w\nerror reason=skill_missing\n")

    def test_an_expired_sign_in_is_one_line_and_other_failures_exit_1(self):
        done = self.watch(cfg={"kind": "gmail", "query": "is:starred"}, FAKE_GOOGLE_EXIT="1",
                          FAKE_GOOGLE_STDERR="Token is invalid. Re-run setup.")
        self.assertEqual((done.returncode, done.stdout), (0, "monitor: gmail watch=w\nerror reason=sign_in_expired\n"))
        done = self.watch(cfg={"kind": "gmail", "query": "is:starred"}, FAKE_GOOGLE_EXIT="1",
                          FAKE_GOOGLE_STDERR=f"HttpError 503 {TOKEN}")
        self.assertEqual((done.returncode, done.stdout, done.stderr.strip()),
                         (1, "", "monitor: gmail watch=w unreachable reason=cli_failed"))
        done = self.watch("{not json", cfg={"kind": "gmail", "query": "is:starred"})
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn("reason=bad_response", done.stderr)

    def test_a_cli_that_hangs_is_a_failed_tick_not_a_change(self):
        module = _load(GOOGLE, "google_watch_under_test")
        module.TIMEOUT_S = 1
        old = {k: os.environ.get(k) for k in ("FAKE_GOOGLE_ARGV", "FAKE_GOOGLE_SLEEP")}
        os.environ.update(FAKE_GOOGLE_ARGV=str(self.argv_file), FAKE_GOOGLE_SLEEP="5")
        try:
            with self.assertRaises(module.Transient) as caught:
                module.run_skill(self.home, {"kind": "calendar", "calendar": "primary", "lead_minutes": 15},
                                 module._start("2026-11-24T09:00:00+00:00"))
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual(caught.exception.reason, "cli_failed")

    def test_config_errors(self):
        for cfg in ({"kind": "gmail"}, {"kind": "gmail", "query": "a\nb"}, {"kind": "gmail", "query": "x", "limit": 51},
                    {"kind": "calendar", "calendar": "--evil"}, {"kind": "calendar", "lead_minutes": 0},
                    {"kind": "drive"}):
            done = self.watch(cfg=cfg)
            self.assertEqual((done.returncode, done.stdout.splitlines()[-1]), (0, "error reason=config"), cfg)
        self.assertFalse(self.argv_file.exists())


class VaultWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "My Vault"
        (self.vault / "Inbox/sub").mkdir(parents=True)
        (self.vault / ".obsidian").mkdir()
        (self.vault / "Inbox/.trash").mkdir()
        self.note("Inbox/a.md", "secret content alpha", 1_700_000_000)
        self.note("Inbox/sub/b.md", "secret content beta", 1_700_000_100)
        self.note("Inbox/image.png", "png", 1_700_000_200)
        self.note(".obsidian/workspace.json", "{}", 1_700_000_300)
        self.note("Inbox/.trash/old.md", "gone", 1_700_000_400)
        self.note("Elsewhere.md", "outside the folder", 1_700_000_500)

    def note(self, relative: str, text: str, mtime: int) -> None:
        path = self.vault / relative
        path.write_text(text, encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def watch(self, env: dict[str, str] | None = None, **cfg) -> subprocess.CompletedProcess:
        cfg = {"name": "w", "kind": "obsidian", "vault": str(self.vault), "folder": "Inbox", **cfg}
        path = Path(self.tmp.name) / "watch.json"
        path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}), encoding="utf-8")
        return _run(VAULT, ["--config", str(path)], env if env is not None else _env())

    def test_prints_a_digest_and_the_newest_names_never_content(self):
        done = self.watch()
        lines = done.stdout.splitlines()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[0], "monitor: obsidian watch=w")
        self.assertRegex(lines[1], r"^folder=Inbox files=2 digest=[0-9a-f]{16}$")
        self.assertEqual(lines[2:], ["recent 2023-11-14T22:15:00Z Inbox/sub/b.md",
                                     "recent 2023-11-14T22:13:20Z Inbox/a.md"])
        self.assertNotIn("secret", done.stdout)
        self.assertNotIn("workspace", done.stdout)
        self.assertNotIn("old.md", done.stdout)

    def test_unchanged_is_byte_stable_and_a_touch_an_edit_or_a_new_note_changes_it(self):
        first = self.watch().stdout
        self.assertEqual(self.watch().stdout, first)
        self.note(".obsidian/workspace.json", "{\"open\": 1}", 1_700_009_999)
        self.assertEqual(self.watch().stdout, first)
        self.note("Inbox/a.md", "secret content alpha!", 1_700_000_000)
        edited = self.watch().stdout
        self.assertNotEqual(edited, first)
        os.utime(self.vault / "Inbox/a.md", (1_700_000_050, 1_700_000_050))
        touched = self.watch().stdout
        self.assertNotEqual(touched, edited)
        self.note("Inbox/c.md", "new", 1_700_000_060)
        self.assertNotEqual(self.watch().stdout, touched)

    def test_without_mtimes_a_touch_wakes_nobody_but_a_size_change_does(self):
        first = self.watch(use_mtime=False)
        self.assertEqual(len(first.stdout.splitlines()), 2)  # no `recent` lines without modification times
        os.utime(self.vault / "Inbox/a.md", (1_700_000_777, 1_700_000_777))
        self.assertEqual(self.watch(use_mtime=False).stdout, first.stdout)
        self.note("Inbox/a.md", "secret content alpha, longer", 1_700_000_000)
        self.assertNotEqual(self.watch(use_mtime=False).stdout, first.stdout)

    def test_a_link_anywhere_in_the_folder_path_is_refused(self):
        outside = Path(self.tmp.name) / "outside"
        (outside / "b").mkdir(parents=True)
        (outside / "b/private diagnosis.md").write_text("x", encoding="utf-8")
        try:
            os.symlink(outside, self.vault / "a", target_is_directory=True)
        except OSError:
            self.assertEqual(self.watch(folder="a/b").stdout.splitlines()[-1], "error reason=folder_missing")
            return  # Windows without the symlink privilege: no link exists, and the missing folder is refused
        done = self.watch(folder="a/b")
        self.assertEqual(done.stdout, "monitor: obsidian watch=w\nerror reason=folder_missing\n")
        self.assertNotIn("private", done.stdout)

    def test_the_vault_comes_from_the_environment_when_the_config_names_none(self):
        done = self.watch(env=_env(OBSIDIAN_VAULT_PATH=str(self.vault)), vault=None)
        self.assertRegex(done.stdout.splitlines()[1], r"^folder=Inbox files=2 ")
        done = self.watch(env=_env(OBSIDIAN_VAULT_PATH=str(self.vault)), vault=None, folder="")
        self.assertRegex(done.stdout.splitlines()[1], r"^folder=\. files=3 ")

    def test_a_linked_folder_is_not_followed(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "linked.md").write_text("x", encoding="utf-8")
        try:
            os.symlink(outside, self.vault / "Inbox/link", target_is_directory=True)
            linked = True
        except OSError:
            linked = False  # Windows without the symlink privilege: there is no link to follow
        done = self.watch()
        self.assertNotIn("linked.md", done.stdout)
        self.assertRegex(done.stdout.splitlines()[1], r"files=2 ")
        if linked:
            done = self.watch(folder="Inbox/link")
            self.assertEqual(done.stdout.splitlines()[-1], "error reason=folder_missing")

    def test_missing_vault_or_folder_and_config_errors_are_one_fixed_line(self):
        self.assertEqual(self.watch(folder="Nope").stdout, "monitor: obsidian watch=w\nerror reason=folder_missing\n")
        done = self.watch(vault=str(Path(self.tmp.name) / "missing"))
        self.assertEqual(done.stdout, "monitor: obsidian watch=w\nerror reason=vault_missing\n")
        for cfg in ({"folder": "../outside"}, {"folder": "/etc"}, {"folder": ".obsidian"}, {"extensions": ["md"]},
                    {"recent": 51}, {"kind": "notion"}, {"use_mtime": "no"}):
            done = self.watch(**cfg)
            self.assertEqual((done.returncode, done.stdout.splitlines()[-1]), (0, "error reason=config"), cfg)

    def test_non_ascii_names_print_as_utf8_under_a_c_locale(self):
        self.note("Inbox/회의록.md", "x", 1_700_000_900)
        done = subprocess.run([sys.executable, str(VAULT), "--config", str(self._config())], capture_output=True,
                              env=_env(LC_ALL="C", LANG="C", PYTHONIOENCODING=""), timeout=60, check=False)
        self.assertIn("Inbox/회의록.md".encode("utf-8"), done.stdout)

    def _config(self) -> Path:
        path = Path(self.tmp.name) / "watch.json"
        path.write_text(json.dumps({"name": "w", "kind": "obsidian", "vault": str(self.vault), "folder": "Inbox"}),
                        encoding="utf-8")
        return path


class RecipeDataTest(unittest.TestCase):
    def test_the_six_triggers_each_have_a_recipe_whose_script_accepts_its_example(self):
        from omh.skills.monitor_recipes import MONITOR_RECIPES
        self.assertEqual(sorted({r.number for r in MONITOR_RECIPES}), [1, 2, 3, 4, 5, 6])
        self.assertEqual({r.kind for r in MONITOR_RECIPES},
                         {"gmail", "calendar", "notion", "linear", "jira", "obsidian", "sentry"})
        api = _load(API, "api_watch_recipe_check")
        modules = {"api_watch.py": api, "google_watch.py": _load(GOOGLE, "google_watch_recipe_check"),
                   "vault_watch.py": _load(VAULT, "vault_watch_recipe_check")}
        for recipe in MONITOR_RECIPES:
            with self.subTest(recipe=recipe.kind):
                cfg = modules[recipe.script].load_config(KIT / "examples" / recipe.example)
                self.assertEqual(cfg["kind"] if "kind" in cfg else "obsidian", recipe.kind)
                self.assertEqual(recipe.env_names, api.TOKEN_KEYS.get(recipe.kind, ()))
                self.assertTrue(recipe.schedule.startswith("every "))

    def test_every_example_ships_and_every_script_is_in_the_inventory(self):
        from omh.skills.monitor_watch_support import TOOLKIT_RESOURCES, monitor_watch_support_templates
        on_disk = sorted(p.relative_to(KIT).as_posix() for p in KIT.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        self.assertEqual(sorted(TOOLKIT_RESOURCES), on_disk)
        shipped = ROOT / "skills/omh-automation-blueprint"
        for template in monitor_watch_support_templates():
            with self.subTest(path=template.relative_path):
                self.assertTrue(template.relative_path.startswith("toolkit/monitors/"))
                self.assertEqual((shipped / template.relative_path).read_text(encoding="utf-8"), template.content)

    def test_the_reference_is_rendered_from_the_recipes_and_every_job_is_created_paused(self):
        from omh.skills.monitor_recipes import MONITOR_RECIPES, monitor_recipes_reference_templates
        (template,) = monitor_recipes_reference_templates()
        shipped = ROOT / "skills/omh-automation-blueprint" / template.relative_path
        self.assertEqual(shipped.read_text(encoding="utf-8"), template.content)
        text = template.content
        self.assertEqual(text.count("cron create"), len(MONITOR_RECIPES))
        self.assertEqual(text.count("--paused --paused-reason"), len(MONITOR_RECIPES))
        for recipe in MONITOR_RECIPES:
            with self.subTest(recipe=recipe.kind):
                stem = recipe.script.removesuffix(".py")
                self.assertIn(f"--monitor-script {stem}_<watch>.py", text)
                self.assertIn((KIT / "examples" / recipe.example).read_text(encoding="utf-8").strip(), text)
        self.assertIn("reply with exactly [SILENT]", text)
        self.assertIn("Notify only", text)
        from omh.skills.catalog_feature_surfaces import _UNATTENDED_GATE
        self.assertIn(_UNATTENDED_GATE, text)

    def test_automation_blueprint_points_these_triggers_at_the_reference(self):
        body = (ROOT / "skills/omh-automation-blueprint/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("follow `references/monitor-recipes.md`", body)
        self.assertIn("create the job paused until the person confirms", body)


if __name__ == "__main__":
    unittest.main()

"""Gate keeping real identities out of test fixtures.

The repository is public. A fixture copied from a live session carries whoever ran it: their email, the
workspace host of their team's chat or wiki, the user folder of their machine. Each one is read by anyone who
opens the file, and removing it later does not remove it from history. The only cheap fix is for the value
never to land, so this module re-reads the fixture tree on every run and fails with the path and line of an
email address, a SaaS tenant host or a user folder that is not on the reserved list below.

Scope: every tracked file under `tests/` and omher's test trees (e2e specs and their mock bridge, the bridge's
tests, the desktop shell's recorded streams and its Rust sources, whose tests live in-file, the page's unit tests
and replay fixtures, the in-page mock hosts and the preview build that ships them). Other product code and docs
are out of scope here; a fixture is where a pasted value most often hides.

The check is deliberately narrow (four patterns, one `git ls-files`) so it stays cheap; it reports where a
value is, never the value itself, so a failure log does not repeat the leak.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SCOPE = (
    "tests",
    "apps/omher/e2e",
    "apps/omher/bridge/tests",
    "apps/omher/src-tauri/tests",
    "apps/omher/src/state/__fixtures__",
    "apps/omher/src/**/*.test.ts",
    "apps/omher/src/**/*.test.tsx",
    "apps/omher/src/**/host.ts",
    "apps/omher/preview",
    "apps/omher/src-tauri/src",
)
BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".zip", ".gz", ".pdf")

# An address whose last label is a real top-level domain: the common generic ones and the country codes a mailbox
# is likely to use. A filename such as `x@host.com.json` still matches on its `x@host.com` part; a decorator such as
# `@pytest.mark` does not, its last label being no TLD. TLDs that read as file suffixes or attribute names (`py`,
# `sh`, `rs`, `md`, `id`, `name`, `is`) are left out: they would flag code, not people.
TLDS = (
    "com|org|net|edu|gov|mil|int|info|biz|pro|io|ai|dev|app|co|me|xyz|tech|site|online|cloud|email|page|tv|cc|ws|gg|ly|fm|to"
    "|us|uk|de|fr|jp|kr|cn|tw|hk|sg|in|au|nz|ca|br|mx|ar|cl|es|it|nl|be|ch|at|se|no|fi|dk|pl|cz|pt|gr|ru|ua|tr|il|za|eu|vn|th|ph|my"
)
EMAIL = re.compile(rf"(?<![\w.+%-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+)({TLDS})\b", re.IGNORECASE)
# Reserved and non-routable names (RFC 2606 / RFC 6761: example.*, *.example, *.invalid, *.test, localhost),
# GitHub's noreply addresses, and the public product addresses tests assert on as protocol shapes: `git@<forge>`
# (an SSH remote, not a person), WhatsApp's JID domains, Devin's bot address, and the conventional attacker
# placeholders of URL-userinfo tests. A forge host (github.com, gitlab.com, a GitHub Enterprise `*.ghe.com`) is the
# `<login>@<host>` account id of omher's Tasks and Accounts (docs/OMHER-BOUNDARY.md rules 18 and 33), not a mailbox.
RESERVED_DOMAIN = re.compile(
    r"(^|\.)(example\.(com|org|net)|example\.co\.kr|[a-z0-9-]+\.example|[a-z0-9-]+\.invalid|[a-z0-9-]+\.test"
    r"|github\.com|gitlab\.com|[a-z0-9-]+\.ghe\.com|users\.noreply\.github\.com|s\.whatsapp\.net|g\.us|app\.devin\.ai|evil\.(com|io))$"
)
PROTOCOL_LOCAL = {"git", "noreply", "no-reply"}

# A SaaS tenant lives in the host's first label (`<team>.slack.com`) or the first path segment
# (`linear.app/<workspace>/`, `notion.so/<workspace>/`; a root page `notion.so/<Title>-<id>` has no slash after it). Only obviously made-up tenants pass, plus a product's own fixed hosts and paths.
TENANT_HOST = re.compile(
    r"\b([a-z0-9-]+)\.(slack\.com|atlassian\.net|notion\.site|zendesk\.com|okta\.com|sharepoint\.com|monday\.com)\b", re.IGNORECASE
)
TENANT_PATH = re.compile(r"\b(?:linear\.app|notion\.so)/([a-z0-9-]+)/", re.IGNORECASE)
SYNTHETIC_TENANT = {"example", "demo", "acme", "x", "team", "app", "www", "api", "hooks", "files", "status", "sse", "mcp"}

# A user folder names a person: only placeholder users pass (compared case-folded). A dot-name (`/home/.local`,
# `/home/..`) or an all-digit one is a path test's directory, not an account, so it is skipped. A folder name with
# spaces (`/Users/<First> <Last>/`) is read whole when a path separator follows it, and passes only when every word is
# a placeholder (`Demo User`, `Jane Doe`), so a real surname cannot ride behind an allowlisted first name.
USER_DIR = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\?Users\\\\?)([A-Za-z0-9._@-]+(?:(?: [A-Za-z0-9._@-]+)+(?=[\\/]))?)")
PLACEHOLDER_USER = {"you", "demo", "me", "user", "runner", "runneradmin", "name", "username", "alice", "bob", "jane", "x", "a", "b", "u",
                    "k", "k2", "h", "o", "test", "tester", "example", "someone", "foo", "shared", "public", "private", "dev", "operator",
                    "person", "admin", "one", "two", "other", "owner", "plain", "secret", "victim", "ci", "user2", "user2024",
                    "project", "repo", "config", "tests", "doe"}


def _names_a_user(user: str) -> bool:
    # a macOS account named by its email (`/Users/<you>@<domain>/`) passes when the domain is reserved
    reserved_mail = "@" in user and RESERVED_DOMAIN.search(user.rsplit("@", 1)[1].lower())
    skipped = user.startswith(".") or user.isdigit()
    placeholder = all(word in PLACEHOLDER_USER for word in user.lower().split(" "))
    return not (placeholder or reserved_mail or skipped)


def _scoped_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--", *SCOPE], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f and not f.endswith(BINARY_SUFFIXES)]


def _findings() -> list[str]:
    found: list[str] = []
    for rel in _scoped_files():
        if rel == "tests/test_identity_fixture_policy.py":
            continue
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:  # tracked but deleted in the working tree: nothing on disk to leak
            continue
        for n, line in enumerate(text.split("\n"), 1):
            for m in EMAIL.finditer(line.replace("%40", "@")):  # a URL-encoded `@` is still an address
                domain = (m.group(2) + m.group(3)).lower()
                if m.group(1).lower() not in PROTOCOL_LOCAL and not RESERVED_DOMAIN.search(domain):
                    found.append(f"{rel}:{n}: email outside the reserved domains")
            for m in TENANT_HOST.finditer(line):
                if m.group(1).lower() not in SYNTHETIC_TENANT:
                    found.append(f"{rel}:{n}: SaaS tenant host")
            for m in TENANT_PATH.finditer(line):
                if m.group(1).lower() not in SYNTHETIC_TENANT:
                    found.append(f"{rel}:{n}: SaaS tenant path")
            for m in USER_DIR.finditer(line):
                if _names_a_user(m.group(1)):
                    found.append(f"{rel}:{n}: user folder of a named user")
    return found


class IdentityFixturePolicyTests(unittest.TestCase):
    def test_fixtures_name_only_reserved_identities(self) -> None:
        found = _findings()
        self.assertFalse(found, "replace these with a reserved name (demo@example.com, example.slack.com, /Users/demo):\n" + "\n".join(found))

    def test_the_patterns_catch_the_shapes_they_exist_for(self) -> None:
        # assembled at run time, so this file holds no such literal itself
        person = "pat" + "@" + "corp" + ".com"
        self.assertTrue(EMAIL.search(person) and not RESERVED_DOMAIN.search("corp.com"))
        self.assertTrue(EMAIL.search("Pat" + "@" + "Corp" + ".Info"), "TLDs match in any case")
        self.assertTrue(RESERVED_DOMAIN.search("example.com") and RESERVED_DOMAIN.search("host.example"))
        self.assertIsNone(EMAIL.search("@pytest.mark.parametrize"))
        self.assertIsNone(EMAIL.search("fn" + "@" + "functools.cache"))
        self.assertEqual(TENANT_HOST.search("https://" + "acme-corp" + ".slack.com/archives/C1").group(1), "acme-corp")
        self.assertEqual(TENANT_HOST.search("https://" + "Acme-Corp" + ".Slack.com/").group(1), "Acme-Corp")
        self.assertEqual(TENANT_PATH.search("https://linear.app/" + "acme-corp" + "/issue/X-1").group(1), "acme-corp")
        self.assertEqual(TENANT_PATH.search("https://www.notion.so/" + "acme-corp" + "/Plan-0f1e").group(1), "acme-corp")
        self.assertIsNone(TENANT_PATH.search("https://www.notion.so/Release-Notes-0f1e2d3c"))
        for path in ("/Users/" + "pat" + "/work", "/home/" + "pat" + "/work", "C:\\Users\\" + "pat" + "\\work", "/Users/Jane " + "Smith" + "/work"):
            with self.subTest(path=path):
                self.assertTrue(_names_a_user(USER_DIR.search(path).group(1)))
        for path in ("/home/.local/bin", "/home/../etc", "/home/1100/x", "/Users/Demo/x", "/Users/demo@example.com/x", "C:\\Users\\Demo User\\npm", "/home/u -la"):
            with self.subTest(path=path):
                self.assertFalse(_names_a_user(USER_DIR.search(path).group(1)))


if __name__ == "__main__":
    unittest.main()

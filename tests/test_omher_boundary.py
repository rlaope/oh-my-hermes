"""omher's boundary (docs/OMHER-BOUNDARY.md) pinned against the code: the doc's sentences, nothing in
``src/`` reaching ``apps/omher``, and the bridge submitting a prompt from exactly one place, with the
main chat's id."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "OMHER-BOUNDARY.md"
BRIDGE = ROOT / "apps" / "omher" / "bridge" / "omher_bridge.py"
CONTEXT = ROOT / "CONTEXT.md"
DOCS_INDEX = ROOT / "docs" / "README.md"

RULES = (
    "omher never patches Hermes.",
    "omher never writes to Slack, Discord or any other elsewhere session.",
    "omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`;",
    "the bridge has exactly one `prompt.submit` call site and it takes the main chat's id.",
    "omher talks only to the person's own Hermes gateway on this machine, over loopback,",
    "omher makes no LLM or API call itself. Every model call is Hermes'.",
    "The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token",
    "The app starts the bridge as a child process and stops it when the app exits.",
    "The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.",
    "omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture",
    "Outside Hermes, omher reads only the usage records coding CLIs write about themselves",
    "it never reads their auth files or tokens, writes nothing there and sends nothing anywhere.",
    "Accounts (Settings › Accounts) are the one exception to rules 4, 10 and 11.",
    "a local CLIProxyAPI is only counted by its auth file names.",
    "The app runs only the CLIs' own status and sign-in commands, as fixed argv (`claude auth status --json`, `claude auth login`,",
    "The browser sign-in happens inside the CLI: omher never asks for, accepts, reads, copies or shows a token or key.",
    "deletes only `~/.omher/accounts/<cli>/<id>/`. An account switch never stops a running session.",
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class DocPins(unittest.TestCase):
    def test_boundary_doc_states_each_rule(self) -> None:
        text = _flat(DOC.read_text(encoding="utf-8"))
        for sentence in RULES:
            self.assertIn(_flat(sentence), text)

    def test_boundary_is_between_six_and_twelve_numbered_rules(self) -> None:
        # 11 (CLI usage records) widened the cap from 10; 12 (accounts) fills it. A new surface still needs its
        # own numbered rule, and one more means revisiting this cap on purpose.
        rules = re.findall(r"^\d+\. ", DOC.read_text(encoding="utf-8"), re.M)
        self.assertTrue(6 <= len(rules) <= 12, len(rules))

    def test_glossary_and_docs_index_name_omher(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        self.assertIn("**omher**:", context)
        self.assertIn("**Elsewhere**:", context)
        self.assertIn("docs/OMHER-BOUNDARY.md", context)
        self.assertIn("(OMHER-BOUNDARY.md)", DOCS_INDEX.read_text(encoding="utf-8"))


class OmhNeverReachesOmher(unittest.TestCase):
    def test_no_file_under_src_imports_or_names_apps_omher(self) -> None:
        offenders = []
        for path in sorted((ROOT / "src").rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".js", ".ts"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "apps/omher" in text or "apps\\omher" in text:
                offenders.append(str(path.relative_to(ROOT)))
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    if any(n.split(".")[0] in {"omher", "omher_bridge"} for n in names):
                        offenders.append(f"{path.relative_to(ROOT)} imports {names}")
        self.assertEqual(offenders, [])


class BridgeSubmitsOnlyToTheMainChat(unittest.TestCase):
    def setUp(self) -> None:
        self.source = BRIDGE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_exactly_one_prompt_submit_call_site(self) -> None:
        self.assertEqual(self.source.count("prompt.submit"), 1, "prompt.submit named more than once")
        sites = [
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.Constant) and n.value == "prompt.submit"
        ]
        self.assertEqual(len(sites), 1)

    def test_that_call_takes_the_main_chat_id_variable(self) -> None:
        calls = []
        for fn in ast.walk(self.tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and any(
                    isinstance(a, ast.Constant) and a.value == "prompt.submit" for a in call.args
                ):
                    calls.append((fn, call))
        self.assertEqual(len(calls), 1)
        fn, call = calls[0]
        session = [k.value for k in call.keywords if k.arg == "session_id"]
        self.assertEqual(len(session), 1, "prompt.submit must pass session_id")
        self.assertIn(ast.unparse(session[0]), {"chat.runtime_id", "chat.session_id", "main_id", "runtime_id", "sid"})
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        self.assertNotIn("session_id", params, "the submitting function must not take a session id from its caller")

    def test_profile_writes_are_only_name_and_picture(self) -> None:
        """Every Hermes profile method the bridge names is a read, except set_asset (the avatar)."""
        names = {n.value for n in ast.walk(self.tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("profiles.")}
        self.assertTrue(names <= {"profiles.list", "profiles.set_asset"}, sorted(names))
        writes = {n.value for n in ast.walk(self.tree)
                  if isinstance(n, ast.Constant) and n.value in {"profiles.configure", "profiles.create", "profile.yaml"}}
        self.assertEqual(writes, {"profile.yaml"})  # named only by the display-name writer

    def test_bridge_has_no_http_or_llm_client(self) -> None:
        banned = {"requests", "httpx", "aiohttp", "urllib3", "openai", "anthropic", "urllib.request", "http.client"}
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(sorted(i for i in imported if i in banned or i.split(".")[0] in banned), [])


class AccountsNeverCarryAToken(unittest.TestCase):
    """Rule 12: fake CLI homes, omher account folders and CLIProxyAPI auth files full of token-like keys; no accounts
    payload the bridge returns may name one, and the app runs only the CLIs' own fixed status / sign-in argv."""

    TOKEN_KEYS = ("access_token", "refresh_token", "id_token", "api_key", "OPENAI_API_KEY", "tokens", "primaryApiKey")
    ACCOUNTS_RS = ROOT / "apps" / "omher" / "src-tauri" / "src" / "accounts.rs"
    LIB_RS = ROOT / "apps" / "omher" / "src-tauri" / "src" / "lib.rs"

    def test_fuzzed_auth_files_never_reach_an_accounts_payload(self) -> None:
        import importlib.util
        import json
        import random
        import sys
        import tempfile

        spec = importlib.util.spec_from_file_location("omher_bridge_boundary", BRIDGE)
        ob = importlib.util.module_from_spec(spec)
        sys.modules["omher_bridge_boundary"] = ob
        spec.loader.exec_module(ob)
        rnd = random.Random(12)
        secret = "sk-SECRET-boundary"
        for round_ in range(25):
            with tempfile.TemporaryDirectory() as d:
                home = Path(d)
                cpa = home / ".cli-proxy-api"
                cpa.mkdir()
                (cpa / "config.yaml").write_text('server:\n  port: 8317\nmanagement:\n  secret-key: "k"\n', encoding="utf-8")
                for i in range(rnd.randint(1, 5)):
                    body = {"email": rnd.choice([f"a{i}@example.com", {"access_token": secret}])}
                    body.update({k: secret for k in rnd.sample(self.TOKEN_KEYS, rnd.randint(1, len(self.TOKEN_KEYS)))})
                    (cpa / f"claude-a{i}@example.com.json").write_text(json.dumps(body), encoding="utf-8")
                # the CLIs' own homes on this computer
                (home / ".codex").mkdir()
                (home / ".codex" / "auth.json").write_text(json.dumps(
                    {"OPENAI_API_KEY": secret, "auth_mode": rnd.choice(["chatgpt", secret, {"id_token": secret}]),
                     "tokens": {k: secret for k in self.TOKEN_KEYS}}), encoding="utf-8")
                (home / ".claude.json").write_text(json.dumps({"oauthAccount": rnd.choice(
                    [{"emailAddress": "owner@example.com"}, {"emailAddress": {"refresh_token": secret}}, secret]),
                    "primaryApiKey": secret}), encoding="utf-8")
                for rel in (".pi/agent/auth.json", ".omp/agent/agent.db"):
                    (home / rel).parent.mkdir(parents=True)
                    (home / rel).write_text(json.dumps({k: secret for k in self.TOKEN_KEYS}), encoding="utf-8")
                for cli in ob.ACCOUNT_CLIS:
                    folder = home / ".omher" / "accounts" / cli / f"acct-{round_}"
                    folder.mkdir(parents=True)
                    (folder / "account.json").write_text(json.dumps(
                        {"label": rnd.choice(["Work", {"access_token": secret}, 3]), "api_key": secret}), encoding="utf-8")
                    (folder / "auth.json").write_text(json.dumps({k: secret for k in self.TOKEN_KEYS}), encoding="utf-8")
                    (folder / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "w@example.com"},
                                                                     "primaryApiKey": secret}), encoding="utf-8")
                (home / ".omher" / "accounts" / "labels.json").write_text(
                    json.dumps({"claude": {"id_token": secret}, "codex": secret[:3]}), encoding="utf-8")
                for which in (lambda c: f"/bin/{c}", lambda c: None):
                    text = json.dumps(ob.read_accounts(home, now=1.0, which=which))
                    for needle in self.TOKEN_KEYS + (secret, "SECRET"):
                        self.assertNotIn(needle, text)

    def test_the_app_runs_only_the_fixed_status_and_sign_in_argv(self) -> None:
        src = self.ACCOUNTS_RS.read_text(encoding="utf-8")
        prod = src[: src.index("#[cfg(test)]")]
        fixed = prod[prod.index("pub fn fixed_args"):]
        fixed = fixed[: fixed.index("\n}\n")]
        argv = re.findall(r'\("(\w+)", Step::(\w+)\) => Some\(&\[([^\]]*)\]\)', fixed)
        self.assertEqual(
            [(cli, step, [a.strip().strip('"') for a in args.split(",")]) for cli, step, args in argv],
            [("claude", "Status", ["auth", "status", "--json"]), ("claude", "Login", ["auth", "login"]),
             ("codex", "Help", ["--help"]), ("codex", "Status", ["login", "status"]), ("codex", "Login", ["login"])])
        self.assertIn("_ => None", fixed)
        # every spawn goes through `command(program, args, …)`, whose args come from `fixed_args` only
        self.assertEqual(prod.count("Command::new("), 2)  # the CLI itself, or cmd.exe /c for a Windows npm shim
        # the second argument of every `run_to_end(…)` / `command(…)` call is a `fixed_args` result
        calls = re.findall(r"\b(?:run_to_end|command)\(&?program, (\w+)", prod)
        self.assertEqual(len(calls), 5, calls)
        self.assertEqual(set(calls), {"args", "help_args"})
        self.assertNotIn(".arg(", prod.replace('c.arg("/c").arg(program)', ""))
        # the page names a CLI and an account id; no Tauri command takes a program or an argument
        lib = self.LIB_RS.read_text(encoding="utf-8")
        for cmd in ("account_status", "account_login_start", "account_login_cancel", "account_clis", "account_env"):
            sig = lib[lib.index(f"async fn {cmd}("):]
            sig = sig[: sig.index(")")]
            self.assertNotRegex(sig, r"\b(argv|args|program|command|path)\b", cmd)
        self.assertNotIn("keyring", lib + src)
        self.assertNotIn("cpa_send", lib)

    def test_rust_spawns_only_in_bridge_and_accounts(self) -> None:
        spawns = {}
        for path in sorted((ROOT / "apps" / "omher" / "src-tauri" / "src").glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            prod = text[: text.index("#[cfg(test)]")] if "#[cfg(test)]" in text else text
            n = prod.count("Command::new(")
            if n:
                spawns[path.name] = n
        # bridge.rs starts the bridge with Hermes' Python; accounts.rs runs the CLIs' fixed status / sign-in argv.
        self.assertEqual(spawns, {"bridge.rs": 1, "accounts.rs": 2})


if __name__ == "__main__":
    unittest.main()

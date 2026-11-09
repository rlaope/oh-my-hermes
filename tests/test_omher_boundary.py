"""omher's boundary (docs/OMHER-BOUNDARY.md) pinned against the code: the doc's sentences, nothing in
``src/`` reaching ``apps/omher``, the bridge submitting a prompt from exactly one place, with the
main chat's id, and SESSIONS starting only the five allow-listed agent programs."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "OMHER-BOUNDARY.md"
BRIDGE = ROOT / "apps" / "omher" / "bridge" / "omher_bridge.py"
SHELL = ROOT / "apps" / "omher" / "src-tauri" / "src"
UI_AGENTS = ROOT / "apps" / "omher" / "src" / "sessions" / "agents.ts"
SESSION_AGENTS = ("claude", "codex", "omh", "pi", "omp", "grok")
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
    "omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a"
    " fixed allow-list: `claude`, `codex`, `omh`, `pi`, `omp`, `grok`, with no arguments,",
    "The UI sends an agent id, never a command line or arguments; the shell refuses any other id.",
    "The process is stopped when its session is closed and when the app exits.",
    "omher runs one installer, and only when the person presses Install on the first-run screen that appears because Hermes is missing:",
    "The command is fixed in the shell; nothing from the page reaches it.",
)
SETUP_RS = ROOT / "apps" / "omher" / "src-tauri" / "src" / "setup.rs"
SHELL_SRC = ROOT / "apps" / "omher" / "src-tauri" / "src"
# The shell's fixed run: the documented one-liner, downloaded to a temp file first so a failed download
# is a failed install (`curl … | sh` exits 0 when curl fails), and on Windows ending with the
# installer's exit status (a script block never reaches install.ps1's own `exit`).
UNIX_RUN = (
    "f=$(mktemp) && trap 'rm -f \"$f\"' EXIT && curl -fsSL -o \"$f\" "
    "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh && sh \"$f\" omher@beta"
)
WINDOWS_RUN = (
    "$ErrorActionPreference = 'Stop'; try { & ([scriptblock]::Create((irm "
    "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta } "
    "catch { $_.Exception.Message; exit 1 }; exit $LASTEXITCODE"
)


def _rust_strings(source: str) -> list[str]:
    """The string literals in a piece of Rust source, with `\\"` unescaped."""
    return [m.replace('\\"', '"') for m in re.findall(r'"((?:[^"\\]|\\.)*)"', source)]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class DocPins(unittest.TestCase):
    def test_boundary_doc_states_each_rule(self) -> None:
        text = _flat(DOC.read_text(encoding="utf-8"))
        for sentence in RULES:
            self.assertIn(_flat(sentence), text)

    def test_boundary_is_between_six_and_twelve_numbered_rules(self) -> None:
        # 12: rule 10 (the bridge's read-only git), rule 11 (SESSIONS' allow-listed agents) and rule 12
        # (the one installer) each widened the boundary on purpose; the rules stay numbered 1..n with no gap
        # or repeat.
        text = DOC.read_text(encoding="utf-8")
        rules = re.findall(r"^(\d+)\. ", text, re.M)
        self.assertTrue(6 <= len(rules) <= 12, len(rules))
        self.assertEqual([int(n) for n in rules], list(range(1, len(rules) + 1)))

    def test_glossary_and_docs_index_name_omher(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        self.assertIn("**omher**:", context)
        self.assertIn("**Elsewhere**:", context)
        self.assertIn("docs/OMHER-BOUNDARY.md", context)
        self.assertIn("(OMHER-BOUNDARY.md)", DOCS_INDEX.read_text(encoding="utf-8"))


class TheOneInstaller(unittest.TestCase):
    """Rule 12: the shell spawns the bridge and, on Install, one fixed installer; nothing else."""

    def test_the_installer_is_the_omher_beta_one_liner_without_the_app(self) -> None:
        setup = SETUP_RS.read_text(encoding="utf-8")
        # The definitions themselves, not the Rust tests that repeat them.
        unix = setup[setup.index("const UNIX: InstallCommand"):]
        unix = unix[: unix.index("\n};")]
        self.assertEqual(_rust_strings(unix), ["/bin/sh", "-c", UNIX_RUN])
        self.assertNotIn("|", UNIX_RUN)
        windows = setup[setup.index("const WINDOWS: InstallCommand"):]
        windows = windows[: windows.index("\n};")]
        self.assertEqual(
            _rust_strings(windows),
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", WINDOWS_RUN],
        )
        env = setup[setup.index("const ENV: &[(&str, &str)]"):]
        self.assertEqual(re.findall(r'"([^"]*)"', env[: env.index(";")]), ["OMH_WITH_DESKTOP", "0", "NO_COLOR", "1"])
        # The doc names the same commands.
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn(f"`{UNIX_RUN}`", doc)
        self.assertIn(f"`{WINDOWS_RUN}`", doc)

    def test_only_two_places_in_the_shell_start_a_process(self) -> None:
        spawns = {}
        for path in sorted(SHELL_SRC.glob("*.rs")):
            n = path.read_text(encoding="utf-8").count("Command::new(")
            if n:
                spawns[path.name] = n
        # bridge.rs starts the bridge with Hermes' Python; setup.rs runs the fixed installer. Sessions (rule 11)
        # start their allow-listed agent through the PTY's `spawn_command`, not `Command::new`.
        self.assertEqual(spawns, {"bridge.rs": 1, "setup.rs": 1})

    def test_the_install_command_takes_nothing_from_the_page(self) -> None:
        lib = (SHELL_SRC / "lib.rs").read_text(encoding="utf-8")
        sig = lib[lib.index("async fn install_engine("):]
        sig = sig[: sig.index(") ->")]
        self.assertNotIn("String", sig)
        self.assertNotIn("&str", sig)
        self.assertIn("Channel<InstallEvent>", sig)


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


class SessionsStartOnlyAllowListedAgents(unittest.TestCase):
    """Rule 11: the Rust shell's allow-list, the commands that start a program, and the UI's list."""

    def setUp(self) -> None:
        self.sessions = (SHELL / "sessions.rs").read_text(encoding="utf-8")
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        self.prod = self.sessions.split("#[cfg(test)]\nmod tests", 1)[0]

    def test_rust_allow_list_is_the_five_agents_and_each_id_is_its_program(self) -> None:
        block = re.search(r"pub const AGENTS: \[Agent; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(block)
        rows = re.findall(r'Agent \{ id: "([^"]+)", program: "([^"]+)"', block.group(2))
        self.assertEqual(int(block.group(1)), len(SESSION_AGENTS))
        self.assertEqual([r[0] for r in rows], list(SESSION_AGENTS))
        self.assertEqual([r[1] for r in rows], list(SESSION_AGENTS))

    def test_ui_list_matches_the_rust_allow_list(self) -> None:
        ui = UI_AGENTS.read_text(encoding="utf-8")
        self.assertEqual(tuple(re.findall(r'\{ id: "([^"]+)", program: "\1"', ui)), SESSION_AGENTS)

    def test_only_the_bridge_and_the_session_pty_start_processes(self) -> None:
        """`Command::new` only in bridge.rs (Hermes' Python) and setup.rs (the one fixed installer, rule 12);
        `spawn_command` only in sessions.rs."""
        for path in sorted(SHELL.glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            prod = text.split("#[cfg(test)]", 1)[0]
            if path.name not in ("bridge.rs", "setup.rs"):
                self.assertNotIn("Command::new", prod, path.name)
            if path.name != "sessions.rs":
                self.assertNotIn("spawn_command", text, path.name)
        self.assertEqual(self.prod.count("spawn_command("), 1)

    def test_session_start_takes_an_agent_id_and_no_command_or_args(self) -> None:
        sig = re.search(r"async fn session_start\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        params = {p.split(":")[0].strip() for p in sig.group(1).split(",") if ":" in p}
        self.assertEqual(params, {"shell", "agent", "cwd", "cols", "rows", "on_data", "on_exit"})
        body = self.lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn("start_agent(&agent", body)
        self.assertNotIn(".spawn(", body)

    def test_start_agent_resolves_argv_from_the_allow_list_only(self) -> None:
        start = self.prod.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("launch_for(agent_id)?", start)
        launch = self.prod.split("pub fn launch_for", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("agent(id).ok_or_else", launch)
        # the only arguments ever added are cmd.exe's own for a Windows .cmd shim
        argv = self.prod.split("pub fn argv_for", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(sorted(set(re.findall(r'"([^"]*)"\.into\(\)', argv))), ["/c", "cmd.exe"])
        # the raw spawn is crate-internal, so no Tauri command can call it with its own argv
        self.assertIn("pub(crate) fn spawn<F>", self.prod)

    def test_sessions_stop_on_close_and_on_app_exit(self) -> None:
        self.assertRegex(self.lib, r"RunEvent::Exit[\s\S]*shell\.sessions\.close_all\(\)")
        self.assertIn("shell.sessions.close(id)", self.lib)


if __name__ == "__main__":
    unittest.main()

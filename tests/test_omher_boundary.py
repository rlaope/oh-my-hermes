"""omher's boundary (docs/OMHER-BOUNDARY.md) pinned against the code: the doc's sentences, nothing in
``src/`` reaching ``apps/omher``, the bridge submitting a prompt from exactly one place, with the
main chat's id or a folder chat's it created, and SESSIONS starting only the six allow-listed agent programs,
in a terminal with no arguments or as a chat with the fixed structured-mode arguments."""

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
SESSION_MODES = ("Chat", "Chat", "Hermes", "Chat", "Chat", "Terminal")
CLAUDE_CHAT_ARGS = ("-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                    "--include-partial-messages", "--permission-prompt-tool", "stdio")
CONTEXT = ROOT / "CONTEXT.md"
DOCS_INDEX = ROOT / "docs" / "README.md"

RULES = (
    "omher never patches Hermes.",
    "omher never writes to Slack, Discord or any other elsewhere session.",
    "omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`,",
    "and in folder chats the bridge created itself for an oh-my-hermes session (`folder.open`);",
    "the bridge has exactly one `prompt.submit` call site and it takes the main chat's id or such a folder chat's.",
    "omher talks only to the person's own Hermes gateway on this machine, over loopback,",
    "omher makes no LLM or API call itself. Every model call is Hermes'.",
    "The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token",
    "The app starts the bridge as a child process and stops it when the app exits.",
    "The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.",
    "omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture",
    "omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a"
    " fixed allow-list: `claude`, `codex`, `omh`, `pi`, `omp`, `grok`, with no arguments,",
    "A chat session starts the same program with its fixed structured-mode arguments from the allow-list",
    "(`claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages"
    " --permission-prompt-tool stdio`, `codex app-server`, `pi --mode rpc`, `omp --mode rpc`) on pipes;",
    "the only other argument is `--resume` with a Claude Code session id the shell checks is a UUID.",
    "The UI sends an agent id, never a command line or arguments; the shell refuses any other id.",
    "The process is stopped when its session is closed and when the app exits.",
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class DocPins(unittest.TestCase):
    def test_boundary_doc_states_each_rule(self) -> None:
        text = _flat(DOC.read_text(encoding="utf-8"))
        for sentence in RULES:
            self.assertIn(_flat(sentence), text)

    def test_boundary_is_between_six_and_ten_numbered_rules(self) -> None:
        rules = re.findall(r"^\d+\. ", DOC.read_text(encoding="utf-8"), re.M)
        self.assertTrue(6 <= len(rules) <= 10, len(rules))

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
        # and its caller takes that id from _target (the main chat, or a folder chat this bridge created)
        callers = [f for f in ast.walk(self.tree) if isinstance(f, ast.AsyncFunctionDef) and f.name == "op_chat_send"]
        self.assertEqual(len(callers), 1)
        self.assertIn("await self._target(conn, p)", ast.unparse(callers[0]))
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

    def test_folder_chats_come_only_from_session_create_with_a_folder(self) -> None:
        """A folder chat id is minted by the bridge (``folder.open`` → ``session.create`` with the picked cwd);
        ``_target`` resolves ``session`` only through ``conn.folders`` and never forwards a client id."""
        target = [f for f in ast.walk(self.tree) if isinstance(f, ast.AsyncFunctionDef) and f.name == "_target"]
        self.assertEqual(len(target), 1)
        fn = target[0]
        code = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]  # no docstring
        body = "\n".join(ast.unparse(n) for n in code)
        self.assertIn("conn.folders.get(fid)", body)
        self.assertIn("return (chat.runtime_id, chat)", body)
        self.assertNotIn("session_id", body)
        writes = [n for n in ast.walk(self.tree) if isinstance(n, ast.Subscript) and ast.unparse(n.value) == "conn.folders"
                  and isinstance(n.ctx, ast.Store)]
        self.assertEqual(len(writes), 1, "folder chats are registered in one place")
        opener = [f for f in ast.walk(self.tree) if isinstance(f, ast.AsyncFunctionDef) and f.name == "op_folder_open"][0]
        self.assertIn("'session.create'", ast.unparse(opener))
        self.assertIn("cwd=cwd", ast.unparse(opener))

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
    """Rule 10: the Rust shell's allow-list, the commands that start a program, and the UI's list."""

    def setUp(self) -> None:
        self.sessions = (SHELL / "sessions.rs").read_text(encoding="utf-8")
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        self.prod = self.sessions.split("#[cfg(test)]\nmod tests", 1)[0]
        self.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]

    def test_rust_allow_list_is_the_six_agents_and_each_id_is_its_program(self) -> None:
        block = re.search(r"pub const AGENTS: \[Agent; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(block)
        rows = re.findall(r'Agent \{ id: "([^"]+)", program: "([^"]+)", label: "[^"]+", mode: Mode::(\w+) \}', block.group(2))
        self.assertEqual(int(block.group(1)), len(SESSION_AGENTS))
        self.assertEqual([r[0] for r in rows], list(SESSION_AGENTS))
        self.assertEqual([r[1] for r in rows], list(SESSION_AGENTS))
        self.assertEqual(tuple(r[2] for r in rows), SESSION_MODES)

    def test_ui_list_matches_the_rust_allow_list(self) -> None:
        ui = UI_AGENTS.read_text(encoding="utf-8")
        rows = re.findall(r'\{ id: "([^"]+)", program: "\1", label: "[^"]+", mode: "(\w+)" \}', ui)
        self.assertEqual(tuple(r[0] for r in rows), SESSION_AGENTS)
        self.assertEqual(tuple(r[1].capitalize() for r in rows), SESSION_MODES)

    def test_chat_arguments_are_fixed_in_the_allow_list(self) -> None:
        """The structured-mode argv per agent is part of the allow-list (rule 10) and nothing else adds one."""
        claude = re.search(r"pub const CLAUDE_CHAT_ARGS: \[&str; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(claude)
        self.assertEqual(re.findall(r'"([^"]*)"', claude.group(2)), list(CLAUDE_CHAT_ARGS))
        chat = self.prod.split("pub fn chat_args", 1)[1].split("\n}\n", 1)[0]
        arms = re.findall(r'^\s+(.+?) => (&.+?\[\.\.\]),?$', chat, re.M)
        self.assertEqual(arms, [('"claude"', "&CLAUDE_CHAT_ARGS[..]"), ('"codex"', '&["app-server"][..]'),
                                ('"pi" | "omp"', '&["--mode", "rpc"][..]')])
        resume = self.prod.split("pub fn resume_args", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('if id != "claude"', resume)
        self.assertIn("if !is_uuid(session)", resume)
        self.assertEqual(sorted(set(re.findall(r'"(--[a-z-]+)"\.into\(\)', resume))), ["--resume"])
        # the chat spawner takes its argv only from launch_for + chat_args (+ resume_args) and is crate-internal
        start = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        for needle in ("launch_for(agent_id)?", "chat_args(agent_id)", "resume_args(agent_id, r)?", "\n        if a.mode != Mode::Chat {\n            return Err("):
            self.assertIn(needle, start)
        self.assertIn("pub(crate) fn spawn<F>", self.chat)

    def test_chat_commands_take_an_agent_id_folder_and_resume_only(self) -> None:
        sig = re.search(r"async fn chat_start\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        params = {p.split(":")[0].strip() for p in sig.group(1).split(",") if ":" in p}
        self.assertEqual(params, {"shell", "agent", "cwd", "resume", "on_event"})
        body = self.lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn("chats.start_agent(&agent", body)
        self.assertNotIn(".spawn(", body)
        # what the person does in a chat is one of five inputs, never a command line
        inputs = re.search(r"pub enum Input \{(.*?)\n\}", self.chat, re.S).group(1)
        self.assertEqual(re.findall(r"^\s+(\w+)", inputs, re.M), ["Send", "Interrupt", "Approve", "Clarify", "Model"])

    def test_only_the_bridge_the_session_pty_and_the_chat_spawner_start_processes(self) -> None:
        """`Command::new` only in bridge.rs (Hermes' Python) and once in agent_chat.rs (the chat spawner);
        `spawn_command` only in sessions.rs."""
        for path in sorted(SHELL.glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            prod = text.split("#[cfg(test)]", 1)[0]
            if path.name not in ("bridge.rs", "agent_chat.rs"):
                self.assertNotIn("Command::new", prod, path.name)
            if path.name != "sessions.rs":
                self.assertNotIn("spawn_command", text, path.name)
        self.assertEqual(self.prod.count("spawn_command("), 1)
        self.assertEqual(self.chat.count("Command::new("), 1)

    def test_session_start_takes_an_agent_id_and_no_command_or_args(self) -> None:
        sig = re.search(r"async fn session_start\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        params = {p.split(":")[0].strip() for p in sig.group(1).split(",") if ":" in p}
        # `resume` is the only extra: a Claude Code session id that resume_args checks is a UUID
        self.assertEqual(params, {"shell", "agent", "cwd", "resume", "cols", "rows", "on_data", "on_exit"})
        body = self.lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn("start_agent(&agent, std::path::Path::new(&cwd), resume.as_deref()", body)
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
        self.assertRegex(self.lib, r"RunEvent::Exit[\s\S]*shell\.chats\.close_all\(\)")
        self.assertIn("shell.sessions.close(id)", self.lib)
        self.assertIn("shell.chats.close(id)", self.lib)


if __name__ == "__main__":
    unittest.main()

"""omher's boundary (docs/OMHER-BOUNDARY.md) pinned against the code: the doc's sentences, nothing in
``src/`` reaching ``apps/omher``, the bridge submitting a prompt from exactly one place, with the
main chat's id or a folder chat's it created, and SESSIONS starting only the eight allow-listed agent programs,
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
SESSION_AGENTS = ("claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode")
SESSION_MODES = ("Chat", "Chat", "Chat", "Chat", "Hermes", "Chat", "Chat", "Terminal", "Chat")
CLAUDE_CHAT_ARGS = ("-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                    "--include-partial-messages", "--permission-prompt-tool", "stdio", "--replay-user-messages")
CONTEXT = ROOT / "CONTEXT.md"
DOCS_INDEX = ROOT / "docs" / "README.md"

RULES = (
    "omher never patches Hermes.",
    "omher never writes to Slack, Discord or any other elsewhere session.",
    "omher may pass a thread reference to the bot; the bot posts with its own tools and approvals.",
    "omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`,",
    "and in folder chats the bridge created itself for an oh-my-hermes session (`folder.open`);",
    "the bridge has exactly one `prompt.submit` call site and it takes the main chat's id or such a folder chat's.",
    "Files the person attaches go to that same chat only, as bytes through Hermes' own `image.attach_bytes`,",
    "the bridge never opens the person's files.",
    "omher talks only to the person's own Hermes gateway on this machine, over loopback,",
    "omher makes no LLM or API call itself. Every model call is Hermes'.",
    "The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token",
    "The app starts the bridge as a child process and stops it when the app exits.",
    "The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.",
    "omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture",
    "Outside Hermes, omher reads only the usage records coding CLIs write about themselves",
    "it never reads their auth files or tokens, writes nothing there and sends nothing anywhere.",
    "Accounts (Settings › Accounts) are the one exception to rules 4, 10 and 17.",
    "a local CLIProxyAPI's Claude logins are listed, read-only, from its auth file names alone",
    "omher never opens those files, never calls CLIProxyAPI or its management API, and never starts a session with, switches to or removes such a login.",
    "The Claude meter also lists the Claude logins of rule 18 by name, each with only its own record;",
    "The app runs only the CLIs' own status and sign-in commands, as fixed argv (`claude auth status --json`, `claude auth login`,",
    "The browser sign-in happens inside the CLI: omher never asks for, accepts, reads, copies or shows a token or key.",
    "deletes only `~/.omher/accounts/<cli>/<id>/`. An account switch never stops a running session.",
    "Besides rule 21's one GitHub CLI read, the only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`,",
    "omher never commits, checks out, pushes or edits a repository.",
    "and OmO's subagent records (`~/.omo/agent/projects/*/senpi-task/tasks/st_*.json`, never the subagents' own"
    " transcripts under `children/`).",
    "omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a"
    " fixed allow-list: `claude`, `codex`, `omo`, `dsh`, `omh`, `pi`, `omp`, `grok`, `opencode`, with no arguments,",
    "A chat session starts the same program with its fixed structured-mode arguments from the allow-list",
    "(`claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages"
    " --permission-prompt-tool stdio --replay-user-messages`, `codex app-server`, `omo --mode rpc`, `pi --mode rpc`, `omp --mode rpc`, `opencode acp`) on pipes;",
    "An Agent Client Protocol agent (`opencode acp`) gets no such argument: omher sends the conversation id it reported",
    "and tells the agent at `initialize` that omher offers no file reading or writing and no terminal,",
    "OpenCode also gets one environment variable, `OPENCODE_CONFIG_CONTENT`, holding ask rules for its `bash` and `edit` tools",
    "right before the chat, the shell runs `opencode agent list` (that one fixed argument, in the same folder, with the same environment, on pipes, nothing on stdin, at most 30 seconds)",
    "so allow becomes ask, ask stays ask and deny stays deny, for blanket and pattern rules alike;",
    "OpenCode is not started and the chat says so in one sentence; omher reads and writes none of OpenCode's own files,",
    "never its always-allow.",
    "the only other argument continues a conversation, with an id the shell checks is a UUID:",
    "`--resume <id>` for Claude Code, `--session <id>` for OmO.",
    "DSH is DeepSeek Harness only:",
    "never another `dsh` on PATH.",
    "A DSH chat runs one `dsh --profile headless --patch <home>/.omher/dsh/headless.patch.yml --json -` per message on pipes,",
    "and continues with `--session-id session-<uuid>`, an id the harness reported (when the harness no longer has that session, the same message is sent once more without it, as a new session, and the chat says so); it has no terminal view.",
    "omher never reads a key and never changes `~/.dsh`.",
    "The UI sends an agent id, never a command line or arguments; the shell refuses any other id.",
    "The process is stopped when its session is closed and when the app exits.",
    "omher runs one installer, and only when the person presses Install on the first-run screen that appears because Hermes is missing,",
    "or, for a person who has Hermes but not oh-my-hermes (no `omh` found), when they press Install in the popover of the sidebar's \"!\""
    " (oh-my-hermes is not installed; the SESSIONS `+` menu's \"Add oh-my-hermes\" line only opens that popover):",
    "so a person who has Hermes but not `omh` gets the same row named Hermes, with no terminal view, and omher never starts `hermes` or any"
    " other program for it.",
    "The command is fixed in the shell; nothing from the page reaches it.",
    "omher shows a file from disk only when the bot named it in a `MEDIA:` line of its own answer,",
    "the desktop app opens only a file the bridge just served this way.",
    "omher reads OMH dag run records (`<omh home>/runtime/dag/*/*.json`) and their handoff files only for runs whose\n    session is in the bot's own `state.db`",
    "never settles, retries or cancels a run; the Plans tab (these runs, listed as plans) is read-only.",
    "For the Plans graph omher also reads, never writes, Hermes' delegate_task folders",
    "and uses only the records written by the bot's own sessions.",
    "The bridge passes on the `subagent.*` events Hermes sends on the bot's own chat",
    "it never passes a subagent's thinking text, and omher never assigns, steers or stops a subagent.",
    "the CLI agents' own session files on this machine",
    "never a prompt or a message body, skips symlinked folders and files, and never starts, resumes or stops a CLI session.",
    "For a SESSIONS row omher reads the same files for one more thing, the title of the conversation that row runs",
    "A `claude`, `codex` or `grok` session gets one more environment variable, the home folder of the account",
    "omher's own `active.json`; \"This computer\" adds nothing, and no login file or token is read for it.",
    "A chat session of the same agent gets the same single variable from the same lookup, and nothing else.",
    "a Claude Code, Codex, OmO or DSH chat that was running starts again by itself in the same folder, continuing its own conversation,",
    "and any other session that was running comes back paused until the person presses Resume; nothing starts twice.",
    "A session started again this way may name the account it ran with, which the shell uses only while that account's folder still exists,",
    "For the composer's `./` skill picker omher reads, never writes, the bot's own skill files",
    "then the folders the profile's `config.yaml` names in `skills.external_dirs`, where oh-my-hermes registers its skills",
    "pressing it puts the model-setup skill's `/command` and one sentence into the composer, and nothing is sent;",
    "omher restarts nothing and runs nothing for it.",
    "It follows the profile's symlinked skill folders and files as Hermes' own skill scan does, reads each real folder once",
    "reads only the first 8 KB of each `SKILL.md` and keeps only the `name` and `description` of its frontmatter,",
    "A picked skill reaches the bot as `/name` at the start of the text the person sends, through the same `chat.send`;",
    "omher updates itself only through Tauri's updater, and only from one fixed address:",
    "It installs a build only when its signature matches the public key pinned in `tauri.conf.json`,"
    " and only after the person presses the update button and confirms the restart; then it restarts omher.",
    "For the Plans graph the bridge asks the person's own GitHub CLI for the state of a pull request a plan node names",
    "with one fixed read: `gh pr view <number> -R <owner>/<repo> --json state,isDraft,mergedAt,url`.",
    "This is the one exception to rules 5 and 10: the request is `gh`'s own, under its own login; omher passes no token,"
    " reads none and changes nothing on GitHub.",
    "An answer is kept 5 minutes, a call is stopped after 3 seconds,",
    "The app opens such a pull request's page in the browser only when the person clicks its number.",
    "omher draws a link in a message as a link chip from its address alone: it fetches nothing from a link"
    " (no preview, title or oEmbed request).",
    "of the bot's own messenger sessions in its `state.db` (`links.places`), never a message.",
    "A link opens only when the person clicks it, through the system opener:",
    "Settings › Providers \"Add key\" may open the person's own system terminal running exactly"
    " `hermes auth add <provider> --type api-key`, and nothing else, only when the person picks a provider.",
    "The provider id is checked against `^[a-z0-9][a-z0-9_-]{0,40}$` and passed as one argument;",
    "Hermes asks for the key in that terminal and stores it itself: omher never sees the key.",
    "never runs this in its own pseudo-terminal, so no keystroke passes through omher.",
    "The two exceptions are a bot's automations and plugins, which omher changes only by asking that bot's own gateway"
    " (rules 24 and 25); omher writes no file of either itself.",
    "omher changes a bot's automations only through Hermes' own `cron.manage` on that bot's gateway (`add`, `pause`,"
    " `resume`, `remove`), only when the person presses a button.",
    "It reads `cron/jobs.json` and never writes it;",
    "Running or editing an automation is a chat message to the bot:",
    "omher never imitates an edit by removing and adding a job.",
    "omher changes a bot's plugins only through Hermes' own `plugins.manage` on that bot's gateway (`list`, `toggle`,"
    " `inspect`, `install` from the curated catalog by name, `update`, `remove`), only when the person presses a button,",
    "`install` carries the pin `inspect` returned.",
    "never installs from a Git URL or `owner/repo`, and never edits config itself.",
    "A refused install is read from Hermes' reason code (`exists`, `source_moved`), never from its message.",
    "Files the person attaches in a SESSIONS chat (paste, the + menu, a drop on the chat) or drops on a session's terminal"
    " are saved by the desktop app under omher's own folder, one folder per session:",
    "`~/.omher/session-files/<session id>/<n>-<name>`, never in the project folder and never in a Hermes profile;",
    "The shell reads back only plain files in that folder (no links, no other path), and the page never names a file outside it.",
    "A session's folder is removed when the session is closed, and the folders of sessions that are no longer in the list"
    " are removed when omher starts.",
    "An oh-my-hermes session takes no files: rule 3 keeps files to a bot's main chat.",
)
TAURI_CONF = ROOT / "apps" / "omher" / "src-tauri" / "tauri.conf.json"
CAPABILITIES = ROOT / "apps" / "omher" / "src-tauri" / "capabilities" / "default.json"
UI_SRC = ROOT / "apps" / "omher" / "src"
UPDATE_ENDPOINT = "https://github.com/rlaope/oh-my-hermes/releases/download/omher-latest/latest.json"
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


class SubagentEvents(unittest.TestCase):
    def test_the_bridge_calls_no_subagent_or_delegation_control_method(self) -> None:
        # Hermes' gateway can steer, pause, interrupt and kill a delegation; omher only shows what Hermes sends
        src = (ROOT / "apps" / "omher" / "bridge" / "omher_bridge.py").read_text(encoding="utf-8")
        calls = set(re.findall(r"_call\(\s*conn,\s*\"([a-z._]+)\"", src))
        self.assertTrue(calls, "no gateway call found: the pattern no longer matches the bridge")
        self.assertEqual({c for c in calls if c.startswith(("subagent.", "delegation."))}, set())
        self.assertNotRegex(src, r"\"(subagent|delegation)\.(steer|interrupt|kill|pause|resume|cancel)\"")


    def test_omo_subagents_are_read_from_their_task_records_only(self) -> None:
        # O15: Plans reads OmO's own record of each subagent (one JSON per task), never a transcript under children/
        src = BRIDGE.read_text(encoding="utf-8")
        body = src[src.index("    def omo(self"):src.index("    # ---- ops")]
        self.assertIn('"senpi-task" / "tasks"', body)
        self.assertIn("_OMO_TASK.match(e.name)", body)
        self.assertNotIn("children", body.split('"""', 2)[2])
        self.assertRegex(src, r'_OMO_TASK = re\.compile\(r"\^st_')

    def test_session_adapters_send_no_subagent_control(self) -> None:
        # a session's subagents are only shown: no adapter writes a message that assigns, steers or stops one
        rust = (SHELL / "agent_chat.rs").read_text(encoding="utf-8")
        code = rust[: rust.index("#[cfg(test)]\nmod tests")]
        for word in ("task_send", "send_input", "SendMessage", "subagent/stop", "agent/stop", "thread/interrupt", "collab"):
            self.assertNotIn(f'"{word}', code, word)


class DocPins(unittest.TestCase):
    def test_boundary_doc_states_each_rule(self) -> None:
        text = _flat(DOC.read_text(encoding="utf-8"))
        for sentence in RULES:
            self.assertIn(_flat(sentence), text)

    def test_boundary_is_between_six_and_twenty_six_numbered_rules(self) -> None:
        # 22: rule 10 (the bridge's read-only git, side panel), rule 11 (SESSIONS' allow-listed agents),
        # rule 12 (the one installer), rule 13 (media.read), rules 14-16 (Plans: dag records, delegation and
        # route reads, CLI agents' session files), rule 17 (CLI usage records), rule 18 (accounts), rule 19
        # (skills.list for the ./ picker), rule 20 (the signed self-update), rule 21 (a plan node's PR state
        # through the person's own `gh`), rule 22 (link chips: channel names read, web links opened on a
        # click), rule 23 (Providers "Add key": the system terminal runs `hermes auth add`, omher never sees
        # the key), rule 24 (Automations: a bot's jobs changed only through its own `cron.manage`) and rule 25
        # (Plugins: only through its own `plugins.manage`, catalog installs after an inspect) each widened the
        # boundary on purpose; 26: rule 26 (SESSIONS attachments saved under ~/.omher/session-files) did too; 27:
        # rule 27 (a session's mode, effort and branch read: only the agent's own switches, never a bypass) as well.
        # The rules stay numbered 1..n with no gap or repeat.
        rules = re.findall(r"^(\d+)\. ", DOC.read_text(encoding="utf-8"), re.M)
        self.assertTrue(6 <= len(rules) <= 27, len(rules))
        self.assertEqual([int(n) for n in rules], list(range(1, len(rules) + 1)))

    def test_glossary_and_docs_index_name_omher(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        self.assertIn("**omher**:", context)
        self.assertIn("**Elsewhere**:", context)
        self.assertIn("docs/OMHER-BOUNDARY.md", context)
        self.assertIn("(OMHER-BOUNDARY.md)", DOCS_INDEX.read_text(encoding="utf-8"))


class SignedSelfUpdateFromOneAddress(unittest.TestCase):
    """Rule 20: the updater reads one fixed endpoint, verifies against a pinned key, and is driven from one
    UI module after a click."""

    def test_the_updater_has_one_fixed_endpoint_and_a_pinned_key(self) -> None:
        import base64
        import json

        conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
        updater = conf["plugins"]["updater"]
        self.assertEqual(updater["endpoints"], [UPDATE_ENDPOINT])
        self.assertNotIn("dangerousInsecureTransportProtocol", updater)
        self.assertIn("minisign public key", base64.b64decode(updater["pubkey"]).decode("utf-8"))
        self.assertIs(conf["bundle"]["createUpdaterArtifacts"], True)
        self.assertIn(f"`{UPDATE_ENDPOINT}`", DOC.read_text(encoding="utf-8"))

    def test_capabilities_add_only_the_updater_and_restart(self) -> None:
        import json

        perms = json.loads(CAPABILITIES.read_text(encoding="utf-8"))["permissions"]
        self.assertEqual(perms, ["core:default", "notification:default", "dialog:allow-open",
                                 "updater:default", "process:allow-restart"])

    def test_only_the_sidebar_updater_module_imports_the_updater(self) -> None:
        users = sorted(
            p.relative_to(UI_SRC).as_posix() for p in UI_SRC.rglob("*.ts*")
            if re.search(r"@tauri-apps/plugin-(updater|process)", p.read_text(encoding="utf-8"))
        )
        self.assertEqual(users, ["sidebar/updater.ts"])
        button = (UI_SRC / "sidebar" / "UpdateButton.tsx").read_text(encoding="utf-8")
        # install runs only from the confirm's "Update and restart"; the button only opens the confirm, the timer
        # only checks
        self.assertEqual(button.count("update.install("), 1)
        self.assertEqual(button.count("void install("), 1)
        self.assertIn("onConfirm={() => {\n            setAsking(false);\n            void install(update);", button)
        self.assertIn("onClick={() => setAsking(true)}", button)


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

    def test_only_three_places_in_the_shell_start_a_process(self) -> None:
        spawns = {}
        for path in sorted(SHELL_SRC.glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            n = (text[: text.index("#[cfg(test)]")] if "#[cfg(test)]" in text else text).count("Command::new(")
            if n:
                spawns[path.name] = n
        # Production code only. bridge.rs starts the bridge with Hermes' Python; setup.rs runs the fixed
        # installer; agent_chat.rs starts a chat session's allow-listed agent (rule 11); accounts.rs runs the
        # CLIs' fixed status / sign-in argv (rule 18); hermes_auth.rs opens the system terminal with
        # `hermes auth add <id> --type api-key` (rule 23); dsh_chat.rs runs a DSH chat's message through DeepSeek
        # Harness's headless profile (rule 11). Terminal sessions start theirs through the PTY's
        # `spawn_command`, not `Command::new`.
        self.assertEqual(spawns, {"accounts.rs": 2, "agent_chat.rs": 1, "bridge.rs": 1, "dsh_chat.rs": 1, "hermes_auth.rs": 1, "setup.rs": 1})

    def test_the_install_command_takes_nothing_from_the_page(self) -> None:
        lib = (SHELL_SRC / "lib.rs").read_text(encoding="utf-8")
        sig = lib[lib.index("async fn install_engine("):]
        sig = sig[: sig.index(") ->")]
        self.assertNotIn("String", sig)
        self.assertNotIn("&str", sig)
        self.assertIn("Channel<InstallEvent>", sig)

    def test_the_offer_to_add_oh_my_hermes_runs_the_same_installer(self) -> None:
        """The sidebar's "!" popover (the one surface; the + menu's line only opens it) reaches the installer only
        through the gate's `install_engine` call (one place in the UI), and the shell has no second install command."""
        callers = sorted(
            p.relative_to(UI_SRC).as_posix() for p in UI_SRC.rglob("*.ts*")
            if not p.name.endswith(".test.ts") and re.search(r"[\"']install_engine[\"']", p.read_text(encoding="utf-8"))
        )
        self.assertEqual(callers, ["app/BridgeGate.tsx"])
        add = (UI_SRC / "sessions" / "addOmh.ts").read_text(encoding="utf-8")
        self.assertIn("gateShell", add)
        self.assertNotIn("invoke", add)
        # one installer surface: only the "!" popover runs it; the + menu's line opens the popover
        runners = sorted(
            p.relative_to(UI_SRC).as_posix() for p in UI_SRC.rglob("*.tsx")
            if re.search(r"\.run\(\)", p.read_text(encoding="utf-8")) and "getAddOmh" in p.read_text(encoding="utf-8")
        )
        self.assertEqual(runners, ["sidebar/OmhNotice.tsx"])
        lib = (SHELL_SRC / "lib.rs").read_text(encoding="utf-8")
        self.assertEqual(lib.count("setup::install_command("), 1)
        self.assertEqual(re.findall(r"^\s+(install_\w+),$", lib, re.M), ["install_engine", "install_engine_command"])


class LinkChipsFetchNothing(unittest.TestCase):
    """Rule 22: a chip is drawn from the address alone; a click opens it through the system opener."""

    CHIP_FILES = ("chat/parts/LinkChip.tsx", "chat/parts/linkKinds.ts", "ui/brandIcons.tsx")

    def test_chip_code_makes_no_request(self) -> None:
        for name in self.CHIP_FILES:
            text = (UI_SRC / name).read_text(encoding="utf-8")
            for bad in ("fetch(", "XMLHttpRequest", "oembed", "new Image(", "<img", "sendBeacon", "WebSocket"):
                self.assertNotIn(bad, text, f"{name}: {bad}")

    def test_the_shell_opens_web_links_without_credentials_only(self) -> None:
        lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        body = lib[lib.index("pub(crate) fn web_link"):]
        body = body[: body.index("\n}\n")]
        self.assertIn('strip_prefix("https://")', body)
        self.assertIn('strip_prefix("http://")', body)
        self.assertIn("!host.contains('@')", body)
        allowed = lib[lib.index("pub(crate) fn allowed_external"):]
        self.assertIn("is_control()", allowed[: allowed.index("\n}\n")])


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

    def test_media_read_checks_the_bots_own_messages_read_only(self) -> None:
        """`media.read` serves a path only after looking it up in state.db (opened with ``ro_uri``)."""
        fns = {n.name: n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)}
        named = ast.unparse(fns["media_named"])
        self.assertIn("ro_uri(db)", named)
        self.assertIn("role = 'assistant'", named)
        self.assertIn("media_named(profile_dir, path)", ast.unparse(fns["read_media"]))
        lib = (ROOT / "apps" / "omher" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn("media_target(&path, |p| shell.bridge.served_media(p))", lib)

    def test_skills_list_reads_frontmatter_only_and_follows_links_once(self) -> None:
        """Rule 19: `skills.list` is `read_skills` on the bot's own profile folder. The reader follows symlinked
        folders as Hermes does but reads each real folder once, skips hidden folders, opens only `SKILL.md` for
        reading and only its first 8 KB, writes nothing and calls nothing in Hermes."""
        fns = {n.name: n for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("'skills.list': self.op_skills_list", ast.unparse(fns["__init__"]))
        op = ast.unparse(fns["op_skills_list"])
        self.assertIn("asyncio.to_thread(read_skills, bot['path'])", op)
        self.assertNotIn("conn", op)  # no gateway call: a file read
        names = ("read_skills", "skill_roots", "_scan_skills", "read_skill_head", "_frontmatter_value")
        reader = "\n".join(ast.unparse(fns[n]) for n in names)
        # the profile's own folder first, then the config's skills.external_dirs (parsed, never written)
        roots = ast.unparse(fns["skill_roots"])
        self.assertIn("roots = [profile_dir / 'skills']", roots)
        self.assertIn("_load_yaml(profile_dir / 'config.yaml').get('skills')", roots)
        self.assertIn("cfg.get('external_dirs')", roots)
        self.assertIn("os.walk(root, followlinks=True)", reader)
        self.assertIn("real = os.path.realpath(dirpath)", reader)
        self.assertIn("if real in seen:", reader)
        self.assertIn("n.startswith('.')", reader)
        self.assertIn("skill = here / 'SKILL.md'", reader)
        self.assertIn("read_skill_head(skill)", reader)
        self.assertIn("fh.read(SKILL_HEAD_MAX)", reader)
        self.assertIn("SKILL_HEAD_MAX = 8 * 1024", self.source)
        opens = [c for n in names for c in ast.walk(fns[n])
                 if isinstance(c, ast.Call) and ast.unparse(c.func) == "open"]
        self.assertEqual([ast.unparse(c) for c in opens], ["open(path, 'rb')"])
        for banned in ("write", "unlink", "rename", "mkdir", "rmdir", "touch", "chmod", "subprocess", "self."):
            self.assertNotIn(banned, reader, banned)

    def test_the_model_setup_line_only_fills_the_composer(self) -> None:
        """Rule 19: the one-time line after omher's own install writes into the composer on the person's press
        (`actions.prefill`) and sends nothing; it runs no program, restarts nothing and asks the shell for nothing."""
        app = ROOT / "apps" / "omher" / "src" / "onboarding"
        line = (app / "OmhPromptLine.tsx").read_text(encoding="utf-8")
        logic = (app / "omhPrompt.ts").read_text(encoding="utf-8")
        self.assertIn("getStore().actions.prefill(promptText(p.command!))", line)
        for text in (line, logic):
            for banned in (".send(", "sendWithFiles", "chat.send", "invoke(", "@tauri-apps", "gateShell", "install("):
                self.assertNotIn(banned, text, banned)
        # the command comes from skills.list, never written as a literal
        self.assertNotIn('"/omh-model-setup"', logic)
        self.assertIn("getStore().actions.skills(bot, true)", logic)

    def test_chat_attach_takes_the_main_chat_id_and_bytes_only(self) -> None:
        """Every Hermes attach call is made by `op_chat_attach`, with the main chat's id, and no path."""
        fns = {n.name: n for n in ast.walk(self.tree) if isinstance(n, ast.AsyncFunctionDef)}
        attach = fns["op_chat_attach"]
        body = ast.unparse(attach)
        self.assertIn("main = await self._main(conn)", body)
        self.assertIn("session_id=main", body)
        self.assertNotIn("path", body)
        self.assertNotIn("open(", body)
        for name in ("image.attach_bytes", "pdf.attach", "file.attach", "image.attach"):
            users = [f.name for f in fns.values() if any(isinstance(c, ast.Constant) and c.value == name for c in ast.walk(f))]
            self.assertEqual(users, [] if name == "image.attach" else ["op_chat_attach"], name)

    def test_bridge_has_no_http_or_llm_client(self) -> None:
        banned = {"requests", "httpx", "aiohttp", "urllib3", "openai", "anthropic", "urllib.request", "http.client"}
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(sorted(i for i in imported if i in banned or i.split(".")[0] in banned), [])

    def test_the_only_gh_call_is_the_fixed_pr_view(self) -> None:
        """Rule 21: one `gh` call site, in gh_pr_view, with a fixed argv, a 3 s timeout, no prompt, and a repo and
        number checked before it runs; nothing passes a token to it."""
        fns = {f.name: f for f in ast.walk(self.tree) if isinstance(f, ast.FunctionDef)}
        calls = [(fn.name, c) for fn in fns.values() for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and ast.unparse(c.func) == "subprocess.run"]
        self.assertEqual(sorted(name for name, _ in calls), ["_git", "gh_pr_view"])
        fn = fns["gh_pr_view"]
        body = ast.unparse(ast.Module(body=fn.body[1:], type_ignores=[]))  # the code, without its docstring
        self.assertIn("timeout=timeout", body)
        self.assertIn("PR_REPO.match(repo)", body)
        self.assertIn("'GH_PROMPT_DISABLED': '1'", body)
        for word in ("token", "GH_TOKEN", "GITHUB_TOKEN", "auth"):
            self.assertNotIn(word, body)
        self.assertIn("PR_TIMEOUT = 3.0", self.source)
        self.assertIn("PR_TTL = 300.0", self.source)
        refs = [c for c in ast.walk(self.tree) if isinstance(c, ast.Name) and c.id == "gh_pr_view"]
        prstates = next(c for c in ast.walk(self.tree) if isinstance(c, ast.ClassDef) and c.name == "PrStates")
        # one use: PrStates' default look-up; op_runs_prs reaches it only through PrStates
        self.assertEqual(len(refs), 1)
        self.assertIn(refs[0], list(ast.walk(prstates)))

    def test_bridge_never_posts_to_a_messenger(self) -> None:
        """Rule 2: a reply target is text handed to the bot. The bridge imports no sender (Hermes'
        send_message tool, its platform adapters, a Slack or Discord client), names no messenger API and
        runs no `hermes send`; the command appears only inside the block the bot reads."""
        # subprocess is imported for rule 10's git reads and rule 21's one `gh pr view` (checked below and in
        # test_the_only_gh_call_is_the_fixed_pr_view).
        banned_roots = {"slack_sdk", "slack_bolt", "discord", "telegram"}
        banned_parts = ("send_message", "gateway.platforms", "plugins.platforms", "gateway.delivery")
        imported = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        offenders = [n for n in imported if n.split(".")[0] in banned_roots or any(p in n for p in banned_parts)]
        self.assertEqual(offenders, [])
        runs = [c for c in ast.walk(self.tree) if isinstance(c, ast.Call) and ast.unparse(c.func).startswith("subprocess.")]
        self.assertEqual(sorted(ast.unparse(c.args[0]) for c in runs),
                         ["['git', *pre, *args]", "[gh, 'pr', 'view', str(number), '-R', repo, '--json', 'state,isDraft,mergedAt,url']"])
        for host in ("slack.com/api", "discord.com/api", "api.telegram.org", "hooks.slack.com"):
            self.assertNotIn(host, self.source)
        hermes_send = [fn.name for fn in ast.walk(self.tree) if isinstance(fn, ast.FunctionDef)
                       and any(isinstance(c, ast.Constant) and isinstance(c.value, str) and "hermes send" in c.value
                               for c in ast.walk(fn))]
        self.assertEqual(hermes_send, ["reply_block"])
        for call in ast.walk(self.tree):
            if isinstance(call, ast.Call):
                self.assertFalse(any(isinstance(a, ast.Constant) and a.value in {"send_message", "send.message"}
                                     for a in call.args), ast.unparse(call))


class AccountsNeverCarryAToken(unittest.TestCase):
    """Rule 13: fake CLI homes, omher account folders and CLIProxyAPI auth files full of token-like keys; no accounts
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

    def test_cliproxyapi_logins_are_listed_from_file_names_only(self) -> None:
        """Rule 18's CLIProxyAPI sentence: its auth files are listed by name and never opened (a fuzzed auth dir
        full of tokens), the bridge never calls CLIProxyAPI (no port, no management path, no HTTP client), and a
        CLIProxyAPI row can never become the account a session starts with."""
        import importlib.util
        import json
        import sys
        import tempfile
        from unittest import mock

        spec = importlib.util.spec_from_file_location("omher_bridge_cpa", BRIDGE)
        ob = importlib.util.module_from_spec(spec)
        sys.modules["omher_bridge_cpa"] = ob
        spec.loader.exec_module(ob)
        secret = "sk-ant-oat01-BOUNDARY"
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            cpa = home / ".cli-proxy-api"
            cpa.mkdir()
            (cpa / "config.yaml").write_text('oauth:\n  auth-dir: "~/.cli-proxy-api"\n', encoding="utf-8")
            for i in range(5):
                (cpa / f"claude-0000000{i}-a{i}@example.com.json").write_text(
                    json.dumps({k: secret for k in self.TOKEN_KEYS}), encoding="utf-8")
            real_open = open
            opened: list[str] = []

            def spy(path, *a, **k):
                opened.append(str(path))
                return real_open(path, *a, **k)

            with mock.patch("builtins.open", spy), mock.patch("io.open", spy):
                payload = json.dumps([ob.read_accounts(home, now=1.0, which=lambda c: None),
                                      ob.read_usage(home, now=1.0, which=lambda c: None)])
            self.assertEqual([p for p in opened if p.endswith(".json") and ".cli-proxy-api" in p], [])
            self.assertNotIn(secret, payload)
            self.assertEqual(payload.count("@example.com"), 10)  # 5 rows + 5 meter lines
            with self.assertRaises(ob.BridgeError):
                ob.set_active_account("claude", "cpa:1", home)
        src = BRIDGE.read_text(encoding="utf-8")
        for bad in ("8317", "/v0/management", "/v8/management", "management-key", "X-Management-Key"):
            self.assertNotIn(bad, src, bad)

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
        # bridge.rs starts the bridge with Hermes' Python; accounts.rs runs the CLIs' fixed status / sign-in argv;
        # agent_chat.rs starts an allow-listed agent in its structured mode (rule 11); hermes_auth.rs opens the
        # system terminal for `hermes auth add` (rule 23); dsh_chat.rs runs DeepSeek Harness's headless profile (rule 11).
        self.assertEqual(spawns, {"accounts.rs": 2, "agent_chat.rs": 1, "bridge.rs": 1, "dsh_chat.rs": 1, "hermes_auth.rs": 1, "setup.rs": 1})


class SessionsStartOnlyAllowListedAgents(unittest.TestCase):
    """Rule 11: the Rust shell's allow-list, the commands that start a program, and the UI's list."""

    def setUp(self) -> None:
        self.sessions = (SHELL / "sessions.rs").read_text(encoding="utf-8")
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        self.prod = self.sessions.split("#[cfg(test)]\nmod tests", 1)[0]
        self.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]

    def test_rust_allow_list_is_the_eight_agents_and_each_id_is_its_program(self) -> None:
        block = re.search(r"pub const AGENTS: \[Agent; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(block)
        rows = re.findall(r'Agent \{ id: "([^"]+)", program: "([^"]+)", label: "[^"]+", mode: Mode::(\w+) \}', block.group(2))
        self.assertEqual(int(block.group(1)), len(SESSION_AGENTS))
        self.assertEqual([r[0] for r in rows], list(SESSION_AGENTS))
        self.assertEqual([r[1] for r in rows], list(SESSION_AGENTS))
        self.assertEqual(tuple(r[2] for r in rows), SESSION_MODES)
        # the Hermes-only row (no `omh`) opens the same Hermes chat: `hermes` is never a session program
        self.assertNotIn('"hermes"', block.group(2))
        self.assertNotIn('program: "hermes"', self.prod)

    def test_ui_list_matches_the_rust_allow_list(self) -> None:
        ui = UI_AGENTS.read_text(encoding="utf-8")
        rows = re.findall(r'\{ id: "([^"]+)", program: "\1", label: "[^"]+", mode: "(\w+)" \}', ui)
        self.assertEqual(tuple(r[0] for r in rows), SESSION_AGENTS)
        self.assertEqual(tuple(r[1].capitalize() for r in rows), SESSION_MODES)

    def test_chat_arguments_are_fixed_in_the_allow_list(self) -> None:
        """The structured-mode argv per agent is part of the allow-list (rule 11) and nothing else adds one."""
        claude = re.search(r"pub const CLAUDE_CHAT_ARGS: \[&str; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(claude)
        self.assertEqual(re.findall(r'"([^"]*)"', claude.group(2)), list(CLAUDE_CHAT_ARGS))
        chat = self.prod.split("pub fn chat_args", 1)[1].split("\n}\n", 1)[0]
        arms = re.findall(r'^\s+(.+?) => (&.+?\[\.\.\]),?$', chat, re.M)
        self.assertEqual(arms, [('"claude"', "&CLAUDE_CHAT_ARGS[..]"), ('"codex"', '&["app-server"][..]'),
                                ('"pi" | "omp" | "omo"', '&["--mode", "rpc"][..]'), ('"opencode"', '&["acp"][..]')])
        resume = self.prod.split("pub fn resume_args", 1)[1].split("\n}\n", 1)[0]
        # exactly two flags, each for named agents only; every other agent is refused
        self.assertEqual(re.findall(r'^\s+(.+?) => ("--[a-z-]+"|return Err)', resume, re.M),
                         [('"claude"', '"--resume"'), ('"omo"', '"--session"'), ('"dsh"', '"--session-id"'), ("_", "return Err")])
        self.assertIn('let ok = if id == "dsh" { session.strip_prefix("session-").is_some_and(is_uuid) } else { is_uuid(session) };', resume)
        self.assertIn("if !ok {", resume)
        self.assertEqual(re.findall(r'"(--[a-z-]+)"', resume), ["--resume", "--session", "--session-id"])
        # the chat spawner takes its argv only from launch_for + chat_args (+ resume_args) and is crate-internal
        start = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        for needle in ("launch_for(agent_id)?", "chat_args(agent_id)", "resume_args(agent_id, r)?", "\n        if a.mode != Mode::Chat {\n            return Err("):
            self.assertIn(needle, start)
        self.assertIn("pub(crate) fn spawn<F>", self.chat)

    def test_acp_agents_turn_off_files_and_terminal_and_continue_inside_the_protocol(self) -> None:
        """Rule 11: the ACP adapter offers the agent no file access and no terminal, a conversation id travels in
        `session/resume` (checked by a strict pattern), OpenCode's only extra variable is the fixed ask rule, and an
        approval answer is never the agent's always-allow."""
        acp = (SHELL / "acp_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        self.assertIn('"clientCapabilities": {"fs": {"readTextFile": false, "writeTextFile": false}, "terminal": false}', acp)
        self.assertNotIn("fs/read_text_file", acp)
        self.assertNotIn("terminal/create", acp)
        self.assertIn("b.is_ascii_alphanumeric() || b == b'_' || b == b'-'", acp)
        self.assertIn("(1..=128).contains(&id.len())", acp)
        rows = re.search(r"pub const ACP_AGENTS: \[AcpAgent; (\d+)\] = \[(.*?)\];", acp, re.S)
        self.assertIsNotNone(rows)
        self.assertEqual(re.findall(r'id: "([^"]+)"', rows.group(2)), ["opencode"])
        # OpenCode's one variable carries ask rules built from its own `agent list`: allow -> ask, deny stays deny
        self.assertEqual(re.findall(r'rules: (.*?),\n', rows.group(2)),
                         ['Some(RuleProbe { args: &["agent", "list"], var: "OPENCODE_CONFIG_CONTENT", build: opencode_ask, kept: opencode_kept })'])
        self.assertNotIn("OPENCODE_PERMISSION", acp)
        self.assertIn('if a == "deny" { "deny" } else { "ask" }', acp)
        self.assertIn('const ASKED: [(&str, &str); 2] = [("bash", "bash *"), ("edit", "edit *")];', acp)
        # the refusal the UI translates is the same sentence on both sides
        no_rules = re.search(r'pub const NO_RULES: &str = "([^"]+)";', acp).group(1)
        ts = (ROOT / "apps" / "omher" / "src" / "sessions" / "sessions.ts").read_text(encoding="utf-8")
        self.assertIn(f'export const NO_RULES = "{no_rules}";', ts)
        # the answer omher sends is the allow-once or reject option the request named, never allow_always
        self.assertIn('let (once, deny) = (opt("allow_once"), opt("reject_once").or_else(|| opt("reject_always")));', acp)
        self.assertNotIn('opt("allow_always")', acp)
        # no process is started here, and no file is opened
        for needle in ("Command::new", "std::fs::", "File::open"):
            self.assertNotIn(needle, acp)
        # the shell adds the row's env and nothing else, and takes an ACP id only through the protocol
        start = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("env.push(agent_rules(probe, &program, cwd, &path_env, account_env)?);", start)
        # the listing runs the same resolved program with the probe's fixed arguments only, and kills it on timeout
        rules = self.chat.split("fn agent_rules(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("argv.extend(probe.args.iter().map(OsString::from));", rules)
        self.assertIn("cmd.stdin(Stdio::null());", rules)
        self.assertIn("rx.recv_timeout(RULES_DEADLINE)", rules)
        self.assertIn("const RULES_DEADLINE: Duration = Duration::from_secs(30);", self.chat)
        self.assertIn('(_, Some(r)) if acp.is_some() && is_acp_session_id(r) => Some(r),', start)

    def test_dsh_is_deepseek_harness_run_headless_with_fixed_arguments(self) -> None:
        """Rule 11's DSH sentences: the CLI is DeepSeek Harness's own, each message is one fixed headless run
        continued by the harness's session id, and the one file written is the fixed credentials overlay."""
        turn = self.prod.split("pub fn dsh_turn_args", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(re.findall(r'"([^"]*)"\.into\(\)', turn), ["--profile", "headless", "--patch", "--json", "-"])
        self.assertIn('a.extend(resume_args("dsh", s)?);', turn)
        self.assertIn('home.join(".omher").join("dsh").join("headless.patch.yml")', self.prod)
        patch = re.search(r'pub const DSH_HEADLESS_PATCH: &str = "(.*?)";', self.prod, re.S).group(1)
        self.assertEqual(re.findall(r"- id: ([a-z-]+)", patch), ["credentials", "authorization", "deepseek-account"])
        for bad in ("!!js", "name:", "insert", "sandbox", "config"):
            self.assertNotIn(bad, patch)
        # found only where DeepSeek Harness installs it; the plain PATH lookup is not used for dsh
        find = self.prod.split("fn find_agent", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('if a.id == "dsh" {', find)
        self.assertIn("return dsh_harness(", find)
        harness = self.prod.split("pub fn is_dsh_harness", 1)[1].split("\n}\n", 1)[0]
        for marker in ('"DeepSeek Harness.app"', '"@deepseek-ai"', '"dsh"'):
            self.assertIn(marker, harness)
        self.assertIn('if agent_id == "dsh" {\n            return Err(', self.prod.split("pub fn start_agent", 1)[1])
        dsh = (SHELL / "dsh_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        self.assertEqual(dsh.count("Command::new("), 1)
        send = dsh.split("fn launch(&self", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("let mut argv = inner.launch.clone();", send)
        self.assertIn("argv.extend(dsh_turn_args(&inner.patch,", send)
        self.assertIn('let (launch, path_env) = launch_for("dsh")?;', dsh)
        # inside a Linux AppImage the run gets the host environment, as every other spawn does (#2778)
        self.assertIn("command_with(argv, cwd, path_env, crate::appimage::host_env)", dsh.split("fn command_for(", 1)[1].split("\n}\n", 1)[0])
        build = dsh.split("fn command_with(", 1)[1].split("\n}\n", 1)[0]
        self.assertTrue(build.rstrip().endswith("host(&mut cmd);\n    Ok(cmd)"))
        self.assertEqual(re.findall(r'cmd\.env\("([A-Z_]+)"', build), ["PATH", "DSH_PERMISSION_MODE", "LANG"])
        self.assertIn('cmd.env("DSH_PERMISSION_MODE", "workspace-write");', build)
        self.assertNotIn(".arg(", build)
        # its only file write is the overlay, never through a link, and nothing under ~/.dsh
        self.assertEqual(dsh.count("std::fs::write("), 1)
        self.assertIn("std::fs::write(path, DSH_HEADLESS_PATCH)", dsh)
        self.assertIn("path.is_symlink()", dsh)
        self.assertNotIn(".dsh\"", dsh)
        for word in ("plugin", "from-default-profile", "approval-policy", "permission-mode", "api_key", "apiKey"):
            self.assertNotIn(word, dsh)
        # the shared chat entry hands dsh to it and nothing else
        start = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn('if agent_id == "dsh" {\n            // DeepSeek Harness', start)
        self.assertIn("DshChat::start(cwd, resume, sink)?", start)

    def test_chat_commands_take_an_agent_id_folder_and_resume_only(self) -> None:
        sig = re.search(r"async fn chat_start\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        params = {p.split(":")[0].strip() for p in sig.group(1).split(",") if ":" in p}
        # `account` names the account a session restarted after an app restart ran with (session_env_for checks it)
        self.assertEqual(params, {"shell", "agent", "cwd", "resume", "account", "on_event"})
        body = self.lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn("chats.start_agent(&agent", body)
        self.assertNotIn(".spawn(", body)
        # what the person does in a chat is one of five inputs, never a command line
        inputs = re.search(r"pub enum Input \{(.*?)\n\}", self.chat, re.S).group(1)
        self.assertEqual(re.findall(r"^\s+(\w+)", inputs, re.M), ["Send", "Interrupt", "Approve", "Clarify", "Model", "Mode", "Effort"])
        # Send carries text, the paths of saved pictures (rule 26) and the bubble's id only: never bytes or a type
        self.assertIn("Send { text: String, #[serde(default)] images: Vec<Picture>, #[serde(default)] id: String },", inputs)
        self.assertIn('#[serde(from = "String")]\npub struct Picture', self.chat)

    def test_only_the_bridge_the_session_pty_and_the_chat_spawner_start_processes(self) -> None:
        """`Command::new` only in bridge.rs (Hermes' Python), setup.rs (the one fixed installer,
        rule 12), once in agent_chat.rs (the chat spawner), in accounts.rs (rule 18's fixed status /
        sign-in argv) and in hermes_auth.rs (rule 23's terminal); `spawn_command` only in sessions.rs."""
        for path in sorted(SHELL.glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            prod = text.split("#[cfg(test)]", 1)[0]
            if path.name not in ("bridge.rs", "setup.rs", "agent_chat.rs", "dsh_chat.rs", "accounts.rs", "hermes_auth.rs"):
                self.assertNotIn("Command::new", prod, path.name)
            if path.name != "sessions.rs":
                self.assertNotIn("spawn_command", text, path.name)
        self.assertEqual(self.prod.count("spawn_command("), 1)
        self.assertEqual(self.chat.count("Command::new("), 1)

    def test_session_start_takes_an_agent_id_and_no_command_or_args(self) -> None:
        sig = re.search(r"async fn session_start\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        params = {p.split(":")[0].strip() for p in sig.group(1).split(",") if ":" in p}
        # `resume` is the only extra: a conversation id (Claude Code, DSH) that resume_args checks is a UUID
        self.assertEqual(params, {"shell", "agent", "cwd", "resume", "account", "cols", "rows", "on_data", "on_exit"})
        body = self.lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn("start_agent(&agent, std::path::Path::new(&cwd), resume.as_deref()", body)
        self.assertNotIn(".spawn(", body)

    def test_a_session_gets_only_the_chosen_account_home(self) -> None:
        """Rule 11's account sentence: session_start and chat_start pass `accounts::session_env_for` (the saved
        account of a restarted session when its folder exists, else `session_env`) and nothing else;
        that reads only omher's `active.json` and yields at most the CLI's home variable; the PTY and the chat's
        pipes add it as env only."""
        for command in ("session_start", "chat_start"):
            sig = re.search(rf"async fn {command}\((.*?)\) -> ", self.lib, re.S)
            body = self.lib[sig.end():].split("\n}\n", 1)[0]
            self.assertEqual(body.count("accounts::session_env_for(&h, &agent, account.as_deref())"), 1, command)
            self.assertIn("start_agent(&agent, std::path::Path::new(&cwd), resume.as_deref(), &account_env,", body)
        accounts = (SHELL / "accounts.rs").read_text(encoding="utf-8").split("#[cfg(test)]", 1)[0]
        cli = accounts.split("pub fn session_cli", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(re.findall(r'"(\w+)" => Some\("(\w+)"\)', cli), [("claude", "claude"), ("codex", "codex"), ("grok", "grok")])
        self.assertIn("_ => None", cli)
        active = accounts.split("pub fn active_account", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(re.findall(r'join\("([^"]+)"\)', active), [".omher", "accounts", "active.json"])
        self.assertEqual(active.count("read_to_string("), 1)
        env = accounts.split("pub fn session_env(", 1)[1].split("\n}\n", 1)[0]
        # the restarted session's account: `default`, or a valid id whose folder exists, else the one above
        again = accounts.split("pub fn session_env_for(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("account_dir(home, cli, id).map(|d| d.is_dir() && !d.is_symlink())", again)
        self.assertIn("_ => session_env(home, agent)", again)
        for word in ("read", "token", "auth", "Command"):
            self.assertNotIn(word, again)
        self.assertIn("account_env(home, cli, &active_account(home, cli))", env)
        for word in ("read", "token", "auth", "Command"):
            self.assertNotIn(word, env)
        for src in (self.prod, self.chat):
            build = src.split("fn command_for(", 1)[1].split("\n}\n", 1)[0]
            self.assertIn("for (k, v) in account_env {\n        cmd.env(k, v);\n    }", build)
            self.assertNotIn(".arg(", build)
        # the chat's spawn builds its command there and the allow-listed start hands the account through
        self.assertIn("command_for(&argv, cwd, path_env, account_env)?", self.chat.split("pub(crate) fn spawn<F>", 1)[1])
        start = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        # the account's variable, plus only the ACP row's ask rules (rule 11: OpenCode's, built from its own listing)
        self.assertIn("let mut env = account_env.to_vec();", start)
        self.assertEqual(start.count("env.push("), 1)
        self.assertIn("env.push(agent_rules(probe, &program, cwd, &path_env, account_env)?);", start)
        self.assertIn("self.spawn(argv, cwd, Some(path_env), &env, adapter, sink)", start)

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


class AddKeyOpensOnlyHermesAuthAdd(unittest.TestCase):
    """Rule 23: "Add key" opens the system terminal with `hermes auth add <id> --type api-key`; omher never
    sees the key."""

    HERMES_AUTH = SHELL / "hermes_auth.rs"
    UI = UI_SRC / "settings" / "providers"

    def setUp(self) -> None:
        text = self.HERMES_AUTH.read_text(encoding="utf-8")
        self.prod = text.split("#[cfg(test)]", 1)[0]
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")

    def test_the_argv_is_fixed_apart_from_the_checked_id(self) -> None:
        args = self.prod[self.prod.index("pub fn auth_args"):]
        args = args[: args.index("\n}\n")]
        self.assertIn("if !valid_provider(provider)", args)
        self.assertEqual(re.findall(r'"([^"]*)"\.into\(\)', args), ["not a provider id", "auth", "add", "--type", "api-key"])
        self.assertIn('["auth".into(), "add".into(), provider.into(), "--type".into(), "api-key".into()]', args)
        # the id check is the doc's regex, written out byte by byte
        valid = self.prod[self.prod.index("pub fn valid_provider"):]
        valid = valid[: valid.index("\n}\n")]
        for piece in ("b.len() <= 41", "b[0].is_ascii_lowercase() || b[0].is_ascii_digit()", "*c == b'_' || *c == b'-'"):
            self.assertIn(piece, valid)
        # `open` checks the id before anything else, and every launcher argv comes from `launchers`
        open_fn = self.prod[self.prod.index("pub fn open("):]
        open_fn = open_fn[: open_fn.index("\n}\n")]
        self.assertTrue(open_fn.split("{\n", 1)[1].lstrip().startswith("auth_args(provider)?;"))
        self.assertEqual(self.prod.count("Command::new("), 1)
        self.assertIn("for (program, argv) in launchers(desk, &hermes, provider, file.as_deref())?", open_fn)
        self.assertNotIn("osascript", self.prod.replace("// ", ""))

    def test_no_pty_no_stdin_and_the_command_takes_only_a_provider(self) -> None:
        self.assertNotIn("spawn_command", self.prod)
        self.assertNotIn("portable_pty", self.prod)
        self.assertIn(".stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())", self.prod)
        sig = re.search(r"async fn open_hermes_auth\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.group(1).strip(), "provider: String")
        self.assertIn("hermes_auth::open(&provider)", self.lib)

    def test_the_page_never_takes_a_key(self) -> None:
        for path in sorted(self.UI.glob("*.ts*")):
            text = path.read_text(encoding="utf-8")
            for bad in ('type="password"', "api_key", "apiKey", "clipboard.read", "session_write", "localStorage"):
                self.assertNotIn(bad, text, f"{path.name}: {bad}")
        host = (self.UI / "authHost.ts").read_text(encoding="utf-8")
        self.assertIn('invoke("open_hermes_auth", { provider })', host)
        self.assertIn("/^[a-z0-9][a-z0-9_-]{0,40}$/", host)


class AutomationsAndPlugins(unittest.TestCase):
    """Rules 24 and 25: a bot's automations and plugins change only through that bot's own `cron.manage` and
    `plugins.manage`, with a closed list of actions; jobs.json is read, never written; installs take a catalog
    name, so a Git URL or `owner/repo` never reaches Hermes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = BRIDGE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)

    def _fn(self, name: str) -> ast.AST:
        found = [f for f in ast.walk(self.tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def _const(self, name: str):
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node.value
        self.fail(name)

    def test_each_manage_rpc_has_one_call_site_behind_an_allow_list(self) -> None:
        owners: dict[str, set[str]] = {}
        for fn in ast.walk(self.tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for c in ast.walk(fn):
                    if isinstance(c, ast.Constant) and c.value in ("cron.manage", "plugins.manage"):
                        owners.setdefault(c.value, set()).add(fn.name)
        self.assertEqual(owners, {"cron.manage": {"_cron"}, "plugins.manage": {"_plugins"}})
        self.assertEqual(ast.literal_eval(self._const("CRON_ACTIONS").args[0]), {"add", "pause", "resume", "remove"})
        self.assertEqual(ast.literal_eval(self._const("PLUGIN_ACTIONS").args[0]),
                         {"list", "toggle", "inspect", "install", "update", "remove"})
        for name, allow in (("_cron", "CRON_ACTIONS"), ("_plugins", "PLUGIN_ACTIONS")):
            self.assertIn(f"if action not in {allow}:", ast.unparse(self._fn(name)))

    def test_no_install_source_but_a_catalog_name(self) -> None:
        body = ast.unparse(self._fn("op_plugins_install")) + ast.unparse(self._fn("op_plugins_inspect"))
        for key in ("identifier", "repo", "force", "ref"):
            self.assertNotIn(f"{key}=", body, key)
        pattern = ast.literal_eval(self._const("CATALOG_NAME").args[0])
        for bad in ("https://github.com/x/y", "x/y", "git@github.com:x/y.git", "../x"):
            self.assertIsNone(re.fullmatch(pattern, bad), bad)
        self.assertIn("inspected_sha=sha", ast.unparse(self._fn("op_plugins_install")))

    def test_jobs_json_is_only_read(self) -> None:
        readers = {f.name for f in ast.walk(self.tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and any(isinstance(c, ast.Constant) and c.value == "jobs.json" for c in ast.walk(f))}
        self.assertEqual(readers, {"_read_jobs", "poll_routines"})
        for name in readers:
            body = ast.unparse(self._fn(name))
            for write in ("write_text", "write_bytes", "open(", "unlink", "rename", "replace(", "os.remove", "dump("):
                self.assertNotIn(write, body, f"{name}: {write}")


if __name__ == "__main__":
    unittest.main()


class SessionFilesStayInOmhersFolder(unittest.TestCase):
    """Rule 26: SESSIONS attachments are saved only under `~/.omher/session-files/<session>/`, read back only from
    there, typed at a terminal only as a saved path, removed with their session; Hermes sessions take none."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.files = (SHELL / "session_files.rs").read_text(encoding="utf-8")
        cls.prod = cls.files.split("#[cfg(test)]", 1)[0]
        cls.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        cls.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        cls.ui = (UI_SRC / "sessions" / "sessions.ts").read_text(encoding="utf-8")
        cls.view = (UI_SRC / "sessions" / "SessionView.tsx").read_text(encoding="utf-8")

    def test_the_one_folder_is_under_omhers_own_home(self) -> None:
        root = self.prod.split("pub fn root", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('home.join(".omher").join("session-files")', root)
        # one plain folder name per session id (`s` and digits), never a path from the page
        valid = self.prod.split("pub fn valid_session", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("b[0] == b's' && b[1..].iter().all(u8::is_ascii_digit)", valid)
        # a saved name is its last path part, never hidden, and a copy never overwrites (create_new)
        self.assertIn("rsplit(['/', '\\\\'])", self.prod)
        self.assertIn(".create_new(true)", self.prod)
        # the only writes: create_dir_all + the new file; the only deletes: the session's own folder
        for banned in ("fs::write(", "fs::rename(", "fs::copy(", "set_permissions"):
            self.assertNotIn(banned, self.prod, banned)
        self.assertEqual(self.prod.count("fs::remove_dir_all("), 1)
        self.assertEqual(self.prod.count("fs::remove_file("), 1)  # a link standing where a session folder should be
        # no process, no network
        for banned in ("Command::new", "TcpStream", "reqwest", "spawn_command"):
            self.assertNotIn(banned, self.files, banned)

    def test_reads_back_only_plain_files_in_that_folder(self) -> None:
        check = self.prod.split("pub fn check", 1)[1].split("\n}\n", 1)[0]
        for needle in ("p.is_symlink()", "canonicalize()", "strip_prefix(&root)", "parts.len() != 2", "valid_session("):
            self.assertIn(needle, check)
        # every read of a page-named path goes through check(): the picture input and the bubble after a restart
        resolve = self.chat.split("pub fn resolve", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("session_files::check(home, &p.path)?", resolve)
        self.assertEqual(resolve.count("std::fs::read("), 1)
        read = self.lib.split("async fn session_file_read", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("session_files::check(&home, &path)?", read)
        chat_input = self.lib.split("async fn chat_input", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("input.resolve(&user_home()?)?;", chat_input)

    def test_the_commands_take_a_session_id_a_name_and_bytes_only(self) -> None:
        save = self.lib.split("async fn session_file_save", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("session_files::save(&home, &session, &name, &data)", save)
        self.assertNotRegex(save.split(")", 1)[0], r"\b(path|cwd|dir)\b")
        for cmd, params in (("session_files_remove", "session: String"), ("session_files_prune", "keep: Vec<String>"), ("session_file_read", "path: String")):
            sig = re.search(rf"async fn {cmd}\((.*?)\) -> ", self.lib, re.S)
            self.assertIsNotNone(sig, cmd)
            self.assertEqual(sig.group(1).strip(), params, cmd)

    def test_close_removes_a_sessions_files_and_a_start_prunes_the_rest(self) -> None:
        close = self.ui.split("const close = (id: string) => {", 1)[1].split("\n  };\n", 1)[0]
        self.assertIn("host.removeFiles(id)", close)
        restore = self.ui.split("const restore = (saved: SavedSession[]) => {", 1)[1].split("\n  };\n", 1)[0]
        self.assertIn("host.pruneFiles(ids)", restore)
        self.assertIn("host.pruneFiles([])", restore)

    def test_a_terminal_gets_only_a_saved_quoted_path_and_hermes_sessions_take_no_files(self) -> None:
        drop = self.ui.split("const dropOnTerminal = async", 1)[1].split("\n  };\n", 1)[0]
        self.assertIn("shellQuote(await host.saveFile(id, f.name, await f.read()), windows)", drop)
        self.assertEqual(self.ui.count("host.write("), 2)  # xterm's own typing, and the dropped path
        # files go to chat agents only: an oh-my-hermes session's composer has no onSendFiles
        self.assertIn('onSendFiles={takesFiles ? (t, files) => getSessions().sendFiles(rec.id, t, files) : undefined}', self.view)
        self.assertIn("=== \"chat\";", self.view.split("const takesFiles", 1)[1].split("\n", 1)[0])
        self.assertIn('onSendFiles={mode === "chat" ? startWithFiles : undefined}', self.view)


class SessionControlsUseOnlyTheAgentsOwnSwitches(unittest.TestCase):
    """Rule 27: a session's permission mode, effort and model go through the agent's own protocol, never a mode that
    skips approvals or lifts the sandbox and never a settings file; the branch comes from `.git/HEAD` with no program."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        cls.branch = (SHELL / "git_branch.rs").read_text(encoding="utf-8")
        cls.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        cls.ui = (UI_SRC / "sessions" / "controls.ts").read_text(encoding="utf-8")

    def test_the_offered_modes_keep_approvals_and_the_sandbox(self) -> None:
        modes = self.chat.split("pub fn modes_for", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(re.findall(r'"(\w+)" => &\[(.*?)\]', modes), [("claude", '"default", "plan", "acceptEdits"'), ("codex", '"read-only", "ask", "auto"')])
        codex = self.chat.split("fn codex_mode(", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(re.findall(r'"([\w-]+)" => Some\(\("([\w-]+)", "(\w+)"\)\)', codex),
                         [("read-only", "on-request", "readOnly"), ("ask", "untrusted", "workspaceWrite"), ("auto", "on-request", "workspaceWrite")])
        # the UI offers the same modes
        self.assertIn('claude: ["default", "plan", "acceptEdits"],', self.ui)
        self.assertIn('codex: ["read-only", "ask", "auto"],', self.ui)
        for banned in ("bypassPermissions", "dangerFullAccess", "danger-full-access", "dangerously", "dontAsk"):
            self.assertNotIn(f'"{banned}"', self.chat, banned)
            self.assertNotIn(banned, self.ui, banned)
        self.assertNotIn('"never"', self.chat.split("fn codex_mode(", 1)[1].split("\n}\n", 1)[0])

    def test_mode_and_effort_go_through_the_agents_own_messages_only(self) -> None:
        self.assertIn('json!({"subtype": "set_permission_mode", "mode": mode})', self.chat)
        self.assertIn('json!({"subtype": "apply_flag_settings", "settings": {"effortLevel": effort}})', self.chat)
        self.assertIn('self.cmd(&mut st, "set_thinking_level", json!({"level": effort}));', self.chat)
        # a mode outside modes_for is refused before anything is written
        self.assertIn('if !modes_for("claude").contains(&mode.as_str()) {', self.chat)
        # no settings or config file of an agent is written or read for them
        for banned in ("settings.json", "config.toml", "fs::write(", "OpenOptions"):
            self.assertNotIn(banned, self.chat, banned)

    def test_the_branch_is_a_head_file_read_and_nothing_else(self) -> None:
        prod = self.branch.split("#[cfg(test)]", 1)[0]
        for banned in ("Command::new", "spawn", "fs::write", "OpenOptions", "remove_", "create_dir", "TcpStream"):
            self.assertNotIn(banned, prod, banned)
        self.assertIn('d.join("HEAD")', prod)
        self.assertIn("const MAX: u64 = 4096;", prod)
        self.assertIn("f.take(MAX)", prod)
        sig = re.search(r"async fn session_branch\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.group(1).strip(), "cwd: String")
        self.assertIn("git_branch::branch(std::path::Path::new(&cwd))", self.lib)

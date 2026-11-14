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
# Rule 11's allow-list: the built-ins (sessions.rs AGENTS) and the generic ACP agents (acp_agents.rs ACP_LIST, one
# structured-mode argument each). Kilo Code is no longer on it.
BUILTIN_AGENTS = ("claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode")
BUILTIN_MODES = ("Chat", "Chat", "Chat", "Chat", "Hermes", "Chat", "Chat", "Terminal", "Chat")
ACP_LIST_ARGS = (("gemini", "--acp"), ("qwen", "--acp"), ("kimi", "acp"), ("copilot", "--acp"), ("cline", "--acp"))
SESSION_AGENTS = BUILTIN_AGENTS + tuple(a for a, _ in ACP_LIST_ARGS)
CLAUDE_CHAT_ARGS = ("-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                    "--include-partial-messages", "--permission-prompt-tool", "stdio", "--replay-user-messages")
CONTEXT = ROOT / "CONTEXT.md"
DOCS_INDEX = ROOT / "docs" / "README.md"

RULES = (
    "omher never patches Hermes.",
    "Stop sends only the agent's own interrupt, and for Claude Code with no turn running also its own `stop_task`",
    "omher never signals or kills an agent's process or the work it started.",
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
    "The app runs only the CLIs' own status, sign-in and version commands, as fixed argv (`claude auth status --json`, `claude auth login`, `claude --version`,",
    "`codex --help`, `codex login status`, `codex login`, `codex --version`)",
    "and from `--version` only the version number (the first `digits.digits.digits` run with its suffix; never the rest of its text), shown beside the CLI's name.",
    "The browser sign-in happens inside the CLI: omher never asks for, accepts, reads, copies or shows a token or key.",
    "deletes only `~/.omher/accounts/<cli>/<id>/`. An account switch never stops a running session.",
    "Besides rule 21's one GitHub CLI read, the only program the bridge runs is `git`, for reads (`worktree list`, `rev-parse`, `status`, `diff`, `log`,",
    "omher never commits, checks out, pushes or edits a repository.",
    "and OmO's subagent records (`~/.omo/agent/projects/*/senpi-task/tasks/st_*.json`, never the subagents' own"
    " transcripts under `children/`).",
    "so for a session's own folder omher also reads `<that folder>/.omo/senpi-task/tasks/st_*.json`, the same records"
    " and nothing else in `.omo`, never a symlinked `.omo` or `senpi-task`, and never another folder's.",
    "An OmO session chat reads the same records for one more thing: when OmO's `task` result names a subagent's"
    " task id but not its answer, it reads that one record (`st_<task id>.json`, from the same folders and under the"
    " same rules, read-only, and only a record of that session)",
    "omher starts a terminal program only when the person asks for a session (SESSIONS `+`), and only one of a"
    " fixed allow-list: `claude`, `codex`, `omo`, `dsh`, `omh`, `pi`, `omp`, `grok`, `opencode`, `gemini`, `qwen`, `kimi`, `copilot`, `cline`, with no arguments,",
    "A chat session starts the same program with its fixed structured-mode arguments from the allow-list",
    "(`claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages"
    " --permission-prompt-tool stdio --replay-user-messages`, `codex app-server`, `omo --mode rpc`, `pi --mode rpc`, `omp --mode rpc`, `opencode acp`, `gemini --acp`, `qwen --acp`, `kimi acp`, `copilot --acp`, `cline --acp`) on pipes;",
    "The last five are the generic Agent Client Protocol agents: each is one fixed row of the shell's own list (`acp_agents.rs`:",
    "An Agent Client Protocol agent (OpenCode and those five) gets no such argument: omher sends the conversation id it reported",
    "omher never sends the protocol's `authenticate` (Cline's opens a browser by itself) and never asks for, takes or shows a key.",
    "These rules are read when the session starts; a deny added later applies from the next session.",
    "an unknown mode refuses, but an unchanged custom agent is allowed.",
    "refuses before the second listing, so the trusted config channel cannot cause the CLI to read a project-named file or variable.",
    "Gemini CLI, Qwen Code, Kimi Code, Copilot CLI and Cline get no extra variable and no rule check:",
    "Besides the fixed list, omher starts a program the person added on the Agents page (Settings › Agents) and confirmed,"
    " exactly with the arguments shown on the card, through ACP on pipes: the confirm card that shows that exact command is the only way an entry is written,",
    "into one file in omher's own folder, `~/.omher/custom-agents.json`, never a CLI's config;",
    "skips and never runs an entry that fails, starts it with no shell (a Windows `.cmd` or `.bat` shim is refused),"
    " adds no variable and no rule check, continues its conversation only inside the protocol, and refuses `opencode` and `kilo`;",
    "a bot may propose such an agent only as an `omher-agent` block in its own reply in its main chat or a Hermes folder chat"
    " (never tool output, a Slack or Discord session, or a SESSIONS agent's chat), which becomes a chip that opens the same card,"
    " checked again by the shell and stricter (no shell, interpreter or built-in program), so a bot never writes the file or starts the program itself.",
    "and tells the agent at `initialize` that omher offers no file reading or writing and no terminal,",
    "OpenCode also gets one environment variable, `OPENCODE_CONFIG_CONTENT`, holding ask rules for its `bash` and `edit` tools",
    "right before the chat, the shell runs `opencode agent list` (that one fixed argument, in the same folder, with the same environment, on pipes, nothing on stdin, at most 30 seconds)",
    "so allow becomes ask, ask stays ask and deny stays deny, for blanket and pattern rules alike;",
    "OpenCode is not started and the chat says so in one sentence; omher reads and writes none of OpenCode's own files,",
    "never its always-allow.",
    "the only other arguments are one that continues a conversation, with an id the shell checks is a UUID:",
    "`--resume <id>` for Claude Code, `--session <id>` for OmO.",
    "A Claude Code chat also gets `--add-dir <home>/.omher/session-files/<session id>`: exactly that session's own"
    " attachment folder (rule 26), passed as one argument, never a parent folder and never the home folder;",
    "the shell makes that folder before Claude Code starts (Claude Code honours only a folder that exists then),"
    " so reading a file the person attached needs no approval card, while a read anywhere else outside the"
    " session's folder still asks.",
    "The UI sends only the session id (`s` and digits), never a path;",
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
    "For the composer's `$` skill picker omher reads, never writes, the bot's own skill files",
    "then the folders the profile's `config.yaml` names in `skills.external_dirs`, where oh-my-hermes registers its skills",
    "pressing it puts the model-setup skill's `/command` and one sentence into the composer, and nothing is sent;",
    "omher restarts and reloads nothing and runs nothing for it.",
    "omher asks that gateway's own `plugins.manage` `list` (rule 25) and reads only whether the `omh` row is enabled",
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
    "A link in a SESSIONS terminal's output follows the same rule, whether omher found the address in the printed text"
    " or the program marked it as a hyperlink itself (OSC 8):",
    "A plain click opens nothing, and the terminal library's own confirm-and-open path for marked hyperlinks is never used.",
    "How terminals look and behave (themes, font, cursor, scrollback, renderer, those two clipboard switches) is one"
    " record in this computer's storage for the app (`omher.term`); omher reads no other program's terminal settings or theme files.",
    "Settings › Providers \"Add key\" may open the person's own system terminal running exactly"
    " `hermes auth add <provider> --type api-key`, only when the person picks a provider.",
    "The chat's connect block may open the same terminal running exactly `hermes auth add <id>` (no `--type`: Hermes"
    " runs that provider's own sign-in) for three ids only, `openai-codex`, `anthropic` and `nous`, a fixed list the"
    " desktop shell checks, only when the person picks one; any other id is refused, and the terminal runs nothing else.",
    "asks whether the bot can answer through Hermes' read-only `setup.runtime_check` on that bot's gateway (`bots.ready`).",
    "sets it through the same `chat.set_model` the model menu uses; it writes no config itself.",
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
    "what it restarts is the gateway process that serves that bot, through Hermes' own command:",
    "never one profile's unserve and serve inside the host. The profile is always named, never left to Hermes'",
    "It adds `--yes` only when the person presses \"Restart anyway\" right after Hermes refused because something was running,",
    "omher never stops a bot, never restarts every gateway at once, never restarts anything by itself",
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

    def test_omo_records_in_a_folder_are_read_only_for_the_sessions_own_folder(self) -> None:
        # O15: OmO 5.0 (and 5.1 once a folder holds them) keeps its records in `<folder>/.omo/senpi-task/tasks/`;
        # omher reads them only for the folder the session runs in, never through a link, and nothing else in .omo
        src = BRIDGE.read_text(encoding="utf-8")
        body = src[src.index("    def omo(self"):src.index("    # ---- ops")]
        code = body.split('"""', 2)[2]
        self.assertIn('dot = Path(cwd) / ".omo"', code)
        self.assertIn("if cwd:", code)
        self.assertIn("not dot.is_symlink()", code)
        self.assertIn('not (dot / "senpi-task").is_symlink()', code)
        self.assertEqual(code.count('".omo"'), 1)
        self.assertEqual(re.findall(r'dot / "([a-z-]+)"', code), ["senpi-task", "senpi-task"])
        rule = next(r for r in re.split(r"\n(?=\d+\. )", DOC.read_text(encoding="utf-8")) if "OmO's subagent records" in r)
        self.assertIn("`<that folder>/.omo/senpi-task/tasks/st_*.json`", rule)
        self.assertIn("never a symlinked `.omo` or `senpi-task`, and never another folder's", rule)

    def test_an_omo_chat_reads_only_its_subagents_own_task_records(self) -> None:
        # the chat's answer for a foreground OmO subagent comes from the record Plans reads (rule 16): one
        # `st_<id>.json` by task id, in `senpi-task/tasks` under `<omo>/agent/projects/*` or the session's own
        # `.omo`, never a link, never another session's record, and nothing is written there
        rust = (SHELL / "agent_chat.rs").read_text(encoding="utf-8")
        code = rust[: rust.index("#[cfg(test)]\nmod tests")]
        body = code[code.index("    fn omo_record(&self"):]
        body = body[: body.index("\n    }\n") + 6]
        self.assertIn('strip_prefix("st_")', body)
        self.assertIn('join("senpi-task").join("tasks")', body)
        self.assertIn('Path::new(&self.cwd).join(".omo")', body)
        self.assertIn("symlink_metadata", body)
        self.assertIn('s(&rec, "root_session_id") == self.session', body)
        self.assertEqual(re.findall(r'join\("([a-z.-]+)"\)', body), [".omo", "senpi-task", "senpi-task", "tasks", "agent", "projects", "senpi-task", "tasks"])
        for w in ("fs::write", "create_dir", "remove_file", "OpenOptions", "children"):
            self.assertNotIn(w, body, w)
        self.assertEqual(code.count("omo_record("), 2)

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
        # (skills.list for the $ picker), rule 20 (the signed self-update), rule 21 (a plan node's PR state
        # through the person's own `gh`), rule 22 (link chips: channel names read, web links opened on a
        # click), rule 23 (Providers "Add key": the system terminal runs `hermes auth add`, omher never sees
        # the key), rule 24 (Automations: a bot's jobs changed only through its own `cron.manage`) and rule 25
        # (Plugins: only through its own `plugins.manage`, catalog installs after an inspect) each widened the
        # boundary on purpose; 26: rule 26 (SESSIONS attachments saved under ~/.omher/session-files) did too; 27:
        # rule 27 (a session's mode, effort and branch read: only the agent's own switches, never a bypass) as well;
        # 28: rule 28 (a session shows the agent's own diff, todo list and thinking; edit and resend only through
        # the agent's own rewind); 29: rule 29 (Restart one bot through Hermes' own `gateway restart`, `--yes` only
        # after a refusal; plugin loads through its `reload-plugins`); 30: rule 30 (continue a Claude Code or Codex
        # conversation from its own files, read-only; a row's folder in the file manager or the system terminal; the
        # asks count on the Dock).
        # The rules stay numbered 1..n with no gap or repeat.
        rules = re.findall(r"^(\d+)\. ", DOC.read_text(encoding="utf-8"), re.M)
        self.assertTrue(6 <= len(rules) <= 30, len(rules))
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
        # Harness's headless profile (rule 11); folder_open.rs opens the person's own system terminal in a session's
        # folder with no command (rule 30). Terminal sessions start theirs through the PTY's
        # `spawn_command`, not `Command::new`.
        self.assertEqual(spawns, {"accounts.rs": 2, "agent_chat.rs": 1, "bridge.rs": 1, "dsh_chat.rs": 1, "folder_open.rs": 1, "hermes_auth.rs": 1, "setup.rs": 1})

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

    def test_a_terminal_link_opens_only_through_the_one_opener(self) -> None:
        # links in a SESSIONS terminal's output (found in the text, or marked by the program with OSC 8): one
        # click rule, one address rule, the app's one opener; nothing fetched, no window opened by the terminal code
        term = UI_SRC / "sessions" / "term"
        links = (term / "engine-links.ts").read_text(encoding="utf-8")
        code = "\n".join(line for line in links.splitlines() if not line.lstrip().startswith(("//", "*", "/**")))
        self.assertIn('import { openExternal } from "../../lib/openExternal";', code)
        # both kinds go through activateLink, which holds the modifier and the address checks
        self.assertEqual(code.count("activateLink(e, uri)"), 2)
        self.assertIn("term.options.linkHandler = { activate: (e, uri) => void activateLink(e, uri)", code)
        self.assertNotIn("allowNonHttpProtocols", code)
        body = code[code.index("export function activateLink"):]
        body = body[: body.index("\n}\n")]
        self.assertLess(body.index("linkModifier(event, mac)"), body.index("open(url)"))
        self.assertLess(body.index("webLinkTarget(text)"), body.index("open(url)"))
        rule = code[code.index("export function webLinkTarget"):]
        rule = rule[: rule.index("\n}\n")]
        self.assertIn('u.protocol !== "https:" && u.protocol !== "http:"', rule)
        self.assertIn("u.username || u.password", rule)
        for path in sorted(term.glob("*.ts")) + sorted(term.glob("*.tsx")):
            if path.name.endswith(".test.ts"):
                continue
            text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("//", "*", "/**")))
            for bad in ("window.open", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "confirm("):
                self.assertNotIn(bad, text, f"{path.name}: {bad}")

    def test_terminal_settings_are_one_record_and_read_no_other_programs_files(self) -> None:
        term = UI_SRC / "sessions" / "term"
        settings = (term / "settings.ts").read_text(encoding="utf-8")
        self.assertIn('export const TERM_KEY = "omher.term";', settings)
        self.assertEqual(settings.count("localStorage.getItem("), 1)
        self.assertEqual(settings.count("localStorage.setItem("), 1)
        for path in sorted(term.glob("*.ts")) + sorted(term.glob("*.tsx")):
            if path.name.endswith(".test.ts"):
                continue
            text = path.read_text(encoding="utf-8")
            # nothing here reaches the shell or the disk: the palettes are data in the bundle
            for bad in ("invoke(", "@tauri-apps", "readTextFile", "plugin-fs"):
                self.assertNotIn(bad, text, f"{path.name}: {bad}")
            if path.name != "settings.ts":
                self.assertNotIn("localStorage", text, path.name)


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
        # the plugin check reads the running gateway's list only (rule 25's `list`), never a toggle or an install
        self.assertIn("getStore().actions.pluginsList(bot)", logic)
        for banned in ("togglePlugin", "installPlugin", "plugins.toggle", "plugins.install", "updatePlugin", "removePlugin"):
            self.assertNotIn(banned, logic, banned)

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
        self.assertEqual(sorted(name for name, _ in calls), ["_git", "gh_pr_view", "run_hermes_restart"])
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
        # subprocess is imported for rule 10's git reads, rule 21's one `gh pr view` (checked below and in
        # test_the_only_gh_call_is_the_fixed_pr_view) and rule 29's one Hermes restart (RestartOneBotOnAPress).
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
                         ["['git', *pre, *args]", "[gh, 'pr', 'view', str(number), '-R', repo, '--json', 'state,isDraft,mergedAt,url']",
                          "argv"])  # argv: rule 29's restart_argv, checked in RestartOneBotOnAPress
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
             ("claude", "Version", ["--version"]), ("codex", "Help", ["--help"]),
             ("codex", "Status", ["login", "status"]), ("codex", "Login", ["login"]), ("codex", "Version", ["--version"])])
        self.assertIn("_ => None", fixed)
        # every spawn goes through `command(program, args, …)`, whose args come from `fixed_args` only
        self.assertEqual(prod.count("Command::new("), 2)  # the CLI itself, or cmd.exe /c for a Windows npm shim
        # the second argument of every `run_to_end(…)` / `command(…)` call is a `fixed_args` result
        calls = re.findall(r"\b(?:run_to_end|command)\(&?program, (\w+)", prod)
        self.assertEqual(len(calls), 6, calls)
        self.assertEqual(set(calls), {"args", "help_args"})
        self.assertNotIn(".arg(", prod.replace('c.arg("/c").arg(program)', ""))
        # the page names a CLI and an account id; no Tauri command takes a program or an argument
        lib = self.LIB_RS.read_text(encoding="utf-8")
        for cmd in ("account_status", "account_version", "account_login_start", "account_login_cancel", "account_clis", "account_env"):
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
        # system terminal for `hermes auth add` (rule 23); dsh_chat.rs runs DeepSeek Harness's headless profile (rule 11);
        # folder_open.rs opens the system terminal in a session's folder with no command (rule 30).
        self.assertEqual(spawns, {"accounts.rs": 2, "agent_chat.rs": 1, "bridge.rs": 1, "dsh_chat.rs": 1, "folder_open.rs": 1, "hermes_auth.rs": 1, "setup.rs": 1})



class CustomAgentsOnlyAfterTheCard(unittest.TestCase):
    """Rule 11's custom-agent sentence: the one file in omher's folder, the checks on every read, a start with no shell
    and nothing but the stored arguments, and the confirm commands as the file's only writers."""

    def setUp(self) -> None:
        text = (SHELL / "custom_agents.rs").read_text(encoding="utf-8")
        # the code only: doc comments name what is refused (`cmd.exe`) and are not code
        self.prod = "\n".join(l for l in text.split("#[cfg(test)]\nmod tests", 1)[0].splitlines() if not l.lstrip().startswith("//"))
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        self.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]

    def fn(self, name: str) -> str:
        return self.prod.split(f"fn {name}", 1)[1].split("\n}\n", 1)[0]

    def test_the_file_is_one_json_file_in_omhers_own_folder(self) -> None:
        self.assertIn('home.join(".omher").join("custom-agents.json")', self.fn("store_path"))
        # no other path is read or written: one file, its temporary sibling, the folder
        self.assertEqual(re.findall(r'"([^"]*\.json[^"]*)"', self.prod), ["custom-agents.json", "custom-agents.json.tmp"])
        for banned in (".claude", ".codex", ".gemini", ".cursor", "config.toml", "settings.json", "auth", "token", "env::set_var"):
            self.assertNotIn(banned, self.prod)

    def test_every_entry_is_checked_on_every_read(self) -> None:
        load = self.fn("load<")
        self.assertIn("check(&c, os, &is_program)", load)
        self.assertIn("out.broken.push(", load)
        self.assertIn("broken: vec![Broken { id: String::new(), why: Why::File }], unreadable: true", load)
        # the start reads the file again, checks it again, and only then resolves
        self.assertIn("load_here().agents.into_iter().find(|c| c.id == id)", self.fn("lookup"))
        self.assertIn("check(c, os, &is_program)", self.fn("launch<"))

    def test_the_validation_patterns(self) -> None:
        # ^[a-z0-9][a-z0-9-]{0,31}$ and never a built-in's (or Kilo Code's)
        self.assertIn("(1..=32).contains(&b.len()) && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit()) && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')", self.fn("id_ok"))
        self.assertIn('id == "kilo" || crate::sessions::AGENTS.iter().any(|a| a.id == id) || crate::acp_agents::entry(id).is_some()', self.fn("reserved"))
        # a bare ^[A-Za-z0-9._-]{1,64}$ program name
        self.assertIn("(1..=64).contains(&p.len()) && p.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-'))", self.fn("bare_ok"))
        # each argument ^[A-Za-z0-9._=/:-]{1,64}$, at most eight
        self.assertIn("(1..=64).contains(&a.len()) && a.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'=' | b'/' | b':' | b'-'))", self.fn("arg_ok"))
        self.assertIn("pub const MAX_ARGS: usize = 8;", self.prod)
        self.assertIn("if c.args.len() > MAX_ARGS || !c.args.iter().all(|a| arg_ok(a)) {", self.fn("check<"))
        # an absolute path must be an executable file now; OpenCode and Kilo Code are refused by name
        check = self.fn("check<")
        self.assertIn("if !is_program(Path::new(&c.program)) {", check)
        self.assertIn('"opencode" => return Err(Why::Opencode),', check)
        self.assertIn('"kilo" | "kilocode" => return Err(Why::Kilo),', check)
        meta = re.search(r"pub const SHELL_META: &\[char\] = &\[(.*?)\];", self.prod).group(1)
        for c in ("`", "$", ";", "|", "&", "<", ">", "(", ")", '"', "\\'", "*", "?", "~", "%", "\\n"):
            self.assertIn(f"'{c}'", meta)

    def test_the_start_runs_the_program_and_the_stored_arguments_with_no_shell(self) -> None:
        launch = self.fn("launch<")
        self.assertIn("let mut argv = vec![path.into_os_string()];", launch)
        self.assertIn("argv.extend(c.args.iter().map(OsString::from));", launch)
        self.assertNotIn("argv_for", launch)  # no cmd.exe /c for a shim
        self.assertIn('return Err(format!("{} cannot start without a shell", c.label));', launch)
        names = self.fn("names")
        self.assertIn('vec![format!("{program}.exe")]', names)
        self.assertNotIn("cmd", names.replace("Os::Unix", ""))
        # the bot drafts' refusal list names shells only to refuse them (pinned word for word in BotDraftsOnlyOpenTheCard)
        code = re.sub(r"pub const INTERPRETERS: &\[&str\] = &\[.*?\];", "", self.prod, flags=re.S)
        for banned in ("Command::new", "/bin/sh", "cmd.exe", "powershell", '"-c"', '"/c"', "spawn_command"):
            self.assertNotIn(banned, code)
        # the chat entry: the generic ACP adapter, argv from launch_here, the generic agents' env, no rule variable
        start = self.chat.split("fn start_custom<F>", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("Box::new(Acp::new(crate::custom_agents::adapter_row(c), &cwd.to_string_lossy(), thread))", start)
        self.assertIn("let (argv, path_env) = crate::custom_agents::launch_here(c, dirs)?;", start)
        self.assertIn("self.spawn(argv, cwd, Some(path_env), account_env, adapter, sink)", start)
        for banned in ("agent_rules", "env.push", "resume_args", ".arg("):
            self.assertNotIn(banned, start)
        self.assertIn("Some(r) if is_acp_session_id(r) => Some(r),", start)
        self.assertIn("rules: None", self.fn("adapter_row"))
        # reached only for an id that is not on the fixed list
        entry = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("if agent(agent_id).is_none() {\n            if let Some(c) = crate::custom_agents::lookup(agent_id) {", entry)

    def test_only_the_confirm_commands_write_the_file(self) -> None:
        # one writer, one write, through no link
        self.assertEqual(self.prod.count("std::fs::write("), 1)
        self.assertEqual(self.prod.count("std::fs::rename("), 1)
        for banned in ("File::create", "OpenOptions", "remove_file", "fs::copy"):
            self.assertNotIn(banned, self.prod)
        save = self.fn("save(")
        self.assertIn("std::fs::write(&tmp", save)
        self.assertIn("if path.is_symlink() {", save)
        self.assertEqual(re.findall(r"\bsave\(home, ", self.prod), ["save(home, ", "save(home, "])
        self.assertIn("save(home, raw)", self.fn("confirm_add<"))
        self.assertIn("save(home, kept)", self.fn("confirm_remove("))
        self.assertNotIn("save(", self.fn("draft<"))
        self.assertNotIn("save(", self.fn("preview_here("))
        # in the app: confirm_add only in custom_agent_confirm, confirm_remove only in custom_agent_remove
        self.assertEqual(self.lib.count("custom_agents::confirm_add("), 1)
        self.assertEqual(self.lib.count("custom_agents::confirm_remove("), 1)
        confirm = self.lib.split("async fn custom_agent_confirm(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("custom_agents::confirm_add(&home, &entry, Os::current(), sessions::is_program_file)", confirm)
        remove = self.lib.split("async fn custom_agent_remove(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("custom_agents::confirm_remove(&home, &id)", remove)
        preview = self.lib.split("async fn custom_agent_preview(", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("confirm", preview)
        # in the UI: customConfirm is called from the one confirm card's Add only, in exactly two places: the Add agent
        # form (AgentsPage.tsx) and a bot draft's chip (AgentChip.tsx), both through AgentConfirmCard
        page = (UI_SRC / "settings" / "agents" / "AgentsPage.tsx").read_text(encoding="utf-8")
        chip = (UI_SRC / "chat" / "parts" / "AgentChip.tsx").read_text(encoding="utf-8")
        callers = {p.relative_to(UI_SRC).as_posix(): p.read_text(encoding="utf-8").count("customConfirm(") for p in UI_SRC.rglob("*.ts*") if not p.name.endswith((".test.ts", ".test.tsx"))}
        self.assertEqual({k: v for k, v in callers.items() if v and k != "sessions/host.ts"}, {"settings/agents/AgentsPage.tsx": 1, "chat/parts/AgentChip.tsx": 1})
        for src in (page, chip):
            add = src.split("const add = async () => {", 1)[1].split("\n  };\n", 1)[0]
            self.assertIn("await getHost().customConfirm(card.entry);", add)
            self.assertIn("onAdd={() => void add()} />", src)
        self.assertIn('onClick={onAdd} data-testid="agent-confirm-add"', page)
        self.assertEqual(chip.count("<AgentConfirmCard "), 1)
        host = (UI_SRC / "sessions" / "host.ts").read_text(encoding="utf-8")
        self.assertIn('await invoke("custom_agent_confirm", { entry });', host)



class BotDraftsOnlyOpenTheCard(unittest.TestCase):
    """Rule 11's bot sentence: a bot's `omher-agent` draft is read only from its own replies in its main chat or a
    folder chat, becomes a chip that opens the same card, and is checked again by the shell, stricter than the form."""

    def setUp(self) -> None:
        self.draft = (UI_SRC / "chat" / "parts" / "agentDraft.ts").read_text(encoding="utf-8")
        self.chip = (UI_SRC / "chat" / "parts" / "AgentChip.tsx").read_text(encoding="utf-8")
        self.bubble = (UI_SRC / "chat" / "parts" / "Bubble.tsx").read_text(encoding="utf-8")
        text = (SHELL / "custom_agents.rs").read_text(encoding="utf-8")
        self.prod = text.split("#[cfg(test)]\nmod tests", 1)[0]
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")

    def test_drafts_come_only_from_bot_replies_in_main_and_folder_chats(self) -> None:
        self.assertIn('export const draftsAllowed = (chatKey: string): boolean => chatKey.startsWith("fold:") || !chatKey.includes(":");', self.draft)
        self.assertIn("draftsAllowed(chatKey) &&", self.chip)
        # the only reader is the bot bubble of a finished reply; no tool, activity, elsewhere or session view reads them
        self.assertIn("{bot && !streaming && <AgentChips chatKey={bot} text={text} />}", self.bubble)
        users = sorted(p.relative_to(UI_SRC).as_posix() for p in UI_SRC.rglob("*.tsx") if "<AgentChips" in p.read_text(encoding="utf-8"))
        self.assertEqual(users, ["chat/parts/Bubble.tsx"])
        self.assertLess(self.bubble.index('if (item.kind === "user")'), self.bubble.index("<AgentChips"))
        for f in ("parseDrafts(", "AgentChips"):
            readers = sorted(p.relative_to(UI_SRC).as_posix() for p in UI_SRC.rglob("*.ts*") if f in p.read_text(encoding="utf-8") and not p.name.endswith((".test.ts", ".test.tsx")))
            self.assertTrue(set(readers) <= {"chat/parts/agentDraft.ts", "chat/parts/AgentChip.tsx", "chat/parts/Bubble.tsx"}, readers)

    def test_the_chip_only_previews_and_the_shell_checks_it_again_stricter(self) -> None:
        preview = self.chip.split("const preview = async () => {", 1)[1].split("\n  };\n", 1)[0]
        self.assertIn("await getHost().customBotPreview(d.name, d.program, d.args, d.install);", preview)
        self.assertNotIn("customConfirm", preview)
        cmd = self.lib.split("async fn custom_agent_bot_preview(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("custom_agents::bot_preview_here(&label, &program, &args, &install)", cmd)
        self.assertNotIn("confirm", cmd)
        bot = self.prod.split("pub fn bot_draft<", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if INTERPRETERS.contains(&base.as_str()) {", bot)
        self.assertIn("return Err(Why::Builtin);", bot)
        self.assertIn("draft_of(home, label, program, args.to_vec(), install, os, is_program)", bot)
        self.assertNotIn("save(", self.prod.split("pub fn bot_preview_here(", 1)[1].split("\n}\n", 1)[0])
        names = re.search(r"pub const INTERPRETERS: &\[&str\] = &\[(.*?)\];", self.prod, re.S).group(1)
        want = "sh bash zsh fish dash ksh csh tcsh cmd powershell pwsh python python3 node deno bun ruby perl php osascript env sudo doas open xargs".split()
        self.assertEqual(re.findall(r'"([a-z0-9]+)"', names), want)
        ui = re.search(r"export const INTERPRETERS: readonly string\[\] = \[(.*?)\];", (UI_SRC / "sessions" / "custom.ts").read_text(encoding="utf-8"), re.S).group(1)
        self.assertEqual(re.findall(r'"([a-z0-9]+)"', ui), want)

class SessionsStartOnlyAllowListedAgents(unittest.TestCase):
    """Rule 11: the Rust shell's allow-list, the commands that start a program, and the UI's list."""

    def setUp(self) -> None:
        self.sessions = (SHELL / "sessions.rs").read_text(encoding="utf-8")
        self.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        self.prod = self.sessions.split("#[cfg(test)]\nmod tests", 1)[0]
        self.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]

    def test_rust_allow_list_is_the_built_ins_and_the_acp_list_and_each_id_is_its_program(self) -> None:
        block = re.search(r"pub const AGENTS: \[Agent; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(block)
        rows = re.findall(r'Agent \{ id: "([^"]+)", program: "([^"]+)", label: "[^"]+", mode: Mode::(\w+) \}', block.group(2))
        self.assertEqual(int(block.group(1)), len(BUILTIN_AGENTS))
        self.assertEqual([r[0] for r in rows], list(BUILTIN_AGENTS))
        self.assertEqual([r[1] for r in rows], list(BUILTIN_AGENTS))
        self.assertEqual(tuple(r[2] for r in rows), BUILTIN_MODES)
        # the generic ACP agents: one `generic(id, …)` row each, id = program (the constructor sets both), always a chat
        acp = (SHELL / "acp_agents.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        lst = re.search(r"pub const ACP_LIST: \[AcpEntry; (\d+)\] = \[(.*?)\];", acp, re.S)
        self.assertIsNotNone(lst)
        generic = re.findall(r'generic\("([^"]+)", "[^"]+", &\["([^"]+)"\], ', lst.group(2))
        self.assertEqual(int(lst.group(1)), len(ACP_LIST_ARGS))
        self.assertEqual(tuple(generic), ACP_LIST_ARGS)
        self.assertIn("agent: Agent { id, program: id, label, mode: Mode::Chat },", acp)
        self.assertIn("acp: AcpAgent { id, label, login, skill_tool: None, rules: None },", acp)
        # the allow-list look-up is exactly those two lists; Kilo Code is on neither
        self.assertIn("AGENTS.iter().find(|a| a.id == id).or_else(|| acp_agents::entry(id).map(|e| &e.agent))", self.prod)
        for src in (self.prod, acp, (SHELL / "acp_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]):
            self.assertNotIn('"kilo"', src)
            self.assertNotIn("KILO_CONFIG_CONTENT", src)
        # the Hermes-only row (no `omh`) opens the same Hermes chat: `hermes` is never a session program
        self.assertNotIn('"hermes"', block.group(2))
        self.assertNotIn('program: "hermes"', self.prod)

    def test_ui_list_matches_the_rust_allow_list(self) -> None:
        ui = UI_AGENTS.read_text(encoding="utf-8")
        rows = re.findall(r'\{ id: "([^"]+)", program: "\1", label: "[^"]+", mode: "(\w+)"(?:, main: true)? \}', ui)
        self.assertEqual(tuple(r[0] for r in rows), BUILTIN_AGENTS)
        self.assertEqual(tuple(r[1].capitalize() for r in rows), BUILTIN_MODES)
        # the main tier is named once, on the first three; the generic ACP agents have no row in the UI (the shell
        # sends them), and nothing in it names Kilo Code but the line a saved session of it shows
        self.assertEqual(re.findall(r'\{ id: "([^"]+)"[^}]*main: true \}', ui), ["claude", "codex", "omo"])
        for gid, _ in ACP_LIST_ARGS:
            self.assertNotIn(f'"{gid}"', ui)
        self.assertEqual(re.findall(r"\bkilo\b", ui), ["kilo"])

    def test_chat_arguments_are_fixed_in_the_allow_list(self) -> None:
        """The structured-mode argv per agent is part of the allow-list (rule 11) and nothing else adds one."""
        claude = re.search(r"pub const CLAUDE_CHAT_ARGS: \[&str; (\d+)\] = \[(.*?)\];", self.prod, re.S)
        self.assertIsNotNone(claude)
        self.assertEqual(re.findall(r'"([^"]*)"', claude.group(2)), list(CLAUDE_CHAT_ARGS))
        chat = self.prod.split("pub fn chat_args", 1)[1].split("\n}\n", 1)[0]
        arms = re.findall(r'^\s+(.+?) => (&.+?\[\.\.\]),?$', chat, re.M)
        self.assertEqual(arms, [('"claude"', "&CLAUDE_CHAT_ARGS[..]"), ('"codex"', '&["app-server"][..]'),
                                ('"pi" | "omp" | "omo"', '&["--mode", "rpc"][..]'), ('"opencode"', '&["acp"][..]')])
        # a generic ACP agent's argument is its list row's, one of the two (pinned row by row above)
        self.assertIn("if let Some(e) = acp_agents::entry(id) {\n        return Some(e.args);\n    }", chat)
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

    def test_claude_reads_only_its_own_attachment_folder_without_a_card(self) -> None:
        """Rule 11: Claude Code's one extra argument is `--add-dir` + the session's own attachment folder as ONE argv
        element: made by `session_files::session_dir` from the session id (never a path from the page), before the
        start, never a parent and never the home folder; no other agent gets it."""
        start = self.chat.split("pub fn start_agent", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn('if let Some(dir) = files.filter(|_| agent_id == "claude") {', start)
        self.assertIn("argv.extend(add_dir_args(&argv[0], dir));", start)
        self.assertNotIn('"--add-dir"', start)  # the flag itself lives in add_dir_args only
        add = self.chat.split("fn add_dir_args", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(re.findall(r'"--add-dir"', add), ['"--add-dir"', '"--add-dir"'])
        self.assertIn('vec!["--add-dir".into(), dir]', add)
        self.assertNotIn("parent()", add)
        self.assertNotIn("join(", add)
        self.assertEqual(self.chat.count('"--add-dir"'), 2)
        lib = (SHELL / "lib.rs").read_text(encoding="utf-8")
        sig = re.search(r"async fn chat_start\((.*?)\) -> ", lib, re.S)
        body = lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn('("claude", Some(s)) => user_home().and_then(|h| session_files::session_dir(&h, s)).ok(),', body)
        self.assertIn("files.as_deref()", body)
        self.assertNotIn("parent()", body)
        files = (SHELL / "session_files.rs").read_text(encoding="utf-8").split("#[cfg(test)]", 1)[0]
        made = files.split("pub fn session_dir", 1)[1].split("\n}\n", 1)[0]
        for needle in ("if !valid_session(session) {", "d.is_symlink()", "let dir = root.join(session);", "fs::create_dir_all(&dir)"):
            self.assertIn(needle, made)
        # the UI passes the session id, never a path
        host = (UI_SRC / "sessions" / "host.ts").read_text(encoding="utf-8")
        self.assertIn('invoke<number>("chat_start", { agent, cwd, resume: resume ?? null, account: account ?? null, session: session ?? null, onEvent: ch })', host)

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
        # OpenCode's one variable carries ask rules built from its own `agent list`: allow -> ask, deny stays deny;
        # the generic rows add no variable (their constructor fixes `rules: None`)
        self.assertEqual(re.findall(r'rules: (Some\(RuleProbe \{.*?\}\)|None)', rows.group(2)),
                         ['Some(RuleProbe { args: &["agent", "list"], var: "OPENCODE_CONFIG_CONTENT", build: opencode_ask, kept: opencode_kept })'])
        # each row's sign-in line is the agent's own command, run by the person; omher never sends `authenticate`
        self.assertEqual(re.findall(r'login: "([^"]+)"', rows.group(2)), ["opencode auth login"])
        lst = (SHELL / "acp_agents.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        self.assertEqual(re.findall(r'generic\("[^"]+", "[^"]+", &\["[^"]+"\], "([^"]+)", ', lst),
                         ["gemini", "qwen", "kimi login", "copilot login", "cline auth"])
        self.assertNotIn('"authenticate"', acp)
        self.assertNotIn("KILO_ASKED", acp)
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
        self.assertIn("env.push(agent_rules(probe, label, &program, cwd, &path_env, account_env)?);", start)
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
        # `session` is the SESSIONS id (`s` and digits) whose attachment folder a Claude Code chat may read (rule 11)
        self.assertEqual(params, {"shell", "agent", "cwd", "resume", "account", "session", "on_event"})
        body = self.lib[sig.end():].split("\n}\n", 1)[0]
        self.assertIn("chats.start_agent(&agent", body)
        self.assertNotIn(".spawn(", body)
        # what the person does in a chat is one of five inputs, never a command line
        inputs = re.search(r"pub enum Input \{(.*?)\n\}", self.chat, re.S).group(1)
        self.assertEqual(re.findall(r"^\s+(\w+)", inputs, re.M), ["Send", "Interrupt", "Approve", "Clarify", "Model", "Mode", "Effort", "Rewind"])
        # Send carries text, the paths of saved pictures (rule 26) and the bubble's id only: never bytes or a type
        self.assertIn("Send { text: String, #[serde(default)] images: Vec<Picture>, #[serde(default)] id: String },", inputs)
        self.assertIn('#[serde(from = "String")]\npub struct Picture', self.chat)

    def test_only_the_bridge_the_session_pty_and_the_chat_spawner_start_processes(self) -> None:
        """`Command::new` only in bridge.rs (Hermes' Python), setup.rs (the one fixed installer,
        rule 12), once in agent_chat.rs (the chat spawner), in accounts.rs (rule 18's fixed status /
        sign-in argv), in hermes_auth.rs (rule 23's terminal) and in folder_open.rs (rule 30's terminal in a session's
        folder); `spawn_command` only in sessions.rs."""
        for path in sorted(SHELL.glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            prod = text.split("#[cfg(test)]", 1)[0]
            if path.name not in ("bridge.rs", "setup.rs", "agent_chat.rs", "dsh_chat.rs", "accounts.rs", "hermes_auth.rs", "folder_open.rs"):
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
        self.assertIn("env.push(agent_rules(probe, label, &program, cwd, &path_env, account_env)?);", start)
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
    """Rule 23: "Add key" opens the system terminal with `hermes auth add <id> --type api-key`, the connect block with
    `hermes auth add <id>` for openai-codex, anthropic or nous only; omher never sees the key or the login. Readiness
    is Hermes' read-only `setup.runtime_check`."""

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
        self.assertTrue(open_fn.split("{\n", 1)[1].lstrip().startswith("form_args(form, provider)?;"))
        self.assertEqual(self.prod.count("Command::new("), 1)
        self.assertIn("for (program, argv) in launchers(desk, &hermes, form, provider, file.as_deref())?", open_fn)
        # both argv forms come from form_args, nowhere else
        form = self.prod[self.prod.index("pub fn form_args"):]
        form = form[: form.index("\n}\n")]
        self.assertIn("Form::ApiKey => auth_args(provider)", form)
        self.assertIn("Form::SignIn => sign_in_args(provider)", form)
        self.assertEqual(self.prod.count("auth_args(provider)"), 1)
        self.assertEqual(self.prod.count("sign_in_args(provider)"), 1)

    def test_the_sign_in_argv_is_fixed_to_three_ids(self) -> None:
        self.assertIn('pub const SIGN_IN: [&str; 3] = ["openai-codex", "anthropic", "nous"];', self.prod)
        args = self.prod[self.prod.index("pub fn sign_in_args"):]
        args = args[: args.index("\n}\n")]
        self.assertIn("if !SIGN_IN.contains(&provider)", args)
        self.assertEqual(re.findall(r'"([^"]*)"\.into\(\)', args), ["not a sign-in provider", "auth", "add"])
        self.assertIn('["auth".into(), "add".into(), provider.into()]', args)
        sig = re.search(r"async fn open_hermes_sign_in\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.group(1).strip(), "provider: String")
        self.assertIn("hermes_auth::open(hermes_auth::Form::SignIn, &provider)", self.lib)
        # the page's list is the shell's list, and its stand-in in a browser is e2e's only
        ready = (UI_SRC / "chat" / "connect" / "ready.ts").read_text(encoding="utf-8")
        self.assertIn('export const SIGN_IN = ["openai-codex", "anthropic", "nous"] as const;', ready)
        host = (self.UI / "authHost.ts").read_text(encoding="utf-8")
        self.assertIn('invoke("open_hermes_sign_in", { provider })', host)
        for path in sorted((UI_SRC / "chat" / "connect").glob("*.ts*")):
            text = path.read_text(encoding="utf-8")
            for bad in ('type="password"', "api_key", "apiKey", "clipboard.read", "session_write", "localStorage", "<input"):
                self.assertNotIn(bad, text, f"{path.name}: {bad}")

    def test_readiness_is_one_read_only_gateway_call(self) -> None:
        tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
        owners: dict[str, set[str]] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for c in ast.walk(fn):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("setup."):
                        owners.setdefault(c.value, set()).add(fn.name)
        # Hermes' readiness probe only, from one op; never setup.status writes, onboarding or free-tier provisioning
        self.assertEqual(owners, {"setup.runtime_check": {"op_bots_ready"}})
        body = ast.unparse(next(f for f in ast.walk(tree) if isinstance(f, ast.AsyncFunctionDef) and f.name == "op_bots_ready"))
        self.assertEqual(re.findall(r"_call\(conn, '([a-z._]+)'", body), ["setup.runtime_check"])
        # the probe's provider is a checked id; which ids may open a terminal is the shell's SIGN_IN list
        self.assertIn("PROVIDER_ID.fullmatch(provider)", body)
        self.assertIn('PROVIDER_ID = re.compile(\'^[a-z0-9][a-z0-9_-]{0,40}$\')', ast.unparse(tree))
        self.assertNotIn("osascript", self.prod.replace("// ", ""))

    def test_no_pty_no_stdin_and_the_command_takes_only_a_provider(self) -> None:
        self.assertNotIn("spawn_command", self.prod)
        self.assertNotIn("portable_pty", self.prod)
        self.assertIn(".stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())", self.prod)
        sig = re.search(r"async fn open_hermes_auth\((.*?)\) -> ", self.lib, re.S)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.group(1).strip(), "provider: String")
        self.assertIn("hermes_auth::open(hermes_auth::Form::ApiKey, &provider)", self.lib)

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

    def test_an_agents_own_unguarded_setting_is_only_said_never_offered(self) -> None:
        # O13: ownSetting.ts recognises the agent's reported values to name them; it sends, offers and writes nothing
        own = (UI_SRC / "sessions" / "ownSetting.ts").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'^import .*$', own, re.M), ['import { t } from "../i18n";', 'import { MODES } from "./controls";'])
        for banned in ("setMode", "getSessions", "invoke(", "input(", "export const MODES", "localStorage"):
            self.assertNotIn(banned, own, banned)
        self.assertIn("export function ownSetting(", own)
        view = (UI_SRC / "sessions" / "SessionView.tsx").read_text(encoding="utf-8")
        # the menu still lists only omher's modes
        self.assertIn("{modesOf(rec.agent).map((m) => {", view)
        text = _flat(DOC.read_text(encoding="utf-8"))
        self.assertIn("the session only says so where the mode is shown, naming the agent's own config as where it comes from", text)

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


class SessionTranscriptComesFromTheAgentsOwnStream(unittest.TestCase):
    """Rule 28: a session's diffs, todo list and thinking come from the agent's own stream (no project file read,
    nothing kept on disk); edit and resend goes only through the agent's own rewind, between turns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.chat = (SHELL / "agent_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]\nmod tests", 1)[0]
        cls.acp = (SHELL / "acp_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]", 1)[0]
        cls.dsh = (SHELL / "dsh_chat.rs").read_text(encoding="utf-8").split("#[cfg(test)]", 1)[0]

    def test_diff_plan_and_thinking_read_no_file(self) -> None:
        for fn in ("fn input_diff(", "fn claude_result_diff(", "fn codex_diff(", "fn plan_event(", "fn thinking_event("):
            body = self.chat.split(fn, 1)[1].split("\n}\n", 1)[0]
            for banned in ("fs::", "File::", "read_to_string", "Command::new"):
                self.assertNotIn(banned, body, f"{fn} {banned}")

    def test_rewind_is_the_agents_own_and_only_between_turns(self) -> None:
        self.assertIn('json!({"subtype": "rewind_conversation", "target_message_uuid": uuid})', self.chat)
        self.assertIn('self.call(&mut st, "thread/revert", json!({"threadId": thread, "beforeTurnId": turn}));', self.chat)
        # both refuse while a turn runs
        self.assertEqual(self.chat.count('Input::Rewind => {\n                if self.turn {\n                    return Err("wait until the turn ends".into());'), 2)
        # the others offer none
        self.assertIn('Input::Rewind => return Err(format!("{} cannot take a message back here", self.label)),', self.chat)
        self.assertIn("Input::Rewind => return Err(", self.acp)
        self.assertIn("Input::Rewind => Err(", self.dsh)
        # no rewind of files: never Claude Code's rewind_files, never a fork that copies the conversation
        for banned in ("rewind_files", "fork_conversation", "thread/fork", "--resume-session-at", "--rewind-files"):
            self.assertNotIn(banned, self.chat, banned)


class RestartOneBotOnAPress(unittest.TestCase):
    """Rule 29: one fixed Hermes argv per press, for the gateway process that serves the bot (always a named profile),
    `--yes` only after a refusal, no stop, no restart-all, no automatic restart, no signal or service manager; plugins
    load through Hermes' `reload-plugins`, never a restart."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = BRIDGE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)
        cls.fns = {f.name: f for f in ast.walk(cls.tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def _body(self, name: str) -> str:
        fn = self.fns[name]
        return ast.unparse(ast.Module(body=fn.body[1:] if ast.get_docstring(fn) else fn.body, type_ignores=[]))

    def test_the_argv_is_hermes_restart_with_the_checked_id_and_yes_only_when_asked(self) -> None:
        body = self._body("restart_argv")
        self.assertIn("PROFILE_ID.fullmatch(bot)", body)
        self.assertIn("return [hermes, '-p', bot, 'gateway', 'restart', '--detach', *(['--yes'] if interrupt is True else [])]", body)
        pattern = ast.literal_eval(next(n.value for n in self.tree.body if isinstance(n, ast.Assign)
                                        and any(getattr(t, "id", "") == "PROFILE_ID" for t in n.targets)).args[0])
        self.assertEqual(pattern, "[a-z0-9][a-z0-9_-]{0,63}")  # Hermes' hermes_constants.PROFILE_ID_RE
        for bad in ("--all", "-p", "Kami", "a b", "x;y", "../x", ""):
            self.assertIsNone(re.fullmatch(pattern, bad), bad)

    def test_one_run_with_no_shell_and_nothing_on_stdin(self) -> None:
        body = self._body("run_hermes_restart")
        self.assertIn("argv = restart_argv(hermes, bot, interrupt)", body)
        self.assertIn("subprocess.run(argv, stdin=subprocess.DEVNULL", body)
        self.assertNotIn("shell=True", self.src)
        # the bridge's own SIGTERM handler (it stops itself) is not a signal sent to anything
        for word in ("Popen", "os.kill", "send_signal", "killpg", "launchctl", "systemctl", "schtasks", "os.system"):
            self.assertNotIn(word, self.src, word)
        callers = [n for n, f in self.fns.items() if n != "run_hermes_restart"
                   and any(isinstance(c, ast.Name) and c.id == "run_hermes_restart" for c in ast.walk(f))]
        self.assertEqual(callers, ["op_bots_restart"])

    def test_yes_needs_a_refusal_first_and_the_bot_comes_from_the_bot_list(self) -> None:
        body = self._body("op_bots_restart")
        self.assertIn("bot = self._bot(p.get('bot'))", body)
        self.assertIn("interrupt = p.get('interrupt') is True", body)
        # the process that serves the bot, as Hermes decides it; the refusal window belongs to that gateway
        self.assertIn("gw = await asyncio.to_thread(gateway_of, self.home, name)", body)
        self.assertIn("if interrupt and self.clock() - self._refused.get(gw, -1000000000.0) > RESTART_ANYWAY_WINDOW:", body)
        self.assertIn("run_hermes_restart, hermes, gw, self.home, interrupt", body)

    def test_the_gateway_is_the_host_or_the_bots_own_never_a_served_profile(self):
        body = self._body("gateway_of")
        self.assertIn("if b['is_default']:\n            return 'default'", body)
        self.assertIn("return bot if _standalone(b['path']) or _hermes_gateway_pid(b['path']) is not None else 'default'", body)
        self.assertIn("from gateway.status import live_gateway_pid_for_home", self._body("_hermes_gateway_pid"))

    def test_no_stop_no_restart_all_and_nothing_restarts_by_itself(self) -> None:
        # the one Hermes verb omher sends is `gateway restart`, from one function: never stop, start or --all
        gateway = {n for n, f in self.fns.items() for lst in ast.walk(f) if isinstance(lst, ast.List)
                   and any(isinstance(c, ast.Constant) and c.value == "gateway" for c in lst.elts)}
        self.assertEqual(gateway, {"restart_argv"})
        argv_consts = [c.value for c in ast.walk(self.fns["restart_argv"]) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        for verb in ("stop", "start", "--all", "--force", "uninstall"):
            self.assertNotIn(verb, argv_consts)
        callers = [n for n, f in self.fns.items()
                   if any(isinstance(c, ast.Attribute) and c.attr == "op_bots_restart" for c in ast.walk(f))]
        self.assertEqual(callers, ["__init__"])  # only the op table: a press from the UI
        # the UI: one store action sends it; only restart.ts calls that action, from press / confirm / anyway
        files = {p.relative_to(UI_SRC).as_posix(): p.read_text(encoding="utf-8") for p in UI_SRC.rglob("*.ts*") if ".test." not in p.name}
        senders = sorted(f for f, src in files.items() if re.search(r'request\("bots\.restart"', src))
        self.assertEqual(senders, ["state/store.ts"])
        callers = sorted(f for f, src in files.items() if re.search(r"\.restartBot\(", src))
        self.assertEqual(callers, ["sidebar/restart.ts"])
        restart = files["sidebar/restart.ts"]
        self.assertEqual(len(re.findall(r"deps\.restart\(", restart)), 1)
        self.assertEqual(sorted(re.findall(r"run\(bot, (true|false)\)", restart)), ["false", "true"])
        self.assertIn('anyway: (bot: string) => (get(bot).step === "refused" ? run(bot, true)', restart)

    def test_plugins_load_through_reload_plugins_never_a_restart(self) -> None:
        body = self._body("reload_plugins")
        self.assertIn("from gateway.control_socket import reload_gateway_plugins", body)
        owners = {n for n, f in self.fns.items() if any(isinstance(c, ast.Name) and c.id == "reload_plugins" for c in ast.walk(f))}
        self.assertEqual(owners, {"op_plugins_reload"})
        self.assertNotIn("restart", self._body("op_plugins_reload").replace("restart_bot", "").replace("'restart' if", ""))


class PastConversationsAreOnlyRead(unittest.TestCase):
    """Rule 30: the conversations Claude Code and Codex keep are listed and shown read-only, from their own files only,
    with links and paths outside the CLI's home refused; a row's folder opens in the file manager or the person's own
    terminal with no command; the asks count goes through Tauri's window calls."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.past = (SHELL / "past_chats.rs").read_text(encoding="utf-8").split("#[cfg(test)]", 1)[0]
        cls.open = (SHELL / "folder_open.rs").read_text(encoding="utf-8").split("#[cfg(test)]", 1)[0]
        cls.lib = (SHELL / "lib.rs").read_text(encoding="utf-8")

    def test_the_conversation_files_are_never_written_and_nothing_else_is_read(self) -> None:
        code = "\n".join(l for l in self.past.splitlines() if not l.lstrip().startswith("//"))
        for banned in ("fs::write", "File::create", "OpenOptions", "remove_file", "remove_dir", "fs::rename", "fs::copy",
                       "create_dir", "set_permissions", "Command::new", "TcpStream", "spawn"):
            self.assertNotIn(banned, code, banned)
        # no login, token or config file of either CLI
        for banned in ("auth.json", ".credentials", "credentials.json", "config.toml", "settings.json", ".claude.json", "oauth", "token"):
            self.assertNotIn(banned, code.lower(), banned)
        # only these names under the CLI's home
        self.assertEqual(sorted(set(re.findall(r'\.join\("([a-z_.]+)"\)', code))), ["projects", "session_index.jsonl", "sessions"])

    def test_links_and_paths_outside_the_home_are_refused_and_reads_are_bounded(self) -> None:
        inside = self.past.split("pub fn inside(", 1)[1].split("\n}\n", 1)[0]
        for needle in ("symlink_metadata(p)", "is_symlink()", "let real = p.canonicalize().ok()?;",
                       "let base = root.canonicalize().ok()?;", "real.starts_with(&base).then_some(real)"):
            self.assertIn(needle, inside)
        self.assertIn("std::fs::symlink_metadata(p).map(|m| m.is_dir())", self.past)
        self.assertIn("const HEAD: u64 = 256 * 1024;", self.past)
        self.assertIn("const TAIL: u64 = 1024 * 1024;", self.past)
        self.assertIn("pub const MSG_MAX: usize = 40;", self.past)
        # every file read goes through inside(): the listing and the messages
        for fn in ("pub fn claude_list(", "pub fn claude_messages(", "pub fn codex_list(", "pub fn codex_messages(", "fn codex_names("):
            body = self.past.split(fn, 1)[1].split("\n}\n", 1)[0]
            self.assertIn("inside(root, ", body, fn)
        # an id is a UUID before it names a file
        for fn in ("pub fn claude_messages(", "pub fn codex_messages("):
            body = self.past.split(fn, 1)[1].split("\n}\n", 1)[0]
            self.assertIn("if !is_uuid(id) {", body, fn)
        text = _flat(DOC.read_text(encoding="utf-8"))
        self.assertIn("It refuses a symlink anywhere under those folders and any file that is not inside that home once its links are resolved", text)
        self.assertIn("never opens a credential, token or config file of either CLI", text)

    def test_the_commands_take_only_an_agent_folders_and_an_id(self) -> None:
        for cmd, params in (("past_chats_list", "agent: String, cwds: Vec<String>"), ("past_chat_messages", "agent: String, id: String, cwd: String"),
                            ("session_reveal", "cwd: String"), ("session_open_terminal", "cwd: String"),
                            ("asks_badge", "window: tauri::WebviewWindow, count: u32")):
            sig = re.search(rf"async fn {cmd}\((.*?)\) -> ", self.lib, re.S)
            self.assertIsNotNone(sig, cmd)
            self.assertEqual(sig.group(1).strip(), params, cmd)
        self.assertIn('matches!(agent, "claude" | "codex")', self.past)

    def test_the_system_terminal_runs_no_command_and_the_folder_is_no_shell_string(self) -> None:
        self.assertEqual(self.open.count("Command::new("), 1)
        launch = self.open.split("pub fn launchers(", 1)[1].split("\n}\n", 1)[0]
        for banned in ('"-e"', '"-x"', '"--command"', '"/k"', '"-c"', '"sh"', '"bash"', "osascript", "format!("):
            self.assertNotIn(banned, launch, banned)
        self.assertIn('vec!["/c".into(), "start".into(), "".into(), "cmd".into()]', launch)
        self.assertIn(".current_dir(&dir).stdin(Stdio::null())", self.open)
        # the folder must exist and be absolute before anything runs
        for fn in ("pub fn open_terminal(", "pub fn reveal("):
            body = self.open.split(fn, 1)[1]
            self.assertTrue(body.split("{\n", 1)[1].lstrip().startswith("let dir = folder(cwd)?;"), fn)
        folder = self.open.split("pub fn folder(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("!p.is_absolute()", folder)
        self.assertIn("real.is_dir()", folder)

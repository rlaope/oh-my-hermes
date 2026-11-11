//! Agent sessions: omher starts one agent program from a FIXED list (`claude`, `codex`, `omo`, `dsh`, `omh`,
//! `pi`, `omp`, `grok`) in a pseudo-terminal (its own terminal UI) or, for a chat, through [`crate::agent_chat`], in a folder the person picked, and stops it when the session is closed or
//! the app quits.
//!
//! The UI only ever names an agent id. The program, its path and its arguments are decided here: an id that
//! is not in [`AGENTS`] is refused, and there is no way to pass a command line or extra arguments from the
//! UI beyond a conversation id to continue ([`resume_args`]). Agent discovery looks on `PATH` plus the usual install folders, because an app started from the Dock
//! or the Start menu gets a much shorter `PATH` than a terminal does.

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;

use crate::bridge::Os;

/// One agent program omher may start.
#[derive(Debug, PartialEq, Eq)]
pub struct Agent {
    /// What the UI sends (`session_start(agent: "claude", …)`).
    pub id: &'static str,
    /// The program looked up on `PATH` and in the install folders.
    pub program: &'static str,
    pub label: &'static str,
    /// How a new session opens: a chat driven through the agent's structured mode, the omher chat on
    /// Hermes (omh, through the bridge), or the agent's own terminal UI.
    pub mode: Mode,
}

/// How a session of an agent opens.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    /// The agent's structured mode (see [`chat_args`]), shown as an omher chat.
    Chat,
    /// oh-my-hermes: a Hermes chat through the bridge, no new program.
    Hermes,
    /// The agent's own terminal UI in a pseudo-terminal.
    Terminal,
}

/// The whole allow-list. Adding a program here is a boundary change (docs/OMHER-BOUNDARY.md rule 11).
pub const AGENTS: [Agent; 8] = [
    Agent { id: "claude", program: "claude", label: "Claude Code", mode: Mode::Chat },
    Agent { id: "codex", program: "codex", label: "Codex", mode: Mode::Chat },
    // OmO (`omo-ai`, oh-my-openagent on the senpi engine) speaks pi's RPC: `omo --mode rpc`, checked against omo
    // 5.0.0-beta.65 (get_state, prompt, agent_end; `--session <id>` continues a conversation).
    Agent { id: "omo", program: "omo", label: "OmO", mode: Mode::Chat },
    // DSH is DeepSeek Harness (deepseek-ai/deepseek-harness), found only where the harness installs its CLI
    // ([`dsh_harness`]), never another `dsh` on PATH. It ships no terminal profile, so its chat runs one
    // `dsh --profile headless --json` per message ([`dsh_turn_args`], crate::dsh_chat), continued by `--session-id`.
    Agent { id: "dsh", program: "dsh", label: "DSH", mode: Mode::Chat },
    Agent { id: "omh", program: "omh", label: "oh-my-hermes", mode: Mode::Hermes },
    Agent { id: "pi", program: "pi", label: "pi", mode: Mode::Chat },
    Agent { id: "omp", program: "omp", label: "oh-my-pi", mode: Mode::Chat },
    // Grok's headless stream is read-only (approvals need ACP, `grok agent stdio`), and grok is not on this
    // machine to verify against, so it keeps the terminal view.
    Agent { id: "grok", program: "grok", label: "Grok", mode: Mode::Terminal },
];

/// Claude Code's structured mode: one long-lived `-p` process reading and writing stream-json, with tool
/// approvals sent to us over the same stream (`--permission-prompt-tool stdio`) instead of a TUI prompt.
pub const CLAUDE_CHAT_ARGS: [&str; 9] = [
    "-p",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--include-partial-messages",
    "--permission-prompt-tool",
    "stdio",
];

/// The fixed arguments that start agent `id` in its structured mode, or `None` when it has none here. These
/// are the only arguments omher ever adds besides a conversation id ([`resume_args`]).
pub fn chat_args(id: &str) -> Option<&'static [&'static str]> {
    match agent(id)?.mode {
        Mode::Chat => Some(match id {
            "claude" => &CLAUDE_CHAT_ARGS[..],
            "codex" => &["app-server"][..],
            "pi" | "omp" | "omo" => &["--mode", "rpc"][..],
            _ => return None,
        }),
        _ => None,
    }
}

/// The argument that continues a conversation: `--resume <id>` for Claude Code (so its terminal view and its
/// chat continue one conversation), `--session <id>` for OmO (the session id it reported), `--session-id <id>`
/// for DSH (the `session-<uuid>` DeepSeek Harness reported). The id must be a UUID (DSH: `session-` and a UUID);
/// every other agent and any other text is refused.
pub fn resume_args(id: &str, session: &str) -> Result<Vec<OsString>, String> {
    let flag = match id {
        "claude" => "--resume",
        "omo" => "--session",
        "dsh" => "--session-id",
        _ => return Err(format!("{id} sessions cannot be resumed")),
    };
    let ok = if id == "dsh" { session.strip_prefix("session-").is_some_and(is_uuid) } else { is_uuid(session) };
    if !ok {
        return Err("not a conversation id".into());
    }
    Ok(vec![flag.into(), session.into()])
}

/// The overlay DSH's chat passes with `--patch`: DeepSeek Harness's shipped headless profile turns off its own
/// saved-credentials store, and these three rows (upstream dsh-headless README, "Credentials") turn it back on
/// for that one run, so the harness uses the keys and sign-in saved in its own app. omher writes this fixed text
/// to [`dsh_patch_path`] and never reads a key; the person's `~/.dsh` is not changed.
pub const DSH_HEADLESS_PATCH: &str = "# omher: DeepSeek Harness's headless runs use the harness's own saved credentials\n\
- id: credentials\n  disabled: false\n- id: authorization\n  disabled: false\n- id: deepseek-account\n  disabled: false\n";

/// `<home>/.omher/dsh/headless.patch.yml`, the one file omher writes for DSH.
pub fn dsh_patch_path(home: &Path) -> PathBuf {
    home.join(".omher").join("dsh").join("headless.patch.yml")
}

/// The arguments of one DSH chat turn, all fixed apart from the overlay path and a checked session id:
/// `--profile headless --patch <overlay> --json [--session-id session-<uuid>] -` (the message goes on stdin).
pub fn dsh_turn_args(patch: &Path, session: Option<&str>) -> Result<Vec<OsString>, String> {
    let mut a: Vec<OsString> = vec!["--profile".into(), "headless".into(), "--patch".into(), patch.as_os_str().to_owned(), "--json".into()];
    if let Some(s) = session {
        a.extend(resume_args("dsh", s)?);
    }
    a.push("-".into());
    Ok(a)
}

/// `8-4-4-4-12` hex digits, nothing else.
pub fn is_uuid(s: &str) -> bool {
    let parts: Vec<&str> = s.split('-').collect();
    parts.len() == 5
        && parts.iter().zip([8, 4, 4, 4, 12]).all(|(p, n)| p.len() == n && p.chars().all(|c| c.is_ascii_hexdigit()))
}

/// The allow-list entry for `id`, or `None` for anything else (paths, command lines, other programs).
pub fn agent(id: &str) -> Option<&'static Agent> {
    AGENTS.iter().find(|a| a.id == id)
}

// ---------------------------------------------------------------------------------------------
// Discovery (pure: env, file check and OS are passed in, so both layouts are tested on any host)
// ---------------------------------------------------------------------------------------------

/// CLI folders that macOS desktop apps carry inside their bundle, relative to an Applications folder.
/// The ChatGPT app (and the Codex app) ship a signed-in Codex CLI there: `bin/codex` is a `/bin/sh`
/// wrapper that execs the sibling `CodexCLI.app/Contents/MacOS/codex`.
const APP_BUNDLE_CLI_DIRS: [&str; 2] =
    ["ChatGPT.app/Contents/Resources/codex-cli/bin", "Codex.app/Contents/Resources/codex-cli/bin"];

/// [`APP_BUNDLE_CLI_DIRS`] under `/Applications`, then under `~/Applications`. Both `search_dirs` (here and
/// in `accounts`) append these after every other folder, so a real install on PATH or in an install folder
/// wins. The folders only exist on macOS.
pub(crate) fn app_bundle_cli_dirs(home: Option<&str>) -> Vec<PathBuf> {
    let mut roots = vec![PathBuf::from("/Applications")];
    roots.extend(home.filter(|h| !h.trim().is_empty()).map(|h| Path::new(h).join("Applications")));
    roots.iter().flat_map(|r| APP_BUNDLE_CLI_DIRS.iter().map(move |d| r.join(d))).collect()
}

/// Folders to look in, in order: every `PATH` entry, then the usual per-user install folders
/// (`~/.local/bin` for Claude Code's installer, Homebrew, npm/pnpm/bun/cargo/volta globals, and on
/// Windows `%APPDATA%\npm`), then on macOS the CLI folders inside app bundles. Duplicates are dropped.
pub fn search_dirs<E: Fn(&str) -> Option<String>>(env: &E, os: Os) -> Vec<PathBuf> {
    let set = |k: &str| env(k).filter(|v| !v.trim().is_empty());
    let mut dirs: Vec<PathBuf> = Vec::new();
    if let Some(path) = set("PATH") {
        let sep = if os == Os::Windows { ';' } else { ':' };
        dirs.extend(path.split(sep).filter(|d| !d.trim().is_empty()).map(PathBuf::from));
    }
    let join = |base: &str, parts: &[&str]| parts.iter().fold(PathBuf::from(base), |p, c| p.join(c));
    match os {
        Os::Unix => {
            if let Some(home) = set("HOME") {
                for parts in [
                    &[".local", "bin"][..],
                    &[".bun", "bin"],
                    &[".cargo", "bin"],
                    &[".npm-global", "bin"],
                    &[".volta", "bin"],
                    &["Library", "pnpm"],
                    &[".local", "share", "pnpm"],
                    // the official installers' own folders, which only a shell's rc file puts on PATH: Grok
                    // (x.ai/cli/install.sh, `~/.grok/bin`) and pi's managed install (pi.dev/install.sh, `~/.pi/agent/bin`)
                    &[".grok", "bin"],
                    &[".pi", "agent", "bin"],
                ] {
                    dirs.push(join(&home, parts));
                }
            }
            if let Some(pnpm) = set("PNPM_HOME") {
                dirs.push(PathBuf::from(pnpm));
            }
            dirs.push(PathBuf::from("/opt/homebrew/bin"));
            dirs.push(PathBuf::from("/usr/local/bin"));
            dirs.extend(app_bundle_cli_dirs(set("HOME").as_deref()));
        }
        Os::Windows => {
            if let Some(appdata) = set("APPDATA") {
                dirs.push(join(&appdata, &["npm"]));
            }
            if let Some(profile) = set("USERPROFILE") {
                for parts in [&[".local", "bin"][..], &[".bun", "bin"], &[".cargo", "bin"], &[".volta", "bin"], &[".grok", "bin"], &[".pi", "agent", "bin"]] {
                    dirs.push(join(&profile, parts));
                }
            }
            if let Some(local) = set("LOCALAPPDATA") {
                dirs.push(join(&local, &["pnpm"]));
            }
            if let Some(pnpm) = set("PNPM_HOME") {
                dirs.push(PathBuf::from(pnpm));
            }
        }
    }
    let mut seen = std::collections::HashSet::new();
    dirs.retain(|d| seen.insert(d.clone()));
    dirs
}

/// File names that start `program`: the bare name on macOS/Linux; `.exe`, then the npm `.cmd` / `.bat`
/// shims on Windows (never `.ps1`, never the extension-less npm shell script).
pub fn file_names(program: &str, os: Os) -> Vec<String> {
    match os {
        Os::Unix => vec![program.to_string()],
        Os::Windows => ["exe", "cmd", "bat"].iter().map(|e| format!("{program}.{e}")).collect(),
    }
}

/// The first `dir/name` that `is_program` accepts.
pub fn resolve<X: Fn(&Path) -> bool>(program: &str, dirs: &[PathBuf], is_program: X, os: Os) -> Option<PathBuf> {
    let names = file_names(program, os);
    dirs.iter().flat_map(|d| names.iter().map(move |n| d.join(n))).find(|p| is_program(p))
}

/// Where DeepSeek Harness puts its CLI, in order: inside the macOS app (`/Applications`, then `~/Applications`),
/// inside the Windows app (its per-user NSIS install, `%LOCALAPPDATA%\\Programs\\DeepSeek Harness`). Linux has no
/// fixed place: the npm package `@deepseek-ai/dsh` on PATH ([`is_dsh_harness`]) is how it is found there.
pub fn dsh_app_clis<E: Fn(&str) -> Option<String>>(env: &E, os: Os) -> Vec<PathBuf> {
    let set = |k: &str| env(k).filter(|v| !v.trim().is_empty());
    let cli = |root: PathBuf, name: &str| ["Resources", "runtime", "cli", "bin", name].iter().fold(root, |p, c| p.join(c));
    match os {
        Os::Unix => {
            let mut roots = vec![PathBuf::from("/Applications")];
            roots.extend(set("HOME").map(|h| Path::new(&h).join("Applications")));
            roots.into_iter().map(|r| cli(r.join("DeepSeek Harness.app").join("Contents"), "dsh")).collect()
        }
        Os::Windows => set("LOCALAPPDATA")
            .map(|l| {
                let app = Path::new(&l).join("Programs").join("DeepSeek Harness");
                ["resources", "runtime", "cli", "bin", "dsh.cmd"].iter().fold(app, |p, c| p.join(c))
            })
            .into_iter()
            .collect(),
    }
}

/// Whether a `dsh` found on PATH is DeepSeek Harness: its real path (links followed) is inside the harness app
/// (`DeepSeek Harness.app`, or `DeepSeek Harness/resources/runtime/cli` on Windows, which is what the app's
/// "Manage dsh Command" installs) or inside the npm package `@deepseek-ai/dsh`; an npm `.cmd` shim counts when
/// that package sits next to it (`node_modules/@deepseek-ai/dsh`). Any other `dsh` (deepseek-bot's launcher in
/// `~/.local/bin` is one) is not.
pub fn is_dsh_harness<X: Fn(&Path) -> bool>(found: &Path, real: &Path, exists: X) -> bool {
    let parts: Vec<String> = real.components().map(|c| c.as_os_str().to_string_lossy().to_string()).collect();
    let has = |i: usize, s: &str| parts.get(i).is_some_and(|p| p.eq_ignore_ascii_case(s));
    let inside_app = parts.iter().any(|p| p == "DeepSeek Harness.app")
        || (0..parts.len()).any(|i| has(i, "DeepSeek Harness") && has(i + 1, "resources") && has(i + 2, "runtime") && has(i + 3, "cli"));
    let npm = parts.windows(2).any(|w| w[0] == "@deepseek-ai" && w[1] == "dsh");
    let shim = found.parent().is_some_and(|d| exists(&d.join("node_modules").join("@deepseek-ai").join("dsh").join("package.json")));
    inside_app || npm || shim
}

/// The DeepSeek Harness CLI on this machine: the app's own CLI first, then a `dsh` in `dirs` that
/// [`is_dsh_harness`] accepts. `real` resolves links. Never the first `dsh` on PATH just because it is first.
pub fn dsh_harness<E, X, R>(env: &E, dirs: &[PathBuf], is_program: X, real: R, os: Os) -> Option<PathBuf>
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
    R: Fn(&Path) -> PathBuf,
{
    if let Some(p) = dsh_app_clis(env, os).into_iter().find(|p| is_program(p)) {
        return Some(p);
    }
    let names = file_names("dsh", os);
    dirs.iter().flat_map(|d| names.iter().map(move |n| d.join(n))).find(|p| is_program(p) && is_dsh_harness(p, &real(p), |q| is_program(q) || q.is_file()))
}

/// Where an agent's official installs put its program, so a same-named other program earlier on PATH (Homebrew's
/// `grok` regex tool, a `pi` or `codex` of some other project) is not started as the agent. A found program
/// matches when its real path (links followed) holds one of these. DSH has its own check ([`is_dsh_harness`]);
/// oh-my-hermes has no row and is found as before.
pub struct Layout {
    pub id: &'static str,
    /// npm (or bun) packages: `node_modules/<package>` in the real path, or on Windows an npm `.cmd` shim with
    /// `node_modules/<package>/package.json` beside it.
    pub packages: &'static [&'static str],
    /// Folder names that follow each other anywhere in the real path (an app bundle, a Homebrew keg, an
    /// installer's own folder).
    pub inside: &'static [&'static [&'static str]],
    /// Folders a standalone installer copies the program itself into, under the home folder (`~`) or
    /// `%LOCALAPPDATA%`: the real path's folder must be one of them.
    pub folders: &'static [(&'static str, &'static [&'static str])],
    /// The install line omher shows for it (the same text as `INSTALL` in src/sessions/agents.ts).
    pub install: &'static str,
}

pub const LAYOUTS: [Layout; 6] = [
    Layout {
        id: "claude",
        packages: &["@anthropic-ai/claude-code"],
        // the native installer (`~/.local/bin/claude` -> `~/.local/share/claude/versions/<v>`), Homebrew's cask
        inside: &[&[".local", "share", "claude", "versions"], &["Caskroom", "claude-code"]],
        // Windows: the native installer's own `claude.exe`
        folders: &[("~", &[".local", "bin"])],
        install: "npm i -g @anthropic-ai/claude-code",
    },
    Layout {
        id: "codex",
        packages: &["@openai/codex"],
        // the CLI inside the ChatGPT or Codex app (APP_BUNDLE_CLI_DIRS), Homebrew's cask
        inside: &[&["ChatGPT.app", "Contents", "Resources", "codex-cli"], &["Codex.app", "Contents", "Resources", "codex-cli"], &["Caskroom", "codex"]],
        folders: &[],
        install: "npm i -g @openai/codex",
    },
    Layout {
        id: "omo",
        packages: &["omo-ai"],
        inside: &[],
        // get.omo.dev/install.sh and install.ps1 copy the binary into ~/.local/bin
        folders: &[("~", &[".local", "bin"])],
        install: "npm i -g omo-ai",
    },
    Layout {
        id: "pi",
        packages: &["@earendil-works/pi-coding-agent", "@mariozechner/pi-coding-agent"],
        // pi.dev/install.sh's managed install (its launcher `~/.pi/agent/bin/pi`, which a link in ~/.local/bin
        // or Homebrew's bin may lead to), Homebrew's formula
        inside: &[&[".pi", "agent", "bin"], &["Cellar", "pi-coding-agent"]],
        folders: &[],
        install: "npm i -g --ignore-scripts @earendil-works/pi-coding-agent",
    },
    Layout {
        id: "omp",
        packages: &["@oh-my-pi/pi-coding-agent"],
        // Homebrew's tap (can1357/tap/omp)
        inside: &[&["Cellar", "omp"]],
        // omp.sh/install's binary (~/.local/bin/omp; %LOCALAPPDATA%\\omp\\omp.exe on Windows)
        folders: &[("~", &[".local", "bin"]), ("LOCALAPPDATA", &["omp"])],
        install: "curl -fsSL https://omp.sh/install | sh",
    },
    Layout {
        id: "grok",
        packages: &["@xai-official/grok"],
        // x.ai/cli/install.sh: `~/.grok/bin/grok` -> `grok-<version>` (or into ~/.grok/downloads)
        inside: &[&[".grok", "bin"], &[".grok", "downloads"]],
        folders: &[],
        install: "curl -fsSL https://x.ai/cli/install.sh | bash",
    },
];

/// The [`LAYOUTS`] row of agent `id`.
pub fn layout(id: &str) -> Option<&'static Layout> {
    LAYOUTS.iter().find(|l| l.id == id)
}

/// A path's folder names, split on both separators so a Windows path reads the same on any host.
fn parts_of(p: &Path) -> Vec<String> {
    // (the `?` of a Windows `\\?\` canonical path is no folder)
    p.to_string_lossy().split(['/', '\\']).filter(|c| !c.is_empty() && *c != "?").map(str::to_string).collect()
}

fn holds(parts: &[String], seq: &[&str]) -> bool {
    !seq.is_empty() && parts.windows(seq.len()).any(|w| w.iter().zip(seq).all(|(a, b)| a.eq_ignore_ascii_case(b)))
}

/// Whether program `found` (real path `real`, links followed) sits where an official install of agent `id` puts it
/// ([`LAYOUTS`]). `exists` checks a file (the npm package beside a Windows shim). An agent without a row: false.
pub fn in_install_layout<E, X>(id: &str, found: &Path, real: &Path, env: &E, exists: X) -> bool
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
{
    let Some(l) = layout(id) else { return false };
    let parts = parts_of(real);
    let package = |pkg: &str| {
        let seq: Vec<&str> = std::iter::once("node_modules").chain(pkg.split('/')).collect();
        holds(&parts, &seq) || found.parent().is_some_and(|d| exists(&pkg.split('/').fold(d.join("node_modules"), |p, c| p.join(c)).join("package.json")))
    };
    let set = |k: &str| env(k).filter(|v| !v.trim().is_empty());
    let folder = |(base, rel): &(&str, &[&str])| {
        let root = if *base == "~" { set("HOME").or_else(|| set("USERPROFILE")) } else { set(base) };
        let Some(root) = root else { return false };
        let want: Vec<String> = parts_of(Path::new(&root)).into_iter().chain(rel.iter().map(|s| s.to_string())).collect();
        // the real path's folder (by both separators: `Path::parent` would not split a Windows path elsewhere)
        let have = &parts[..parts.len().saturating_sub(1)];
        have.len() == want.len() && have.iter().zip(&want).all(|(a, b)| a.eq_ignore_ascii_case(b))
    };
    l.packages.iter().any(|p| package(p)) || l.inside.iter().any(|seq| holds(&parts, seq)) || l.folders.iter().any(folder)
}

/// Program `program` of agent `id` in `dirs`: the first candidate that [`in_install_layout`] accepts, else (no row, or
/// no candidate in a known layout) the first candidate, as [`resolve`] finds it. A real install in a layout this
/// table does not know is therefore still found, never "Not installed".
pub fn find_in_layouts<E, X, R>(id: &str, program: &str, dirs: &[PathBuf], env: &E, is_program: X, real: R, os: Os) -> Option<PathBuf>
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
    R: Fn(&Path) -> PathBuf,
{
    let names = file_names(program, os);
    let found: Vec<PathBuf> = dirs.iter().flat_map(|d| names.iter().map(move |n| d.join(n))).filter(|p| is_program(p)).collect();
    found.iter().find(|p| in_install_layout(id, p, &real(p), env, |q| is_program(q) || q.is_file())).or(found.first()).cloned()
}

fn real_path(p: &Path) -> PathBuf {
    std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf())
}

/// Where allow-listed agent `a` is on this machine: [`find_in_layouts`] over `dirs`, except DSH ([`dsh_harness`]).
fn find_agent(a: &Agent, dirs: &[PathBuf]) -> Option<PathBuf> {
    if a.id == "dsh" {
        return dsh_harness(&host_env, dirs, is_program_file, real_path, Os::current());
    }
    find_in_layouts(a.id, a.program, dirs, &host_env, is_program_file, real_path, Os::current())
}

/// The program omher would start for agent `id` when it lies in none of that agent's install layouts ([`LAYOUTS`]),
/// so it may be another program with the same name; `None` when it is in one, or the agent has no row.
pub fn unrecognized_program(id: &str) -> Option<PathBuf> {
    let a = agent(id)?;
    layout(id)?;
    let path = find_agent(a, &host_dirs())?;
    (!in_install_layout(id, &path, &real_path(&path), &host_env, |q| is_program_file(q) || q.is_file())).then_some(path)
}

/// argv for a resolved program. A Windows `.cmd`/`.bat` shim runs through `cmd.exe /c`, because
/// CreateProcess does not start batch files on its own. No other argument is ever added.
pub fn argv_for(path: &Path, os: Os) -> Result<Vec<OsString>, String> {
    let ext = path.extension().and_then(|e| e.to_str()).map(|e| e.to_ascii_lowercase());
    if os == Os::Windows && matches!(ext.as_deref(), Some("cmd") | Some("bat")) {
        Ok(vec!["cmd.exe".into(), "/c".into(), cmd_path_arg(&path.to_string_lossy())?.into()])
    } else {
        Ok(vec![path.as_os_str().to_owned()])
    }
}

/// The shim path as `cmd.exe /c` must see it. cmd parses that line itself, so `&`, `|`, `<`, `>`, `^`,
/// `(`, `)` and `@` in a folder name would split or change the command. Without whitespace, the path
/// reaches cmd unquoted (portable-pty quotes only on whitespace), so each of those gets a `^` escape.
/// With whitespace it arrives in quotes, and cmd keeps quotes only when no such character is inside, so
/// that case is refused, as is `%` (variable expansion, which no escape stops on a `/c` line).
pub fn cmd_path_arg(path: &str) -> Result<String, String> {
    const META: &[char] = &['&', '|', '<', '>', '^', '(', ')', '@'];
    let refuse = || Err(format!("cannot start {path} through cmd.exe: its folder name has characters cmd treats as commands"));
    if path.contains('%') || path.contains('"') {
        return refuse();
    }
    if path.chars().any(char::is_whitespace) {
        return if path.contains(META) { refuse() } else { Ok(path.to_string()) };
    }
    let mut out = String::with_capacity(path.len() + 4);
    for c in path.chars() {
        if META.contains(&c) {
            out.push('^');
        }
        out.push(c);
    }
    Ok(out)
}

fn host_env(k: &str) -> Option<String> {
    std::env::var(k).ok()
}

#[cfg(unix)]
fn is_program_file(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(p).map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
}

#[cfg(not(unix))]
fn is_program_file(p: &Path) -> bool {
    p.is_file()
}

/// `search_dirs` on this machine plus the newest nvm Node (`~/.nvm/versions/node/<v>/bin`), which npm
/// globals such as Codex live in when Node came from nvm. The nvm folders go before the app-bundle tail, so
/// an npm install still wins over the ChatGPT app's copy.
fn host_dirs() -> Vec<PathBuf> {
    let os = Os::current();
    let mut dirs = search_dirs(&host_env, os);
    if os == Os::Unix {
        if let Some(home) = host_env("HOME") {
            let nvm = Path::new(&home).join(".nvm").join("versions").join("node");
            if let Ok(rd) = std::fs::read_dir(&nvm) {
                let mut vs: Vec<PathBuf> = rd.flatten().map(|e| e.path().join("bin")).filter(|p| p.is_dir()).collect();
                vs.sort();
                vs.reverse();
                let bundles = app_bundle_cli_dirs(Some(&home));
                let at = dirs.len() - dirs.iter().rev().take_while(|d| bundles.contains(d)).count();
                dirs.splice(at..at, vs);
            }
        }
    }
    dirs
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct AgentInfo {
    pub id: &'static str,
    pub label: &'static str,
    pub mode: Mode,
    /// Where the program was found, or `None` when it is not installed.
    pub path: Option<String>,
}

/// Every allow-listed agent with where it was found on this machine.
pub fn agents_on_this_machine() -> Vec<AgentInfo> {
    let dirs = host_dirs();
    AGENTS
        .iter()
        .map(|a| AgentInfo {
            id: a.id,
            label: a.label,
            mode: a.mode,
            path: find_agent(a, &dirs).map(|p| p.to_string_lossy().into_owned()),
        })
        .collect()
}

/// What omher runs for agent `id`: the allow-list entry resolved on this machine, as argv, plus the
/// `PATH` the child gets (the program's own folder and the install folders first, so `#!/usr/bin/env node`
/// shims find Node even when the app was started from the Dock).
pub fn launch_for(id: &str) -> Result<(Vec<OsString>, OsString), String> {
    let a = agent(id).ok_or_else(|| format!("unknown agent \"{id}\""))?;
    let dirs = host_dirs();
    let path = find_agent(a, &dirs).ok_or_else(|| match a.id {
        "dsh" => "DeepSeek Harness is not installed (no DeepSeek Harness `dsh` found)".to_string(),
        _ => format!("{} is not installed (no `{}` found)", a.label, a.program),
    })?;
    let mut child_dirs: Vec<PathBuf> = path.parent().map(|p| vec![p.to_path_buf()]).unwrap_or_default();
    child_dirs.extend(dirs);
    let joined = std::env::join_paths(child_dirs.iter().filter(|d| d.is_dir())).map_err(|e| e.to_string())?;
    Ok((argv_for(&path, Os::current())?, joined))
}

// ---------------------------------------------------------------------------------------------
// Live sessions
// ---------------------------------------------------------------------------------------------

/// What a session sends back: terminal bytes, then once, the exit (code; `None` when a signal ended it).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Output {
    Data(Vec<u8>),
    Exit(Option<u32>),
}

type Sink = Arc<Mutex<Box<dyn FnMut(Output) + Send>>>;

struct Live {
    master: Box<dyn MasterPty + Send>,
    /// Input for the session's writer thread. The PTY takes only about 1 KB before a write blocks, so the
    /// write happens there, never under the sessions lock.
    input: SyncSender<Vec<u8>>,
    /// Set by the writer thread when it ends.
    writer_done: Arc<AtomicBool>,
    killer: Box<dyn ChildKiller + Send + Sync>,
    pid: Option<u32>,
    exited: Arc<AtomicBool>,
}

/// Pending writes per session (keystrokes or whole pastes). A program that stops reading fills it, and
/// further writes fail at once instead of piling up.
pub(crate) const INPUT_QUEUE: usize = 256;

/// Reads from the PTY are merged into one message of up to this many bytes...
pub(crate) const COALESCE_BYTES: usize = 64 * 1024;
/// ...collected for at most this long after the first byte arrives (keeps typing echo prompt).
pub(crate) const COALESCE_WINDOW: Duration = Duration::from_millis(4);

/// Every running session of this app. Dropped sessions are stopped; [`Sessions::close_all`] runs on exit.
#[derive(Default)]
pub struct Sessions {
    live: Mutex<HashMap<u32, Live>>,
    next: AtomicU32,
}

fn clamp_size(cols: u16, rows: u16) -> PtySize {
    PtySize { cols: cols.clamp(2, 1000), rows: rows.clamp(2, 500), pixel_width: 0, pixel_height: 0 }
}

impl Sessions {
    pub fn new() -> Arc<Sessions> {
        Arc::new(Sessions::default())
    }

    /// Start `argv` in a new pseudo-terminal in `cwd`. Crate-internal: the app reaches it only through
    /// [`Sessions::start_agent`], so argv always comes from the allow-list (tests use it directly).
    pub(crate) fn spawn<F>(
        &self,
        argv: Vec<OsString>,
        cwd: &Path,
        path_env: Option<OsString>,
        account_env: &[(String, String)],
        cols: u16,
        rows: u16,
        sink: F,
    ) -> Result<u32, String>
    where
        F: FnMut(Output) + Send + 'static,
    {
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(format!("not a folder: {}", cwd.display()));
        }
        let pair = native_pty_system().openpty(clamp_size(cols, rows)).map_err(|e| e.to_string())?;
        let cmd = command_for(argv, cwd, path_env, account_env);
        let mut child = pair.slave.spawn_command(cmd).map_err(|e| e.to_string())?;
        drop(pair.slave); // only the child holds the terminal side, so its exit ends our reads
        let reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
        let mut writer = pair.master.take_writer().map_err(|e| e.to_string())?;
        let killer = child.clone_killer();
        let pid = child.process_id();
        let exited = Arc::new(AtomicBool::new(false));
        let sink: Sink = Arc::new(Mutex::new(Box::new(sink)));

        let id = self.next.fetch_add(1, Ordering::SeqCst) + 1;
        spawn_reader(reader, sink.clone());
        let (input, queued) = mpsc::sync_channel::<Vec<u8>>(INPUT_QUEUE);
        let writer_done = Arc::new(AtomicBool::new(false));
        {
            let done = writer_done.clone();
            thread::spawn(move || {
                for chunk in queued {
                    if writer.write_all(&chunk).and_then(|_| writer.flush()).is_err() {
                        break;
                    }
                }
                drop(writer);
                done.store(true, Ordering::SeqCst);
            });
        }
        {
            let exited = exited.clone();
            thread::spawn(move || {
                let code = match child.wait() {
                    Ok(st) if st.signal().is_none() => Some(st.exit_code()),
                    _ => None,
                };
                exited.store(true, Ordering::SeqCst);
                // let the reader drain what the program printed last
                thread::sleep(Duration::from_millis(120));
                if let Ok(mut f) = sink.lock() {
                    f(Output::Exit(code));
                }
            });
        }
        self.live.lock().unwrap().insert(id, Live { master: pair.master, input, writer_done, killer, pid, exited });
        Ok(id)
    }

    /// Start allow-listed agent `agent` in `cwd`. Anything not in [`AGENTS`] is refused before a process
    /// exists. `account_env` is `accounts::session_env` for that agent: the chosen account's home variable,
    /// or nothing. `resume` (Claude Code) continues that conversation in the agent's own terminal UI.
    pub fn start_agent<F>(
        &self,
        agent_id: &str,
        cwd: &Path,
        resume: Option<&str>,
        account_env: &[(String, String)],
        cols: u16,
        rows: u16,
        sink: F,
    ) -> Result<u32, String>
    where
        F: FnMut(Output) + Send + 'static,
    {
        // DeepSeek Harness ships no terminal profile: DSH runs only as a chat
        if agent_id == "dsh" {
            return Err("DeepSeek Harness has no terminal view here".into());
        }
        let (mut argv, path_env) = launch_for(agent_id)?;
        if let Some(r) = resume {
            argv.extend(resume_args(agent_id, r)?);
        }
        self.spawn(argv, cwd, Some(path_env), account_env, cols, rows, sink)
    }

    /// Queue `data` for session `id`'s writer thread. Never blocks: a program that is not reading its
    /// input makes this fail once the queue is full.
    pub fn write(&self, id: u32, data: &[u8]) -> Result<(), String> {
        let input = self.live.lock().unwrap().get(&id).ok_or("no such session")?.input.clone();
        match input.try_send(data.to_vec()) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => Err("the program is not reading its input".into()),
            Err(TrySendError::Disconnected(_)) => Err("the session's input is closed".into()),
        }
    }

    pub fn resize(&self, id: u32, cols: u16, rows: u16) -> Result<(), String> {
        let g = self.live.lock().unwrap();
        let s = g.get(&id).ok_or("no such session")?;
        s.master.resize(clamp_size(cols, rows)).map_err(|e| e.to_string())
    }

    /// Stop the session's program (hang-up, then a hard kill after a grace period) and forget it.
    pub fn close(&self, id: u32) {
        let live = self.live.lock().unwrap().remove(&id);
        if let Some(s) = live {
            thread::spawn(move || stop(s, Duration::from_millis(1500)));
        }
    }

    /// Stop every session now (the app is quitting).
    pub fn close_all(&self) {
        let all: Vec<Live> = self.live.lock().unwrap().drain().map(|(_, s)| s).collect();
        let handles: Vec<_> = all.into_iter().map(|s| thread::spawn(move || stop(s, Duration::from_millis(400)))).collect();
        for h in handles {
            let _ = h.join();
        }
    }

    #[cfg(test)]
    pub fn count(&self) -> usize {
        self.live.lock().unwrap().len()
    }
}

/// The command a session runs: `argv` in `cwd`, with the terminal variables, the child `PATH`, and the chosen
/// account's home variable (`account_env`, empty for the CLI's own login). Nothing else is added.
fn command_for(argv: Vec<OsString>, cwd: &Path, path_env: Option<OsString>, account_env: &[(String, String)]) -> CommandBuilder {
    let mut cmd = CommandBuilder::from_argv(argv);
    cmd.cwd(cwd);
    cmd.env("TERM", "xterm-256color");
    cmd.env("COLORTERM", "truecolor");
    cmd.env("TERM_PROGRAM", "omher");
    if let Some(p) = path_env {
        cmd.env("PATH", p);
    }
    #[cfg(unix)]
    if std::env::var_os("LANG").is_none() {
        // A Dock-started app has no locale; the agents' TUIs need UTF-8.
        cmd.env("LANG", "en_US.UTF-8");
    }
    for (k, v) in account_env {
        cmd.env(k, v);
    }
    crate::appimage::host_env(&mut cmd);
    cmd
}

/// One thread reads the PTY (macOS hands out at most 1 KB per read); another merges what arrives into
/// one message per [`COALESCE_WINDOW`] / [`COALESCE_BYTES`], so a big dump is a few dozen Channel sends
/// instead of one per KB.
fn spawn_reader(mut reader: Box<dyn Read + Send>, sink: Sink) {
    let (tx, rx) = mpsc::channel::<Vec<u8>>();
    thread::spawn(move || {
        let mut buf = [0u8; 16 * 1024];
        loop {
            match reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if tx.send(buf[..n].to_vec()).is_err() {
                        break;
                    }
                }
            }
        }
    });
    thread::spawn(move || {
        coalesce(rx, COALESCE_BYTES, COALESCE_WINDOW, |b| {
            if let Ok(mut f) = sink.lock() {
                f(Output::Data(b));
            }
        })
    });
}

/// Wait for a chunk, then keep taking chunks until `max` bytes or `window` after that first chunk, and
/// emit them as one buffer. Returns when the sender is gone and everything was emitted.
pub(crate) fn coalesce(rx: Receiver<Vec<u8>>, max: usize, window: Duration, mut emit: impl FnMut(Vec<u8>)) {
    while let Ok(mut buf) = rx.recv() {
        let deadline = Instant::now() + window;
        let mut open = true;
        while buf.len() < max {
            let left = deadline.saturating_duration_since(Instant::now());
            match rx.recv_timeout(left) {
                Ok(more) => buf.extend_from_slice(&more),
                Err(RecvTimeoutError::Timeout) => break,
                Err(RecvTimeoutError::Disconnected) => {
                    open = false;
                    break;
                }
            }
        }
        emit(buf);
        if !open {
            return;
        }
    }
}

/// Hang up the program's process group, wait up to `grace`, then kill it hard. Dropping the master side
/// closes the terminal, which hangs up anything still attached to it. A writer thread stuck on a full PTY
/// is waited for only briefly: it ends once the terminal is gone, and nothing here waits on it for long.
fn stop(mut s: Live, grace: Duration) {
    // A program that already ended is not signalled: its pid may belong to someone else by now.
    if !s.exited.load(Ordering::SeqCst) {
        signal_group(s.pid, false);
        let _ = s.killer.kill();
    }
    let Live { master, input, writer_done, exited, pid, .. } = s;
    drop(input); // the writer thread ends after the write it is in, if any
    let wait = |flag: &AtomicBool, limit: Duration| {
        let deadline = Instant::now() + limit;
        while !flag.load(Ordering::SeqCst) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(25));
        }
        flag.load(Ordering::SeqCst)
    };
    if !wait(&exited, grace) {
        signal_group(pid, true);
    }
    drop(master);
    wait(&writer_done, Duration::from_millis(200));
}

/// SIGHUP (or SIGKILL when `hard`) to the session's process group. The child is a session leader (the
/// PTY made it one), so its group id is its pid and helpers it started go too. Windows: the ConPTY close
/// and `TerminateProcess` from the killer end it.
#[cfg(unix)]
pub(crate) fn signal_group(pid: Option<u32>, hard: bool) {
    if let Some(pid) = pid.filter(|p| *p > 1) {
        let sig = if hard { libc::SIGKILL } else { libc::SIGHUP };
        unsafe {
            libc::kill(-(pid as i32), sig);
            if hard {
                libc::kill(pid as i32, sig);
            }
        }
    }
}

#[cfg(not(unix))]
pub(crate) fn signal_group(_pid: Option<u32>, _hard: bool) {}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn env_of(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let m: HashMap<String, String> = pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        move |k| m.get(k).cloned()
    }

    fn fs_of(files: &[&Path]) -> impl Fn(&Path) -> bool {
        let set: HashSet<PathBuf> = files.iter().map(|p| p.to_path_buf()).collect();
        move |p| set.contains(p)
    }

    #[test]
    fn allow_list_is_exactly_the_eight_agents() {
        let ids: Vec<&str> = AGENTS.iter().map(|a| a.id).collect();
        assert_eq!(ids, ["claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok"]);
        for a in &AGENTS {
            assert_eq!(a.id, a.program, "the id is the program name; nothing else is ever run");
        }
    }

    #[test]
    fn modes_and_the_fixed_chat_arguments() {
        let modes: Vec<(&str, Mode)> = AGENTS.iter().map(|a| (a.id, a.mode)).collect();
        assert_eq!(
            modes,
            [
                ("claude", Mode::Chat),
                ("codex", Mode::Chat),
                ("omo", Mode::Chat),
                ("dsh", Mode::Chat),
                ("omh", Mode::Hermes),
                ("pi", Mode::Chat),
                ("omp", Mode::Chat),
                ("grok", Mode::Terminal)
            ]
        );
        assert_eq!(
            chat_args("claude").unwrap(),
            ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--include-partial-messages", "--permission-prompt-tool", "stdio"]
        );
        assert_eq!(chat_args("codex").unwrap(), ["app-server"]);
        assert_eq!(chat_args("pi").unwrap(), ["--mode", "rpc"]);
        assert_eq!(chat_args("omp").unwrap(), ["--mode", "rpc"]);
        assert_eq!(chat_args("omo").unwrap(), ["--mode", "rpc"]);
        // DSH's chat takes its arguments per message (dsh_turn_args), not here
        for none in ["omh", "grok", "dsh", "sh", "", "claude -p"] {
            assert!(chat_args(none).is_none(), "{none}");
        }
        let p = Path::new("/h/.omher/dsh/headless.patch.yml");
        assert_eq!(dsh_turn_args(p, None).unwrap(), ["--profile", "headless", "--patch", "/h/.omher/dsh/headless.patch.yml", "--json", "-"].map(OsString::from));
        let sid = "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8";
        assert_eq!(
            dsh_turn_args(p, Some(sid)).unwrap(),
            ["--profile", "headless", "--patch", "/h/.omher/dsh/headless.patch.yml", "--json", "--session-id", sid, "-"].map(OsString::from)
        );
        for bad in ["", "8c11e2bc-9f55-4bcb-a597-19ea472184e8", "session-x", "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8 --approval-policy", "--from-default-profile"] {
            assert!(dsh_turn_args(p, Some(bad)).is_err(), "{bad:?}");
        }
        // no turn argument widens permissions, names another profile or touches the harness's own setup
        for a in dsh_turn_args(p, Some(sid)).unwrap() {
            let a = a.to_string_lossy();
            assert!(!a.contains("permission") && !a.contains("approval") && !a.contains("plugin") && !a.contains("default-profile"), "{a}");
        }
        // no allow-listed argument can run a shell, skip permissions or load extra config
        for a in AGENTS.iter().filter_map(|a| chat_args(a.id)).flatten() {
            assert!(!a.contains("dangerously") && !a.contains("bypass") && !a.contains("config") && !a.contains("mcp"), "{a}");
        }
    }

    #[test]
    fn resume_takes_only_a_claude_uuid() {
        let id = "eee5079a-c52e-4526-b633-f3d8cb7d6394";
        assert_eq!(resume_args("claude", id).unwrap(), [OsString::from("--resume"), OsString::from(id)]);
        for bad in ["", "x", "--dangerously-skip-permissions", "eee5079a-c52e-4526-b633-f3d8cb7d639", "eee5079a-c52e-4526-b633-f3d8cb7d6394 --x", "../eee5079a-c52e-4526-b633-f3d8cb7d6394", "eee5079a_c52e_4526_b633_f3d8cb7d6394"] {
            assert!(resume_args("claude", bad).is_err(), "{bad:?}");
        }
        assert!(resume_args("codex", id).is_err());
        // OmO continues with --session, only with a UUID
        assert_eq!(resume_args("omo", id).unwrap(), [OsString::from("--session"), OsString::from(id)]);
        // DSH continues DeepSeek Harness's own `session-<uuid>` with --session-id; a bare UUID (a 0.2.4 deepseek-bot
        // conversation id) is refused
        let sid = format!("session-{id}");
        assert_eq!(resume_args("dsh", &sid).unwrap(), [OsString::from("--session-id"), OsString::from(&sid)]);
        assert!(resume_args("dsh", id).is_err());
        for agent in ["omo", "dsh"] {
            for bad in ["", "default", "--yolo", "eee5079a-c52e-4526-b633-f3d8cb7d6394 --x", "../x"] {
                assert!(resume_args(agent, bad).is_err(), "{agent} {bad:?}");
            }
        }
        for agent in ["pi", "omp", "grok", "omh"] {
            assert!(resume_args(agent, id).is_err(), "{agent}");
        }
        let s = Sessions::default();
        assert!(s.start_agent("claude", &std::env::temp_dir(), Some("--yolo"), &[], 80, 24, |_| {}).is_err());
        assert_eq!(s.count(), 0);
    }

    /// The DeepSeek Harness CLI is found where the harness installs it, never as "the first `dsh` on PATH":
    /// deepseek-bot's launcher in ~/.local/bin, first on PATH, is skipped.
    #[test]
    fn dsh_is_deepseek_harness_not_the_first_dsh_on_path() {
        let env = env_of(&[("PATH", "/Users/k/.local/bin:/usr/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        let bot = PathBuf::from("/Users/k/.local/bin/dsh");
        let app = PathBuf::from("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh");
        let user_app = PathBuf::from("/Users/k/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh");
        let same = |p: &Path| p.to_path_buf();
        // the plain lookup would start deepseek-bot
        assert_eq!(resolve("dsh", &dirs, fs_of(&[&bot, &app]), Os::Unix), Some(bot.clone()));
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &app]), same, Os::Unix), Some(app.clone()));
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &user_app]), same, Os::Unix), Some(user_app));
        // deepseek-bot alone: DSH is not installed
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot]), same, Os::Unix), None);
        // the app's "Manage dsh Command" link in /usr/local/bin and the npm package count, by where they lead
        let link = PathBuf::from("/usr/local/bin/dsh");
        let to_app = |p: &Path| if p == link { app.clone() } else { p.to_path_buf() };
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &link]), to_app, Os::Unix), Some(link.clone()));
        let npm = PathBuf::from("/opt/homebrew/bin/dsh");
        let to_npm = |p: &Path| if p == npm { PathBuf::from("/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/lib/bin.js") } else { p.to_path_buf() };
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &npm]), to_npm, Os::Unix), Some(npm));
        // a `dsh` that leads anywhere else is not the harness
        let other = |p: &Path| if p == link { PathBuf::from("/Users/k/Desktop/deepseek-bot/dist/tui/main.js") } else { p.to_path_buf() };
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &link]), other, Os::Unix), None);
        // Linux: npm only (no app folder)
        let lin = env_of(&[("PATH", "/home/k/.local/bin:/home/k/.npm-global/bin"), ("HOME", "/home/k")]);
        let ldirs = search_dirs(&lin, Os::Unix);
        let lnpm = PathBuf::from("/home/k/.npm-global/bin/dsh");
        let lbot = PathBuf::from("/home/k/.local/bin/dsh");
        let to_lnpm = |p: &Path| if p == lnpm { PathBuf::from("/home/k/.npm-global/lib/node_modules/@deepseek-ai/dsh/lib/bin.js") } else { p.to_path_buf() };
        assert_eq!(dsh_harness(&lin, &ldirs, fs_of(&[&lbot, &lnpm]), to_lnpm, Os::Unix), Some(lnpm));
    }

    #[test]
    fn dsh_on_windows_is_the_app_cli_or_the_npm_shim() {
        let env = env_of(&[("PATH", r"C:\Users\k\.local\bin;C:\Users\k\AppData\Roaming\npm"), ("LOCALAPPDATA", r"C:\Users\k\AppData\Local"), ("APPDATA", r"C:\Users\k\AppData\Roaming"), ("USERPROFILE", r"C:\Users\k")]);
        let dirs = search_dirs(&env, Os::Windows);
        let app = dsh_app_clis(&env, Os::Windows);
        assert_eq!(app, [Path::new(r"C:\Users\k\AppData\Local").join("Programs").join("DeepSeek Harness").join("resources").join("runtime").join("cli").join("bin").join("dsh.cmd")]);
        let same = |p: &Path| p.to_path_buf();
        let bot = Path::new(r"C:\Users\k\.local\bin").join("dsh.cmd");
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &app[0]]), same, Os::Windows), Some(app[0].clone()));
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot]), same, Os::Windows), None);
        // the npm shim counts when @deepseek-ai/dsh sits next to it
        let npm_dir = Path::new(r"C:\Users\k\AppData\Roaming\npm");
        let shim = npm_dir.join("dsh.cmd");
        let pkg = npm_dir.join("node_modules").join("@deepseek-ai").join("dsh").join("package.json");
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &shim, &pkg]), same, Os::Windows), Some(shim.clone()));
        assert_eq!(dsh_harness(&env, &dirs, fs_of(&[&bot, &shim]), same, Os::Windows), None);
        // and DeepSeek Harness never opens in a terminal session
        let s = Sessions::default();
        assert!(s.start_agent("dsh", &std::env::temp_dir(), None, &[], 80, 24, |_| {}).is_err());
        assert_eq!(s.count(), 0);
    }

    #[test]
    fn refuses_anything_not_on_the_allow_list() {
        assert!(agent("claude").is_some());
        for bad in ["", "sh", "bash", "/bin/sh", "claude --dangerously-skip-permissions", "claude;rm -rf ~", "CLAUDE", " claude", "../claude", "codex.cmd"] {
            assert!(agent(bad).is_none(), "{bad:?} must be refused");
            assert!(launch_for(bad).is_err(), "{bad:?} must not launch");
        }
    }

    #[test]
    fn start_agent_refuses_an_unknown_id_before_any_process() {
        let s = Sessions::default();
        let tmp = std::env::temp_dir();
        let err = s.start_agent("/bin/sh", &tmp, None, &[], 80, 24, |_| {}).unwrap_err();
        assert!(err.contains("unknown agent"), "{err}");
        assert_eq!(s.count(), 0);
    }

    #[test]
    fn unix_dirs_are_path_then_install_folders_without_duplicates() {
        let env = env_of(&[("PATH", "/usr/bin:/bin:/opt/homebrew/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        assert_eq!(dirs[0], PathBuf::from("/usr/bin"));
        assert!(dirs.contains(&PathBuf::from("/Users/k/.local/bin")));
        assert!(dirs.contains(&PathBuf::from("/usr/local/bin")));
        assert_eq!(dirs.iter().filter(|d| **d == PathBuf::from("/opt/homebrew/bin")).count(), 1);
        // the folders Grok's and pi's official installers use, which only a shell rc file puts on PATH
        assert!(dirs.contains(&PathBuf::from("/Users/k/.grok/bin")));
        assert!(dirs.contains(&PathBuf::from("/Users/k/.pi/agent/bin")));
        let grok = PathBuf::from("/Users/k/.grok/bin/grok");
        let pi = PathBuf::from("/Users/k/.pi/agent/bin/pi");
        let short = env_of(&[("PATH", "/usr/bin:/bin"), ("HOME", "/Users/k")]);
        let sdirs = search_dirs(&short, Os::Unix);
        assert_eq!(resolve("grok", &sdirs, fs_of(&[&grok]), Os::Unix), Some(grok));
        assert_eq!(resolve("pi", &sdirs, fs_of(&[&pi]), Os::Unix), Some(pi));
        let win = env_of(&[("USERPROFILE", r"C:\Users\k")]);
        let wdirs = search_dirs(&win, Os::Windows);
        assert!(wdirs.contains(&Path::new(r"C:\Users\k").join(".grok").join("bin")));
        assert!(wdirs.contains(&Path::new(r"C:\Users\k").join(".pi").join("agent").join("bin")));
    }

    /// H1: a same-named other program earlier on PATH (the QA report's shadow stubs; Homebrew's `grok` regex tool)
    /// is passed over for the agent's own install; with no install in a known layout, the first one is still found.
    #[test]
    fn agents_are_found_in_their_install_layout_not_as_the_first_same_name_on_path() {
        let env = env_of(&[("PATH", "/Users/k/shadow:/opt/homebrew/bin:/usr/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        // (agent, its real install as found on PATH or in an install folder, where that leads)
        let real_installs: [(&str, &str, &str); 12] = [
            ("claude", "/Users/k/.local/bin/claude", "/Users/k/.local/share/claude/versions/2.1.322"),
            ("claude", "/opt/homebrew/bin/claude", "/opt/homebrew/Caskroom/claude-code/2.1.311/claude"),
            ("codex", "/Users/k/.local/bin/codex", "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"),
            ("codex", "/opt/homebrew/bin/codex", "/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js"),
            ("omo", "/Users/k/.local/bin/omo", "/Users/k/.local/bin/omo"),
            ("omo", "/opt/homebrew/bin/omo", "/opt/homebrew/lib/node_modules/omo-ai/bin/omo.js"),
            ("pi", "/opt/homebrew/bin/pi", "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"),
            ("pi", "/Users/k/.local/bin/pi", "/Users/k/.pi/agent/bin/pi"),
            ("omp", "/Users/k/.bun/bin/omp", "/Users/k/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js"),
            ("omp", "/Users/k/.local/bin/omp", "/Users/k/.local/bin/omp"),
            ("grok", "/Users/k/.grok/bin/grok", "/Users/k/.grok/bin/grok-1.0.77"),
            ("grok", "/usr/local/bin/grok", "/Users/k/.grok/downloads/grok-1.0.77"),
        ];
        for (id, found, leads_to) in real_installs {
            let shadow = PathBuf::from(format!("/Users/k/shadow/{id}"));
            let found = PathBuf::from(found);
            let real = |p: &Path| if p == found { PathBuf::from(leads_to) } else { p.to_path_buf() };
            // the plain lookup starts the shadow, the layout check the agent
            assert_eq!(resolve(id, &dirs, fs_of(&[&shadow, &found]), Os::Unix), Some(shadow.clone()), "{id}");
            assert_eq!(find_in_layouts(id, id, &dirs, &env, fs_of(&[&shadow, &found]), real, Os::Unix), Some(found.clone()), "{id} {leads_to}");
            assert!(in_install_layout(id, &found, Path::new(leads_to), &env, |_| false), "{id} {leads_to}");
            assert!(!in_install_layout(id, &shadow, &shadow, &env, |_| false), "{id}");
            // only the shadow: still found (a real install in a layout the table does not know never reads "Not installed")
            assert_eq!(find_in_layouts(id, id, &dirs, &env, fs_of(&[&shadow]), real, Os::Unix), Some(shadow.clone()), "{id}");
        }
        // Homebrew's `grok` (jordansissel/grok, a regex tool) is not Grok
        let brew = PathBuf::from("/opt/homebrew/bin/grok");
        assert!(!in_install_layout("grok", &brew, Path::new("/opt/homebrew/Cellar/grok/0.9.2/bin/grok"), &env, |_| false));
        // another agent's package is not this one: oh-my-pi's npm package is not pi
        assert!(!in_install_layout("pi", &brew, Path::new("/x/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js"), &env, |_| false));
        // a standalone installer's folder counts only for the program itself, not for anything below it
        assert!(!in_install_layout("omo", &brew, Path::new("/Users/k/.local/bin/x/omo"), &env, |_| false));
        // oh-my-hermes has no row: found as before
        let omh = PathBuf::from("/Users/k/shadow/omh");
        assert_eq!(find_in_layouts("omh", "omh", &dirs, &env, fs_of(&[&omh]), |p: &Path| p.to_path_buf(), Os::Unix), Some(omh));
    }

    #[test]
    fn windows_agents_are_found_in_their_install_layout() {
        let env = env_of(&[
            ("PATH", r"C:\tools;C:\Users\k\AppData\Roaming\npm"),
            ("APPDATA", r"C:\Users\k\AppData\Roaming"),
            ("USERPROFILE", r"C:\Users\k"),
            ("LOCALAPPDATA", r"C:\Users\k\AppData\Local"),
        ]);
        let same = |p: &Path| p.to_path_buf();
        let npm = Path::new(r"C:\Users\k\AppData\Roaming\npm");
        // an npm shim counts when its package sits beside it
        let shim = npm.join("codex.cmd");
        let pkg = npm.join("node_modules").join("@openai").join("codex").join("package.json");
        assert!(in_install_layout("codex", &shim, &shim, &env, fs_of(&[&pkg])));
        assert!(!in_install_layout("codex", &shim, &shim, &env, fs_of(&[])));
        // the official installers' own folders
        for (id, path) in [
            ("grok", r"C:\Users\k\.grok\bin\grok.exe"),
            ("pi", r"C:\Users\k\.pi\agent\bin\pi.cmd"),
            ("omp", r"C:\Users\k\AppData\Local\omp\omp.exe"),
            ("omo", r"C:\Users\k\.local\bin\omo.exe"),
            ("claude", r"C:\Users\k\.local\bin\claude.exe"),
        ] {
            assert!(in_install_layout(id, Path::new(path), Path::new(path), &env, fs_of(&[])), "{path}");
        }
        let dirs = search_dirs(&env, Os::Windows);
        let shadow = Path::new(r"C:\tools").join("grok.exe");
        let grok = Path::new(r"C:\Users\k").join(".grok").join("bin").join("grok.exe");
        assert_eq!(find_in_layouts("grok", "grok", &dirs, &env, fs_of(&[&shadow, &grok]), same, Os::Windows), Some(grok));
    }

    /// The install line omher names when a program does not look like the agent is the one the menu shows.
    #[test]
    fn layout_install_lines_are_the_menus() {
        let ts = std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("../src/sessions/agents.ts")).unwrap();
        for l in &LAYOUTS {
            assert!(ts.contains(&format!("  {}: \"{}\",", l.id, l.install)), "{} {}", l.id, l.install);
            assert!(agent(l.id).is_some_and(|a| a.mode == Mode::Chat || a.mode == Mode::Terminal), "{}", l.id);
        }
        assert!(layout("dsh").is_none() && layout("omh").is_none());
    }

    #[test]
    fn unix_dirs_end_with_the_cli_folders_inside_app_bundles() {
        let env = env_of(&[("PATH", "/usr/bin:/Applications/Codex.app/Contents/Resources/codex-cli/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        assert_eq!(dirs[..2], [PathBuf::from("/usr/bin"), PathBuf::from("/Applications/Codex.app/Contents/Resources/codex-cli/bin")]);
        // the PATH copy is kept where PATH put it, not repeated in the tail
        assert_eq!(
            dirs[dirs.len() - 3..],
            [
                PathBuf::from("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin"),
                PathBuf::from("/Users/k/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin"),
                PathBuf::from("/Users/k/Applications/Codex.app/Contents/Resources/codex-cli/bin"),
            ]
        );
        let unique: HashSet<&PathBuf> = dirs.iter().collect();
        assert_eq!(unique.len(), dirs.len());
        // a real install wins over the ChatGPT app's copy; the copy is found when it is the only one
        let bundled = PathBuf::from("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex");
        let npm = PathBuf::from("/opt/homebrew/bin/codex");
        assert_eq!(resolve("codex", &dirs, &fs_of(&[&bundled, &npm]), Os::Unix), Some(npm));
        assert_eq!(resolve("codex", &dirs, &fs_of(&[&bundled]), Os::Unix), Some(bundled));
        let home_only = env_of(&[("HOME", "/Users/k"), ("USERPROFILE", "C:/Users/k")]);
        assert!(!search_dirs(&home_only, Os::Windows).iter().any(|d| d.to_string_lossy().contains(".app")));
    }

    #[test]
    fn finds_claude_in_local_bin_when_the_app_path_is_short() {
        // A Dock-started app sees PATH=/usr/bin:/bin; Claude Code's installer puts it in ~/.local/bin.
        let env = env_of(&[("PATH", "/usr/bin:/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        let claude = PathBuf::from("/Users/k/.local/bin/claude");
        let codex = PathBuf::from("/opt/homebrew/bin/codex");
        let fs = fs_of(&[&claude, &codex]);
        assert_eq!(resolve("claude", &dirs, &fs, Os::Unix), Some(claude.clone()));
        assert_eq!(resolve("codex", &dirs, &fs, Os::Unix), Some(codex));
        assert_eq!(resolve("pi", &dirs, &fs, Os::Unix), None);
        assert_eq!(argv_for(&claude, Os::Unix).unwrap(), vec![OsString::from(claude.as_os_str())]);
    }

    #[test]
    fn windows_finds_npm_shims_and_runs_them_through_cmd() {
        let env = env_of(&[
            ("PATH", "C:/Windows/System32;C:/Program Files/nodejs"),
            ("APPDATA", "C:/Users/k/AppData/Roaming"),
            ("USERPROFILE", "C:/Users/k"),
        ]);
        let dirs = search_dirs(&env, Os::Windows);
        assert!(dirs.contains(&PathBuf::from("C:/Users/k/AppData/Roaming").join("npm")));
        let shim = PathBuf::from("C:/Users/k/AppData/Roaming").join("npm").join("codex.cmd");
        let script = PathBuf::from("C:/Users/k/AppData/Roaming").join("npm").join("codex");
        let exe = PathBuf::from("C:/Users/k").join(".local").join("bin").join("claude.exe");
        let fs = fs_of(&[&shim, &script, &exe]);
        // never the extension-less shell script npm also writes
        assert_eq!(resolve("codex", &dirs, &fs, Os::Windows), Some(shim.clone()));
        assert_eq!(resolve("claude", &dirs, &fs, Os::Windows), Some(exe.clone()));
        assert_eq!(argv_for(&shim, Os::Windows).unwrap(), vec![OsString::from("cmd.exe"), OsString::from("/c"), shim.into_os_string()]);
        assert_eq!(argv_for(&exe, Os::Windows).unwrap(), vec![exe.into_os_string()]);
        assert_eq!(file_names("omp", Os::Windows), ["omp.exe", "omp.cmd", "omp.bat"]);
    }

    #[test]
    fn windows_shim_paths_are_escaped_for_cmd() {
        // no whitespace: reaches cmd unquoted, so cmd's operators get a ^
        assert_eq!(cmd_path_arg(r"C:\Users\A&B\npm\codex.cmd").unwrap(), r"C:\Users\A^&B\npm\codex.cmd");
        assert_eq!(cmd_path_arg(r"C:\x^y\a|b\(1)\<c>@\codex.cmd").unwrap(), r"C:\x^^y\a^|b\^(1^)\^<c^>^@\codex.cmd");
        assert_eq!(cmd_path_arg(r"C:\Users\k\AppData\Roaming\npm\codex.cmd").unwrap(), r"C:\Users\k\AppData\Roaming\npm\codex.cmd");
        // whitespace only: quoted by the PTY layer, and cmd keeps those quotes
        assert_eq!(cmd_path_arg(r"C:\Users\Kim Lee\npm\codex.cmd").unwrap(), r"C:\Users\Kim Lee\npm\codex.cmd");
        // whitespace plus an operator, or %: cmd would split it, so refuse
        for bad in [r"C:\Users\A & B\npm\codex.cmd", r"C:\Program Files (x86)\npm\codex.cmd", r"C:\%PATH%\codex.cmd", r"C:\a\b%c\codex.cmd"] {
            assert!(cmd_path_arg(bad).is_err(), "{bad}");
        }
        let shim = PathBuf::from(r"C:\Users\A&B\npm\codex.cmd");
        assert_eq!(argv_for(&shim, Os::Windows).unwrap()[2], OsString::from(r"C:\Users\A^&B\npm\codex.cmd"));
        assert!(argv_for(Path::new(r"C:\A & B\codex.bat"), Os::Windows).is_err());
        // an .exe never goes through cmd, so its path is left alone
        let exe = PathBuf::from(r"C:\A & B\claude.exe");
        assert_eq!(argv_for(&exe, Os::Windows).unwrap(), vec![exe.into_os_string()]);
    }

    #[test]
    fn coalesce_merges_reads_up_to_the_size_cap() {
        let (tx, rx) = mpsc::channel();
        for _ in 0..200 {
            tx.send(vec![b'a'; 1024]).unwrap();
        }
        drop(tx);
        let mut out = Vec::new();
        coalesce(rx, 64 * 1024, Duration::from_secs(5), |b| out.push(b.len()));
        assert_eq!(out.iter().sum::<usize>(), 200 * 1024);
        assert_eq!(out, [64 * 1024, 64 * 1024, 64 * 1024, 8 * 1024]);
    }

    #[test]
    fn coalesce_sends_a_lone_keystroke_after_the_window() {
        let (tx, rx) = mpsc::channel();
        let (got_tx, got) = mpsc::channel();
        let t = thread::spawn(move || coalesce(rx, 64 * 1024, Duration::from_millis(4), |b| got_tx.send((b, Instant::now())).unwrap()));
        let sent = Instant::now();
        tx.send(b"k".to_vec()).unwrap();
        let (b, at) = got.recv_timeout(Duration::from_secs(2)).expect("a lone chunk must not wait for more");
        assert_eq!(b, b"k");
        assert!(at - sent < Duration::from_millis(100), "{:?}", at - sent);
        drop(tx);
        t.join().unwrap();
    }

    #[test]
    fn empty_env_still_has_system_folders() {
        let dirs = search_dirs(&env_of(&[]), Os::Unix);
        assert!(dirs.contains(&PathBuf::from("/opt/homebrew/bin")));
        assert!(search_dirs(&env_of(&[]), Os::Windows).is_empty());
    }

    #[cfg(unix)]
    fn collect(s: &Sessions, argv: &[&str], cols: u16, rows: u16) -> (u32, Arc<Mutex<Vec<u8>>>, Arc<Mutex<Option<Option<u32>>>>) {
        let out = Arc::new(Mutex::new(Vec::new()));
        let exit = Arc::new(Mutex::new(None));
        let (o, x) = (out.clone(), exit.clone());
        let id = s
            .spawn(argv.iter().map(OsString::from).collect(), &std::env::temp_dir().canonicalize().unwrap(), None, &[], cols, rows, move |ev| match ev {
                Output::Data(b) => o.lock().unwrap().extend(b),
                Output::Exit(c) => *x.lock().unwrap() = Some(c),
            })
            .unwrap();
        (id, out, exit)
    }

    #[cfg(unix)]
    fn wait_for(cond: impl Fn() -> bool) -> bool {
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline {
            if cond() {
                return true;
            }
            thread::sleep(Duration::from_millis(20));
        }
        false
    }

    #[cfg(unix)]
    #[test]
    fn pty_runs_in_the_folder_with_the_size_and_reports_exit() {
        let s = Sessions::default();
        let (_id, out, exit) = collect(&s, &["/bin/sh", "-c", "pwd; stty size; exit 3"], 91, 27);
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "no exit");
        let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
        assert!(text.contains("27 91"), "{text:?}");
        assert!(text.contains(&std::env::temp_dir().canonicalize().unwrap().to_string_lossy().to_string()), "{text:?}");
        assert_eq!(*exit.lock().unwrap(), Some(Some(3)));
    }

    #[cfg(unix)]
    #[test]
    fn pty_runs_the_chatgpt_apps_codex_wrapper() {
        // the layout and wrapper the ChatGPT app ships: bin/codex is a sh script that resolves its own folder
        // and execs ../CodexCLI.app/Contents/MacOS/codex with the arguments
        use std::os::unix::fs::PermissionsExt;
        let root = std::env::temp_dir().canonicalize().unwrap().join(format!("omher-bundle-{}", std::process::id()));
        let bin = root.join("ChatGPT.app/Contents/Resources/codex-cli/bin");
        let real = root.join("ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS");
        std::fs::create_dir_all(&bin).unwrap();
        std::fs::create_dir_all(&real).unwrap();
        let wrapper = "#!/bin/sh\nset -eu\nentry=\"$0\"\nwhile [ -L \"$entry\" ]; do\n  parent=$(CDPATH= cd -P -- \"$(dirname -- \"$entry\")\" && pwd)\n  entry=$(readlink \"$entry\")\n  case \"$entry\" in /*) ;; *) entry=\"$parent/$entry\" ;; esac\ndone\nbin_dir=$(CDPATH= cd -P -- \"$(dirname -- \"$entry\")\" && pwd)\nexec \"$bin_dir/../CodexCLI.app/Contents/MacOS/codex\" \"$@\"\n";
        for (p, body) in [(bin.join("codex"), wrapper), (real.join("codex"), "#!/bin/sh\necho \"bundled codex $*\"\n")] {
            std::fs::write(&p, body).unwrap();
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
        let path = resolve("codex", &[bin.clone()], is_program_file, Os::Unix).expect("wrapper found");
        let argv = argv_for(&path, Os::Unix).unwrap();
        assert_eq!(argv, vec![OsString::from(bin.join("codex"))]);
        let s = Sessions::default();
        let (out, exit) = (Arc::new(Mutex::new(Vec::new())), Arc::new(Mutex::new(None)));
        let (o, x) = (out.clone(), exit.clone());
        let mut argv = argv;
        argv.push("--version".into());
        s.spawn(argv, &root, Some(OsString::from("/usr/bin:/bin")), &[], 80, 24, move |ev| match ev {
            Output::Data(b) => o.lock().unwrap().extend(b),
            Output::Exit(c) => *x.lock().unwrap() = Some(c),
        })
        .unwrap();
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "no exit");
        let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
        assert!(text.contains("bundled codex --version"), "{text:?}");
        assert_eq!(*exit.lock().unwrap(), Some(Some(0)));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn typing_reaches_the_program_and_close_stops_it() {
        let s = Sessions::default();
        let (id, out, exit) = collect(&s, &["/bin/cat"], 80, 24);
        s.write(id, b"ping\r").unwrap();
        assert!(wait_for(|| String::from_utf8_lossy(&out.lock().unwrap()).matches("ping").count() >= 2), "cat did not echo");
        s.resize(id, 100, 30).unwrap();
        s.close(id);
        assert_eq!(s.count(), 0);
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "close did not stop cat");
        assert!(s.write(id, b"x").is_err());
    }

    #[cfg(unix)]
    #[test]
    fn close_all_kills_a_program_that_ignores_hangup() {
        let s = Sessions::default();
        let (_id, out, exit) = collect(&s, &["/bin/sh", "-c", "trap '' HUP; echo ready; while :; do sleep 1; done"], 80, 24);
        assert!(wait_for(|| String::from_utf8_lossy(&out.lock().unwrap()).contains("ready")));
        s.close_all();
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "SIGHUP-ignoring program survived close_all");
    }

    #[cfg(unix)]
    #[test]
    fn a_big_write_to_a_program_that_never_reads_blocks_nothing() {
        let s = Sessions::default();
        let (id, out, exit) = collect(&s, &["/bin/sh", "-c", "stty raw -echo; echo ready; sleep 60"], 80, 24);
        let (other, other_out, _) = collect(&s, &["/bin/cat"], 80, 24);
        assert!(wait_for(|| String::from_utf8_lossy(&out.lock().unwrap()).contains("ready")));
        // 1 MB in 64 KB pastes: the PTY takes about 1 KB, the rest must not hold anything up
        let started = Instant::now();
        for _ in 0..16 {
            s.write(id, &vec![b'x'; 64 * 1024]).unwrap();
        }
        assert!(started.elapsed() < Duration::from_millis(500), "write blocked: {:?}", started.elapsed());
        // other sessions keep working while that one is stuck
        s.write(other, b"pong\r").unwrap();
        s.resize(other, 100, 30).unwrap();
        assert!(wait_for(|| String::from_utf8_lossy(&other_out.lock().unwrap()).contains("pong")), "other session stalled");
        let t = Instant::now();
        s.close_all();
        assert!(t.elapsed() < Duration::from_secs(2), "close_all took {:?}", t.elapsed());
        assert_eq!(s.count(), 0);
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "the stuck program survived close_all");
    }

    #[cfg(unix)]
    #[test]
    fn a_large_dump_arrives_in_few_messages() {
        let s = Sessions::default();
        let events = Arc::new(Mutex::new(Vec::<usize>::new()));
        let exit = Arc::new(Mutex::new(None));
        let (e, x) = (events.clone(), exit.clone());
        s.spawn(
            ["/bin/sh", "-c", "head -c 524288 /dev/zero | tr '\\0' a"].iter().map(OsString::from).collect(),
            &std::env::temp_dir().canonicalize().unwrap(),
            None,
            &[],
            80,
            24,
            move |ev| match ev {
                Output::Data(b) => e.lock().unwrap().push(b.len()),
                Output::Exit(c) => *x.lock().unwrap() = Some(c),
            },
        )
        .unwrap();
        assert!(wait_for(|| exit.lock().unwrap().is_some()));
        let ev = events.lock().unwrap();
        let total: usize = ev.iter().sum();
        assert!(total >= 524288, "{total}");
        // 1 KB per read would be over 500 messages
        assert!(ev.len() < 64, "{} messages for {total} bytes", ev.len());
    }

    #[test]
    fn refuses_a_cwd_that_is_not_a_folder() {
        let s = Sessions::default();
        assert!(s.spawn(vec!["x".into()], Path::new("relative/dir"), None, &[], 80, 24, |_| {}).is_err());
        assert!(s.spawn(vec!["x".into()], &std::env::temp_dir().join("omher-no-such-dir-x9"), None, &[], 80, 24, |_| {}).is_err());
    }

    /// A temp home whose `active.json` picks `active` for claude, with that account's folder made.
    fn home_with_claude(name: &str, active: &str) -> PathBuf {
        let home = std::env::temp_dir().join(format!("omher-sess-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        let root = home.join(".omher").join("accounts");
        std::fs::create_dir_all(root.join("claude").join("work")).unwrap();
        std::fs::write(root.join("active.json"), format!(r#"{{"claude":"{active}"}}"#)).unwrap();
        home
    }

    #[test]
    fn a_claude_session_carries_the_stacked_account_home_and_this_computer_carries_none() {
        let cwd = std::env::temp_dir();
        let argv = || vec![OsString::from("/x/claude")];
        let extra = |cmd: &CommandBuilder| -> Vec<(String, String)> {
            cmd.iter_extra_env_as_str().map(|(k, v)| (k.to_string(), v.to_string())).collect()
        };
        let base = extra(&command_for(argv(), &cwd, None, &[]));

        let home = home_with_claude("stacked", "work");
        let env = crate::accounts::session_env(&home, "claude");
        let cmd = command_for(argv(), &cwd, None, &env);
        let work = home.join(".omher").join("accounts").join("claude").join("work");
        assert_eq!(cmd.get_env("CLAUDE_CONFIG_DIR"), Some(work.as_os_str()));
        assert_eq!(cmd.get_argv(), &argv(), "the account changes no argument");
        // the chosen account's home is the only thing added
        let mut added: Vec<_> = extra(&cmd).into_iter().filter(|p| !base.contains(p)).collect();
        added.sort();
        assert_eq!(added, vec![("CLAUDE_CONFIG_DIR".to_string(), work.to_string_lossy().into_owned())]);

        let mine = home_with_claude("this-computer", "default");
        let cmd = command_for(argv(), &cwd, None, &crate::accounts::session_env(&mine, "claude"));
        assert_eq!(extra(&cmd), base);
        assert!(!extra(&cmd).iter().any(|(k, _)| k == "CLAUDE_CONFIG_DIR"));
        let _ = (std::fs::remove_dir_all(home), std::fs::remove_dir_all(mine));
    }

    #[cfg(unix)]
    #[test]
    fn the_account_home_reaches_the_program() {
        let home = home_with_claude("pty", "work");
        let s = Sessions::default();
        let out = Arc::new(Mutex::new(Vec::new()));
        let exit = Arc::new(Mutex::new(None));
        let (o, x) = (out.clone(), exit.clone());
        let argv = ["/bin/sh", "-c", "echo \"cfg=${CLAUDE_CONFIG_DIR-unset}\""].iter().map(OsString::from).collect();
        s.spawn(argv, &std::env::temp_dir().canonicalize().unwrap(), None, &crate::accounts::session_env(&home, "claude"), 80, 24, move |ev| match ev {
            Output::Data(b) => o.lock().unwrap().extend(b),
            Output::Exit(c) => *x.lock().unwrap() = Some(c),
        })
        .unwrap();
        assert!(wait_for(|| exit.lock().unwrap().is_some()));
        let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
        let work = home.join(".omher").join("accounts").join("claude").join("work");
        assert!(text.contains(&format!("cfg={}", work.display())), "{text:?}");
        let _ = std::fs::remove_dir_all(home);
    }

    /// The real check on a developer machine: `claude --version` / `codex --version` through the same
    /// discovery and PTY path a session uses. Ignored by default (needs the programs installed):
    /// `cargo test real_agents_print_their_version -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_agents_print_their_version() {
        let s = Sessions::default();
        let mut ran = 0;
        for info in agents_on_this_machine() {
            println!("{:<7} {}", info.id, info.path.as_deref().unwrap_or("not installed"));
            if !matches!(info.id, "claude" | "codex") || info.path.is_none() {
                continue;
            }
            let (mut argv, path_env) = launch_for(info.id).unwrap();
            argv.push("--version".into()); // test only: sessions never take arguments
            let out = Arc::new(Mutex::new(Vec::new()));
            let exit = Arc::new(Mutex::new(None));
            let (o, x) = (out.clone(), exit.clone());
            let home = PathBuf::from(host_env("HOME").or_else(|| host_env("USERPROFILE")).unwrap());
            s.spawn(argv, &home, Some(path_env), &[], 80, 24, move |ev| match ev {
                Output::Data(b) => o.lock().unwrap().extend(b),
                Output::Exit(c) => *x.lock().unwrap() = Some(c),
            })
            .unwrap();
            let deadline = Instant::now() + Duration::from_secs(30);
            while exit.lock().unwrap().is_none() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(50));
            }
            let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
            println!("{} --version via PTY -> exit {:?}, output {:?}", info.id, *exit.lock().unwrap(), text.trim());
            assert_eq!(*exit.lock().unwrap(), Some(Some(0)));
            assert!(text.chars().any(|c| c.is_ascii_digit()), "{text:?}");
            ran += 1;
        }
        assert!(ran > 0, "neither claude nor codex is installed");
    }
}

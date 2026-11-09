//! Accounts: the coding-CLI logins on this computer, and adding another subscription through the CLI's own login.
//!
//! * `account_env(cli, id)` gives the env a new session of `cli` starts with to use the omher account
//!   `~/.omher/accounts/<cli>/<id>/` (CLAUDE_CONFIG_DIR, CODEX_HOME, PI_CODING_AGENT_DIR, GROK_HOME,
//!   GEMINI_CLI_HOME). `default` is the CLI's own home on this computer: no env.
//! * The only programs run here are the CLIs' own status and login commands, as FIXED argv from
//!   [`fixed_args`] (`claude auth status --json`, `claude auth login`, `codex --help`, `codex login status`,
//!   `codex login`), resolved in the PATH and install folders. Nothing the page sends reaches a command line:
//!   the page names a CLI and an account id, both checked against fixed lists.
//! * The browser sign-in happens inside the CLI. omher never sees, asks for or accepts a token or key; from a
//!   status it keeps only [`LoginStatus`] (signed in, email, plan, method), never the CLI's text.

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::bridge::Os;

/// Every coding CLI Accounts knows, in page order.
pub const ACCOUNT_CLIS: [&str; 6] = ["claude", "codex", "pi", "omp", "grok", "gemini"];
const STATUS_TIMEOUT: Duration = Duration::from_secs(10);

/// The env var each CLI reads for its home folder (Claude Code CLAUDE_CONFIG_DIR, Codex CODEX_HOME, pi and
/// oh-my-pi PI_CODING_AGENT_DIR, Grok Build GROK_HOME, Gemini CLI GEMINI_CLI_HOME).
pub fn home_var(cli: &str) -> Option<&'static str> {
    match cli {
        "claude" => Some("CLAUDE_CONFIG_DIR"),
        "codex" => Some("CODEX_HOME"),
        "pi" | "omp" => Some("PI_CODING_AGENT_DIR"),
        "grok" => Some("GROK_HOME"),
        "gemini" => Some("GEMINI_CLI_HOME"),
        _ => None,
    }
}

/// Same rule as the bridge: lower-case letters, digits, `.`, `_`, `-`; up to 40; not `default`.
pub fn valid_account_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 40
        && id != "default"
        && b[0].is_ascii_alphanumeric()
        && !b[0].is_ascii_uppercase()
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, b'.' | b'_' | b'-'))
        && !id.contains("..")
}

/// `<home>/.omher/accounts/<cli>/<id>`.
pub fn account_dir(home: &Path, cli: &str, id: &str) -> Result<PathBuf, String> {
    home_var(cli).ok_or("unknown cli")?;
    if !valid_account_id(id) {
        return Err("bad account id".into());
    }
    Ok(home.join(".omher").join("accounts").join(cli).join(id))
}

/// The env a new session of `cli` starts with to use account `id`. `default` is the CLI's own home: no env.
pub fn account_env(home: &Path, cli: &str, id: &str) -> Result<Vec<(String, String)>, String> {
    let var = home_var(cli).ok_or("unknown cli")?;
    if id == "default" {
        return Ok(Vec::new());
    }
    let dir = account_dir(home, cli, id)?;
    Ok(vec![(var.to_string(), dir.to_string_lossy().into_owned())])
}

/// The Accounts CLI a SESSIONS agent signs in as: claude, codex and grok map 1:1. omh has no login of its own,
/// and pi / omp sessions do not take an account yet, so those start with the CLI's own home.
pub fn session_cli(agent: &str) -> Option<&'static str> {
    match agent {
        "claude" => Some("claude"),
        "codex" => Some("codex"),
        "grok" => Some("grok"),
        _ => None,
    }
}

/// The account new sessions of `cli` use: `active.json`'s `{cli: id}` (written by the bridge's
/// `accounts.set_active`), when that id is a valid name whose folder still exists; otherwise `default`.
/// Reads omher's own `active.json` only, never a CLI's login file.
pub fn active_account(home: &Path, cli: &str) -> String {
    let file = home.join(".omher").join("accounts").join("active.json");
    let id = std::fs::read_to_string(file)
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v.get(cli).and_then(|x| x.as_str()).map(str::to_string));
    match id {
        Some(id) if account_dir(home, cli, &id).map(|d| d.is_dir() && !d.is_symlink()).unwrap_or(false) => id,
        _ => "default".to_string(),
    }
}

/// The extra env a new session of SESSIONS agent `agent` starts with: the chosen account's home variable
/// (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GROK_HOME`) pointing at its folder, or nothing for "This computer",
/// no choice, or an agent without accounts.
pub fn session_env(home: &Path, agent: &str) -> Vec<(String, String)> {
    let Some(cli) = session_cli(agent) else {
        return Vec::new();
    };
    account_env(home, cli, &active_account(home, cli)).unwrap_or_default()
}

// ---------------------------------------------------------------------------------------------
// The fixed commands
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    /// Does this CLI have the status command (`codex --help` lists `login`)?
    Help,
    Status,
    Login,
}

/// The whole allow-list of what Accounts runs: program = the CLI id, arguments = these. `'static`, so no
/// runtime text can become an argument.
pub fn fixed_args(cli: &str, step: Step) -> Option<&'static [&'static str]> {
    match (cli, step) {
        ("claude", Step::Status) => Some(&["auth", "status", "--json"]),
        ("claude", Step::Login) => Some(&["auth", "login"]),
        ("codex", Step::Help) => Some(&["--help"]),
        ("codex", Step::Status) => Some(&["login", "status"]),
        ("codex", Step::Login) => Some(&["login"]),
        _ => None,
    }
}

/// What omher keeps from a CLI's status: never its text, a token or a key.
#[derive(Debug, Clone, Default, Serialize, PartialEq, Eq)]
pub struct LoginStatus {
    pub logged_in: bool,
    pub email: Option<String>,
    /// `max_20x`, `pro`, … (the page words it).
    pub plan: Option<String>,
    /// `claude.ai`, `chatgpt`, `api_key`, …
    pub method: Option<String>,
    pub last_refresh: Option<String>,
}

/// The fields of `claude auth status --json` omher reads; serde skips every other one.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ClaudeStatus {
    logged_in: Option<bool>,
    email: Option<String>,
    plan_tier: Option<String>,
    subscription_type: Option<String>,
    auth_method: Option<String>,
}

fn short(s: Option<String>, n: usize) -> Option<String> {
    s.map(|v| v.trim().chars().filter(|c| !c.is_control()).take(n).collect::<String>()).filter(|v| !v.is_empty())
}

pub fn parse_claude_status(stdout: &str) -> Option<LoginStatus> {
    let s: ClaudeStatus = serde_json::from_str(stdout.trim()).ok()?;
    let logged_in = s.logged_in.unwrap_or(false);
    Some(LoginStatus {
        logged_in,
        email: if logged_in { short(s.email, 120).filter(|e| e.contains('@')) } else { None },
        plan: if logged_in { short(s.plan_tier.or(s.subscription_type), 40) } else { None },
        method: short(s.auth_method, 40),
        last_refresh: None,
    })
}

/// `codex login status` prints a fixed phrase on stderr (`Logged in using ChatGPT`, or `API key configured -
/// sk-…` with part of the key). Only the exit code and which phrase it was are kept; the text never leaves.
pub fn parse_codex_status(code: Option<i32>, stderr: &str) -> LoginStatus {
    let method = if stderr.contains("ChatGPT") {
        Some("chatgpt".to_string())
    } else if stderr.contains("API key") {
        Some("api_key".to_string())
    } else {
        None
    };
    LoginStatus { logged_in: code == Some(0) && method.is_some(), email: None, plan: None, method, last_refresh: None }
}

/// The two fields of Codex's `auth.json` omher may read when the CLI has no status command. The `tokens`
/// object and the key are skipped by serde without being kept; `id_token` is never decoded.
#[derive(Deserialize)]
struct CodexAuthFile {
    #[serde(default, deserialize_with = "string_or_none")]
    auth_mode: Option<String>,
    #[serde(default, deserialize_with = "string_or_none")]
    last_refresh: Option<String>,
}

/// A string field, or `None` for any other JSON value (so a wrong-typed field is dropped, not echoed).
fn string_or_none<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<String>, D::Error> {
    Ok(match serde_json::Value::deserialize(d)? {
        serde_json::Value::String(s) => Some(s),
        _ => None,
    })
}

pub fn codex_status_from_file(path: &Path) -> LoginStatus {
    let Ok(text) = std::fs::read_to_string(path) else {
        return LoginStatus::default();
    };
    match serde_json::from_str::<CodexAuthFile>(&text) {
        Ok(f) => {
            let method = short(f.auth_mode, 40)
                .filter(|m| m.len() <= 24 && m.bytes().all(|c| c.is_ascii_lowercase() || c == b'_'));
            let refresh = short(f.last_refresh, 40)
                .filter(|r| r.bytes().all(|c| c.is_ascii_digit() || matches!(c, b'-' | b':' | b'.' | b'T' | b'Z' | b'+')));
            LoginStatus { logged_in: method.is_some(), email: None, plan: None, method, last_refresh: refresh }
        }
        Err(_) => LoginStatus::default(),
    }
}

/// Whether `codex --help` lists the `login` command (older builds lack `login status`).
pub fn codex_has_login(help: &str) -> bool {
    help.lines().any(|l| l.trim_start().starts_with("login "))
}

// ---------------------------------------------------------------------------------------------
// Finding the CLIs (a Dock-started app has PATH=/usr/bin:/bin)
// ---------------------------------------------------------------------------------------------

/// PATH first, then the folders CLI installers use: `~/.local/bin` (Claude Code), Homebrew, npm/pnpm/bun/
/// cargo/volta globals; on Windows the npm and WinGet folders.
pub fn search_dirs<E: Fn(&str) -> Option<String>>(env: &E, os: Os) -> Vec<PathBuf> {
    let sep = if os == Os::Windows { ';' } else { ':' };
    let mut dirs: Vec<PathBuf> =
        env("PATH").unwrap_or_default().split(sep).filter(|s| !s.is_empty()).map(PathBuf::from).collect();
    match os {
        Os::Unix => {
            if let Some(home) = env("HOME").filter(|h| !h.is_empty()) {
                let h = Path::new(&home);
                for rel in [".local/bin", ".npm-global/bin", "Library/pnpm", ".bun/bin", ".cargo/bin", ".volta/bin"] {
                    dirs.push(h.join(rel));
                }
            }
            dirs.push(PathBuf::from("/opt/homebrew/bin"));
            dirs.push(PathBuf::from("/usr/local/bin"));
        }
        Os::Windows => {
            if let Some(app) = env("APPDATA").filter(|h| !h.is_empty()) {
                dirs.push(Path::new(&app).join("npm"));
            }
            if let Some(local) = env("LOCALAPPDATA").filter(|h| !h.is_empty()) {
                dirs.push(Path::new(&local).join("Microsoft").join("WinGet").join("Links"));
                dirs.push(Path::new(&local).join("pnpm"));
            }
            if let Some(home) = env("USERPROFILE").filter(|h| !h.is_empty()) {
                dirs.push(Path::new(&home).join(".local").join("bin"));
                dirs.push(Path::new(&home).join(".bun").join("bin"));
            }
        }
    }
    let mut seen = std::collections::HashSet::new();
    dirs.retain(|d| seen.insert(d.clone()));
    dirs
}

pub fn file_names(program: &str, os: Os) -> Vec<String> {
    match os {
        Os::Unix => vec![program.to_string()],
        Os::Windows => ["exe", "cmd"].iter().map(|e| format!("{program}.{e}")).collect(),
    }
}

/// The first `dir/name` that `is_program` accepts.
pub fn resolve<X: Fn(&Path) -> bool>(program: &str, dirs: &[PathBuf], is_program: X, os: Os) -> Option<PathBuf> {
    let names = file_names(program, os);
    dirs.iter().flat_map(|d| names.iter().map(move |n| d.join(n))).find(|p| is_program(p))
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

/// Which of [`ACCOUNT_CLIS`] are on this computer (PATH and install folders).
pub fn clis_on_this_computer() -> Vec<(&'static str, bool)> {
    let dirs = search_dirs(&host_env, Os::current());
    ACCOUNT_CLIS.iter().map(|c| (*c, resolve(c, &dirs, is_program_file, Os::current()).is_some())).collect()
}

type Prepared = (PathBuf, &'static [&'static str], Vec<(String, OsString)>);

/// The program, its fixed arguments, and the env for `cli`'s `step` with account `id`: the account's home var
/// and a PATH that starts with the program's folder (so `#!/usr/bin/env node` shims find Node).
pub fn command_for(home: &Path, cli: &str, id: &str, step: Step) -> Result<Prepared, String> {
    let args = fixed_args(cli, step).ok_or("not something omher runs")?;
    let mut env: Vec<(String, OsString)> =
        account_env(home, cli, id)?.into_iter().map(|(k, v)| (k, v.into())).collect();
    let os = Os::current();
    let dirs = search_dirs(&host_env, os);
    let program = resolve(cli, &dirs, is_program_file, os).ok_or_else(|| format!("{cli} is not on this computer"))?;
    let mut child_dirs: Vec<PathBuf> = program.parent().map(|p| vec![p.to_path_buf()]).unwrap_or_default();
    child_dirs.extend(dirs.into_iter().filter(|d| d.is_dir()));
    env.push(("PATH".into(), std::env::join_paths(child_dirs).map_err(|e| e.to_string())?));
    Ok((program, args, env))
}

fn command(program: &Path, args: &[&str], env: &[(String, OsString)]) -> Command {
    let shim = Os::current() == Os::Windows && program.extension().is_some_and(|e| e.eq_ignore_ascii_case("cmd"));
    let mut cmd = if shim {
        // CreateProcess does not start a batch shim on its own. The path comes from the install folders above
        // and the arguments are fixed.
        let mut c = Command::new("cmd.exe");
        c.arg("/c").arg(program);
        c
    } else {
        Command::new(program)
    };
    cmd.args(args).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    for (k, v) in env {
        cmd.env(k, v);
    }
    crate::bridge::no_console_window(&mut cmd);
    cmd
}

/// Run a fixed command to the end (or `STATUS_TIMEOUT`): `(exit code, stdout, stderr)`.
fn run_to_end(program: &Path, args: &[&str], env: &[(String, OsString)]) -> Result<(Option<i32>, String, String), String> {
    let mut child =
        command(program, args, env).spawn().map_err(|e| format!("could not start {}: {e}", program.display()))?;
    let read = |s: Option<Box<dyn Read + Send>>| {
        thread::spawn(move || {
            let mut buf = Vec::new();
            if let Some(s) = s {
                let _ = s.take(256 * 1024).read_to_end(&mut buf);
            }
            String::from_utf8_lossy(&buf).into_owned()
        })
    };
    let out = read(child.stdout.take().map(|s| Box::new(s) as Box<dyn Read + Send>));
    let err = read(child.stderr.take().map(|s| Box::new(s) as Box<dyn Read + Send>));
    let start = Instant::now();
    let code = loop {
        if let Some(st) = child.try_wait().map_err(|e| e.to_string())? {
            break st.code();
        }
        if start.elapsed() > STATUS_TIMEOUT {
            let _ = child.kill();
            let _ = child.wait();
            return Err("the status check took too long".into());
        }
        thread::sleep(Duration::from_millis(30));
    };
    Ok((code, out.join().unwrap_or_default(), err.join().unwrap_or_default()))
}

/// The login status of `cli` account `id` (`default` = the CLI's own home), or `None` for CLIs without a
/// status command (pi, oh-my-pi, Grok, Gemini: the bridge's file check stands).
pub fn status(home: &Path, cli: &str, id: &str) -> Result<Option<LoginStatus>, String> {
    match cli {
        "claude" => {
            let (program, args, env) = command_for(home, cli, id, Step::Status)?;
            let (_, out, _) = run_to_end(&program, args, &env)?;
            Ok(Some(parse_claude_status(&out).ok_or("Claude Code gave no status")?))
        }
        "codex" => {
            let (program, help_args, env) = command_for(home, cli, id, Step::Help)?;
            let (_, help, _) = run_to_end(&program, help_args, &env)?;
            if codex_has_login(&help) {
                let args = fixed_args(cli, Step::Status).ok_or("not something omher runs")?;
                let (code, _, err) = run_to_end(&program, args, &env)?;
                Ok(Some(parse_codex_status(code, &err)))
            } else {
                let codex_home = if id == "default" { home.join(".codex") } else { account_dir(home, cli, id)? };
                Ok(Some(codex_status_from_file(&codex_home.join("auth.json"))))
            }
        }
        _ => Ok(None),
    }
}

// ---------------------------------------------------------------------------------------------
// Sign-in sessions: the CLI's own login with the account's home, output streamed to the page
// ---------------------------------------------------------------------------------------------

/// Streamed to the Accounts page through a Tauri channel.
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum LoginEvent {
    Line { text: String },
    Exit { code: Option<i32> },
}

/// One output line for the page: colour codes and carriage-return redraws removed, and any prompt for a code
/// or key dropped (omher never asks for one; the browser hands the sign-in back to the CLI).
pub fn clean_line(raw: &str) -> Option<String> {
    let last = raw.trim_end_matches(['\r', '\n']).rsplit('\r').next().unwrap_or("");
    let mut out = String::with_capacity(last.len());
    let mut chars = last.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            if chars.peek() == Some(&'[') {
                chars.next();
                for d in chars.by_ref() {
                    if ('@'..='~').contains(&d) {
                        break;
                    }
                }
            } else {
                chars.next();
            }
            continue;
        }
        if c.is_control() && c != '\t' {
            continue;
        }
        out.push(c);
    }
    let text = out.trim().to_string();
    let lower = text.to_ascii_lowercase();
    if text.is_empty() || lower.contains("paste") || lower.contains("api key") || lower.contains("token") {
        return None;
    }
    Some(text.chars().take(600).collect())
}

/// Running sign-ins, so Cancel (and app exit) can stop them.
#[derive(Default)]
pub struct Logins {
    next: AtomicU32,
    live: Mutex<HashMap<u32, Arc<Mutex<Child>>>>,
}

impl Logins {
    pub fn new() -> Arc<Logins> {
        Arc::new(Logins::default())
    }

    /// Start `cli`'s own login for omher account `id` (never `default`: the CLI's own home is signed in to in
    /// the CLI itself). The folder must already exist (`accounts.add`).
    pub fn start<F: FnMut(LoginEvent) + Send + 'static>(
        self: &Arc<Self>,
        home: &Path,
        cli: &str,
        id: &str,
        emit: F,
    ) -> Result<u32, String> {
        let dir = account_dir(home, cli, id)?;
        if dir.is_symlink() || !dir.is_dir() {
            return Err("no such account folder".into());
        }
        let (program, args, env) = command_for(home, cli, id, Step::Login)?;
        self.spawn(command(&program, args, &env), emit)
    }

    fn spawn<F: FnMut(LoginEvent) + Send + 'static>(self: &Arc<Self>, mut cmd: Command, mut emit: F) -> Result<u32, String> {
        let mut child = cmd.spawn().map_err(|e| format!("could not start the sign-in: {e}"))?;
        let (tx, rx) = mpsc::channel::<String>();
        let readers: Vec<_> = [
            child.stdout.take().map(|s| Box::new(s) as Box<dyn Read + Send>),
            child.stderr.take().map(|s| Box::new(s) as Box<dyn Read + Send>),
        ]
        .into_iter()
        .flatten()
        .map(|stream| {
            let tx = tx.clone();
            thread::spawn(move || {
                // A prompt without a newline ("Paste code here > ") arrives with the next line or at exit.
                for line in BufReader::new(stream).split(b'\n').map_while(Result::ok) {
                    let _ = tx.send(String::from_utf8_lossy(&line).into_owned());
                }
            })
        })
        .collect();
        drop(tx);
        let id = self.next.fetch_add(1, Ordering::SeqCst) + 1;
        let child = Arc::new(Mutex::new(child));
        self.live.lock().unwrap().insert(id, Arc::clone(&child));
        let me = Arc::clone(self);
        thread::spawn(move || {
            // Watch the process, not the pipes: a helper the CLI started (a browser opener, a shell's `sleep`) can
            // keep stdout open after the CLI itself has exited or was cancelled, and waiting for EOF would then hold
            // the Exit event (and Cancel) until that helper ends.
            let mut emit_line = |raw: String| {
                if let Some(text) = clean_line(&raw) {
                    emit(LoginEvent::Line { text });
                }
            };
            let code = loop {
                match rx.recv_timeout(Duration::from_millis(30)) {
                    Ok(raw) => {
                        emit_line(raw);
                        continue;
                    }
                    // both pipes closed: the process is ending; poll its status without spinning
                    Err(mpsc::RecvTimeoutError::Disconnected) => thread::sleep(Duration::from_millis(30)),
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                }
                if let Ok(Some(st)) = child.lock().unwrap().try_wait() {
                    break st.code();
                }
            };
            // lines already written before the exit still go out, but never wait long for a helper's pipe
            let grace = Instant::now() + Duration::from_millis(200);
            while let Some(left) = grace.checked_duration_since(Instant::now()) {
                match rx.recv_timeout(left) {
                    Ok(raw) => emit_line(raw),
                    Err(_) => break,
                }
            }
            drop(readers); // detached: a reader blocked on a helper's pipe ends when that helper does
            me.live.lock().unwrap().remove(&id);
            emit(LoginEvent::Exit { code });
        });
        Ok(id)
    }

    /// Stop one sign-in (Cancel). Its `Exit` event still arrives.
    pub fn cancel(&self, id: u32) {
        let child = self.live.lock().unwrap().get(&id).cloned();
        if let Some(c) = child {
            let _ = c.lock().unwrap().kill();
        }
    }

    pub fn cancel_all(&self) {
        let all: Vec<_> = self.live.lock().unwrap().values().cloned().collect();
        for c in all {
            let _ = c.lock().unwrap().kill();
        }
    }

    #[cfg(test)]
    fn count(&self) -> usize {
        self.live.lock().unwrap().len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TOKEN_KEYS: [&str; 6] = ["access_token", "refresh_token", "id_token", "api_key", "OPENAI_API_KEY", "tokens"];
    const SECRET: &str = "sk-SECRET-never-shown";

    #[test]
    fn env_per_cli_points_at_the_account_folder() {
        let home = Path::new("/h");
        let dir = |cli: &str| Path::new("/h/.omher/accounts").join(cli).join("work").to_string_lossy().into_owned();
        assert_eq!(account_env(home, "claude", "work").unwrap(), vec![("CLAUDE_CONFIG_DIR".to_string(), dir("claude"))]);
        assert_eq!(account_env(home, "codex", "work").unwrap(), vec![("CODEX_HOME".to_string(), dir("codex"))]);
        assert_eq!(account_env(home, "pi", "work").unwrap(), vec![("PI_CODING_AGENT_DIR".to_string(), dir("pi"))]);
        assert_eq!(account_env(home, "omp", "work").unwrap()[0].0, "PI_CODING_AGENT_DIR");
        assert_eq!(account_env(home, "grok", "work").unwrap()[0].0, "GROK_HOME");
        assert_eq!(account_env(home, "gemini", "work").unwrap()[0].0, "GEMINI_CLI_HOME");
        assert_eq!(account_env(home, "claude", "default").unwrap(), vec![]);
    }

    /// `<tmp>/<name>` with `.omher/accounts/active.json` = `active` and one folder per `(cli, id)` in `folders`.
    fn session_home(name: &str, active: &str, folders: &[(&str, &str)]) -> PathBuf {
        let home = std::env::temp_dir().join(format!("omher-acct-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        for (cli, id) in folders {
            std::fs::create_dir_all(home.join(".omher").join("accounts").join(cli).join(id)).unwrap();
        }
        std::fs::create_dir_all(home.join(".omher").join("accounts")).unwrap();
        std::fs::write(home.join(".omher").join("accounts").join("active.json"), active).unwrap();
        home
    }

    #[test]
    fn session_env_follows_the_account_chosen_for_new_sessions() {
        let home = session_home("sess", r#"{"claude":"work","codex":"default","grok":"gone","pi":"p"}"#, &[("claude", "work"), ("pi", "p")]);
        let work = home.join(".omher").join("accounts").join("claude").join("work").to_string_lossy().into_owned();
        assert_eq!(session_env(&home, "claude"), vec![("CLAUDE_CONFIG_DIR".to_string(), work)]);
        // "This computer", a folder that is gone, an agent without accounts (pi / omp for now, omh never)
        for agent in ["codex", "grok", "pi", "omp", "omh", "bash"] {
            assert_eq!(session_env(&home, agent), vec![], "{agent}");
        }
        // nothing chosen, or an active.json that is not ours to trust
        for active in ["", "{}", "[]", r#"{"claude":"../../x"}"#, r#"{"claude":{"id":"work"}}"#, r#"{"claude":"Work"}"#] {
            let h = session_home("sess-bad", active, &[("claude", "work")]);
            assert_eq!(session_env(&h, "claude"), vec![], "{active}");
            let _ = std::fs::remove_dir_all(h);
        }
        let _ = std::fs::remove_dir_all(home);
    }

    #[test]
    fn env_refuses_other_paths_and_clis() {
        let home = Path::new("/h");
        for id in ["../x", "..", "a/b", "a\\b", "", "Work", "/tmp", "a..b", &"x".repeat(41)] {
            assert!(account_env(home, "claude", id).is_err(), "{id}");
        }
        assert!(account_env(home, "bash", "work").is_err());
        assert!(account_dir(home, "claude", "default").is_err());
        assert!(valid_account_id("account-2") && valid_account_id("a.b_c"));
    }

    #[test]
    fn the_fixed_argv_is_the_whole_allow_list() {
        assert_eq!(fixed_args("claude", Step::Status), Some(&["auth", "status", "--json"][..]));
        assert_eq!(fixed_args("claude", Step::Login), Some(&["auth", "login"][..]));
        assert_eq!(fixed_args("codex", Step::Help), Some(&["--help"][..]));
        assert_eq!(fixed_args("codex", Step::Status), Some(&["login", "status"][..]));
        assert_eq!(fixed_args("codex", Step::Login), Some(&["login"][..]));
        let mut n = 0;
        for cli in ACCOUNT_CLIS.iter().chain(["bash", "sh", "claude --x"].iter()) {
            for step in [Step::Help, Step::Status, Step::Login] {
                n += usize::from(fixed_args(cli, step).is_some());
            }
        }
        assert_eq!(n, 5, "only the five commands above");
        assert!(fixed_args("pi", Step::Login).is_none() && fixed_args("omp", Step::Login).is_none());
    }

    #[test]
    fn command_for_refuses_before_looking_for_a_program() {
        let home = Path::new("/h");
        assert_eq!(command_for(home, "pi", "default", Step::Login).unwrap_err(), "not something omher runs");
        assert_eq!(command_for(home, "bash", "default", Step::Status).unwrap_err(), "not something omher runs");
        assert_eq!(command_for(home, "claude", "../x", Step::Status).unwrap_err(), "bad account id");
    }

    #[test]
    fn claude_status_keeps_its_fields_and_no_secret() {
        // The shape `claude auth status --json` printed on this Mac (values replaced), plus planted secrets.
        let raw = format!(
            r#"{{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty","configDirectory":"/x/.claude",
            "loginExpiresAt":"2026-12-07T05:24:39.079Z","email":"owner@example.com","orgId":"0000","orgName":"Org",
            "subscriptionType":"max","storedClaudeAiLogin":true,"planTier":"max_20x",
            "access_token":"{SECRET}","refresh_token":"{SECRET}","primaryApiKey":"{SECRET}","nested":{{"id_token":"{SECRET}"}}}}"#
        );
        let s = parse_claude_status(&raw).unwrap();
        assert_eq!(
            s,
            LoginStatus {
                logged_in: true,
                email: Some("owner@example.com".into()),
                plan: Some("max_20x".into()),
                method: Some("claude.ai".into()),
                last_refresh: None
            }
        );
        let out = serde_json::to_string(&s).unwrap();
        for k in TOKEN_KEYS.iter().chain(["primaryApiKey", SECRET, "configDirectory", "orgId"].iter()) {
            assert!(!out.contains(k), "{k}");
        }
        let signed_out = parse_claude_status(r#"{"loggedIn":false,"authMethod":"none","email":"x@y.z"}"#).unwrap();
        assert!(!signed_out.logged_in && signed_out.email.is_none());
        assert!(parse_claude_status("not json").is_none());
    }

    #[test]
    fn codex_status_keeps_only_the_kind_of_login() {
        let s = parse_codex_status(Some(0), "API key configured - sk-proj-***abcd\nsome notice\n");
        assert_eq!((s.logged_in, s.method.as_deref()), (true, Some("api_key")));
        assert!(!serde_json::to_string(&s).unwrap().contains("sk-"));
        let c = parse_codex_status(Some(0), "Logged in using ChatGPT\n");
        assert_eq!((c.logged_in, c.method.as_deref()), (true, Some("chatgpt")));
        assert!(!parse_codex_status(Some(1), "Not logged in\n").logged_in);
        assert!(codex_has_login("Commands:\n  exec        Run Codex\n  login       Manage login\n"));
        assert!(!codex_has_login("Commands:\n  exec  Run\n"));
    }

    #[test]
    fn codex_auth_file_gives_mode_and_refresh_and_never_a_token() {
        let d = std::env::temp_dir().join(format!("omher-acct-test-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let f = d.join("auth.json");
        let mut rnd: u32 = 25;
        for round in 0..25 {
            rnd = rnd.wrapping_mul(1_103_515_245).wrapping_add(12_345);
            let tokens = format!(
                r#"{{"id_token":"{SECRET}.{round}","access_token":"{SECRET}","refresh_token":"{SECRET}","account_id":"a"}}"#
            );
            let body = match (rnd >> 8) % 5 {
                0 => format!(r#"{{"OPENAI_API_KEY":"{SECRET}","auth_mode":"chatgpt","last_refresh":"2026-11-09T00:00:00Z","tokens":{tokens}}}"#),
                1 => format!(r#"{{"tokens":{tokens},"auth_mode":"{SECRET}","last_refresh":"{SECRET}"}}"#),
                2 => format!(r#"{{"auth_mode":{{"access_token":"{SECRET}"}},"last_refresh":{tokens},"tokens":{tokens}}}"#),
                3 => format!(r#"{{"OPENAI_API_KEY":"{SECRET}","auth_mode":"apikey","tokens":null}}"#),
                _ => format!(r#"[{tokens}]"#),
            };
            std::fs::write(&f, body).unwrap();
            let out = serde_json::to_string(&codex_status_from_file(&f)).unwrap();
            for k in TOKEN_KEYS.iter().chain([SECRET, "sk-", "SECRET"].iter()) {
                assert!(!out.contains(k), "round {round}: {k} in {out}");
            }
        }
        std::fs::write(&f, r#"{"auth_mode":"chatgpt","last_refresh":"2026-11-09T00:00:00Z","tokens":{"id_token":"x"}}"#).unwrap();
        let s = codex_status_from_file(&f);
        assert_eq!(
            (s.logged_in, s.method.as_deref(), s.last_refresh.as_deref()),
            (true, Some("chatgpt"), Some("2026-11-09T00:00:00Z"))
        );
        assert!(!codex_status_from_file(&d.join("missing.json")).logged_in);
        std::fs::remove_dir_all(&d).unwrap();
    }

    #[test]
    fn install_folders_follow_path_without_duplicates() {
        let env = |k: &str| match k {
            "PATH" => Some("/usr/bin:/bin:/opt/homebrew/bin".to_string()),
            "HOME" => Some("/Users/k".to_string()),
            _ => None,
        };
        let dirs = search_dirs(&env, Os::Unix);
        assert_eq!(dirs[0], PathBuf::from("/usr/bin"));
        assert!(dirs.contains(&PathBuf::from("/Users/k/.local/bin")));
        assert_eq!(dirs.iter().filter(|d| **d == PathBuf::from("/opt/homebrew/bin")).count(), 1);
        let claude = PathBuf::from("/Users/k/.local/bin/claude");
        assert_eq!(resolve("claude", &dirs, |p| p == claude, Os::Unix), Some(claude.clone()));
        let wenv = |k: &str| match k {
            "PATH" => Some(r"C:\Windows".to_string()),
            "APPDATA" => Some(r"C:\Users\k\AppData\Roaming".to_string()),
            _ => None,
        };
        let wdirs = search_dirs(&wenv, Os::Windows);
        let shim = Path::new(r"C:\Users\k\AppData\Roaming").join("npm").join("codex.cmd");
        assert_eq!(resolve("codex", &wdirs, |p| p == shim, Os::Windows), Some(shim.clone()));
    }

    #[test]
    fn sign_in_lines_are_plain_and_never_ask_for_a_code_or_key() {
        assert_eq!(
            clean_line("\u{1b}[1mOpening browser to sign in…\u{1b}[0m\r\n").as_deref(),
            Some("Opening browser to sign in…")
        );
        assert_eq!(clean_line("Paste code here if prompted > "), None);
        assert_eq!(clean_line("Or enter an API key"), None);
        assert_eq!(clean_line("Saved token to keychain"), None);
        assert_eq!(clean_line("50%\r100%"), Some("100%".into()));
        assert_eq!(clean_line("   "), None);
    }

    #[test]
    fn logins_refuse_the_default_home_and_missing_folders() {
        let logins = Logins::new();
        let home = std::env::temp_dir().join(format!("omher-acct-login-{}", std::process::id()));
        assert_eq!(logins.start(&home, "claude", "default", |_| {}).unwrap_err(), "bad account id");
        assert_eq!(logins.start(&home, "claude", "work", |_| {}).unwrap_err(), "no such account folder");
        assert_eq!(logins.start(&home, "bash", "work", |_| {}).unwrap_err(), "unknown cli");
        assert_eq!(logins.count(), 0);
    }

    #[cfg(unix)]
    #[test]
    fn a_sign_in_streams_lines_then_exit_and_cancel_stops_it() {
        let logins = Logins::new();
        let (tx, rx) = mpsc::channel();
        let mut cmd = Command::new("/bin/sh");
        cmd.args(["-c", "printf 'Opening browser\\nPaste code here > '; echo; sleep 30"])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let id = logins.spawn(cmd, move |e| tx.send(e).unwrap()).unwrap();
        assert_eq!(rx.recv_timeout(Duration::from_secs(5)).unwrap(), LoginEvent::Line { text: "Opening browser".into() });
        assert_eq!(logins.count(), 1);
        logins.cancel(id);
        let exit = loop {
            match rx.recv_timeout(Duration::from_secs(5)).unwrap() {
                e @ LoginEvent::Exit { .. } => break e,
                LoginEvent::Line { text } => assert!(!text.contains("Paste"), "{text}"),
            }
        };
        assert_eq!(exit, LoginEvent::Exit { code: None });
        assert_eq!(logins.count(), 0);
    }

    /// Real check on a Mac with Claude Code: the fixed status command in a temp CLAUDE_CONFIG_DIR reads signed
    /// out, and the person's own ~/.claude is not used. `cargo test -- --ignored`.
    #[test]
    #[ignore]
    fn real_claude_status_in_a_temp_home() {
        let home = std::env::temp_dir().join(format!("omher-acct-real-{}", std::process::id()));
        std::fs::create_dir_all(account_dir(&home, "claude", "probe").unwrap()).unwrap();
        let s = status(&home, "claude", "probe").unwrap().unwrap();
        assert!(!s.logged_in && s.email.is_none());
        std::fs::remove_dir_all(&home).unwrap();
    }
}

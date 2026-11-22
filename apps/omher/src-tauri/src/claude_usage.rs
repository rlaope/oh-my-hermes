//! omher's own record of the subscription usage Claude Code reports, for the sidebar meter (the bridge reads it).
//!
//! Claude Code writes no usage number to its own files on a normal run (only a request that hit a limit leaves a
//! `rate_limit_info` in its transcript). It does report the numbers live, in two places, and omher keeps them:
//! * a chat session's stream-json `rate_limit_event` (`rate_limit_info.unifiedWindows.<window>.utilization`, 0..1),
//!   read by the chat spawner ([`UsageTap`] in agent_chat.rs), on every system;
//! * the JSON a TERMINALS Claude Code hands its status line command on stdin (`rate_limits.<window>.used_percentage`,
//!   0..100), on macOS and on Linux outside an AppImage only ([`RelayHost::enabled`]), and only for a person who has
//!   a status line of their own ([`terminal_args`]). There omher starts an interactive Claude Code with `--settings`
//!   whose `statusLine` runs this binary as a relay
//!   (`omher --statusline-relay <account>`, [`relay_main`]): it records the `rate_limits` part, then runs the person's
//!   own `statusLine` command (resolved as Claude Code resolves it) with the same stdin and prints its output
//!   unchanged. Without a status line of their own, on Windows and inside an AppImage, no `--settings` is added.
//!
//! The record is `~/.omher/usage/claude/<account id or "default">.json`, replaced whole through a temporary file:
//! `{at, windows: {<window>: {used_percent, resets_at}}, status, source: "chat" | "terminal"}`, merged window by
//! window with what is already there ([`merge`]). Nothing is sent anywhere and no token is read.

use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

use serde_json::{json, Map, Value};

/// The first argument that turns the omher binary into the status line relay (checked in `main` before Tauri starts).
pub const RELAY_FLAG: &str = "--statusline-relay";
/// The account name of Claude Code's own login on this computer (no `CLAUDE_CONFIG_DIR` from omher).
pub const DEFAULT_ACCOUNT: &str = "default";
/// A temporary record file older than this was left by a write that never finished, and is removed.
const STALE_TMP: Duration = Duration::from_secs(60);

fn now() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

fn window(used_percent: Option<f64>, resets_at: Option<f64>) -> Option<Value> {
    if used_percent.is_none() && resets_at.is_none() {
        return None;
    }
    let mut w = Map::new();
    if let Some(p) = used_percent {
        w.insert("used_percent".into(), json!(round2(p)));
    }
    if let Some(r) = resets_at {
        w.insert("resets_at".into(), json!(r));
    }
    Some(Value::Object(w))
}

fn record(windows: Map<String, Value>, status: Option<&str>, source: &str, at: f64) -> Option<Value> {
    if windows.is_empty() {
        return None;
    }
    Some(json!({"at": at, "windows": windows, "status": status, "source": source}))
}

/// The record a Claude Code stream-json `rate_limit_event` gives (`utilization` 0..1 becomes `used_percent` 0..100),
/// or `None` for any other line or an event with no window.
pub fn from_stream_event(v: &Value, at: f64) -> Option<Value> {
    if v.get("type").and_then(Value::as_str) != Some("rate_limit_event") {
        return None;
    }
    let info = v.get("rate_limit_info")?.as_object()?;
    let mut windows = Map::new();
    if let Some(unified) = info.get("unifiedWindows").and_then(Value::as_object) {
        for (name, w) in unified {
            let pct = w.get("utilization").and_then(Value::as_f64).map(|u| u * 100.0);
            if let Some(w) = window(pct, w.get("resetsAt").and_then(Value::as_f64)) {
                windows.insert(name.clone(), w);
            }
        }
    }
    if windows.is_empty() {
        // an older Claude Code: the one window the event is about, with its reset time
        if let Some(name) = info.get("rateLimitType").and_then(Value::as_str).filter(|n| !n.is_empty()) {
            let pct = info.get("utilization").and_then(Value::as_f64).map(|u| u * 100.0);
            if let Some(w) = window(pct, info.get("resetsAt").and_then(Value::as_f64)) {
                windows.insert(name.to_string(), w);
            }
        }
    }
    record(windows, info.get("status").and_then(Value::as_str), "chat", at)
}

/// The record a status line input's `rate_limits` gives (`used_percentage` is already 0..100), or `None` without one.
pub fn from_statusline(v: &Value, at: f64) -> Option<Value> {
    let limits = v.get("rate_limits")?.as_object()?;
    let mut windows = Map::new();
    for (name, w) in limits {
        let pct = w.get("used_percentage").and_then(Value::as_f64);
        if let Some(w) = window(pct, w.get("resets_at").and_then(Value::as_f64)) {
            windows.insert(name.clone(), w);
        }
    }
    record(windows, None, "terminal", at)
}

/// `default`, or a name omher gives its account folders (accounts.rs' rule).
fn valid_account(account: &str) -> bool {
    account == DEFAULT_ACCOUNT || crate::accounts::valid_account_id(account)
}

/// The account a Claude Code session started with `account_env` runs under: the omher account folder its
/// `CLAUDE_CONFIG_DIR` names, or `default` without one. `None` for a folder that is not an omher account's name.
pub fn account_of(account_env: &[(String, String)]) -> Option<String> {
    match account_env.iter().find(|(k, _)| k == "CLAUDE_CONFIG_DIR") {
        None => Some(DEFAULT_ACCOUNT.to_string()),
        Some((_, dir)) => Path::new(dir).file_name().and_then(|n| n.to_str()).filter(|n| crate::accounts::valid_account_id(n)).map(str::to_string),
    }
}

/// `<home>/.omher/usage/claude/<account>.json`.
pub fn record_path(home: &Path, account: &str) -> Option<PathBuf> {
    valid_account(account).then(|| home.join(".omher").join("usage").join("claude").join(format!("{account}.json")))
}

/// `new` laid over `old`, window by window, so two readers (a chat and a terminal, two sessions) never make the meter
/// jump back: a later `resets_at` (a new period) replaces the window; the same one keeps the larger `used_percent`;
/// an earlier one (an older reading) changes nothing; a window `new` lacks stays while its reset is ahead of `now`.
/// The status is `new`'s, else the old one unless a window started a new period.
pub fn merge(old: Option<&Value>, new: &Value, now: f64) -> Value {
    let none = Map::new();
    let windows_of = |r: Option<&Value>| r.and_then(|r| r.get("windows")).and_then(Value::as_object).cloned().unwrap_or_else(|| none.clone());
    let (old_w, new_w) = (windows_of(old), windows_of(Some(new)));
    let reset = |w: &Value| w.get("resets_at").and_then(Value::as_f64);
    let pct = |w: &Value| w.get("used_percent").and_then(Value::as_f64);
    let mut out = Map::new();
    let mut new_period = false;
    for (name, w) in &new_w {
        let kept = match old_w.get(name) {
            None => w.clone(),
            Some(o) => match (reset(o), reset(w)) {
                (Some(a), Some(b)) if b > a => {
                    new_period = true;
                    w.clone()
                }
                (Some(a), Some(b)) if b < a => o.clone(),
                _ => {
                    let mut same = w.clone();
                    if let Some(p) = pct(o).into_iter().chain(pct(w)).reduce(f64::max) {
                        same["used_percent"] = json!(p);
                    }
                    if let (None, Some(r)) = (reset(w), reset(o)) {
                        same["resets_at"] = json!(r);
                    }
                    same
                }
            },
        };
        out.insert(name.clone(), kept);
    }
    for (name, o) in &old_w {
        if !out.contains_key(name) && reset(o).is_some_and(|r| r > now) {
            out.insert(name.clone(), o.clone());
        }
    }
    let status = match new.get("status").filter(|s| !s.is_null()) {
        Some(s) => s.clone(),
        None if new_period => Value::Null,
        None => old.and_then(|o| o.get("status")).cloned().unwrap_or(Value::Null),
    };
    json!({"at": new.get("at").cloned().unwrap_or(Value::Null), "windows": out, "status": status,
           "source": new.get("source").cloned().unwrap_or(Value::Null)})
}

/// Temporary record files left by a write that never finished (`.<account>.<pid>.<n>.tmp`, over a minute old).
fn sweep_tmp(dir: &Path) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    for e in entries.flatten() {
        let name = e.file_name();
        let name = name.to_string_lossy();
        let old = e.metadata().ok().and_then(|m| m.modified().ok()).and_then(|t| t.elapsed().ok()).is_some_and(|age| age > STALE_TMP);
        if name.starts_with('.') && name.ends_with(".tmp") && old {
            let _ = std::fs::remove_file(e.path());
        }
    }
}

/// Lay `record` over `account`'s record ([`merge`]) and replace the file: written to a temporary file beside it, then
/// renamed over it. Nothing is written when the windows and status are what the file already holds (`Ok(false)`).
pub fn write_record(home: &Path, account: &str, record: &Value, now: f64) -> Result<bool, String> {
    static SEQ: AtomicU32 = AtomicU32::new(0);
    let file = record_path(home, account).ok_or("bad account")?;
    let dir = file.parent().ok_or("no folder")?;
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    sweep_tmp(dir);
    let old = std::fs::read(&file).ok().and_then(|b| serde_json::from_slice::<Value>(&b).ok()).filter(Value::is_object);
    let merged = merge(old.as_ref(), record, now);
    if old.as_ref().is_some_and(|o| o.get("windows") == merged.get("windows") && o.get("status") == merged.get("status")) {
        return Ok(false);
    }
    let tmp = dir.join(format!(".{account}.{}.{}.tmp", std::process::id(), SEQ.fetch_add(1, Ordering::SeqCst)));
    let body = serde_json::to_vec(&merged).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, body).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, &file).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        e.to_string()
    })?;
    Ok(true)
}

/// A chat line: when it is a `rate_limit_event`, it goes into `account`'s record. Errors are dropped (the meter only
/// misses one reading).
pub fn record_chat_line(home: &Path, account: &str, line: &str) {
    if !line.contains("\"rate_limit_event\"") {
        return;
    }
    let Ok(v) = serde_json::from_str::<Value>(line) else { return };
    let t = now();
    if let Some(r) = from_stream_event(&v, t) {
        let _ = write_record(home, account, &r, t);
    }
}

// ---------------------------------------------------------------------------------------------
// TERMINALS: the status line relay (macOS, and Linux outside an AppImage)
// ---------------------------------------------------------------------------------------------

fn read_settings(path: &Path) -> Option<Map<String, Value>> {
    let text = std::fs::read_to_string(path).ok()?;
    match serde_json::from_str::<Value>(&text).ok()? {
        Value::Object(m) => Some(m),
        _ => None,
    }
}

/// A `statusLine` Claude Code 2.1.330 accepts: an object with `type: "command"`, a string `command`, and `padding`
/// and `hideVimModeIndicator` of their types when present (`refreshInterval` it drops by itself when wrong).
fn valid_line(line: &Value) -> bool {
    let Some(o) = line.as_object() else { return false };
    o.get("type").and_then(Value::as_str) == Some("command")
        && o.get("command").is_some_and(Value::is_string)
        && o.get("padding").is_none_or(Value::is_number)
        && o.get("hideVimModeIndicator").is_none_or(Value::is_boolean)
}

/// The person's own `statusLine`, as Claude Code resolves it from their files: `~/.claude/settings.json` (or
/// `$CLAUDE_CONFIG_DIR/settings.json`), overlaid by the project's `.claude/settings.json`, then its
/// `.claude/settings.local.json` (the later one wins key by key). Only the `statusLine` key is read. A file whose
/// `statusLine` Claude Code would refuse is skipped, as Claude Code skips that whole file and uses the others. `None`
/// when no file sets a command line.
pub fn user_status_line(project: Option<&Path>, config_dir: &Path) -> Option<Map<String, Value>> {
    let mut files = vec![config_dir.join("settings.json")];
    if let Some(p) = project {
        files.push(p.join(".claude").join("settings.json"));
        files.push(p.join(".claude").join("settings.local.json"));
    }
    let mut line: Option<Map<String, Value>> = None;
    for f in files {
        if let Some(Value::Object(o)) = read_settings(&f).and_then(|mut m| m.remove("statusLine")).filter(valid_line) {
            line.get_or_insert_with(Map::new).extend(o);
        }
    }
    let line = line?;
    let command = line.get("command").and_then(Value::as_str).unwrap_or("");
    // a line that is omher's own relay would only call itself
    if command.trim().is_empty() || command.contains(RELAY_FLAG) {
        return None;
    }
    Some(line)
}

/// One word for `sh`, quoted the way Claude Code quotes (plain when it is all `[A-Za-z0-9_./:=@+,-]`, `''` when
/// empty, else single quotes with `'` as `'"'"'`).
fn sh_quote(s: &str) -> String {
    if s.is_empty() {
        return "''".into();
    }
    if s.chars().all(|c| c.is_ascii_alphanumeric() || "_./:=@+,-".contains(c)) {
        return s.into();
    }
    format!("'{}'", s.replace('\'', "'\"'\"'"))
}

/// The `--settings` JSON a TERMINALS Claude Code starts with: a `statusLine` that runs the relay at `exe` for
/// `account`, with the person's own padding (a non-negative integer), refresh interval (a number of at least 1) and
/// vim-indicator choice (a boolean) from `user`, so the line looks the same; any other value is dropped. `None` for an
/// account name omher does not give.
pub fn terminal_settings(exe: &Path, account: &str, user: Option<&Map<String, Value>>) -> Option<String> {
    if !valid_account(account) {
        return None;
    }
    let mut line = Map::new();
    line.insert("type".into(), json!("command"));
    line.insert("command".into(), json!(format!("{} {RELAY_FLAG} {account}", sh_quote(&exe.to_string_lossy()))));
    let get = |k: &str| user.and_then(|u| u.get(k));
    if let Some(p) = get("padding").and_then(Value::as_u64) {
        line.insert("padding".into(), json!(p));
    }
    if let Some(r) = get("refreshInterval").filter(|r| r.as_f64().is_some_and(|r| r.is_finite() && r >= 1.0)) {
        line.insert("refreshInterval".into(), r.clone());
    }
    if let Some(h) = get("hideVimModeIndicator").and_then(Value::as_bool) {
        line.insert("hideVimModeIndicator".into(), json!(h));
    }
    Some(json!({"statusLine": line}).to_string())
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).filter(|v| !v.is_empty()).map(PathBuf::from)
}

/// Where a TERMINALS Claude Code runs, for the relay: the home folder, this executable, and the system.
pub struct RelayHost {
    pub home: Option<PathBuf>,
    pub exe: Option<PathBuf>,
    /// omher's own `CLAUDE_CONFIG_DIR`, which a session without an omher account inherits.
    pub claude_config: Option<PathBuf>,
    pub windows: bool,
    pub appimage: bool,
}

impl RelayHost {
    pub fn current() -> RelayHost {
        RelayHost {
            home: home_dir(),
            exe: std::env::current_exe().ok(),
            claude_config: std::env::var_os("CLAUDE_CONFIG_DIR").filter(|v| !v.is_empty()).map(PathBuf::from),
            windows: cfg!(windows),
            appimage: cfg!(target_os = "linux") && std::env::var_os("APPIMAGE").is_some_and(|a| !a.is_empty()),
        }
    }

    /// macOS, and Linux outside an AppImage. Windows (cmd.exe and PowerShell quoting, Git Bash or WSL's `bash`, a GUI
    /// executable) and an AppImage (its image mounted again on every refresh) get no relay.
    pub fn enabled(&self) -> bool {
        !self.windows && !self.appimage
    }
}

/// Claude Code's config folder for a session with `account_env`: its `CLAUDE_CONFIG_DIR`, else omher's own one
/// (`inherited`), else `~/.claude`.
fn config_dir(home: &Path, account_env: &[(String, String)], inherited: Option<&Path>) -> PathBuf {
    account_env
        .iter()
        .find(|(k, _)| k == "CLAUDE_CONFIG_DIR")
        .map(|(_, v)| PathBuf::from(v))
        .or_else(|| inherited.map(Path::to_path_buf))
        .unwrap_or_else(|| home.join(".claude"))
}

/// The arguments a TERMINALS session of `agent_id` in `cwd` with `account_env` gets for the relay: `--settings <json>`
/// (the flag, then the JSON as one argument) only for Claude Code, on a system where the relay runs, when the person
/// already has a status line of their own, resolved as the relay resolves it ([`user_status_line`]). Without one
/// nothing is added, so nothing on screen changes (Claude Code keeps a row for any configured status line, even an
/// empty one), and that session's usage is recorded from chats only.
pub fn terminal_args(agent_id: &str, cwd: &Path, account_env: &[(String, String)], host: &RelayHost) -> Vec<OsString> {
    if agent_id != "claude" || !host.enabled() {
        return Vec::new();
    }
    let (Some(home), Some(exe), Some(account)) = (host.home.as_deref(), host.exe.as_deref(), account_of(account_env)) else {
        return Vec::new();
    };
    let Some(user) = user_status_line(Some(cwd), &config_dir(home, account_env, host.claude_config.as_deref())) else {
        return Vec::new();
    };
    match terminal_settings(exe, &account, Some(&user)) {
        Some(json) => vec!["--settings".into(), json.into()],
        None => Vec::new(),
    }
}

/// The command line Claude Code runs for a status line `command` when `CLAUDE_CODE_SHELL_PREFIX` is `prefix` (2.1.330's
/// join: a prefix ending in ` -<flags>` keeps its flags bare, the program and the command are quoted words).
pub fn with_shell_prefix(prefix: Option<&str>, command: &str) -> String {
    match prefix.filter(|p| !p.is_empty()) {
        None => command.to_string(),
        Some(p) => match p.rfind(" -") {
            Some(i) if i > 0 => format!("{} {} {}", sh_quote(&p[..i]), &p[i + 1..], sh_quote(command)),
            _ => format!("{} {}", sh_quote(p), sh_quote(command)),
        },
    }
}

/// Run the person's status line `command` with `input` on stdin, as Claude Code would (`/bin/sh -c`, after
/// `CLAUDE_CODE_SHELL_PREFIX` when set): its stdout and exit code (stderr goes where the relay's goes). `None` when the
/// shell could not start.
pub fn run_user(command: &str, input: &[u8], prefix: Option<&str>) -> Option<(Vec<u8>, i32)> {
    let mut cmd = Command::new("/bin/sh");
    cmd.arg("-c").arg(with_shell_prefix(prefix, command)).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
    crate::appimage::host_env(&mut cmd);
    let mut child = cmd.spawn().ok()?;
    let mut stdin = child.stdin.take()?;
    let data = input.to_vec();
    // fed from its own thread, so a command that prints before it reads cannot block on a full pipe
    let feeder = std::thread::spawn(move || {
        let _ = stdin.write_all(&data);
    });
    let mut out = Vec::new();
    if let Some(mut o) = child.stdout.take() {
        let _ = o.read_to_end(&mut out);
    }
    let _ = feeder.join();
    let code = child.wait().ok().and_then(|s| s.code()).unwrap_or(1);
    Some((out, code))
}

/// The relay itself: record `input`'s `rate_limits` for `account` (none without a valid account, and never failing
/// the line), then run the person's own status line command, resolved for the input's project, with the same input.
/// Its output and exit code, or nothing and 0 when they have no status line.
pub fn relay(input: &[u8], home: &Path, account: Option<&str>, config_dir: &Path, cwd: Option<&Path>, prefix: Option<&str>) -> (Vec<u8>, i32) {
    let parsed = serde_json::from_slice::<Value>(input).ok();
    if let (Some(v), Some(account)) = (&parsed, account.filter(|a| valid_account(a))) {
        let (v, home, account) = (v.clone(), home.to_path_buf(), account.to_string());
        let _ = std::panic::catch_unwind(move || {
            let t = now();
            if let Some(r) = from_statusline(&v, t) {
                let _ = write_record(&home, &account, &r, t);
            }
        });
    }
    let project = parsed
        .as_ref()
        .and_then(|v| v.pointer("/workspace/project_dir").or_else(|| v.get("cwd")))
        .and_then(Value::as_str)
        .filter(|p| !p.is_empty())
        .map(PathBuf::from)
        .or_else(|| cwd.map(Path::to_path_buf));
    let Some(line) = user_status_line(project.as_deref(), config_dir) else { return (Vec::new(), 0) };
    let command = line.get("command").and_then(Value::as_str).unwrap_or_default();
    run_user(command, input, prefix).unwrap_or((Vec::new(), 1))
}

/// `omher --statusline-relay <account>`: read stdin, [`relay`], print what the person's command printed, exit with its
/// code. Runs before any app start-up. An account omher does not give records nothing; the line still runs.
pub fn relay_main(args: &[OsString]) -> i32 {
    let mut input = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut input);
    let account = args.get(2).and_then(|a| a.to_str());
    let Some(home) = home_dir() else { return 0 };
    let config = std::env::var_os("CLAUDE_CONFIG_DIR").filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| home.join(".claude"));
    let cwd = std::env::current_dir().ok();
    let prefix = std::env::var("CLAUDE_CODE_SHELL_PREFIX").ok();
    let (out, code) = relay(&input, &home, account, &config, cwd.as_deref(), prefix.as_deref());
    let mut stdout = std::io::stdout();
    let _ = stdout.write_all(&out);
    let _ = stdout.flush();
    code
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("omher-claude-usage-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d.canonicalize().unwrap()
    }

    fn read(home: &Path, account: &str) -> Value {
        serde_json::from_str(&std::fs::read_to_string(record_path(home, account).unwrap()).unwrap()).unwrap()
    }

    fn host(home: &Path, windows: bool, appimage: bool) -> RelayHost {
        RelayHost { home: Some(home.to_path_buf()), exe: Some(PathBuf::from("/Applications/omher.app/Contents/MacOS/omher")), claude_config: None, windows, appimage }
    }

    /// The `rate_limit_event` a `claude -p --output-format stream-json --verbose` turn printed (Claude Code 2.1.330,
    /// a Max login), unchanged.
    const REAL_EVENT: &str = r#"{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1795420800,"rateLimitType":"seven_day","overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,"unifiedWindows":{"seven_day":{"utilization":0.06,"resetsAt":1795420800,"status":"allowed"}}},"uuid":"5c7a2c3e-9a51-4f0e-8d1c-0c2f9e3c1a77","session_id":"0b0c7f7e-3c1e-4c55-9a39-3c7c1d1c2b6a"}"#;

    #[test]
    fn a_real_rate_limit_event_becomes_a_percent_record() {
        let v: Value = serde_json::from_str(REAL_EVENT).unwrap();
        let r = from_stream_event(&v, 1795000000.0).unwrap();
        assert_eq!(r, json!({"at": 1795000000.0, "windows": {"seven_day": {"used_percent": 6.0, "resets_at": 1795420800.0}}, "status": "allowed", "source": "chat"}));
    }

    #[test]
    fn every_unified_window_is_kept_and_an_old_event_keeps_its_one_window() {
        let v = json!({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning", "unifiedWindows": {
            "five_hour": {"utilization": 0.734, "resetsAt": 1795000100, "status": "allowed_warning"},
            "seven_day": {"utilization": 0.2, "resetsAt": 1795420800, "status": "allowed"}}}});
        let r = from_stream_event(&v, 1.0).unwrap();
        assert_eq!(r["windows"]["five_hour"], json!({"used_percent": 73.4, "resets_at": 1795000100.0}));
        assert_eq!(r["windows"]["seven_day"]["used_percent"], json!(20.0));
        assert_eq!(r["status"], json!("allowed_warning"));
        // no unifiedWindows: the event's own window and reset time, and no number it did not give
        let old = json!({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 1795420800, "rateLimitType": "seven_day"}});
        assert_eq!(from_stream_event(&old, 1.0).unwrap()["windows"], json!({"seven_day": {"resets_at": 1795420800.0}}));
        for other in [json!({"type": "assistant"}), json!({"type": "rate_limit_event"}), json!({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}})] {
            assert_eq!(from_stream_event(&other, 1.0), None, "{other}");
        }
    }

    #[test]
    fn a_status_line_input_becomes_a_terminal_record() {
        let v = json!({"session_id": "x", "rate_limits": {"five_hour": {"used_percentage": 12, "resets_at": 1795000100}, "seven_day": {"used_percentage": 6, "resets_at": 1795420800}}});
        assert_eq!(from_statusline(&v, 5.0).unwrap(), json!({"at": 5.0, "windows": {
            "five_hour": {"used_percent": 12.0, "resets_at": 1795000100.0}, "seven_day": {"used_percent": 6.0, "resets_at": 1795420800.0}},
            "status": null, "source": "terminal"}));
        assert_eq!(from_statusline(&json!({"session_id": "x"}), 5.0), None);
        assert_eq!(from_statusline(&json!({"rate_limits": {}}), 5.0), None);
    }

    #[test]
    fn the_record_is_replaced_whole_only_under_omher_usage_and_old_temporaries_go() {
        let home = tmp("write");
        let r = |at: f64, pct: f64| json!({"at": at, "windows": {"seven_day": {"used_percent": pct, "resets_at": 1795420800.0}}, "status": "allowed", "source": "chat"});
        assert!(write_record(&home, "default", &r(1.0, 6.0), 0.0).unwrap());
        assert!(write_record(&home, "work", &r(2.0, 9.0), 0.0).unwrap());
        assert!(write_record(&home, "default", &r(3.0, 7.0), 0.0).unwrap());
        assert_eq!(read(&home, "default"), r(3.0, 7.0));
        assert_eq!(read(&home, "work")["windows"]["seven_day"]["used_percent"], json!(9.0));
        // the same reading again changes nothing on disk
        assert!(!write_record(&home, "default", &r(4.0, 7.0), 0.0).unwrap());
        assert_eq!(read(&home, "default")["at"], json!(3.0));
        let dir = home.join(".omher/usage/claude");
        // a temporary file over a minute old is removed by the next write; a fresh one (a write under way) is not
        let (stale, fresh) = (dir.join(".default.1.0.tmp"), dir.join(".work.2.0.tmp"));
        std::fs::write(&stale, "{").unwrap();
        std::fs::write(&fresh, "{").unwrap();
        let old = std::time::SystemTime::now() - Duration::from_secs(120);
        std::fs::File::options().write(true).open(&stale).unwrap().set_modified(old).unwrap();
        write_record(&home, "default", &r(5.0, 8.0), 0.0).unwrap();
        assert!(!stale.exists());
        assert!(fresh.exists());
        std::fs::remove_file(&fresh).unwrap();
        let mut names: Vec<String> = std::fs::read_dir(&dir).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["default.json", "work.json"], "no temporary file is left");
        for bad in ["", "../x", "Work", "a/b", "..", "default/.."] {
            assert!(write_record(&home, bad, &r(1.0, 1.0), 0.0).is_err(), "{bad:?}");
        }
        // a chat line that is not a rate_limit_event writes nothing
        record_chat_line(&home, "chatonly", r#"{"type":"assistant","message":{}}"#);
        assert!(!dir.join("chatonly.json").exists());
        record_chat_line(&home, "chatonly", REAL_EVENT);
        assert_eq!(read(&home, "chatonly")["windows"]["seven_day"]["used_percent"], json!(6.0));
    }

    #[test]
    fn an_older_reading_never_lowers_the_meter() {
        let w = |pct: f64, reset: f64| json!({"used_percent": pct, "resets_at": reset});
        let rec = |at: f64, windows: Value, status: Value| json!({"at": at, "windows": windows, "status": status, "source": "terminal"});
        let now = 1000.0;
        let held = rec(10.0, json!({"seven_day": w(40.0, 5000.0)}), json!("allowed_warning"));
        // the same window read lower (another session, a reading taken earlier): the larger % stays
        let m = merge(Some(&held), &rec(11.0, json!({"seven_day": w(30.0, 5000.0)}), Value::Null), now);
        assert_eq!(m["windows"]["seven_day"], w(40.0, 5000.0));
        assert_eq!(m["status"], json!("allowed_warning"));
        // a reading of the period before (an earlier reset): nothing changes
        let m = merge(Some(&held), &rec(12.0, json!({"seven_day": w(90.0, 4000.0)}), Value::Null), now);
        assert_eq!(m["windows"]["seven_day"], w(40.0, 5000.0));
        // a new period (a later reset): the window starts again, and the old status goes with it
        let m = merge(Some(&held), &rec(13.0, json!({"seven_day": w(2.0, 9000.0)}), Value::Null), now);
        assert_eq!(m["windows"]["seven_day"], w(2.0, 9000.0));
        assert_eq!(m["status"], Value::Null);
        // higher in the same window: it rises
        let m = merge(Some(&held), &rec(14.0, json!({"seven_day": w(55.0, 5000.0)}), json!("allowed")), now);
        assert_eq!((m["windows"]["seven_day"].clone(), m["status"].clone(), m["at"].clone()), (w(55.0, 5000.0), json!("allowed"), json!(14.0)));
        assert_eq!(merge(None, &held, now), held);
    }

    #[test]
    fn the_five_hour_window_does_not_flicker_between_chat_and_terminal_writes() {
        let home = tmp("flicker");
        let five = json!({"used_percent": 22.0, "resets_at": 1795000100.0});
        // the terminal's status line has both windows; a chat's event only the weekly one
        let terminal = json!({"at": 1.0, "windows": {"five_hour": five, "seven_day": {"used_percent": 6.0, "resets_at": 1795420800.0}}, "status": null, "source": "terminal"});
        let chat = json!({"at": 2.0, "windows": {"seven_day": {"used_percent": 7.0, "resets_at": 1795420800.0}}, "status": "allowed", "source": "chat"});
        write_record(&home, "default", &terminal, 1795000000.0).unwrap();
        write_record(&home, "default", &chat, 1795000000.0).unwrap();
        let r = read(&home, "default");
        assert_eq!(r["windows"]["five_hour"], five);
        assert_eq!(r["windows"]["seven_day"]["used_percent"], json!(7.0));
        assert_eq!((r["status"].clone(), r["source"].clone()), (json!("allowed"), json!("chat")));
        // once the 5-hour window has reset, a reading without it drops it
        write_record(&home, "default", &json!({"at": 3.0, "windows": {"seven_day": {"used_percent": 8.0, "resets_at": 1795420800.0}}, "status": "allowed", "source": "chat"}), 1795000200.0).unwrap();
        assert_eq!(read(&home, "default")["windows"].as_object().unwrap().keys().collect::<Vec<_>>(), ["seven_day"]);
    }

    #[test]
    fn the_account_is_the_omher_folder_name_or_default() {
        assert_eq!(account_of(&[]), Some("default".into()));
        assert_eq!(account_of(&[("CLAUDE_CONFIG_DIR".into(), "/h/.omher/accounts/claude/work".into())]), Some("work".into()));
        assert_eq!(account_of(&[("CLAUDE_CONFIG_DIR".into(), "/h/Somewhere Else".into())]), None);
    }

    #[test]
    fn the_person_s_status_line_is_resolved_local_then_project_then_user() {
        let root = tmp("precedence");
        let (user, project) = (root.join("user"), root.join("project"));
        std::fs::create_dir_all(project.join(".claude")).unwrap();
        std::fs::create_dir_all(&user).unwrap();
        let set = |p: PathBuf, v: Value| std::fs::write(p, v.to_string()).unwrap();
        // nothing anywhere
        assert_eq!(user_status_line(Some(&project), &user), None);
        set(user.join("settings.json"), json!({"hooks": {"Stop": []}, "statusLine": {"type": "command", "command": "user-line", "padding": 2}}));
        assert_eq!(user_status_line(Some(&project), &user).unwrap()["command"], json!("user-line"));
        set(project.join(".claude/settings.json"), json!({"statusLine": {"type": "command", "command": "project-line"}}));
        let l = user_status_line(Some(&project), &user).unwrap();
        assert_eq!((l["command"].clone(), l["padding"].clone()), (json!("project-line"), json!(2)));
        set(project.join(".claude/settings.local.json"), json!({"statusLine": {"type": "command", "command": "local-line"}}));
        assert_eq!(user_status_line(Some(&project), &user).unwrap()["command"], json!("local-line"));
        // a file Claude Code refuses is skipped and the lower ones still count, as in Claude Code 2.1.330 ("Files with
        // errors are skipped entirely"): broken JSON, a statusLine that is not an object, or not a command line
        for bad in ["{not json".to_string(), json!({"statusLine": "echo hi"}).to_string(), json!({"statusLine": null}).to_string(),
                    json!({"statusLine": {"type": "command"}}).to_string(), json!({"statusLine": {"type": "static", "command": "x"}}).to_string(),
                    json!({"statusLine": {"type": "command", "command": "x", "padding": "2"}}).to_string()] {
            std::fs::write(project.join(".claude/settings.local.json"), &bad).unwrap();
            assert_eq!(user_status_line(Some(&project), &user).unwrap()["command"], json!("project-line"), "{bad}");
        }
        // no project: the user's own; omher's relay is never the person's line
        assert_eq!(user_status_line(None, &user).unwrap()["command"], json!("user-line"));
        set(user.join("settings.json"), json!({"statusLine": {"type": "command", "command": "'/x/omher' --statusline-relay default"}}));
        assert_eq!(user_status_line(None, &user), None);
    }

    #[test]
    fn the_settings_run_the_relay_and_keep_how_the_line_looks() {
        let exe = Path::new("/Applications/omher.app/Contents/MacOS/omher");
        let user: Map<String, Value> = serde_json::from_value(json!({"type": "command", "command": "mine", "padding": 0, "refreshInterval": 5, "hideVimModeIndicator": true, "other": 1})).unwrap();
        let s: Value = serde_json::from_str(&terminal_settings(exe, "work", Some(&user)).unwrap()).unwrap();
        assert_eq!(s, json!({"statusLine": {"type": "command", "command": "/Applications/omher.app/Contents/MacOS/omher --statusline-relay work", "padding": 0, "refreshInterval": 5, "hideVimModeIndicator": true}}));
        let s: Value = serde_json::from_str(&terminal_settings(Path::new("/x/it's here/omher"), "default", None).unwrap()).unwrap();
        assert_eq!(s["statusLine"]["command"], json!("'/x/it'\"'\"'s here/omher' --statusline-relay default"));
        assert_eq!(s.as_object().unwrap().len(), 1, "only statusLine");
        // an account name omher does not give makes no settings at all
        for bad in ["", "Work", "a b", "x; rm -rf ~", "../x"] {
            assert_eq!(terminal_settings(exe, bad, None), None, "{bad:?}");
        }
    }

    #[test]
    fn hostile_look_values_are_dropped() {
        let exe = Path::new("/o/omher");
        for (k, v) in [("padding", json!("2; rm -rf ~")), ("padding", json!(-1)), ("padding", json!(1.5)), ("padding", json!({"a": 1})),
                       ("refreshInterval", json!("5")), ("refreshInterval", json!(0)), ("refreshInterval", json!(0.5)), ("refreshInterval", json!([1])),
                       ("hideVimModeIndicator", json!("true")), ("hideVimModeIndicator", json!(1)), ("command", json!("evil")), ("type", json!("evil"))] {
            let user: Map<String, Value> = serde_json::from_value(json!({"type": "command", "command": "mine", k: v})).unwrap();
            let s: Value = serde_json::from_str(&terminal_settings(exe, "default", Some(&user)).unwrap()).unwrap();
            assert_eq!(s, json!({"statusLine": {"type": "command", "command": "/o/omher --statusline-relay default"}}), "{k}: {v}");
        }
        let user: Map<String, Value> = serde_json::from_value(json!({"padding": 3, "refreshInterval": 1.5})).unwrap();
        let s: Value = serde_json::from_str(&terminal_settings(exe, "default", Some(&user)).unwrap()).unwrap();
        assert_eq!((s["statusLine"]["padding"].clone(), s["statusLine"]["refreshInterval"].clone()), (json!(3), json!(1.5)));
    }

    #[test]
    fn only_claude_with_its_own_status_line_on_macos_or_linux_outside_an_appimage_gets_settings_as_one_argument() {
        let root = tmp("args");
        let (home, cwd) = (root.join("home"), root.join("project"));
        std::fs::create_dir_all(home.join(".claude")).unwrap();
        std::fs::create_dir_all(cwd.join(".claude")).unwrap();
        let on = host(&home, false, false);
        let line = |cmd: &str| json!({"statusLine": {"type": "command", "command": cmd, "padding": 1}}).to_string();
        // no status line of their own anywhere: nothing added, so nothing on screen changes
        assert!(terminal_args("claude", &cwd, &[], &on).is_empty());
        // only lines Claude Code would refuse, or omher's own relay: still nothing
        std::fs::write(cwd.join(".claude/settings.local.json"), json!({"statusLine": "echo hi"}).to_string()).unwrap();
        std::fs::write(cwd.join(".claude/settings.json"), json!({"statusLine": {"type": "command"}}).to_string()).unwrap();
        std::fs::write(home.join(".claude/settings.json"), line("'/x/omher' --statusline-relay default")).unwrap();
        assert!(terminal_args("claude", &cwd, &[], &on).is_empty());
        // their own line in the user's settings: `--settings`, then the JSON as one argument
        std::fs::write(home.join(".claude/settings.json"), line("~/.claude/statusline.sh")).unwrap();
        let args = terminal_args("claude", &cwd, &[], &on);
        assert_eq!(args.len(), 2);
        assert_eq!(args[0], "--settings");
        let s: Value = serde_json::from_str(args[1].to_str().unwrap()).unwrap();
        assert_eq!(s, json!({"statusLine": {"type": "command", "command": "/Applications/omher.app/Contents/MacOS/omher --statusline-relay default", "padding": 1}}));
        // or only in the project (local first): the same
        std::fs::remove_file(home.join(".claude/settings.json")).unwrap();
        std::fs::write(cwd.join(".claude/settings.local.json"), line("echo local")).unwrap();
        assert_eq!(terminal_args("claude", &cwd, &[], &on).len(), 2);
        std::fs::remove_file(cwd.join(".claude/settings.local.json")).unwrap();
        assert!(terminal_args("claude", &cwd, &[], &on).is_empty());
        // an omher account: its own config folder decides, not ~/.claude
        let work_dir = root.join(".omher/accounts/claude/work");
        std::fs::create_dir_all(&work_dir).unwrap();
        let work = [("CLAUDE_CONFIG_DIR".to_string(), work_dir.to_string_lossy().into_owned())];
        assert!(terminal_args("claude", &cwd, &work, &on).is_empty());
        std::fs::write(work_dir.join("settings.json"), line("echo work")).unwrap();
        assert!(terminal_args("claude", &cwd, &work, &on)[1].to_str().unwrap().contains("--statusline-relay work"));
        // omher's own CLAUDE_CONFIG_DIR, inherited by a session without an account
        let inherited = RelayHost { claude_config: Some(work_dir.clone()), ..host(&home, false, false) };
        assert_eq!(terminal_args("claude", &cwd, &[], &inherited).len(), 2);
        std::fs::write(home.join(".claude/settings.json"), line("echo mine")).unwrap();
        // Windows and an AppImage: no --settings, no relay, even with a line of their own
        assert!(terminal_args("claude", &cwd, &[], &host(&home, true, false)).is_empty());
        assert!(terminal_args("claude", &cwd, &[], &host(&home, false, true)).is_empty());
        // every other agent, and a folder that is not an omher account: nothing
        for agent in ["codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode", "gemini", "shell", "claude -p", ""] {
            assert!(terminal_args(agent, &cwd, &[], &on).is_empty(), "{agent}");
        }
        assert!(terminal_args("claude", &cwd, &[("CLAUDE_CONFIG_DIR".into(), root.join("Not An Account").to_string_lossy().into_owned())], &on).is_empty());
        assert_eq!(terminal_args("claude", &cwd, &[], &on).len(), 2);
    }

    #[test]
    fn the_shell_prefix_is_joined_as_claude_code_joins_it() {
        assert_eq!(with_shell_prefix(None, "echo hi"), "echo hi");
        assert_eq!(with_shell_prefix(Some(""), "echo hi"), "echo hi");
        assert_eq!(with_shell_prefix(Some("/usr/local/bin/wrap"), "echo hi"), "/usr/local/bin/wrap 'echo hi'");
        // the flags after the last ` -` stay bare (Claude Code's `lastIndexOf(" -")`)
        assert_eq!(with_shell_prefix(Some("/opt/my wrap -q --x"), "echo 'a'"), "'/opt/my wrap -q' --x 'echo '\"'\"'a'\"'\"''");
        assert_eq!(with_shell_prefix(Some("/opt/wrap"), ""), "/opt/wrap ''");
        assert_eq!(with_shell_prefix(Some("-x"), "ls"), "-x ls");
    }

    #[cfg(unix)]
    #[test]
    fn the_relay_passes_stdin_through_and_prints_the_person_s_output_unchanged() {
        let root = tmp("relay");
        let (home, config, project) = (root.join("home"), root.join("config"), root.join("project"));
        for d in [&home, &config, &project] {
            std::fs::create_dir_all(d).unwrap();
        }
        let input = json!({"workspace": {"project_dir": project}, "rate_limits": {"seven_day": {"used_percentage": 6, "resets_at": 4102444800u64}}}).to_string() + "\n";
        // no status line of their own: nothing printed, but the record is written
        assert_eq!(relay(input.as_bytes(), &home, Some("default"), &config, None, None), (Vec::new(), 0));
        let rec = read(&home, "default");
        assert_eq!(rec["windows"]["seven_day"], json!({"used_percent": 6.0, "resets_at": 4102444800.0}));
        assert_eq!(rec["source"], json!("terminal"));
        // their command gets the same bytes on stdin; its stdout comes back byte for byte (colours, no trailing newline)
        let cmd = "cat > \"$0.in\"; printf '\\033[2mline\\033[0m one\\n  two'".replace("$0", &root.join("seen").to_string_lossy());
        std::fs::write(config.join("settings.json"), json!({"statusLine": {"type": "command", "command": cmd}}).to_string()).unwrap();
        let (out, code) = relay(input.as_bytes(), &home, Some("work"), &config, None, None);
        assert_eq!(out, b"\x1b[2mline\x1b[0m one\n  two");
        assert_eq!(code, 0);
        assert_eq!(std::fs::read(root.join("seen.in")).unwrap(), input.as_bytes());
        assert!(record_path(&home, "work").unwrap().exists());
        // an account omher does not give: the line still runs, nothing is recorded, and never as `default`
        std::fs::remove_file(record_path(&home, "default").unwrap()).unwrap();
        for bad in [None, Some(""), Some("Work"), Some("../x")] {
            assert_eq!(relay(input.as_bytes(), &home, bad, &config, None, None).0, b"\x1b[2mline\x1b[0m one\n  two", "{bad:?}");
        }
        assert!(!record_path(&home, "default").unwrap().exists());
        // the project's own line wins over the user's
        std::fs::create_dir_all(project.join(".claude")).unwrap();
        std::fs::write(project.join(".claude/settings.json"), json!({"statusLine": {"type": "command", "command": "echo project"}}).to_string()).unwrap();
        assert_eq!(relay(input.as_bytes(), &home, Some("default"), &config, None, None).0, b"project\n");
        // CLAUDE_CODE_SHELL_PREFIX: the command runs through the prefix, as Claude Code runs it
        let wrap = root.join("wrap.sh");
        std::fs::write(&wrap, "#!/bin/sh\nprintf 'wrapped:'\nexec /bin/sh -c \"$1\"\n").unwrap();
        std::fs::set_permissions(&wrap, std::os::unix::fs::PermissionsExt::from_mode(0o755)).unwrap();
        assert_eq!(relay(input.as_bytes(), &home, Some("default"), &config, None, Some(&wrap.to_string_lossy())).0, b"wrapped:project\n");
    }

    #[cfg(unix)]
    #[test]
    fn a_failing_command_prints_what_it_prints_without_the_relay() {
        let root = tmp("failing");
        let (home, config) = (root.join("home"), root.join("config"));
        std::fs::create_dir_all(&config).unwrap();
        for cmd in ["echo partial; exit 3", "exit 1", "no-such-program-omher-test", "printf 'x'; kill -9 $$"] {
            std::fs::write(config.join("settings.json"), json!({"statusLine": {"type": "command", "command": cmd}}).to_string()).unwrap();
            // what Claude Code itself would get from `sh -c <cmd>` with the same stdin
            let mut direct = Command::new("/bin/sh").arg("-c").arg(cmd).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().unwrap();
            // a command that exits without reading its stdin closes the pipe first (EPIPE on Linux); Claude Code and
            // the relay both ignore that, so the reference run does too
            let _ = direct.stdin.take().unwrap().write_all(b"{}");
            let d = direct.wait_with_output().unwrap();
            let (out, code) = relay(b"not json at all", &home, Some("default"), &config, Some(&root), None);
            assert_eq!(out, d.stdout, "{cmd}");
            assert_eq!(code, d.status.code().unwrap_or(1), "{cmd}");
        }
        // input that is not JSON records nothing
        assert!(!home.join(".omher/usage/claude/default.json").exists());
    }
}

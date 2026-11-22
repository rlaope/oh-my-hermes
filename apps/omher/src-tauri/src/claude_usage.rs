//! omher's own record of the subscription usage Claude Code reports, for the sidebar meter (the bridge reads it).
//!
//! Claude Code writes no usage number to its own files on a normal run (only a request that hit a limit leaves a
//! `rate_limit_info` in its transcript). It does report the numbers live, in two places, and omher keeps them:
//! * a chat session's stream-json `rate_limit_event` (`rate_limit_info.unifiedWindows.<window>.utilization`, 0..1),
//!   read by the chat spawner ([`UsageTap`] in agent_chat.rs);
//! * the JSON a TERMINALS Claude Code hands its status line command on stdin (`rate_limits.<window>.used_percentage`,
//!   0..100). omher starts an interactive Claude Code with `--settings` whose `statusLine` runs this binary as a relay
//!   (`omher --statusline-relay <account>`, [`relay_main`]): it records the `rate_limits` part, then runs the
//!   person's own `statusLine` command (resolved as Claude Code resolves it) with the same stdin and prints its
//!   output unchanged, or prints nothing when they have none.
//!
//! The record is `~/.omher/usage/claude/<account id or "default">.json`, replaced whole through a temporary file:
//! `{at, windows: {<window>: {used_percent, resets_at}}, status, source: "chat" | "terminal"}`. Nothing is sent
//! anywhere and no token is read.

use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU32, Ordering};

use serde_json::{json, Map, Value};

/// The first argument that turns the omher binary into the status line relay (checked in `main` before Tauri starts).
pub const RELAY_FLAG: &str = "--statusline-relay";
/// The account name of Claude Code's own login on this computer (no `CLAUDE_CONFIG_DIR` from omher).
pub const DEFAULT_ACCOUNT: &str = "default";
/// The `statusLine` keys that change how the line looks, copied from the person's own so it looks the same.
const LOOK_KEYS: [&str; 3] = ["padding", "refreshInterval", "hideVimModeIndicator"];

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

/// Replace `account`'s record with `record`: written to a temporary file beside it, then renamed over it.
pub fn write_record(home: &Path, account: &str, record: &Value) -> Result<(), String> {
    static SEQ: AtomicU32 = AtomicU32::new(0);
    let file = record_path(home, account).ok_or("bad account")?;
    let dir = file.parent().ok_or("no folder")?;
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let tmp = dir.join(format!(".{account}.{}.{}.tmp", std::process::id(), SEQ.fetch_add(1, Ordering::SeqCst)));
    let body = serde_json::to_vec(record).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, body).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, &file).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        e.to_string()
    })
}

/// A chat line: when it is a `rate_limit_event`, `account`'s record becomes what it says. Errors are dropped (the
/// meter only misses one reading).
pub fn record_chat_line(home: &Path, account: &str, line: &str) {
    if !line.contains("\"rate_limit_event\"") {
        return;
    }
    let Ok(v) = serde_json::from_str::<Value>(line) else { return };
    if let Some(r) = from_stream_event(&v, now()) {
        let _ = write_record(home, account, &r);
    }
}

// ---------------------------------------------------------------------------------------------
// TERMINALS: the status line relay
// ---------------------------------------------------------------------------------------------

fn read_settings(path: &Path) -> Option<Map<String, Value>> {
    let text = std::fs::read_to_string(path).ok()?;
    match serde_json::from_str::<Value>(&text).ok()? {
        Value::Object(m) => Some(m),
        _ => None,
    }
}

/// The person's own `statusLine`, as Claude Code resolves it from their files: `~/.claude/settings.json` (or
/// `$CLAUDE_CONFIG_DIR/settings.json`), overlaid by the project's `.claude/settings.json`, then its
/// `.claude/settings.local.json` (the later one wins key by key). Only the `statusLine` key is read. `None` when no
/// file sets a command line.
pub fn user_status_line(project: Option<&Path>, config_dir: &Path) -> Option<Map<String, Value>> {
    let mut files = vec![config_dir.join("settings.json")];
    if let Some(p) = project {
        files.push(p.join(".claude").join("settings.json"));
        files.push(p.join(".claude").join("settings.local.json"));
    }
    let mut line: Option<Map<String, Value>> = None;
    for f in files {
        match read_settings(&f).and_then(|mut m| m.remove("statusLine")) {
            Some(Value::Object(o)) => {
                let merged = line.get_or_insert_with(Map::new);
                for (k, v) in o {
                    merged.insert(k, v);
                }
            }
            Some(Value::Null) | None => {}
            Some(_) => line = None,
        }
    }
    let line = line?;
    let command = line.get("command").and_then(Value::as_str).unwrap_or("");
    // a line that is omher's own relay would only call itself
    if line.get("type").and_then(Value::as_str) != Some("command") || command.trim().is_empty() || command.contains(RELAY_FLAG) {
        return None;
    }
    Some(line)
}

/// How a status line command names `exe`: single-quoted for `sh` (macOS, Linux); on Windows with forward slashes,
/// bare when the path has nothing a shell reads (so Git Bash and PowerShell both run it), else double-quoted.
fn shell_word(exe: &Path, windows: bool) -> String {
    let s = exe.to_string_lossy();
    if windows {
        let s = s.replace('\\', "/");
        if s.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, ':' | '/' | '.' | '_' | '-')) {
            return s;
        }
        return format!("\"{s}\"");
    }
    format!("'{}'", s.replace('\'', "'\\''"))
}

/// The `--settings` JSON a TERMINALS Claude Code starts with: a `statusLine` that runs the relay for `account`,
/// with the person's own padding, refresh interval and vim-indicator choice (`user`) so the line looks the same.
pub fn terminal_settings(exe: &Path, account: &str, user: Option<&Map<String, Value>>, windows: bool) -> String {
    let mut line = Map::new();
    line.insert("type".into(), json!("command"));
    line.insert("command".into(), json!(format!("{} {RELAY_FLAG} {account}", shell_word(exe, windows))));
    for k in LOOK_KEYS {
        if let Some(v) = user.and_then(|u| u.get(k)) {
            line.insert(k.into(), v.clone());
        }
    }
    json!({"statusLine": line}).to_string()
}

/// The program a status line runs to reach this omher: the AppImage file inside an AppImage (its mounted binary
/// needs the image's libraries), else this executable.
fn relay_exe() -> Option<PathBuf> {
    if cfg!(target_os = "linux") {
        if let Some(a) = std::env::var_os("APPIMAGE").filter(|a| !a.is_empty()) {
            return Some(PathBuf::from(a));
        }
    }
    std::env::current_exe().ok()
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).filter(|v| !v.is_empty()).map(PathBuf::from)
}

/// Claude Code's config folder for a session with `account_env`: its `CLAUDE_CONFIG_DIR`, else omher's own one,
/// else `~/.claude`.
fn config_dir(home: &Path, account_env: &[(String, String)]) -> PathBuf {
    account_env
        .iter()
        .find(|(k, _)| k == "CLAUDE_CONFIG_DIR")
        .map(|(_, v)| PathBuf::from(v))
        .or_else(|| std::env::var_os("CLAUDE_CONFIG_DIR").filter(|v| !v.is_empty()).map(PathBuf::from))
        .unwrap_or_else(|| home.join(".claude"))
}

/// The arguments a TERMINALS Claude Code in `cwd` with `account_env` gets for the relay: `--settings <json>`, or none
/// when this omher cannot name itself or the account.
pub fn terminal_args(cwd: &Path, account_env: &[(String, String)]) -> Vec<OsString> {
    let (Some(home), Some(exe), Some(account)) = (home_dir(), relay_exe(), account_of(account_env)) else {
        return Vec::new();
    };
    let user = user_status_line(Some(cwd), &config_dir(&home, account_env));
    vec!["--settings".into(), terminal_settings(&exe, &account, user.as_ref(), cfg!(windows)).into()]
}

/// The shell Claude Code runs a status line command with: `sh -c` on macOS and Linux; on Windows Git Bash
/// (`CLAUDE_CODE_GIT_BASH_PATH`, else `bash`), else PowerShell.
fn shells(command: &str) -> Vec<Command> {
    let with = |program: OsString, args: &[&str]| {
        let mut c = Command::new(program);
        c.args(args).arg(command);
        c
    };
    if cfg!(windows) {
        let bash = std::env::var_os("CLAUDE_CODE_GIT_BASH_PATH").filter(|v| !v.is_empty()).unwrap_or_else(|| "bash".into());
        vec![with(bash, &["-c"]), with("powershell".into(), &["-NoProfile", "-Command"])]
    } else {
        vec![with("/bin/sh".into(), &["-c"])]
    }
}

/// Run the person's status line `command` with `input` on stdin, as Claude Code would: its stdout and exit code
/// (stderr goes where the relay's goes). `None` when no shell could start it.
pub fn run_user(command: &str, input: &[u8]) -> Option<(Vec<u8>, i32)> {
    for mut cmd in shells(command) {
        let Ok(mut child) = cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit()).spawn() else { continue };
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
        return Some((out, code));
    }
    None
}

/// The relay itself: record `input`'s `rate_limits` for `account` (never failing the line), then run the person's
/// own status line command, resolved for the input's project, with the same input. Its output and exit code, or
/// nothing and 0 when they have no status line.
pub fn relay(input: &[u8], home: &Path, account: &str, config_dir: &Path, cwd: Option<&Path>) -> (Vec<u8>, i32) {
    let parsed = serde_json::from_slice::<Value>(input).ok();
    if let Some(v) = &parsed {
        let v = v.clone();
        let home = home.to_path_buf();
        let account = account.to_string();
        let _ = std::panic::catch_unwind(move || {
            if let Some(r) = from_statusline(&v, now()) {
                let _ = write_record(&home, &account, &r);
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
    run_user(command, input).unwrap_or((Vec::new(), 1))
}

/// `omher --statusline-relay <account>`: read stdin, [`relay`], print what the person's command printed, exit
/// with its code. Runs before any app start-up.
pub fn relay_main(args: &[OsString]) -> i32 {
    let mut input = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut input);
    let account = args.get(2).and_then(|a| a.to_str()).filter(|a| valid_account(a)).unwrap_or(DEFAULT_ACCOUNT).to_string();
    let Some(home) = home_dir() else { return 0 };
    let config = std::env::var_os("CLAUDE_CONFIG_DIR").filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| home.join(".claude"));
    let cwd = std::env::current_dir().ok();
    let (out, code) = relay(&input, &home, &account, &config, cwd.as_deref());
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
    fn the_record_is_replaced_whole_and_only_under_omher_usage() {
        let home = tmp("write");
        let r = json!({"at": 1.0, "windows": {"seven_day": {"used_percent": 6.0}}, "status": "allowed", "source": "chat"});
        write_record(&home, "default", &r).unwrap();
        write_record(&home, "work", &json!({"at": 2.0})).unwrap();
        write_record(&home, "default", &json!({"at": 3.0})).unwrap();
        let dir = home.join(".omher/usage/claude");
        let read = |n: &str| serde_json::from_str::<Value>(&std::fs::read_to_string(dir.join(n)).unwrap()).unwrap();
        assert_eq!(read("default.json"), json!({"at": 3.0}));
        assert_eq!(read("work.json"), json!({"at": 2.0}));
        let mut names: Vec<String> = std::fs::read_dir(&dir).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["default.json", "work.json"], "no temporary file is left");
        for bad in ["", "../x", "Work", "a/b", "..", "default/.."] {
            assert!(write_record(&home, bad, &r).is_err(), "{bad:?}");
        }
        // a chat line that is not a rate_limit_event writes nothing
        record_chat_line(&home, "chatonly", r#"{"type":"assistant","message":{}}"#);
        assert!(!dir.join("chatonly.json").exists());
        record_chat_line(&home, "chatonly", REAL_EVENT);
        assert_eq!(read("chatonly.json")["windows"]["seven_day"]["used_percent"], json!(6.0));
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
        // a broken local file is skipped, as Claude Code skips it
        std::fs::write(project.join(".claude/settings.local.json"), "{not json").unwrap();
        assert_eq!(user_status_line(Some(&project), &user).unwrap()["command"], json!("project-line"));
        // no project: the user's own; omher's relay is never the person's line
        assert_eq!(user_status_line(None, &user).unwrap()["command"], json!("user-line"));
        set(user.join("settings.json"), json!({"statusLine": {"type": "command", "command": "'/x/omher' --statusline-relay default"}}));
        assert_eq!(user_status_line(None, &user), None);
    }

    #[test]
    fn the_settings_run_the_relay_and_keep_how_the_line_looks() {
        let user: Map<String, Value> = serde_json::from_value(json!({"type": "command", "command": "mine", "padding": 0, "refreshInterval": 5, "other": 1})).unwrap();
        let s: Value = serde_json::from_str(&terminal_settings(Path::new("/Applications/omher.app/Contents/MacOS/omher"), "work", Some(&user), false)).unwrap();
        assert_eq!(s, json!({"statusLine": {"type": "command", "command": "'/Applications/omher.app/Contents/MacOS/omher' --statusline-relay work", "padding": 0, "refreshInterval": 5}}));
        let s: Value = serde_json::from_str(&terminal_settings(Path::new("/x/it's/omher"), "default", None, false)).unwrap();
        assert_eq!(s["statusLine"]["command"], json!("'/x/it'\\''s/omher' --statusline-relay default"));
        assert_eq!(s.as_object().unwrap().len(), 1, "only statusLine");
        let w: Value = serde_json::from_str(&terminal_settings(Path::new(r"C:\Users\k\AppData\Local\omher\omher.exe"), "default", None, true)).unwrap();
        assert_eq!(w["statusLine"]["command"], json!("C:/Users/k/AppData/Local/omher/omher.exe --statusline-relay default"));
        let w: Value = serde_json::from_str(&terminal_settings(Path::new(r"C:\Program Files\omher\omher.exe"), "default", None, true)).unwrap();
        assert_eq!(w["statusLine"]["command"], json!("\"C:/Program Files/omher/omher.exe\" --statusline-relay default"));
    }

    #[cfg(unix)]
    #[test]
    fn the_relay_passes_stdin_through_and_prints_the_person_s_output_unchanged() {
        let root = tmp("relay");
        let (home, config, project) = (root.join("home"), root.join("config"), root.join("project"));
        for d in [&home, &config, &project] {
            std::fs::create_dir_all(d).unwrap();
        }
        let input = json!({"workspace": {"project_dir": project}, "rate_limits": {"seven_day": {"used_percentage": 6, "resets_at": 1795420800}}}).to_string() + "\n";
        // no status line of their own: nothing printed, but the record is written
        assert_eq!(relay(input.as_bytes(), &home, "default", &config, None), (Vec::new(), 0));
        let rec: Value = serde_json::from_str(&std::fs::read_to_string(home.join(".omher/usage/claude/default.json")).unwrap()).unwrap();
        assert_eq!(rec["windows"]["seven_day"], json!({"used_percent": 6.0, "resets_at": 1795420800.0}));
        assert_eq!(rec["source"], json!("terminal"));
        // their command gets the same bytes on stdin; its stdout comes back byte for byte (colours, no trailing newline)
        let cmd = "cat > \"$0.in\"; printf '\\033[2mline\\033[0m one\\n  two'".replace("$0", &root.join("seen").to_string_lossy());
        std::fs::write(config.join("settings.json"), json!({"statusLine": {"type": "command", "command": cmd}}).to_string()).unwrap();
        let (out, code) = relay(input.as_bytes(), &home, "work", &config, None);
        assert_eq!(out, b"\x1b[2mline\x1b[0m one\n  two");
        assert_eq!(code, 0);
        assert_eq!(std::fs::read(root.join("seen.in")).unwrap(), input.as_bytes());
        assert!(home.join(".omher/usage/claude/work.json").exists());
        // the project's own line wins over the user's
        std::fs::create_dir_all(project.join(".claude")).unwrap();
        std::fs::write(project.join(".claude/settings.json"), json!({"statusLine": {"type": "command", "command": "echo project"}}).to_string()).unwrap();
        assert_eq!(relay(input.as_bytes(), &home, "default", &config, None).0, b"project\n");
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
            direct.stdin.take().unwrap().write_all(b"{}").unwrap();
            let d = direct.wait_with_output().unwrap();
            let (out, code) = relay(b"not json at all", &home, "default", &config, Some(&root));
            assert_eq!(out, d.stdout, "{cmd}");
            assert_eq!(code, d.status.code().unwrap_or(1), "{cmd}");
        }
        // input that is not JSON records nothing
        assert!(!home.join(".omher/usage/claude/default.json").exists());
    }
}

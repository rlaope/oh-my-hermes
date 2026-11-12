//! Continue a conversation made outside omher (BOUNDARY rule 30). The SESSIONS + menu lists, read-only, the
//! recent Claude Code and Codex conversations for the folders it offers, and opening one shows its last messages
//! before the agent continues it (`--resume <id>`, Codex `thread/resume`; rule 11).
//!
//! Only the CLIs' own conversation files are read, never written: Claude Code transcripts
//! (`<claude config>/projects/<folder slug>/<uuid>.jsonl`) and Codex rollouts
//! (`<codex home>/sessions/YYYY/MM/DD/rollout-*.jsonl`, plus `session_index.jsonl` for thread names). A symlink
//! anywhere under those folders is refused, and every file read must lie inside the CLI's own home once its
//! links are resolved. No credential, token or config file is opened. Each file is read in bounded pieces (its
//! head and its tail), so a long conversation costs the same as a short one.
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use serde::Serialize;
use serde_json::Value;

use crate::sessions::is_uuid;

/// Conversations listed per agent.
pub const LIST_MAX: usize = 20;
/// Messages shown from the conversation the person opens (the same cap as omher's own saved chats).
pub const MSG_MAX: usize = 40;
/// Characters kept of one message (as omher's saved chats, `resume.ts` MAX_TEXT).
const TEXT_MAX: usize = 4_000;
/// Characters of a title or first words.
const TITLE_MAX: usize = 80;
/// Bytes read from the start of a file (its folder, first message, early title).
const HEAD: u64 = 256 * 1024;
/// Bytes read from the end of a file (its latest title, its last messages).
const TAIL: u64 = 1024 * 1024;
/// Codex rollouts looked at for one listing, newest first.
const CODEX_FILES_MAX: usize = 400;
/// `session_index.jsonl` is read whole only up to this size.
const INDEX_MAX: u64 = 4 * 1024 * 1024;

#[derive(Serialize, Debug, Clone, PartialEq)]
pub struct PastChat {
    pub agent: &'static str,
    /// The CLI's own id: a Claude Code session or a Codex thread (a UUID).
    pub id: String,
    pub cwd: String,
    /// The conversation's name (Claude Code's title, a Codex thread name) or its first words.
    pub title: String,
    /// `title` is a name the CLI or the person gave it, not the first words.
    pub named: bool,
    /// Last change, seconds since the epoch.
    pub at: f64,
}

#[derive(Serialize, Debug, Clone, PartialEq)]
pub struct PastMsg {
    pub role: &'static str,
    pub text: String,
    pub ts: f64,
}

/// The two agents whose conversations can be listed.
pub fn lists(agent: &str) -> bool {
    matches!(agent, "claude" | "codex")
}

/// The folder a CLI keeps its conversations in, as a new session of it would use: the home of the account
/// Settings › Accounts picked for new sessions (`account_env`), else the variable omher itself runs with, else
/// `~/.claude` / `~/.codex`.
pub fn cli_home(home: &Path, agent: &str, account_env: &[(String, String)], env: &dyn Fn(&str) -> Option<String>) -> Option<PathBuf> {
    let (var, dir) = match agent {
        "claude" => ("CLAUDE_CONFIG_DIR", ".claude"),
        "codex" => ("CODEX_HOME", ".codex"),
        _ => return None,
    };
    let picked = account_env.iter().find(|(k, _)| k == var).map(|(_, v)| v.clone());
    Some(picked.or_else(|| env(var).filter(|v| !v.is_empty())).map(PathBuf::from).unwrap_or_else(|| home.join(dir)))
}

/// Claude Code's project folder for a cwd: every character that is not a letter or a digit becomes `-`.
pub fn claude_slug(cwd: &str) -> String {
    cwd.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect()
}

/// `p` when it is a real file (not a link) inside `root` once both are resolved; else `None`.
pub fn inside(root: &Path, p: &Path) -> Option<PathBuf> {
    let meta = std::fs::symlink_metadata(p).ok()?;
    if meta.file_type().is_symlink() || !meta.is_file() {
        return None;
    }
    let real = p.canonicalize().ok()?;
    let base = root.canonicalize().ok()?;
    real.starts_with(&base).then_some(real)
}

/// A real folder, not a link.
fn plain_dir(p: &Path) -> bool {
    std::fs::symlink_metadata(p).map(|m| m.is_dir()).unwrap_or(false)
}

fn same_folder(a: &str, b: &str) -> bool {
    let t = |s: &str| s.trim_end_matches(['/', '\\']).to_string();
    !a.is_empty() && t(a) == t(b)
}

fn mtime(p: &Path) -> f64 {
    std::fs::metadata(p).and_then(|m| m.modified()).ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// Whole lines from `[start, start + len)` of `path`: a line cut by either edge is dropped.
fn lines_in(path: &Path, start: u64, len: u64) -> Vec<Value> {
    let Ok(mut f) = File::open(path) else { return Vec::new() };
    let size = f.metadata().map(|m| m.len()).unwrap_or(0);
    let start = start.min(size);
    if f.seek(SeekFrom::Start(start)).is_err() {
        return Vec::new();
    }
    let mut buf = Vec::new();
    if f.take(len).read_to_end(&mut buf).is_err() {
        return Vec::new();
    }
    let mut parts: Vec<&[u8]> = buf.split(|b| *b == b'\n').collect();
    if start > 0 && !parts.is_empty() {
        parts.remove(0); // begins mid-line
    }
    if start + (buf.len() as u64) < size {
        parts.pop(); // ends mid-line
    }
    parts.into_iter().filter(|l| !l.is_empty()).filter_map(|l| serde_json::from_slice(l).ok()).collect()
}

fn head(path: &Path) -> Vec<Value> {
    lines_in(path, 0, HEAD)
}

/// The tail of a file, or nothing when the head already covered it.
fn tail(path: &Path) -> Vec<Value> {
    let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    if size <= HEAD {
        return Vec::new();
    }
    lines_in(path, size.saturating_sub(TAIL).max(HEAD), TAIL)
}

/// All of a file when small, else its tail: where the last messages are.
fn last_part(path: &Path) -> Vec<Value> {
    let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
    lines_in(path, size.saturating_sub(TAIL), TAIL)
}

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v.get(k).and_then(Value::as_str).unwrap_or("")
}

/// One line, control characters out, at most `n` characters.
fn clip(t: &str, n: usize) -> String {
    let one = t.split_whitespace().collect::<Vec<_>>().join(" ");
    if one.chars().count() <= n {
        one
    } else {
        format!("{}…", one.chars().take(n - 1).collect::<String>())
    }
}

/// Text the person typed, not what the CLI put in the user turn for itself (command tags, reminders, the
/// AGENTS.md and environment blocks Codex sends first, interrupted-request notes).
fn typed(text: &str) -> bool {
    let t = text.trim_start();
    !t.is_empty() && !t.starts_with('<') && !t.starts_with("# AGENTS.md instructions") && !t.starts_with("Caveat:") && !t.starts_with("[Request interrupted")
}

/// `2026-11-12T15:28:55.873Z` → seconds since the epoch (UTC; a fraction kept). `None` when it is not that shape.
pub fn iso_secs(t: &str) -> Option<f64> {
    let b = t.as_bytes();
    if b.len() < 20 || b[4] != b'-' || b[7] != b'-' || b[10] != b'T' || b[13] != b':' || b[16] != b':' {
        return None;
    }
    let n = |r: std::ops::Range<usize>| t.get(r).and_then(|x| x.parse::<i64>().ok());
    let (y, mo, d, h, mi, se) = (n(0..4)?, n(5..7)?, n(8..10)?, n(11..13)?, n(14..16)?, n(17..19)?);
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) {
        return None;
    }
    let rest = &t[19..];
    let frac = rest.strip_prefix('.').map(|r| r.trim_end_matches('Z')).and_then(|f| format!("0.{f}").parse::<f64>().ok()).unwrap_or(0.0);
    // days from civil (Howard Hinnant)
    let y2 = if mo <= 2 { y - 1 } else { y };
    let era = y2.div_euclid(400);
    let yoe = y2 - era * 400;
    let doy = (153 * (if mo > 2 { mo - 3 } else { mo + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some((days * 86_400 + h * 3_600 + mi * 60 + se) as f64 + frac)
}

// ---- Claude Code ------------------------------------------------------------------------------

/// The text of a Claude Code user line the person typed (not a tool result, a meta line or a subagent's).
fn claude_user_text(o: &Value) -> Option<String> {
    if s(o, "type") != "user" || o.get("isMeta").and_then(Value::as_bool) == Some(true) || o.get("isSidechain").and_then(Value::as_bool) == Some(true) {
        return None;
    }
    let c = &o["message"]["content"];
    let text = match c {
        Value::String(t) => t.clone(),
        Value::Array(blocks) => blocks.iter().filter(|b| s(b, "type") == "text").map(|b| s(b, "text")).collect::<Vec<_>>().join("\n"),
        _ => return None,
    };
    typed(&text).then_some(text)
}

/// The text blocks of a Claude Code assistant line (its tool calls and thinking left out).
fn claude_assistant_text(o: &Value) -> Option<String> {
    if s(o, "type") != "assistant" || o.get("isSidechain").and_then(Value::as_bool) == Some(true) {
        return None;
    }
    let blocks = o["message"]["content"].as_array()?;
    let text = blocks.iter().filter(|b| s(b, "type") == "text").map(|b| s(b, "text")).collect::<Vec<_>>().join("\n");
    (!text.trim().is_empty()).then_some(text)
}

/// The latest name in `lines`: a `custom-title` (a rename in Claude Code) wins over an `ai-title`.
fn claude_title(lines: &[Value]) -> (String, String) {
    let (mut custom, mut ai) = (String::new(), String::new());
    for o in lines {
        match s(o, "type") {
            "custom-title" if !s(o, "customTitle").trim().is_empty() => custom = clip(s(o, "customTitle"), TITLE_MAX),
            "ai-title" if !s(o, "aiTitle").trim().is_empty() => ai = clip(s(o, "aiTitle"), TITLE_MAX),
            _ => {}
        }
    }
    (custom, ai)
}

/// One Claude Code transcript as a list row, when it ran in `cwd` and the person said something in it.
pub fn claude_row(path: &Path, cwd: &str) -> Option<PastChat> {
    let id = path.file_stem()?.to_str()?.to_string();
    if !is_uuid(&id) {
        return None;
    }
    let first = head(path);
    // the slug is lossy ("/a/b-c" and "/a/b/c" share it): the transcript's own cwd decides
    let seen = first.iter().map(|o| s(o, "cwd")).find(|c| !c.is_empty())?;
    if !same_folder(seen, cwd) {
        return None;
    }
    let words = first.iter().find_map(claude_user_text)?;
    let (mut custom, mut ai) = claude_title(&first);
    let (c2, a2) = claude_title(&tail(path));
    if !c2.is_empty() {
        custom = c2;
    }
    if !a2.is_empty() {
        ai = a2;
    }
    let named = !custom.is_empty() || !ai.is_empty();
    let title = if !custom.is_empty() { custom } else if !ai.is_empty() { ai } else { clip(&words, TITLE_MAX) };
    Some(PastChat { agent: "claude", id, cwd: cwd.trim_end_matches(['/', '\\']).to_string(), title, named, at: mtime(path) })
}

/// The recent Claude Code conversations in each of `cwds`, newest first.
pub fn claude_list(root: &Path, cwds: &[String]) -> Vec<PastChat> {
    let projects = root.join("projects");
    if !plain_dir(&projects) {
        return Vec::new();
    }
    let mut out = Vec::new();
    for cwd in cwds {
        let dir = projects.join(claude_slug(cwd));
        if !plain_dir(&dir) {
            continue;
        }
        let Ok(rd) = std::fs::read_dir(&dir) else { continue };
        let mut files: Vec<(f64, PathBuf)> = rd
            .flatten()
            .filter(|e| e.file_type().map(|t| t.is_file()).unwrap_or(false))
            .map(|e| e.path())
            .filter(|p| p.extension().is_some_and(|x| x == "jsonl") && p.file_stem().and_then(|x| x.to_str()).is_some_and(is_uuid))
            .filter_map(|p| inside(root, &p))
            .map(|p| (mtime(&p), p))
            .collect();
        files.sort_by(|a, b| b.0.total_cmp(&a.0));
        // a few more than shown: empty ones (only /clear) and other folders' are skipped
        out.extend(files.iter().take(LIST_MAX * 2).filter_map(|(_, p)| claude_row(p, cwd)).take(LIST_MAX));
    }
    newest(out)
}

/// The last messages of Claude Code conversation `id` in `cwd`: what the person typed and the agent's answers.
pub fn claude_messages(root: &Path, id: &str, cwd: &str) -> Result<Vec<PastMsg>, String> {
    if !is_uuid(id) {
        return Err("not a conversation id".into());
    }
    let projects = root.join("projects");
    let dir = projects.join(claude_slug(cwd));
    if !plain_dir(&projects) || !plain_dir(&dir) {
        return Err("no such conversation".into());
    }
    let path = inside(root, &dir.join(format!("{id}.jsonl"))).ok_or("no such conversation")?;
    let mut out: Vec<PastMsg> = Vec::new();
    let mut last_answer = String::new();
    for o in last_part(&path) {
        let ts = iso_secs(s(&o, "timestamp")).unwrap_or(0.0);
        if let Some(t) = claude_user_text(&o) {
            out.push(PastMsg { role: "user", text: clip_text(&t), ts });
            last_answer.clear();
        } else if let Some(t) = claude_assistant_text(&o) {
            // one answer is split over several lines (one per content block) with the same message id
            let mid = s(&o["message"], "id").to_string();
            match out.last_mut() {
                Some(m) if m.role == "assistant" && !mid.is_empty() && mid == last_answer => m.text = clip_text(&format!("{}\n\n{t}", m.text)),
                _ => out.push(PastMsg { role: "assistant", text: clip_text(&t), ts }),
            }
            last_answer = mid;
        }
    }
    Ok(keep_last(out))
}

// ---- Codex ------------------------------------------------------------------------------------

/// Codex rollout files, newest day first (names carry the time, so newest first within a day too), at most
/// `max`. Links are skipped at every level.
fn codex_rollouts(root: &Path, max: usize) -> Vec<PathBuf> {
    let sessions = root.join("sessions");
    if !plain_dir(&sessions) {
        return Vec::new();
    }
    let digits = |p: &Path, n: usize| p.file_name().and_then(|x| x.to_str()).is_some_and(|x| x.len() == n && x.bytes().all(|b| b.is_ascii_digit()));
    let sub = |d: &Path, n: usize| -> Vec<PathBuf> {
        let mut v: Vec<PathBuf> = std::fs::read_dir(d).map(|rd| rd.flatten().map(|e| e.path()).filter(|p| plain_dir(p) && digits(p, n)).collect()).unwrap_or_default();
        v.sort();
        v.reverse();
        v
    };
    let mut out = Vec::new();
    for y in sub(&sessions, 4) {
        for m in sub(&y, 2) {
            for d in sub(&m, 2) {
                let mut files: Vec<PathBuf> = std::fs::read_dir(&d)
                    .map(|rd| {
                        rd.flatten()
                            .filter(|e| e.file_type().map(|t| t.is_file()).unwrap_or(false))
                            .map(|e| e.path())
                            .filter(|p| p.file_name().and_then(|x| x.to_str()).is_some_and(|x| x.starts_with("rollout-") && x.ends_with(".jsonl")))
                            .collect()
                    })
                    .unwrap_or_default();
                files.sort();
                files.reverse();
                for f in files {
                    if out.len() >= max {
                        return out;
                    }
                    out.push(f);
                }
            }
        }
    }
    out
}

/// Thread names from `session_index.jsonl` (the last name of each id wins).
fn codex_names(root: &Path) -> std::collections::HashMap<String, String> {
    let mut names = std::collections::HashMap::new();
    let idx = root.join("session_index.jsonl");
    let Some(p) = inside(root, &idx) else { return names };
    if std::fs::metadata(&p).map(|m| m.len() > INDEX_MAX).unwrap_or(true) {
        return names;
    }
    for o in lines_in(&p, 0, INDEX_MAX) {
        let (id, name) = (s(&o, "id"), s(&o, "thread_name"));
        if !id.is_empty() && !name.trim().is_empty() {
            names.insert(id.to_string(), clip(name, TITLE_MAX));
        }
    }
    names
}

/// The text of a Codex user message the person typed (Codex's own AGENTS.md and environment blocks left out).
fn codex_user_text(o: &Value) -> Option<String> {
    let p = &o["payload"];
    if s(o, "type") != "response_item" || s(p, "type") != "message" || s(p, "role") != "user" {
        return None;
    }
    let text = p["content"].as_array()?.iter().filter(|b| s(b, "type") == "input_text").map(|b| s(b, "text")).filter(|t| typed(t)).collect::<Vec<_>>().join("\n");
    (!text.trim().is_empty()).then_some(text)
}

fn codex_assistant_text(o: &Value) -> Option<String> {
    let p = &o["payload"];
    if s(o, "type") != "response_item" || s(p, "type") != "message" || s(p, "role") != "assistant" {
        return None;
    }
    // a thread Codex imported from another agent carries that agent's tool results as answer text: not an answer
    let text = p["content"]
        .as_array()?
        .iter()
        .filter(|b| s(b, "type") == "output_text")
        .map(|b| s(b, "text"))
        .filter(|t| !t.trim_start().starts_with("[external_agent_tool_result]"))
        .collect::<Vec<_>>()
        .join("\n");
    (!text.trim().is_empty()).then_some(text)
}

/// A rollout's `session_meta`: (thread id, cwd), when it is a conversation of its own (not a subagent's thread).
fn codex_meta(lines: &[Value]) -> Option<(String, String)> {
    let first = lines.first()?;
    if s(first, "type") != "session_meta" {
        return None;
    }
    let p = &first["payload"];
    // a subagent's thread names its parent in `source`; a fork names where it came from
    if p.get("source").is_some_and(Value::is_object) || p.get("forked_from_id").is_some_and(|v| !v.is_null()) {
        return None;
    }
    let id = s(p, "id").to_string();
    is_uuid(&id).then(|| (id, s(p, "cwd").to_string()))
}

/// One Codex rollout as a list row, when it ran in one of `cwds` and the person said something in it.
pub fn codex_row(path: &Path, cwds: &[String], names: &std::collections::HashMap<String, String>) -> Option<PastChat> {
    let first = head(path);
    let (id, seen) = codex_meta(&first)?;
    let cwd = cwds.iter().find(|c| same_folder(&seen, c))?;
    let words = first.iter().find_map(codex_user_text)?;
    let name = names.get(&id).cloned().unwrap_or_default();
    let named = !name.is_empty();
    let title = if named { name } else { clip(&words, TITLE_MAX) };
    Some(PastChat { agent: "codex", id, cwd: cwd.trim_end_matches(['/', '\\']).to_string(), title, named, at: mtime(path) })
}

/// The recent Codex conversations in any of `cwds`, newest first.
pub fn codex_list(root: &Path, cwds: &[String]) -> Vec<PastChat> {
    let names = codex_names(root);
    let rows = codex_rollouts(root, CODEX_FILES_MAX).iter().filter_map(|p| inside(root, p)).filter_map(|p| codex_row(&p, cwds, &names)).collect();
    newest(rows)
}

/// The last messages of Codex thread `id` (its rollout found by name; the folder is checked against `cwd`).
pub fn codex_messages(root: &Path, id: &str, cwd: &str) -> Result<Vec<PastMsg>, String> {
    if !is_uuid(id) {
        return Err("not a conversation id".into());
    }
    let suffix = format!("-{id}.jsonl");
    let path = codex_rollouts(root, usize::MAX)
        .into_iter()
        .find(|p| p.file_name().and_then(|x| x.to_str()).is_some_and(|x| x.ends_with(&suffix)))
        .and_then(|p| inside(root, &p))
        .ok_or("no such conversation")?;
    match codex_meta(&head(&path)) {
        Some((tid, seen)) if tid == id && same_folder(&seen, cwd) => {}
        _ => return Err("no such conversation".into()),
    }
    let mut out = Vec::new();
    for o in last_part(&path) {
        let ts = iso_secs(s(&o, "timestamp")).unwrap_or(0.0);
        if let Some(t) = codex_user_text(&o) {
            out.push(PastMsg { role: "user", text: clip_text(&t), ts });
        } else if let Some(t) = codex_assistant_text(&o) {
            out.push(PastMsg { role: "assistant", text: clip_text(&t), ts });
        }
    }
    Ok(keep_last(out))
}

// ---- both -------------------------------------------------------------------------------------

fn clip_text(t: &str) -> String {
    let t = t.trim();
    if t.chars().count() <= TEXT_MAX {
        t.to_string()
    } else {
        format!("{}…", t.chars().take(TEXT_MAX - 1).collect::<String>())
    }
}

fn keep_last(mut v: Vec<PastMsg>) -> Vec<PastMsg> {
    if v.len() > MSG_MAX {
        v.drain(..v.len() - MSG_MAX);
    }
    v
}

fn newest(mut v: Vec<PastChat>) -> Vec<PastChat> {
    v.sort_by(|a, b| b.at.total_cmp(&a.at));
    let mut seen = std::collections::HashSet::new();
    v.retain(|c| seen.insert(c.id.clone()));
    v.truncate(LIST_MAX);
    v
}

/// An absolute folder path, as each CLI records its cwd (`/…` on macOS and Linux, `C:\\…` on Windows).
fn absolute(c: &str) -> bool {
    Path::new(c).is_absolute() || c.starts_with('/')
}

/// Only absolute folders, at most 12 (the + menu offers the recent folders and home).
pub fn checked_cwds(cwds: &[String]) -> Vec<String> {
    cwds.iter().filter(|c| absolute(c)).take(12).cloned().collect()
}

/// `agent`'s recent conversations in `cwds`, read from `root` (its home, [`cli_home`]).
pub fn list(root: &Path, agent: &str, cwds: &[String]) -> Result<Vec<PastChat>, String> {
    let cwds = checked_cwds(cwds);
    match agent {
        "claude" => Ok(claude_list(root, &cwds)),
        "codex" => Ok(codex_list(root, &cwds)),
        _ => Err(format!("{agent} conversations are not listed")),
    }
}

/// The last messages of `agent`'s conversation `id` in `cwd`.
pub fn messages(root: &Path, agent: &str, id: &str, cwd: &str) -> Result<Vec<PastMsg>, String> {
    if !absolute(cwd) {
        return Err("not a folder".into());
    }
    match agent {
        "claude" => claude_messages(root, id, cwd),
        "codex" => codex_messages(root, id, cwd),
        _ => Err(format!("{agent} conversations are not listed")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    const C1: &str = "11111111-2222-4333-8444-555555555555";
    const C2: &str = "22222222-2222-4333-8444-555555555555";
    const X1: &str = "01a1d060-4ab7-72b2-b02b-1dbee1d5f52c";
    const X2: &str = "01a1d060-6967-74c3-8b7c-33c05229878b";

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("omher-past-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn write(p: &Path, lines: &[Value]) {
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        let mut f = File::create(p).unwrap();
        for l in lines {
            writeln!(f, "{l}").unwrap();
        }
    }

    fn claude_file(cwd: &str, id: &str) -> Vec<Value> {
        vec![
            serde_json::json!({"type": "user", "isMeta": true, "cwd": cwd, "message": {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}, "timestamp": "2026-11-12T10:00:00.000Z", "sessionId": id}),
            serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": "<command-name>/clear</command-name>"}, "timestamp": "2026-11-12T10:00:01.000Z"}),
            serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": "Remember the word MARIGOLD for later"}, "timestamp": "2026-11-12T10:00:02.000Z"}),
            serde_json::json!({"type": "assistant", "cwd": cwd, "message": {"id": "m1", "role": "assistant", "content": [{"type": "thinking", "thinking": "hm"}]}, "timestamp": "2026-11-12T10:00:03.000Z"}),
            serde_json::json!({"type": "assistant", "cwd": cwd, "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "Noted."}]}, "timestamp": "2026-11-12T10:00:04.000Z"}),
            serde_json::json!({"type": "assistant", "cwd": cwd, "message": {"id": "m1", "role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}, "timestamp": "2026-11-12T10:00:05.000Z"}),
            serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}, "timestamp": "2026-11-12T10:00:06.000Z"}),
            serde_json::json!({"type": "assistant", "cwd": cwd, "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "I will remember it."}]}, "timestamp": "2026-11-12T10:00:07.000Z"}),
            serde_json::json!({"type": "assistant", "isSidechain": true, "cwd": cwd, "message": {"id": "s1", "role": "assistant", "content": [{"type": "text", "text": "subagent says"}]}}),
            serde_json::json!({"type": "ai-title", "aiTitle": "Remember a word", "sessionId": id}),
        ]
    }

    #[test]
    fn claude_lists_the_folders_conversations_with_their_title_and_skips_empty_ones() {
        let root = tmp("claude-list");
        let cwd = "/Users/you/code/web-app";
        let dir = root.join("projects").join(claude_slug(cwd));
        write(&dir.join(format!("{C1}.jsonl")), &claude_file(cwd, C1));
        // only /clear: nothing the person said, so not listed
        write(&dir.join(format!("{C2}.jsonl")), &claude_file(cwd, C2)[..2]);
        // the lossy slug: another folder with the same slug is not this one
        let other = "/Users/you/code/web/app";
        assert_eq!(claude_slug(other), claude_slug(cwd));
        write(&dir.join("33333333-2222-4333-8444-555555555555.jsonl"), &claude_file(other, "x"));
        // not a conversation file
        write(&dir.join("notes.jsonl"), &claude_file(cwd, "y"));
        let rows = list(&root, "claude", &[cwd.to_string(), "relative/x".to_string()]).unwrap();
        assert_eq!(rows.len(), 1, "{rows:?}");
        assert_eq!((rows[0].id.as_str(), rows[0].title.as_str(), rows[0].named, rows[0].cwd.as_str()), (C1, "Remember a word", true, cwd));
        // a rename in Claude Code wins; without any title the first words name it
        let mut lines = claude_file(cwd, C1);
        lines.push(serde_json::json!({"type": "custom-title", "customTitle": "My  word\ngame"}));
        write(&dir.join(format!("{C1}.jsonl")), &lines);
        assert_eq!(claude_list(&root, &[cwd.into()])[0].title, "My word game");
        write(&dir.join(format!("{C1}.jsonl")), &claude_file(cwd, C1)[..8]);
        let r = &claude_list(&root, &[cwd.into()])[0];
        assert_eq!((r.title.as_str(), r.named), ("Remember the word MARIGOLD for later", false));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn claude_messages_keep_what_was_typed_and_answered() {
        let root = tmp("claude-msgs");
        let cwd = "/w";
        write(&root.join("projects").join(claude_slug(cwd)).join(format!("{C1}.jsonl")), &claude_file(cwd, C1));
        let m = messages(&root, "claude", C1, cwd).unwrap();
        let got: Vec<(&str, &str)> = m.iter().map(|x| (x.role, x.text.as_str())).collect();
        assert_eq!(got, [("user", "Remember the word MARIGOLD for later"), ("assistant", "Noted.\n\nI will remember it.")]);
        assert_eq!(m[0].ts, iso_secs("2026-11-12T10:00:02.000Z").unwrap());
        // the id is a UUID, never a path
        for bad in ["../x", "x", &format!("{C1}/../{C1}"), ""] {
            assert!(messages(&root, "claude", bad, cwd).is_err(), "{bad}");
        }
        assert!(messages(&root, "claude", C2, cwd).is_err());
        assert!(messages(&root, "claude", C1, "w").is_err());
        assert!(messages(&root, "omo", C1, cwd).is_err());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[test]
    fn links_and_paths_outside_the_cli_home_are_refused() {
        use std::os::unix::fs::symlink;
        let root = tmp("links");
        let away = tmp("links-away");
        let cwd = "/w";
        let slug = claude_slug(cwd);
        // a transcript outside the home, linked in as a file
        write(&away.join(format!("{C1}.jsonl")), &claude_file(cwd, C1));
        std::fs::create_dir_all(root.join("projects").join(&slug)).unwrap();
        symlink(away.join(format!("{C1}.jsonl")), root.join("projects").join(&slug).join(format!("{C1}.jsonl"))).unwrap();
        assert!(claude_list(&root, &[cwd.into()]).is_empty());
        assert!(claude_messages(&root, C1, cwd).is_err());
        // a linked project folder
        let root2 = tmp("links2");
        std::fs::create_dir_all(root2.join("projects")).unwrap();
        symlink(&away, root2.join("projects").join(&slug)).unwrap();
        assert!(claude_list(&root2, &[cwd.into()]).is_empty());
        assert!(claude_messages(&root2, C1, cwd).is_err());
        // a linked projects folder
        let root3 = tmp("links3");
        let real = tmp("links3-real");
        write(&real.join(&slug).join(format!("{C1}.jsonl")), &claude_file(cwd, C1));
        symlink(&real, root3.join("projects")).unwrap();
        assert!(claude_list(&root3, &[cwd.into()]).is_empty());
        // Codex: a linked day folder and a linked rollout
        let x = tmp("links-codex");
        let day = x.join("sessions/2026/11/12");
        std::fs::create_dir_all(&day).unwrap();
        write(&away.join("r.jsonl"), &codex_file(X1, cwd));
        symlink(away.join("r.jsonl"), day.join(format!("rollout-2026-11-12T00-00-00-{X1}.jsonl"))).unwrap();
        symlink(&away, x.join("sessions/2026/11/13")).unwrap();
        assert!(codex_list(&x, &[cwd.into()]).is_empty());
        assert!(codex_messages(&x, X1, cwd).is_err());
        // inside() itself
        assert!(inside(&root, &away.join(format!("{C1}.jsonl"))).is_none());
        for d in [root, away, root2, root3, real, x] {
            let _ = std::fs::remove_dir_all(d);
        }
    }

    fn codex_file(id: &str, cwd: &str) -> Vec<Value> {
        vec![
            serde_json::json!({"timestamp": "2026-11-12T15:28:55.873Z", "type": "session_meta", "payload": {"id": id, "cwd": cwd, "originator": "codex-tui", "source": "cli"}}),
            serde_json::json!({"timestamp": "2026-11-12T15:28:56.000Z", "type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules"}]}}),
            serde_json::json!({"timestamp": "2026-11-12T15:28:56.000Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /w\n..."}, {"type": "input_text", "text": "<environment_context>x</environment_context>"}]}}),
            serde_json::json!({"timestamp": "2026-11-12T15:29:00.000Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Remember COBALT please"}]}}),
            serde_json::json!({"timestamp": "2026-11-12T15:29:05.000Z", "type": "response_item", "payload": {"type": "reasoning", "summary": []}}),
            serde_json::json!({"timestamp": "2026-11-12T15:29:08.000Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "[external_agent_tool_result]\n{}\n[/external_agent_tool_result]"}]}}),
            serde_json::json!({"timestamp": "2026-11-12T15:29:09.000Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Remembered."}]}}),
        ]
    }

    #[test]
    fn codex_lists_its_own_threads_named_from_the_index_and_skips_subagents() {
        let root = tmp("codex-list");
        let cwd = "/Users/you/code/api";
        let day = root.join("sessions/2026/11/12");
        write(&day.join(format!("rollout-2026-11-12T15-28-54-{X1}.jsonl")), &codex_file(X1, cwd));
        write(&day.join(format!("rollout-2026-11-12T15-29-01-{X2}.jsonl")), &codex_file(X2, cwd));
        // a subagent's thread and a fork are not conversations of their own
        let mut sub = codex_file("01a1d060-7a13-75e3-aa36-356cd0706c8a", cwd);
        sub[0]["payload"]["source"] = serde_json::json!({"subagent": {"thread_spawn": {"parent_thread_id": X1}}});
        write(&day.join("rollout-2026-11-12T15-29-06-01a1d060-7a13-75e3-aa36-356cd0706c8a.jsonl"), &sub);
        // another folder
        write(&root.join("sessions/2026/11/11").join("rollout-2026-11-11T00-00-00-01a1d060-0000-75e3-aa36-356cd0706c8a.jsonl"), &codex_file("01a1d060-0000-75e3-aa36-356cd0706c8a", "/elsewhere"));
        write(&root.join("session_index.jsonl"), &[serde_json::json!({"id": X1, "thread_name": "Old name"}), serde_json::json!({"id": X1, "thread_name": "Remember a colour"})]);
        let rows = list(&root, "codex", &[cwd.to_string()]).unwrap();
        let mut got: Vec<(&str, &str, bool)> = rows.iter().map(|r| (r.id.as_str(), r.title.as_str(), r.named)).collect();
        got.sort();
        assert_eq!(got, [(X1, "Remember a colour", true), (X2, "Remember COBALT please", false)]);
        let m = messages(&root, "codex", X2, cwd).unwrap();
        assert_eq!(m.iter().map(|x| (x.role, x.text.as_str())).collect::<Vec<_>>(), [("user", "Remember COBALT please"), ("assistant", "Remembered.")]);
        // the thread must be in the folder asked for
        assert!(messages(&root, "codex", X2, "/elsewhere").is_err());
        assert!(messages(&root, "codex", "01a1d060-7a13-75e3-aa36-356cd0706c8a", cwd).is_err());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn a_long_transcript_is_read_by_its_head_and_tail_only() {
        let root = tmp("long");
        let cwd = "/w";
        let mut lines = claude_file(cwd, C1)[..8].to_vec();
        let filler = "x".repeat(2000);
        for i in 0..1500 {
            lines.push(serde_json::json!({"type": "attachment", "cwd": cwd, "attachment": {"n": i, "pad": filler}}));
        }
        lines.push(serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": "What was the word?"}, "timestamp": "2026-11-12T11:00:00.000Z"}));
        lines.push(serde_json::json!({"type": "assistant", "cwd": cwd, "message": {"id": "m9", "role": "assistant", "content": [{"type": "text", "text": "MARIGOLD"}]}, "timestamp": "2026-11-12T11:00:01.000Z"}));
        lines.push(serde_json::json!({"type": "ai-title", "aiTitle": "Late title"}));
        let p = root.join("projects").join(claude_slug(cwd)).join(format!("{C1}.jsonl"));
        write(&p, &lines);
        assert!(std::fs::metadata(&p).unwrap().len() > HEAD + TAIL);
        let r = &claude_list(&root, &[cwd.into()])[0];
        assert_eq!(r.title, "Late title");
        let m = claude_messages(&root, C1, cwd).unwrap();
        // the early messages lie outside the tail; the last ones are there
        assert_eq!(m.iter().map(|x| x.text.as_str()).collect::<Vec<_>>(), ["What was the word?", "MARIGOLD"]);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn the_home_follows_the_picked_account_then_the_env_then_the_default() {
        let h = Path::new("/home/you");
        let none = |_: &str| None;
        let env = |k: &str| (k == "CLAUDE_CONFIG_DIR").then(|| "/env/claude".to_string());
        assert_eq!(cli_home(h, "claude", &[], &none), Some(h.join(".claude")));
        assert_eq!(cli_home(h, "codex", &[], &none), Some(h.join(".codex")));
        assert_eq!(cli_home(h, "claude", &[], &env), Some(PathBuf::from("/env/claude")));
        let acct = [("CLAUDE_CONFIG_DIR".to_string(), "/home/you/.omher/accounts/claude/work".to_string())];
        assert_eq!(cli_home(h, "claude", &acct, &env), Some(PathBuf::from("/home/you/.omher/accounts/claude/work")));
        assert_eq!(cli_home(h, "omo", &[], &none), None);
        assert!(lists("claude") && lists("codex") && !lists("omo") && !lists("../claude"));
    }

    #[test]
    fn iso_times_and_typed_text() {
        assert_eq!(iso_secs("1970-01-01T00:00:00.000Z"), Some(0.0));
        assert_eq!(iso_secs("2026-11-12T15:28:55.500Z"), Some(1_794_497_335.5));
        assert_eq!(iso_secs("2024-02-29T00:00:00Z"), Some(1_709_164_800.0));
        assert_eq!(iso_secs("nope"), None);
        assert!(typed("hello") && !typed("<command-name>/x</command-name>") && !typed("  ") && !typed("# AGENTS.md instructions for /w"));
        assert_eq!(checked_cwds(&["/a".into(), "b".into(), "C:\\x".into()]).first().map(String::as_str), Some("/a"));
    }

    /// A real conversation made in the Claude Code (or Codex) CLI outside omher: list it from the CLI's own files,
    /// read its last messages, then continue it through omher's own chat path and ask about the first message.
    /// `OMHER_REAL_AGENT` (claude | codex), `OMHER_REAL_DIR` (the scratch folder the CLI ran in). Prints what came
    /// back; run with `cargo test real_past -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_past_conversation_continues_in_omher() {
        use crate::agent_chat::{ChatOut, ChatSessions, Input};
        use std::sync::{Arc, Mutex};
        use std::time::{Duration, Instant};
        let agent = std::env::var("OMHER_REAL_AGENT").unwrap_or_else(|_| "claude".into());
        let dir = PathBuf::from(std::env::var("OMHER_REAL_DIR").expect("OMHER_REAL_DIR")).canonicalize().unwrap();
        let cwd = dir.to_string_lossy().into_owned();
        let home = PathBuf::from(std::env::var("HOME").unwrap());
        let root = cli_home(&home, &agent, &[], &|k| std::env::var(k).ok()).unwrap();
        let rows = list(&root, &agent, &[cwd.clone()]).unwrap();
        println!("LIST {rows:?}");
        let row = rows.first().expect("the CLI's conversation is listed");
        let msgs = messages(&root, &agent, &row.id, &cwd).unwrap();
        println!("MESSAGES {msgs:?}");
        // OMHER_REAL_LIST_ONLY: only the read-only listing and messages (no model turn)
        if std::env::var("OMHER_REAL_LIST_ONLY").is_ok() {
            return;
        }
        let c = Arc::new(ChatSessions::default());
        let out = Arc::new(Mutex::new(Vec::<serde_json::Value>::new()));
        let o = out.clone();
        let id = c
            .start_agent(&agent, &dir, Some(&row.id), &[], None, move |x| {
                if let ChatOut::Event(e) = x {
                    o.lock().unwrap().push(e);
                }
            })
            .unwrap();
        let q = std::env::var("OMHER_REAL_ASK").unwrap_or_else(|_| "What word did I ask you to remember at the start of this conversation? Answer with the word only.".into());
        c.input(id, Input::Send { text: q.clone(), images: vec![], id: "local-1".into() }).unwrap();
        let deadline = Instant::now() + Duration::from_secs(240);
        while Instant::now() < deadline && !out.lock().unwrap().iter().any(|e| s(e, "event") == "turn.end") {
            std::thread::sleep(Duration::from_millis(200));
        }
        c.close(id);
        let got = out.lock().unwrap().clone();
        for e in &got {
            if matches!(s(e, "event"), "message" | "turn.end" | "session.info" | "session.error" | "session.note") {
                println!("EVENT {e}");
            }
        }
        println!("ASKED {q}");
        let answer: String = got.iter().filter(|e| s(e, "event") == "message").map(|e| s(e, "text").to_string()).collect::<Vec<_>>().join("\n");
        println!("ANSWER {answer}");
        let session = got.iter().filter(|e| s(e, "event") == "session.info").map(|e| s(e, "agent_session").to_string()).find(|x| !x.is_empty()).unwrap_or_default();
        println!("SESSION {session} (listed {})", row.id);
        assert!(!answer.trim().is_empty());
    }
}

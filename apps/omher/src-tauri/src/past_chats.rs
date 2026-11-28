//! Continue a conversation made outside omher (BOUNDARY rule 30). The TERMINALS + menu lists, read-only, the
//! recent Claude Code and Codex conversations for the folders it offers (or for every folder the CLI keeps
//! conversations for), and picking one continues it (rule 11).
//!
//! Only the CLIs' own conversation files are read, never written: Claude Code transcripts
//! (`<claude config>/projects/<folder slug>/<uuid>.jsonl`) and Codex rollouts
//! (`<codex home>/sessions/YYYY/MM/DD/rollout-*.jsonl`, plus `session_index.jsonl` for thread names). A symlink
//! anywhere under those folders is refused, and every file read must lie inside the CLI's own home once its
//! links are resolved. No credential, token or config file is opened. Each file is read in bounded pieces (its
//! head and its tail), so a long conversation costs the same as a short one.
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use serde::Serialize;
use serde_json::Value;

use crate::sessions::is_uuid;

/// Conversations listed per agent.
pub const LIST_MAX: usize = 40;
/// Rows looked for beyond [`LIST_MAX`] before a listing stops walking (a conversation seen twice is listed once).
const LIST_MARGIN: usize = 10;
/// Conversation files one listing looks at, at most. The walk stops long before this once it has its rows: this only
/// guards against a runaway tree, so it is not a window that hides real conversations behind other runs (`codex exec`
/// runs are most of a Codex home; a fixed window of 400 newest files hid every real conversation for some people).
const FILES_MAX: usize = 20_000;
/// Lines read from the start of a file (its folder, its first message, an early title), within its first [`HEAD`].
const HEAD_LINES: usize = 200;
/// Of those, the lines a Claude Code transcript's own folder (`cwd`) is looked for in: Claude Code writes it in the
/// first few lines, and the folder's slug cannot be turned back into it (`-` stands for every other character).
const CWD_LINES: usize = 40;
/// Bytes read from the end of a file for the last thing said in it.
const LAST_TAIL: u64 = 128 * 1024;
/// Characters of that line.
const LAST_MAX: usize = 200;
/// Bytes of a rollout's first line looked at for Codex's exec mark before the line is parsed.
const PEEK: u64 = 8 * 1024;
/// What Codex writes in the first line of a `codex exec` run.
const EXEC_MARK: &[u8] = br#""originator":"codex_exec""#;
/// Claude Code shortens a project folder's name longer than this to its first this many characters and a hash.
const SLUG_MAX: usize = 200;
/// Characters of a title or first words.
const TITLE_MAX: usize = 80;
/// Bytes read from the start of a file (its folder, first message, early title).
const HEAD: u64 = 256 * 1024;
/// Bytes read from the end of a file for its latest title.
const TAIL: u64 = 1024 * 1024;
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
    /// A Codex fork: the title of the conversation it was forked from when that one is listed too, else empty. `None`
    /// when it is not a fork. A fork starts with its parent's messages, so without this the two read the same.
    pub fork: Option<String>,
    /// The last thing the person or the agent said in it (one line, at most [`LAST_MAX`] characters), from the end of
    /// the file; `None` when that end holds no such line (nothing is guessed).
    pub last: Option<PastMsg>,
    /// The conversation it was forked from (a Codex thread id), or empty.
    #[serde(skip)]
    parent: String,
    /// Its file, for the last line once the row is kept.
    #[serde(skip)]
    file: PathBuf,
}

/// One thing said in a conversation: the person's typed text or the agent's answer text (a row's last line).
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

/// The first whole lines of `path`, parsed: at most `max` lines, all within its first [`HEAD`] bytes, read one at a
/// time so that a short file or an early `done` costs only what was read. A line cut by the [`HEAD`] edge is dropped,
/// a line that is not JSON skipped (it still counts).
fn head_lines(path: &Path, max: usize, done: &dyn Fn(&[Value]) -> bool) -> Vec<Value> {
    let Ok(f) = File::open(path) else { return Vec::new() };
    let mut r = BufReader::new(f.take(HEAD));
    let (mut out, mut line, mut used) = (Vec::new(), Vec::new(), 0u64);
    for _ in 0..max {
        line.clear();
        match r.read_until(b'\n', &mut line) {
            Ok(0) | Err(_) => break,
            Ok(n) => used += n as u64,
        }
        if line.last() != Some(&b'\n') && used >= HEAD {
            break; // cut by the edge
        }
        if let Ok(v) = serde_json::from_slice::<Value>(&line) {
            out.push(v);
            if done(&out) {
                break;
            }
        }
    }
    out
}

/// The head of a file: [`head_lines`] read to its line cap.
fn head(path: &Path) -> Vec<Value> {
    head_lines(path, HEAD_LINES, &|_| false)
}

/// The folder a Claude Code transcript ran in, from its own first [`CWD_LINES`] lines.
fn claude_cwd(lines: &[Value]) -> Option<&str> {
    lines.iter().take(CWD_LINES).map(|o| s(o, "cwd")).find(|c| !c.is_empty())
}

/// The last thing the person or the agent said in `agent`'s conversation file `path`: the last such line in its final
/// [`LAST_TAIL`] bytes, on one line, at most [`LAST_MAX`] characters. Meta lines, the turns a CLI or another agent put
/// in the person's place (as for titles) and tool results are passed over; when that end holds none, `None`.
fn last_said(path: &Path, agent: &str) -> Option<PastMsg> {
    let size = std::fs::metadata(path).map(|m| m.len()).ok()?;
    lines_in(path, size.saturating_sub(LAST_TAIL), LAST_TAIL).iter().rev().find_map(|o| {
        let (user, answer) = match agent {
            "claude" => (claude_user_text(o), claude_assistant_text(o)),
            _ => (codex_user_text(o), codex_assistant_text(o)),
        };
        let (role, text) = match (user, answer) {
            (Some(t), _) => ("user", t),
            (None, Some(t)) => ("assistant", t),
            _ => return None,
        };
        let text = clip(&text, LAST_MAX);
        (!text.is_empty()).then(|| PastMsg { role, text, ts: iso_secs(s(o, "timestamp")).unwrap_or(0.0) })
    })
}

/// All of a file when small, else its last [`TAIL`] bytes: where its latest title is.
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

/// How a user turn begins when the person did not type it: the AGENTS.md block Codex sends first, Claude Code's
/// caveat and interrupted-request notes, the summary Claude Code puts in after compacting a long conversation, its
/// retry note after a malformed tool call, and the boilerplate of a Codex collaboration turn (another agent's task or
/// message, or a worker's brief). A turn that starts with `<` (command tags, `<system-reminder>`,
/// `<task-notification>`, `<teammate-message …>`, `<cross-session-message …>`, Codex's environment block) is never
/// typed text either.
const NOT_TYPED: [&str; 9] = [
    "# AGENTS.md instructions",
    "Caveat:",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
    "Your tool call was malformed",
    "Message Type: NEW_TASK",
    "Message Type: MESSAGE",
    "Message Type: FINAL_ANSWER",
    "You are a worker agent",
];

/// Text the person typed, not what the CLI or another agent put in the user turn: such a turn names no
/// conversation and is not the person's side of it.
fn typed(text: &str) -> bool {
    let t = text.trim_start();
    !t.is_empty() && !t.starts_with('<') && !NOT_TYPED.iter().any(|m| t.starts_with(m))
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

/// The text of a Claude Code user line the person typed (not a tool result, a subagent's, or a line Claude Code marks
/// as its own: meta, a compaction summary, one shown only in the transcript). In a list of text blocks each block is
/// judged on its own, as for Codex: an editor's context block written before the prompt (`<ide_opened_file>…`,
/// `<ide_selection>…`) is passed over and the prompt after it kept.
fn claude_user_text(o: &Value) -> Option<String> {
    let flag = |k: &str| o.get(k).and_then(Value::as_bool) == Some(true);
    if s(o, "type") != "user" || ["isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly"].iter().any(|k| flag(k)) {
        return None;
    }
    let text = match &o["message"]["content"] {
        Value::String(t) => t.clone(),
        Value::Array(blocks) => blocks.iter().filter(|b| s(b, "type") == "text").map(|b| s(b, "text")).filter(|t| typed(t)).collect::<Vec<_>>().join("\n"),
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

/// One Claude Code transcript as a list row, when the person said something in it and it ran in one of `cwds` (any
/// folder when `None`). Its folder is the transcript's own `cwd`, never its project folder's lossy slug.
fn claude_row(path: &Path, cwds: Option<&[String]>) -> Option<PastChat> {
    let id = path.file_stem()?.to_str()?.to_string();
    if !is_uuid(&id) {
        return None;
    }
    let first = head(path);
    // the slug is lossy ("/a/b-c" and "/a/b/c" share it): the transcript's own cwd decides
    let seen = claude_cwd(&first)?;
    let cwd = match cwds {
        Some(cwds) => cwds.iter().find(|c| same_folder(seen, c))?.as_str(),
        None if absolute(seen) => seen,
        None => return None,
    };
    let words = first.iter().find_map(claude_user_text)?;
    // a later name wins: one in the last part of the file (all of a small one) over one near the start
    let (mut custom, mut ai) = claude_title(&first);
    let (c2, a2) = claude_title(&last_part(path));
    if !c2.is_empty() {
        custom = c2;
    }
    if !a2.is_empty() {
        ai = a2;
    }
    let named = !custom.is_empty() || !ai.is_empty();
    let title = if !custom.is_empty() { custom } else if !ai.is_empty() { ai } else { clip(&words, TITLE_MAX) };
    Some(row("claude", id, cwd, title, named, path))
}

/// The project folders a Claude Code listing walks: every one when `cwds` is `None`, else each folder's own: the one
/// its slug names and, for a long path, those Claude Code named by the slug's first [`SLUG_MAX`] characters and a
/// hash (the transcript's own `cwd` still decides). Links are not followed.
fn claude_dirs(projects: &Path, cwds: Option<&[String]>) -> Vec<PathBuf> {
    let all: Vec<PathBuf> = std::fs::read_dir(projects).map(|rd| rd.flatten().map(|e| e.path()).filter(|p| plain_dir(p)).collect()).unwrap_or_default();
    let Some(cwds) = cwds else { return all };
    let mut out: Vec<PathBuf> = Vec::new();
    for cwd in cwds {
        let slug = claude_slug(cwd);
        let short = (slug.len() > SLUG_MAX).then(|| format!("{}-", &slug[..SLUG_MAX]));
        for d in &all {
            let name = d.file_name().and_then(|x| x.to_str()).unwrap_or("");
            if (name == slug || short.as_deref().is_some_and(|p| name.starts_with(p))) && !out.contains(d) {
                out.push(d.clone());
            }
        }
    }
    out
}

/// The recent Claude Code conversations in any of `cwds` (in every folder when `None`), newest first. Transcripts are
/// opened newest first until the list is full: a folder with thousands costs as much as one with a page of them.
pub fn claude_list(root: &Path, cwds: Option<&[String]>) -> Vec<PastChat> {
    let projects = root.join("projects");
    if !plain_dir(&projects) {
        return Vec::new();
    }
    let mut files: Vec<(f64, PathBuf)> = Vec::new();
    'dirs: for dir in claude_dirs(&projects, cwds) {
        let Ok(rd) = std::fs::read_dir(&dir) else { continue };
        for e in rd.flatten() {
            if files.len() >= FILES_MAX {
                break 'dirs;
            }
            let p = e.path();
            // the entry's own type: a link is not a file here
            let plain = e.file_type().map(|t| t.is_file()).unwrap_or(false);
            if plain && p.extension().is_some_and(|x| x == "jsonl") && p.file_stem().and_then(|x| x.to_str()).is_some_and(is_uuid) {
                files.push((e.metadata().ok().and_then(|m| m.modified().ok()).and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs_f64()).unwrap_or(0.0), p));
            }
        }
    }
    files.sort_by(|a, b| b.0.total_cmp(&a.0));
    let mut out = Vec::new();
    for (_, p) in files {
        if out.len() >= LIST_MAX + LIST_MARGIN {
            break;
        }
        if let Some(r) = inside(root, &p).and_then(|p| claude_row(&p, cwds)) {
            out.push(r);
        }
    }
    newest(out)
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

/// A rollout's `session_meta`, when it is a conversation the person had: not a subagent's thread (its `source` names
/// the parent that spawned it) and not a `codex exec` run (a script's one-off run, most of the files in a Codex home).
struct Meta {
    id: String,
    cwd: String,
    /// The thread it was forked from, or empty: the first of these that is not its own id.
    parent: String,
}

fn codex_meta(lines: &[Value]) -> Option<Meta> {
    let first = lines.first()?;
    if s(first, "type") != "session_meta" {
        return None;
    }
    let p = &first["payload"];
    let exec = s(p, "originator").contains("exec") || s(p, "source") == "exec";
    if exec || p.get("source").is_some_and(Value::is_object) {
        return None;
    }
    let id = s(p, "id").to_string();
    if !is_uuid(&id) {
        return None;
    }
    let parent = ["forked_from_id", "parent_thread_id", "session_id"].iter().map(|k| s(p, k)).find(|x| !x.is_empty() && *x != id).unwrap_or("").to_string();
    Some(Meta { id, cwd: s(p, "cwd").to_string(), parent })
}

/// Whether rollout `path` is marked as a `codex exec` run in its first line, told from that line's first [`PEEK`]
/// bytes as plain text, before any of it is parsed: that line carries the whole system prompt (often over 50 KB) and
/// exec runs are most of the files, so this keeps a listing from parsing them. A change in how Codex writes it only
/// misses this shortcut; [`codex_meta`] still drops the run once its line is parsed.
fn exec_marked(path: &Path) -> bool {
    let Ok(f) = File::open(path) else { return false };
    let mut buf = Vec::new();
    if f.take(PEEK).read_to_end(&mut buf).is_err() {
        return false;
    }
    let line = buf.split(|b| *b == b'\n').next().unwrap_or(&[]);
    line.windows(EXEC_MARK.len()).any(|w| w == EXEC_MARK)
}

/// The lines of rollout `path` a listing reads: up to the first words, and no further than the first line when that
/// is not a conversation's meta or names a folder not in `cwds` (when given). A rollout's meta line carries the whole
/// system prompt, and the instruction items after it are as long again, so another folder's conversation costs that
/// one line, not everything up to its first words.
fn codex_head(path: &Path, cwds: Option<&[String]>) -> Vec<Value> {
    head_lines(path, HEAD_LINES, &|seen| match codex_meta(seen) {
        None => true,
        Some(m) if cwds.is_some_and(|cwds| !cwds.iter().any(|c| same_folder(&m.cwd, c))) => true,
        Some(_) => seen.last().and_then(codex_user_text).is_some(),
    })
}

/// One Codex rollout as a list row, when it is a conversation the person had (they said something in it) in one of
/// `cwds` (any folder when `None`). Only its first [`HEAD_LINES`] lines are read, and the read stops once its folder
/// and first words are known ([`codex_head`]).
fn codex_row(path: &Path, cwds: Option<&[String]>, names: &std::collections::HashMap<String, String>) -> Option<PastChat> {
    if exec_marked(path) {
        return None;
    }
    let first = codex_head(path, cwds);
    let meta = codex_meta(&first)?;
    let cwd = match cwds {
        Some(cwds) => cwds.iter().find(|c| same_folder(&meta.cwd, c))?.as_str(),
        None if absolute(&meta.cwd) => meta.cwd.as_str(),
        None => return None,
    };
    let words = first.iter().find_map(codex_user_text)?;
    let name = names.get(&meta.id).cloned().unwrap_or_default();
    let named = !name.is_empty();
    let title = if named { name } else { clip(&words, TITLE_MAX) };
    let mut r = row("codex", meta.id.clone(), cwd, title, named, path);
    r.parent = meta.parent;
    Some(r)
}

/// The recent Codex conversations in any of `cwds` (in every folder when `None`), newest first. Rollouts are opened
/// newest first until the list is full, so the exec runs and other folders' threads in between cost a short read each
/// and hide nothing.
pub fn codex_list(root: &Path, cwds: Option<&[String]>) -> Vec<PastChat> {
    let names = codex_names(root);
    let mut files: Vec<(f64, PathBuf)> = codex_rollouts(root, FILES_MAX).into_iter().map(|p| (mtime(&p), p)).collect();
    files.sort_by(|a, b| b.0.total_cmp(&a.0));
    let mut out = Vec::new();
    for (_, p) in files {
        if out.len() >= LIST_MAX + LIST_MARGIN {
            break;
        }
        if let Some(r) = inside(root, &p).and_then(|p| codex_row(&p, cwds, &names)) {
            out.push(r);
        }
    }
    newest(out)
}

/// The Codex conversation id a rollout path names: the path must be a real file (no link) inside `root` (the Codex
/// home, [`cli_home`]) once both are resolved, at `sessions/YYYY/MM/DD/rollout-*-<uuid>.jsonl` there. A TERMINALS
/// Codex session asks with the paths its Codex process holds open (`fg::codex_conversation`, rule 11); only the id
/// comes back, and the file is not opened.
pub fn rollout_id(root: &Path, path: &Path) -> Option<String> {
    let real = inside(root, path)?;
    let rel = real.strip_prefix(root.canonicalize().ok()?).ok()?;
    let parts: Vec<&str> = rel.iter().map(|c| c.to_str()).collect::<Option<_>>()?;
    let &[top, y, m, d, name] = parts.as_slice() else { return None };
    let digits = |s: &str, n: usize| s.len() == n && s.bytes().all(|b| b.is_ascii_digit());
    if top != "sessions" || !digits(y, 4) || !digits(m, 2) || !digits(d, 2) {
        return None;
    }
    let stem = name.strip_prefix("rollout-")?.strip_suffix(".jsonl")?;
    let cut = stem.len().checked_sub(36)?;
    let id = stem.get(cut..)?;
    (cut > 0 && stem.as_bytes()[cut - 1] == b'-' && is_uuid(id)).then(|| id.to_string())
}

// ---- both -------------------------------------------------------------------------------------

/// A list row; its fork and last line are filled in once it is kept ([`list`]).
fn row(agent: &'static str, id: String, cwd: &str, title: String, named: bool, path: &Path) -> PastChat {
    let cwd = cwd.trim_end_matches(['/', '\\']).to_string();
    PastChat { agent, id, cwd, title, named, at: mtime(path), fork: None, last: None, parent: String::new(), file: path.to_path_buf() }
}

fn newest(mut v: Vec<PastChat>) -> Vec<PastChat> {
    v.sort_by(|a, b| b.at.total_cmp(&a.at));
    let mut seen = std::collections::HashSet::new();
    v.retain(|c| seen.insert(c.id.clone()));
    v.truncate(LIST_MAX);
    v
}

/// A fork's label: the title of the listed conversation it came from, else empty (the row reads just "fork").
fn label_forks(rows: &mut [PastChat]) {
    let titles: std::collections::HashMap<String, String> = rows.iter().map(|r| (r.id.clone(), r.title.clone())).collect();
    for r in rows.iter_mut().filter(|r| !r.parent.is_empty()) {
        r.fork = Some(titles.get(&r.parent).cloned().unwrap_or_default());
    }
}

/// An absolute folder path, as each CLI records its cwd (`/…` on macOS and Linux, `C:\\…` on Windows).
fn absolute(c: &str) -> bool {
    Path::new(c).is_absolute() || c.starts_with('/')
}

/// Only absolute folders, at most 12 (the + menu offers the recent folders and home).
pub fn checked_cwds(cwds: &[String]) -> Vec<String> {
    cwds.iter().filter(|c| absolute(c)).take(12).cloned().collect()
}

/// `agent`'s recent conversations, read from `root` (its home, [`cli_home`]): those in `cwds`, or in every folder
/// that agent keeps conversations for when `all`. Only the rows kept get their last line read (the end of each file).
pub fn list(root: &Path, agent: &str, cwds: &[String], all: bool) -> Result<Vec<PastChat>, String> {
    let cwds = checked_cwds(cwds);
    let scope = (!all).then_some(cwds.as_slice());
    let mut rows = match agent {
        "claude" => claude_list(root, scope),
        "codex" => codex_list(root, scope),
        _ => return Err(format!("{agent} conversations are not listed")),
    };
    label_forks(&mut rows);
    for r in &mut rows {
        r.last = last_said(&r.file, agent);
    }
    Ok(rows)
}

/// Whether `agent`'s conversation `id` has its file in `root` where the CLI looks for it when asked to continue it:
/// `exists`, `absent`, or `unknown` when a folder could not be read. Only names are looked at, links followed as
/// the CLI follows them, and no file is opened. Claude Code: `<root>/projects/*/<id>.jsonl` (any project folder, so
/// a folder name Claude Code shortened or a cwd reached through a link still counts). Codex: a rollout named
/// `rollout-*-<id>.jsonl` under `<root>/sessions` (`YYYY/MM/DD`) or `<root>/archived_sessions`.
pub fn conversation_state(root: &Path, agent: &str, id: &str) -> Result<&'static str, String> {
    if !is_uuid(id) {
        return Err("not a conversation id".into());
    }
    let (found, unknown) = match agent {
        "claude" => {
            // each project folder is asked for that one name, as Claude Code does
            let name = format!("{id}.jsonl");
            let mut unknown = false;
            let mut found = false;
            match std::fs::read_dir(root.join("projects")) {
                Err(e) => unknown = !not_found(&e),
                Ok(rd) => {
                    for e in rd {
                        let Ok(e) = e else {
                            unknown = true;
                            continue;
                        };
                        match std::fs::metadata(e.path().join(&name)) {
                            Ok(m) if m.is_file() => {
                                found = true;
                                break;
                            }
                            Ok(_) => {}
                            // a file beside the project folders (.DS_Store) has no name under it
                            Err(err) => unknown |= !not_found(&err) && std::fs::metadata(e.path()).map(|m| m.is_dir()).unwrap_or(true),
                        }
                    }
                }
            }
            (found, unknown)
        }
        "codex" => {
            let suffix = format!("-{id}.jsonl");
            let named = |p: &Path| p.file_name().and_then(|x| x.to_str()).is_some_and(|x| x.starts_with("rollout-") && x.ends_with(&suffix));
            let (a, ua) = seek(&root.join("sessions"), 3, &named);
            if a {
                (true, ua)
            } else {
                let (b, ub) = seek(&root.join("archived_sessions"), 3, &named);
                (b, ua || ub)
            }
        }
        _ => return Err(format!("{agent} conversations are not listed")),
    };
    Ok(if found {
        "exists"
    } else if unknown {
        "unknown"
    } else {
        "absent"
    })
}

fn not_found(e: &std::io::Error) -> bool {
    e.kind() == std::io::ErrorKind::NotFound
}

/// A file `want` takes (by name) in `dir` or in folders up to `depth` levels under it, links followed: whether one
/// was found, and whether any folder or entry could not be read (every error but NotFound). Only a link is asked what
/// it points to; any other entry's type comes with the folder's listing.
fn seek(dir: &Path, depth: u32, want: &dyn Fn(&Path) -> bool) -> (bool, bool) {
    let rd = match std::fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(e) => return (false, !not_found(&e)),
    };
    let mut unknown = false;
    for e in rd {
        let Ok(e) = e else {
            unknown = true;
            continue;
        };
        let p = e.path();
        let named = want(&p);
        if !named && depth == 0 {
            continue;
        }
        let Ok(kind) = e.file_type() else {
            unknown = true;
            continue;
        };
        let (file, folder) = if kind.is_symlink() {
            match std::fs::metadata(&p) {
                Ok(m) => (m.is_file(), m.is_dir()),
                Err(err) => {
                    unknown |= !not_found(&err);
                    continue;
                }
            }
        } else {
            (kind.is_file(), kind.is_dir())
        };
        if named && file {
            return (true, unknown);
        }
        if folder && depth > 0 {
            let (f, u) = seek(&p, depth - 1, want);
            if f {
                return (true, unknown || u);
            }
            unknown |= u;
        }
    }
    (false, unknown)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn a_conversation_is_found_by_name_in_any_project_folder_or_rollout_day() {
        let root = tmp("state");
        let n = |agent: &str, id: &str| conversation_state(&root, agent, id).unwrap();
        // no projects or sessions folder yet: nothing was written
        assert_eq!(n("claude", C1), "absent");
        assert_eq!(n("codex", X1), "absent");
        // a folder name Claude Code shortened (200 characters and a hash) is still a project folder
        let long = format!("-{}-1a2b3c", "x".repeat(200));
        std::fs::create_dir_all(root.join("projects").join(&long)).unwrap();
        std::fs::write(root.join("projects").join(&long).join(format!("{C1}.jsonl")), "{}\n").unwrap();
        std::fs::write(root.join("projects").join(".DS_Store"), "").unwrap();
        assert_eq!(n("claude", C1), "exists");
        assert_eq!(n("claude", C2), "absent");
        // a project folder that is a link to the real one: followed, as Claude Code follows it
        #[cfg(unix)]
        {
            let real = tmp("state-real");
            std::fs::write(real.join(format!("{C2}.jsonl")), "{}\n").unwrap();
            std::os::unix::fs::symlink(&real, root.join("projects").join("-linked")).unwrap();
            assert_eq!(n("claude", C2), "exists");
            let _ = std::fs::remove_dir_all(real);
        }
        // Codex: a rollout of that id on any day, or archived
        let day = root.join("sessions").join("2026").join("11").join("22");
        std::fs::create_dir_all(&day).unwrap();
        std::fs::write(day.join(format!("rollout-2026-11-22T10-00-00-{X1}.jsonl")), "{}\n").unwrap();
        assert_eq!(n("codex", X1), "exists");
        assert_eq!(n("codex", X2), "absent");
        std::fs::create_dir_all(root.join("archived_sessions")).unwrap();
        std::fs::write(root.join("archived_sessions").join(format!("rollout-2026-11-01T10-00-00-{X2}.jsonl")), "{}\n").unwrap();
        assert_eq!(n("codex", X2), "exists");
        // a rollout that is a link to the real file counts; a broken link does not
        #[cfg(unix)]
        {
            let x3 = "01a1d060-6967-74c3-8b7c-33c05229878c";
            let real = tmp("state-rollout");
            std::fs::write(real.join("r.jsonl"), "{}\n").unwrap();
            std::os::unix::fs::symlink(real.join("r.jsonl"), day.join(format!("rollout-2026-11-22T11-00-00-{x3}.jsonl"))).unwrap();
            assert_eq!(n("codex", x3), "exists");
            std::fs::remove_file(real.join("r.jsonl")).unwrap();
            assert_eq!(n("codex", x3), "absent");
            let _ = std::fs::remove_dir_all(real);
        }
        // not a UUID, or an agent whose conversations are not looked at
        assert!(conversation_state(&root, "claude", "../x").is_err());
        assert!(conversation_state(&root, "grok", C1).is_err());
        let _ = std::fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn a_folder_that_cannot_be_read_makes_it_unknown_not_absent() {
        use std::os::unix::fs::PermissionsExt;
        let root = tmp("state-perm");
        let shut = root.join("projects").join("-shut");
        std::fs::create_dir_all(&shut).unwrap();
        std::fs::set_permissions(&shut, std::fs::Permissions::from_mode(0o000)).unwrap();
        // root can read anything: the check means nothing there
        let readable = std::fs::read_dir(&shut).is_ok();
        if !readable {
            assert_eq!(conversation_state(&root, "claude", C1).unwrap(), "unknown");
        }
        std::fs::set_permissions(&shut, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert_eq!(conversation_state(&root, "claude", C1).unwrap(), "absent");
        let _ = std::fs::remove_dir_all(root);
    }

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
        let rows = list(&root, "claude", &[cwd.to_string(), "relative/x".to_string()], false).unwrap();
        // an agent whose conversations are not looked at
        assert!(list(&root, "omo", &[cwd.to_string()], false).is_err());
        assert_eq!(rows.len(), 1, "{rows:?}");
        assert_eq!((rows[0].id.as_str(), rows[0].title.as_str(), rows[0].named, rows[0].cwd.as_str()), (C1, "Remember a word", true, cwd));
        // a rename in Claude Code wins; without any title the first words name it
        let mut lines = claude_file(cwd, C1);
        lines.push(serde_json::json!({"type": "custom-title", "customTitle": "My  word\ngame"}));
        write(&dir.join(format!("{C1}.jsonl")), &lines);
        assert_eq!(claude_list(&root, Some(&[cwd.into()]))[0].title, "My word game");
        write(&dir.join(format!("{C1}.jsonl")), &claude_file(cwd, C1)[..8]);
        let r = &claude_list(&root, Some(&[cwd.into()]))[0];
        assert_eq!((r.title.as_str(), r.named), ("Remember the word MARIGOLD for later", false));
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
        assert!(claude_list(&root, Some(&[cwd.into()])).is_empty());
        // a linked project folder
        let root2 = tmp("links2");
        std::fs::create_dir_all(root2.join("projects")).unwrap();
        symlink(&away, root2.join("projects").join(&slug)).unwrap();
        assert!(claude_list(&root2, Some(&[cwd.into()])).is_empty());
        // a linked projects folder
        let root3 = tmp("links3");
        let real = tmp("links3-real");
        write(&real.join(&slug).join(format!("{C1}.jsonl")), &claude_file(cwd, C1));
        symlink(&real, root3.join("projects")).unwrap();
        assert!(claude_list(&root3, Some(&[cwd.into()])).is_empty());
        // Codex: a linked day folder and a linked rollout
        let x = tmp("links-codex");
        let day = x.join("sessions/2026/11/12");
        std::fs::create_dir_all(&day).unwrap();
        write(&away.join("r.jsonl"), &codex_file(X1, cwd));
        symlink(away.join("r.jsonl"), day.join(format!("rollout-2026-11-12T00-00-00-{X1}.jsonl"))).unwrap();
        symlink(&away, x.join("sessions/2026/11/13")).unwrap();
        assert!(codex_list(&x, Some(&[cwd.into()])).is_empty());
        assert!(codex_list(&x, None).is_empty());
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
    fn a_rollout_path_gives_its_id_only_inside_the_home_and_by_its_name() {
        let root = tmp("rollout-id");
        let day = root.join("sessions/2026/11/20");
        let ok = day.join(format!("rollout-2026-11-20T00-23-46-{X1}.jsonl"));
        write(&ok, &codex_file(X1, "/w"));
        assert_eq!(rollout_id(&root, &ok).as_deref(), Some(X1));
        // not a rollout's name, no UUID in it, not under sessions/YYYY/MM/DD
        for bad in [
            day.join(format!("{X1}.jsonl")),
            day.join(format!("rollout-{X1}.jsonl")),
            day.join(format!("rollout-2026-11-20T00-23-46-{X1}.json")),
            day.join(format!("rollout-2026-11-20T00-23-46x{X1}.jsonl")),
            day.join("rollout-2026-11-20T00-23-46-01a1d060-4ab7-72b2-b02b-1dbee1d5f52g.jsonl"),
            day.join("history.jsonl"),
            root.join(format!("sessions/2026/11/rollout-2026-11-20T00-23-46-{X1}.jsonl")),
            root.join(format!("sessions/26/11/20/rollout-2026-11-20T00-23-46-{X1}.jsonl")),
            root.join(format!("archived_sessions/2026/11/20/rollout-2026-11-20T00-23-46-{X1}.jsonl")),
            root.join(format!("sessions/2026/11/20/x/rollout-2026-11-20T00-23-46-{X1}.jsonl")),
        ] {
            write(&bad, &codex_file(X1, "/w"));
            assert!(rollout_id(&root, &bad).is_none(), "{}", bad.display());
        }
        // a folder, a path that does not exist
        assert!(rollout_id(&root, &day).is_none());
        assert!(rollout_id(&root, &day.join(format!("rollout-2026-11-20T00-23-47-{X2}.jsonl"))).is_none());
        // a rollout outside the home, a link to it in the home, and a linked day folder
        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            let away = tmp("rollout-id-away");
            let far = away.join(format!("sessions/2026/11/20/rollout-2026-11-20T00-23-46-{X2}.jsonl"));
            write(&far, &codex_file(X2, "/w"));
            assert!(rollout_id(&root, &far).is_none());
            assert_eq!(rollout_id(&away, &far).as_deref(), Some(X2));
            let link = day.join(format!("rollout-2026-11-20T00-23-48-{X2}.jsonl"));
            symlink(&far, &link).unwrap();
            assert!(rollout_id(&root, &link).is_none());
            symlink(away.join("sessions/2026/11/20"), root.join("sessions/2026/11/21")).unwrap();
            assert!(rollout_id(&root, &root.join(format!("sessions/2026/11/21/rollout-2026-11-20T00-23-46-{X2}.jsonl"))).is_none());
            let _ = std::fs::remove_dir_all(away);
        }
        let _ = std::fs::remove_dir_all(root);
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
        let rows = list(&root, "codex", &[cwd.to_string()], false).unwrap();
        let mut got: Vec<(&str, &str, bool)> = rows.iter().map(|r| (r.id.as_str(), r.title.as_str(), r.named)).collect();
        got.sort();
        assert_eq!(got, [(X1, "Remember a colour", true), (X2, "Remember COBALT please", false)]);
        // the answer, not the imported tool result before it, is the last thing said
        assert!(rows.iter().all(|r| r.last.as_ref().map(|l| (l.role, l.text.as_str())) == Some(("assistant", "Remembered.")) && r.fork.is_none()));
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
        let r = &list(&root, "claude", &[cwd.into()], false).unwrap()[0];
        // the first words from the head, the latest title and the last line from the end
        assert_eq!(r.title, "Late title");
        assert_eq!(r.last.as_ref().map(|l| (l.role, l.text.as_str())), Some(("assistant", "MARIGOLD")));
        let _ = std::fs::remove_dir_all(&root);
    }

    /// A rollout at `day` (sessions/YYYY/MM/DD), its file's time set to `at` seconds after an hour, newest last.
    fn rollout(root: &Path, id: &str, lines: &[Value], at: u64) -> PathBuf {
        let p = root.join("sessions/2026/11/12").join(format!("rollout-2026-11-12T10-00-00-{id}.jsonl"));
        write(&p, lines);
        let t = std::time::SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_794_000_000 + at);
        File::options().append(true).open(&p).unwrap().set_modified(t).unwrap();
        p
    }

    /// A Codex id made from `n` (a valid UUID shape).
    fn xid(n: usize) -> String {
        format!("01a1d060-{:04x}-7000-8000-{:012x}", n / 65_536, n)
    }

    #[test]
    fn codex_drops_exec_runs_without_parsing_them_and_finds_real_conversations_behind_hundreds() {
        let root = tmp("codex-exec");
        let cwd = "/Users/you/code/api";
        // three conversations the person had, older than 500 `codex exec` runs
        // (their names sort after the runs' too, as an older day's would: a window of the newest names misses them)
        for n in 1..=3 {
            rollout(&root, &xid(n), &codex_file(&xid(n), cwd), n as u64);
        }
        // an exec run's first line as Codex writes it (its fields in Codex's order, the system prompt after them)
        let exec = |id: &str| {
            let first = format!(
                r#"{{"timestamp":"2026-11-12T10:00:00.000Z","type":"session_meta","payload":{{"id":"{id}","timestamp":"2026-11-12T10:00:00.000Z","cwd":"{cwd}","originator":"codex_exec","cli_version":"0.150.0","source":"exec","base_instructions":{{"text":"{}"}}}}}}"#,
                "x".repeat(60_000)
            );
            let mut v: Vec<Value> = vec![serde_json::from_str(&first).unwrap()];
            v.extend(codex_file(id, cwd)[1..].iter().cloned());
            (first, v)
        };
        for n in 1_000..1_500 {
            let p = rollout(&root, &xid(n), &[], n as u64);
            let (first, rest) = exec(&xid(n));
            let body: String = std::iter::once(first).chain(rest[1..].iter().map(|v| v.to_string())).map(|l| l + "\n").collect();
            std::fs::write(&p, body).unwrap();
            let t = std::time::SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_794_000_000 + n as u64);
            File::options().append(true).open(&p).unwrap().set_modified(t).unwrap();
            assert!(exec_marked(&p));
        }
        let rows = list(&root, "codex", &[cwd.to_string()], false).unwrap();
        assert_eq!(rows.iter().map(|r| r.id.clone()).collect::<Vec<_>>(), [xid(3), xid(2), xid(1)]);
        let all = list(&root, "codex", &[], true).unwrap();
        assert_eq!(all.len(), 3);
        // the mark is found as text in the first line only, before any parse; a later line that quotes it is not it
        let mut quoted = codex_file(&xid(2), cwd);
        quoted[3]["payload"]["content"][0]["text"] = serde_json::json!(r#"why does "originator":"codex_exec" show up?"#);
        let p = rollout(&root, &xid(2), &quoted, 0);
        assert!(!exec_marked(&p));
        // written another way (spaces, a newer originator name): the parsed first line still drops it
        let other = vec![serde_json::json!({"type": "session_meta", "payload": {"id": xid(3), "cwd": cwd, "originator": "codex_exec_v2"}}), codex_file(&xid(3), cwd)[3].clone()];
        assert!(codex_meta(&other).is_none());
        let other = vec![serde_json::json!({"type": "session_meta", "payload": {"id": xid(3), "cwd": cwd, "originator": "codex-tui", "source": "exec"}})];
        assert!(codex_meta(&other).is_none());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn codex_lists_forks_by_what_they_were_forked_from() {
        let root = tmp("codex-fork");
        let cwd = "/w";
        let (parent, fork, orphan) = (xid(10), xid(11), xid(12));
        rollout(&root, &parent, &codex_file(&parent, cwd), 1);
        let mut f = codex_file(&fork, cwd);
        f[0]["payload"]["forked_from_id"] = serde_json::json!(parent);
        rollout(&root, &fork, &f, 2);
        // its parent named by a field Codex used before, and not in the list
        let mut o = codex_file(&orphan, cwd);
        o[0]["payload"]["session_id"] = serde_json::json!(xid(99));
        rollout(&root, &orphan, &o, 3);
        // a thread whose `session_id` is its own id is not a fork
        let own = xid(13);
        let mut n = codex_file(&own, cwd);
        n[0]["payload"]["session_id"] = serde_json::json!(own);
        rollout(&root, &own, &n, 4);
        let rows = list(&root, "codex", &[cwd.into()], false).unwrap();
        let got: Vec<(String, Option<String>)> = rows.iter().map(|r| (r.id.clone(), r.fork.clone())).collect();
        assert_eq!(got, [(own, None), (orphan, Some(String::new())), (fork, Some("Remember COBALT please".into())), (parent, None)]);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn a_head_is_read_line_by_line_to_its_cap_and_no_further() {
        let root = tmp("head-cap");
        let cwd = "/w";
        // the first words after more than HEAD_LINES lines of other turns: not read, so not listed
        let id = xid(20);
        let mut lines = codex_file(&id, cwd)[..3].to_vec();
        for _ in 0..HEAD_LINES {
            lines.push(serde_json::json!({"type": "response_item", "payload": {"type": "reasoning", "summary": []}}));
        }
        lines.push(codex_file(&id, cwd)[3].clone());
        let p = rollout(&root, &id, &lines, 1);
        assert_eq!(head(&p).len(), HEAD_LINES);
        assert!(list(&root, "codex", &[cwd.into()], false).unwrap().is_empty());
        // the read stops at the first words
        let q = rollout(&root, &xid(21), &codex_file(&xid(21), cwd), 2);
        let names = std::collections::HashMap::new();
        assert!(codex_row(&q, Some(&[cwd.into()]), &names).is_some());
        assert_eq!(head_lines(&q, HEAD_LINES, &|seen| seen.last().and_then(codex_user_text).is_some()).len(), 4);
        // a Claude Code transcript names its folder in its first CWD_LINES lines, or it is not listed
        let late = claude_file(cwd, C1).into_iter().map(|mut v| {
            v.as_object_mut().unwrap().remove("cwd");
            v
        });
        let mut t: Vec<Value> = (0..CWD_LINES).map(|i| serde_json::json!({"type": "attachment", "n": i})).collect();
        t.extend(late);
        t.push(serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": "late"}}));
        write(&root.join("projects").join(claude_slug(cwd)).join(format!("{C1}.jsonl")), &t);
        assert!(claude_list(&root, Some(&[cwd.into()])).is_empty());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn injected_turns_name_no_conversation_and_are_not_the_persons_turn() {
        let root = tmp("injected");
        let cwd = "/w";
        let user = |extra: Value, text: &str| {
            let mut v = serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": text}, "timestamp": "2026-11-12T09:00:00.000Z"});
            for (k, x) in extra.as_object().unwrap() {
                v[k] = x.clone();
            }
            v
        };
        let none = serde_json::json!({});
        let mut lines = vec![
            user(serde_json::json!({"isCompactSummary": true}), "Summary of what came before"),
            user(serde_json::json!({"isVisibleInTranscriptOnly": true}), "Shown in the transcript only"),
            user(none.clone(), "This session is being continued from a previous conversation that ran out of context."),
            user(none.clone(), "Your tool call was malformed and could not be parsed. Please retry."),
            user(none.clone(), "<teammate-message teammate_id=\"lead\">do this</teammate-message>"),
            user(none.clone(), "<cross-session-message from=\"x\">hi</cross-session-message>"),
            user(none.clone(), "<task-notification>done</task-notification>"),
            user(none.clone(), "<system-reminder>remember</system-reminder>"),
        ];
        lines.extend(claude_file(cwd, C1)[2..8].iter().cloned());
        // the same turns after the last answer are not the person's last line
        lines.extend(lines[..8].to_vec());
        write(&root.join("projects").join(claude_slug(cwd)).join(format!("{C1}.jsonl")), &lines);
        let r = &list(&root, "claude", &[cwd.into()], false).unwrap()[0];
        assert_eq!((r.title.as_str(), r.named), ("Remember the word MARIGOLD for later", false));
        assert_eq!(r.last.as_ref().map(|l| (l.role, l.text.as_str())), Some(("assistant", "I will remember it.")));
        // Codex: a collaboration turn's boilerplate
        let id = xid(30);
        let mut c = codex_file(&id, cwd);
        let said = |t: &str| serde_json::json!({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t}]}});
        for t in ["Message Type: NEW_TASK\nTask: x", "Message Type: MESSAGE\nhi", "Message Type: FINAL_ANSWER\nok", "You are a worker agent in a team."] {
            c.insert(3, said(t));
        }
        c.push(said("Message Type: MESSAGE\nlater"));
        rollout(&root, &id, &c, 1);
        let r = &list(&root, "codex", &[cwd.into()], false).unwrap()[0];
        assert_eq!(r.title, "Remember COBALT please");
        // and the last line passes them over too
        assert_eq!(r.last.as_ref().map(|l| (l.role, l.text.as_str())), Some(("assistant", "Remembered.")));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn each_row_carries_the_last_thing_said_from_the_end_of_its_file() {
        let root = tmp("last");
        let cwd = "/w";
        let dir = root.join("projects").join(claude_slug(cwd));
        write(&dir.join(format!("{C1}.jsonl")), &claude_file(cwd, C1));
        let r = &claude_list(&root, Some(&[cwd.into()]))[0];
        // before list() keeps it, no end is read
        assert!(r.last.is_none());
        let r = &list(&root, "claude", &[cwd.into()], false).unwrap()[0];
        assert_eq!(r.last.as_ref().map(|l| (l.role, l.text.as_str())), Some(("assistant", "I will remember it.")));
        // the person's turn, on one line, clipped
        let mut lines = claude_file(cwd, C1);
        lines.push(serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": format!("and then\n\n{}", "y".repeat(300))}}));
        lines.push(serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}));
        write(&dir.join(format!("{C1}.jsonl")), &lines);
        let r = &list(&root, "claude", &[cwd.into()], false).unwrap()[0];
        let l = r.last.as_ref().unwrap();
        assert_eq!((l.role, l.text.chars().count()), ("user", LAST_MAX));
        assert!(l.text.starts_with("and then yyy") && l.text.ends_with('…'), "{}", l.text);
        // an end that holds only a large tool result says nothing rather than guess
        let mut lines = claude_file(cwd, C1);
        lines.push(serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": [{"type": "tool_result", "content": "z".repeat(LAST_TAIL as usize + 10)}]}}));
        write(&dir.join(format!("{C1}.jsonl")), &lines);
        let r = &list(&root, "claude", &[cwd.into()], false).unwrap()[0];
        assert!(r.last.is_none(), "{:?}", r.last);
        // Codex: the answer
        let id = xid(40);
        rollout(&root, &id, &codex_file(&id, cwd), 1);
        let r = &list(&root, "codex", &[cwd.into()], false).unwrap()[0];
        assert_eq!(r.last.as_ref().map(|l| (l.role, l.text.as_str())), Some(("assistant", "Remembered.")));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn all_folders_lists_every_project_folder_by_each_transcripts_own_folder() {
        let root = tmp("all");
        // two folders that share one slug, and a third elsewhere
        let (a, b, c) = ("/Users/you/code/web-app", "/Users/you/code/web/app", "/Users/you/notes");
        let ids = ["44444444-2222-4333-8444-555555555555", "55555555-2222-4333-8444-555555555555", "66666666-2222-4333-8444-555555555555"];
        for (cwd, id) in [(a, ids[0]), (b, ids[1]), (c, ids[2])] {
            write(&root.join("projects").join(claude_slug(cwd)).join(format!("{id}.jsonl")), &claude_file(cwd, id));
        }
        let mut got: Vec<(String, String)> = list(&root, "claude", &[], true).unwrap().into_iter().map(|r| (r.id, r.cwd)).collect();
        got.sort();
        assert_eq!(got, [(ids[0].into(), a.into()), (ids[1].into(), b.into()), (ids[2].into(), c.into())]);
        // this folder only
        let here = list(&root, "claude", &[b.into()], false).unwrap();
        assert_eq!(here.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(), [ids[1]]);
        // a transcript whose own folder is not an absolute path is not listed (nothing could continue it there)
        write(&root.join("projects/-rel").join(format!("{C2}.jsonl")), &claude_file("rel/x", C2));
        assert_eq!(list(&root, "claude", &[], true).unwrap().len(), 3);
        // Codex: every folder, each row its own
        let x = tmp("all-codex");
        rollout(&x, &xid(50), &codex_file(&xid(50), a), 1);
        rollout(&x, &xid(51), &codex_file(&xid(51), c), 2);
        let got: Vec<String> = list(&x, "codex", &[], true).unwrap().into_iter().map(|r| r.cwd).collect();
        assert_eq!(got, [c, a]);
        for d in [root, x] {
            let _ = std::fs::remove_dir_all(d);
        }
    }

    #[test]
    fn a_long_folder_claude_code_shortened_is_listed() {
        let root = tmp("long-slug");
        let cwd = format!("/Users/you/{}", "deep/".repeat(50));
        let cwd = cwd.trim_end_matches('/').to_string();
        let slug = claude_slug(&cwd);
        assert!(slug.len() > SLUG_MAX);
        // the name Claude Code gives it: the slug's first 200 characters and a hash
        let short = format!("{}-1a2b3c", &slug[..SLUG_MAX]);
        write(&root.join("projects").join(&short).join(format!("{C1}.jsonl")), &claude_file(&cwd, C1));
        let rows = list(&root, "claude", &[cwd.clone()], false).unwrap();
        assert_eq!(rows.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(), [C1]);
        // and the look before a terminal continues it finds its file there
        assert_eq!(conversation_state(&root, "claude", C1).unwrap(), "exists");
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
    fn a_scoped_codex_listing_stops_reading_another_folders_rollout_at_its_meta() {
        let root = tmp("codex-other-folder");
        let id = xid(60);
        // another folder's conversation: its meta, then many instruction items before the first words
        let mut lines = codex_file(&id, "/elsewhere")[..3].to_vec();
        for _ in 0..100 {
            lines.push(serde_json::json!({"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules"}]}}));
        }
        lines.push(codex_file(&id, "/elsewhere")[3].clone());
        let p = rollout(&root, &id, &lines, 1);
        // every line is JSON, so the lines kept are the lines read
        assert_eq!(codex_head(&p, Some(&["/w".into()])).len(), 1, "only the meta line is read");
        let names = std::collections::HashMap::new();
        assert!(codex_row(&p, Some(&["/w".into()]), &names).is_none());
        // the same rollout in its own folder, or with no folder scope, is read to its first words and listed
        assert_eq!(codex_head(&p, Some(&["/elsewhere/".into()])).len(), lines.len());
        assert_eq!(codex_head(&p, None).len(), lines.len());
        assert!(codex_row(&p, Some(&["/elsewhere/".into()]), &names).is_some());
        assert!(codex_row(&p, None, &names).is_some());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn a_claude_turn_that_starts_with_an_editor_context_block_is_still_the_persons() {
        let root = tmp("ide-block");
        let cwd = "/w";
        let mut lines = claude_file(cwd, C1);
        lines[2] = serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": [
            {"type": "text", "text": "<ide_opened_file>The user opened the file /w/src/main.rs in the IDE.</ide_opened_file>"},
            {"type": "text", "text": "<ide_selection>fn main() {}</ide_selection>"},
            {"type": "text", "text": "Why does main return nothing?"},
            {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
        ]}, "timestamp": "2026-11-12T10:00:02.000Z"});
        lines.truncate(8); // no title: the first words name it
        lines.push(serde_json::json!({"type": "user", "cwd": cwd, "message": {"role": "user", "content": [
            {"type": "text", "text": "<ide_opened_file>/w/README.md</ide_opened_file>"}, {"type": "text", "text": "and the readme?"}]}}));
        write(&root.join("projects").join(claude_slug(cwd)).join(format!("{C1}.jsonl")), &lines);
        let r = &list(&root, "claude", &[cwd.into()], false).unwrap()[0];
        assert_eq!((r.title.as_str(), r.named), ("Why does main return nothing?", false));
        assert_eq!(r.last.as_ref().map(|l| (l.role, l.text.as_str())), Some(("user", "and the readme?")));
        // a turn of context blocks only is nobody's words
        let only = serde_json::json!({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "<ide_selection>x</ide_selection>"}]}});
        assert!(claude_user_text(&only).is_none());
        let _ = std::fs::remove_dir_all(&root);
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
    /// then continue it through omher's own chat path and ask about the first message.
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
        let rows = list(&root, &agent, &[cwd.clone()], false).unwrap();
        println!("LIST {rows:?}");
        let row = rows.first().expect("the CLI's conversation is listed");
        // OMHER_REAL_LIST_ONLY: only the read-only listing (no model turn)
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

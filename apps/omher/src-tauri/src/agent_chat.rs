//! Chat sessions: an allow-listed agent started in its structured mode ([`crate::sessions::chat_args`]) on
//! pipes, with one adapter per agent that turns the agent's own protocol into the events omher's bot chat
//! already draws (turn start/end, one progress line from tool start/end, text deltas, final messages,
//! approval and question cards) and turns the person's chat input (text, Stop, approval answers, model) into
//! the agent's own messages.
//!
//! - Claude Code: `claude -p` stream-json both ways; tool approvals arrive as `can_use_tool` control requests
//!   (`--permission-prompt-tool stdio`), Stop is an `interrupt` control request.
//! - Codex: `codex app-server`, JSON-RPC over stdio (`thread/start`, `turn/start`, `item/*`,
//!   `item/commandExecution/requestApproval`, `turn/interrupt`).
//! - pi and oh-my-pi: `--mode rpc`, JSONL commands, responses and events (`prompt`, `abort`,
//!   `extension_ui_request` dialogs).
//!
//! The UI sends only an agent id, a folder and chat input; the program and its arguments come from the
//! allow-list. Closing the session (or quitting the app) stops the program.

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::mpsc::{self, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::session_files;
use crate::sessions::{agent, chat_args, coalesce, is_uuid, launch_for, resume_args, signal_group, Mode, COALESCE_BYTES, COALESCE_WINDOW, INPUT_QUEUE};

/// What the person did in the chat. Mirrors `ChatInput` in src/sessions/host.ts. A message's `images` are the
/// saved copies (`session_files`) of the pictures the person attached, for the agent's own image input; any other
/// file is already named in `text` by its saved copy's path.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Input {
    Send { text: String, #[serde(default)] images: Vec<Picture> },
    Interrupt,
    Approve { request_id: String, choice: String },
    /// A string, or per-question answers (`{qid: text|null}`) for several questions at once.
    Clarify { request_id: String, answer: Value },
    Model { model: String },
}

impl Input {
    /// Check that every attached picture is a file omher saved for a session (`session_files::check`) that an
    /// agent's image input takes, and read it. Nothing outside omher's own folder is read.
    pub fn resolve(&mut self, home: &Path) -> Result<(), String> {
        let Input::Send { images, .. } = self else { return Ok(()) };
        for p in images.iter_mut() {
            let real = session_files::check(home, &p.path)?;
            let mime = session_files::image_mime(&p.path).ok_or_else(|| format!("not a picture: {}", p.path))?;
            let bytes = std::fs::read(&real).map_err(|e| e.to_string())?;
            if bytes.len() as u64 > session_files::INLINE_MAX {
                return Err("picture over 5 MB".into());
            }
            p.path = real.to_string_lossy().into_owned();
            p.mime = mime.into();
            p.data = session_files::base64(&bytes);
        }
        Ok(())
    }
}

/// A picture the person attached: its saved copy's path (from the UI) and, once [`Input::resolve`] read it, its type
/// and bytes (base64) for an agent that takes pictures inline.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(from = "String")]
pub struct Picture {
    pub path: String,
    pub mime: String,
    pub data: String,
}

impl From<String> for Picture {
    fn from(path: String) -> Picture {
        Picture { path, ..Picture::default() }
    }
}

/// Events for the UI: the bot chat's own event names (`turn.start`, `tool.start`, `delta`, `message`,
/// `approval.request`, `turn.end`, …) plus `session.info` (agent session id, model) and `session.models`.
pub type Event = Value;

fn ev(name: &str, fields: Value) -> Event {
    let mut m = Map::new();
    m.insert("event".into(), Value::String(name.into()));
    if let Value::Object(f) = fields {
        m.extend(f);
    }
    Value::Object(m)
}

/// Lines to write to the agent and events to show, from one step of an adapter.
#[derive(Debug, Default, PartialEq)]
pub struct Step {
    pub write: Vec<String>,
    pub events: Vec<Event>,
}

impl Step {
    fn out(&mut self, v: Value) {
        self.write.push(v.to_string());
    }
    fn emit(&mut self, e: Event) {
        self.events.push(e);
    }
}

/// One agent's protocol. Pure: lines in, lines and events out, so each adapter is tested with recorded
/// streams and no process.
pub trait Adapter: Send {
    /// What to write right after the program starts.
    fn start(&mut self) -> Step;
    /// One line the program printed on stdout.
    fn on_line(&mut self, line: &str) -> Step;
    /// One thing the person did. `Err` = refused (unknown request, nothing running …).
    fn on_input(&mut self, input: Input) -> Result<Step, String>;
    /// Whether a turn is running (so an exit mid-turn ends it as an error).
    fn in_turn(&self) -> bool;
    /// The line to show for an exit reason (the program's stderr), e.g. a missing login in plain words.
    fn explain(&self, err: &str) -> String {
        err.to_string()
    }
}

/// The adapter for an allow-listed chat agent, or `None` for agents that have no chat mode here. `resume` is a
/// Codex thread to continue (Codex resumes over its protocol; the others take an argument, [`resume_args`]).
pub fn adapter_for(id: &str, cwd: &str, resume: Option<&str>) -> Option<Box<dyn Adapter>> {
    let label = agent(id).map(|a| a.label).unwrap_or(id);
    match id {
        "claude" => Some(Box::new(Claude::new(cwd))),
        "codex" => Some(Box::new(Codex::new(cwd, resume))),
        // OmO speaks pi's RPC (senpi engine): the same adapter, under its own name
        "pi" | "omp" | "omo" => Some(Box::new(Pi::new(cwd, label))),
        _ => None,
    }
}

// ---------------------------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------------------------

fn s(v: &Value, k: &str) -> String {
    v.get(k).and_then(Value::as_str).unwrap_or("").to_string()
}

fn clip(t: &str, n: usize) -> String {
    let one = t.split_whitespace().collect::<Vec<_>>().join(" ");
    if one.chars().count() <= n {
        one
    } else {
        format!("{}…", one.chars().take(n - 1).collect::<String>())
    }
}

/// A conversation name an agent reported, as the session row shows it: one line, at most 80 characters.
fn title_of(t: &str) -> String {
    let t: String = t.chars().map(|c| if c.is_control() { ' ' } else { c }).collect();
    clip(t.trim(), 80)
}

/// `path` relative to the session folder when it is inside it (agents report absolute paths).
fn rel(path: &str, cwd: &str) -> String {
    let c = cwd.trim_end_matches(['/', '\\']);
    if !c.is_empty() {
        for sep in ['/', '\\'] {
            if let Some(r) = path.strip_prefix(&format!("{c}{sep}")) {
                return r.to_string();
            }
        }
    }
    path.to_string()
}

fn lines_of(t: &str) -> u64 {
    t.lines().count() as u64
}

/// `+a` / `-d` counts of a unified diff (headers skipped).
fn unified_counts(diff: &str) -> (u64, u64) {
    let (mut a, mut d) = (0, 0);
    for l in diff.lines() {
        if l.starts_with("+++") || l.starts_with("---") {
            continue;
        }
        if l.starts_with('+') {
            a += 1;
        } else if l.starts_with('-') {
            d += 1;
        }
    }
    (a, d)
}

/// One line for a file change: `notes.txt +1`, `a.ts +3 -1, b.ts +1`.
fn edit_detail(files: &[(String, u64, u64)]) -> String {
    let parts: Vec<String> = files
        .iter()
        .map(|(p, a, d)| {
            let mut x = p.clone();
            if *a > 0 {
                x.push_str(&format!(" +{a}"));
            }
            if *d > 0 {
                x.push_str(&format!(" -{d}"));
            }
            x
        })
        .collect();
    clip(&parts.join(", "), 160)
}

/// The command a shell wrapper runs: `/bin/zsh -lc 'mkdir -p d1'` -> `mkdir -p d1` (Codex reports the
/// wrapped form). Anything else comes back as it is.
fn unwrap_shell(cmd: &str) -> String {
    let t = cmd.trim();
    let Some((prog, rest)) = t.split_once(' ') else { return t.to_string() };
    let base = prog.rsplit(['/', '\\']).next().unwrap_or(prog);
    if !matches!(base, "sh" | "bash" | "zsh") {
        return t.to_string();
    }
    let rest = rest.trim_start();
    let Some((flag, body)) = rest.split_once(' ') else { return t.to_string() };
    if !matches!(flag, "-c" | "-lc" | "-lic" | "-ic") {
        return t.to_string();
    }
    let body = body.trim();
    if body.len() >= 2 && body.starts_with('\'') && body.ends_with('\'') {
        return body[1..body.len() - 1].replace("'\\''", "'");
    }
    if body.len() >= 2 && body.starts_with('"') && body.ends_with('"') {
        return body[1..body.len() - 1].replace("\\\"", "\"");
    }
    body.to_string()
}

/// The first useful line of what a program wrote to stderr: log lines (`2026-11-10T05:09:59Z ERROR …`) and
/// blank lines skipped, else the last line.
/// How a turn ends when its program exits in the middle of it: a clean exit (code 0, nothing on stderr) is
/// "ended", which the UI shows in grey; any other exit is an "error" carrying the reason.
pub(crate) fn exit_turn_end(code: Option<i32>, err: &str) -> Value {
    if code == Some(0) && err.is_empty() {
        return ev("turn.end", json!({"outcome": "ended"}));
    }
    let e = if err.is_empty() { "the agent stopped" } else { err };
    ev("turn.end", json!({"outcome": "error", "error": e}))
}

pub(crate) fn exit_reason(tail: &str) -> String {
    let is_log = |l: &str| l.len() > 11 && l.as_bytes()[..4].iter().all(u8::is_ascii_digit) && l.as_bytes()[4] == b'-' && l.as_bytes()[10] == b'T';
    let lines: Vec<&str> = tail.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
    lines.iter().find(|l| !is_log(l)).or(lines.last()).map(|l| clip(l, 200)).unwrap_or_default()
}

/// What a tool call is about, for the progress line and the approval card: the command, path, pattern,
/// query or URL from its arguments, else a short JSON.
fn tool_detail(input: &Value) -> String {
    for k in ["command", "cmd", "file_path", "path", "notebook_path", "pattern", "query", "url", "code", "description", "prompt"] {
        if let Some(v) = input.get(k) {
            if let Some(t) = v.as_str() {
                if !t.trim().is_empty() {
                    return clip(t, 160);
                }
            }
            if let Some(a) = v.as_array() {
                let parts: Vec<String> = a.iter().filter_map(|x| x.as_str().map(String::from)).collect();
                if !parts.is_empty() {
                    return clip(&parts.join(" "), 160);
                }
            }
        }
    }
    // oh-my-pi's hashline edit: `[path#TAG]` on the first line of `input`
    if let Some(t) = input.get("input").and_then(Value::as_str) {
        let first = t.lines().find(|l| !l.trim().is_empty()).unwrap_or("").trim();
        let first = first.trim_start_matches('[').split('#').next().unwrap_or(first).trim_end_matches(']');
        if !first.is_empty() {
            return clip(first, 160);
        }
    }
    match input {
        Value::Object(m) if m.is_empty() => String::new(),
        Value::Null => String::new(),
        other => clip(&other.to_string(), 160),
    }
}

/// The bot chat's tool names for the verbs on the progress line ("Running", "Reading", "Editing" …).
fn tool_kind(name: &str) -> &str {
    match name.to_ascii_lowercase().as_str() {
        "bash" | "shell" | "exec" | "exec_command" | "local_shell" | "powershell" | "eval" => "terminal",
        "read" | "notebookread" | "view" => "read_file",
        "write" | "edit" | "multiedit" | "notebookedit" | "apply_patch" | "patch" | "ast_edit" => "patch",
        "grep" | "glob" | "ls" | "find" => "search_files",
        "websearch" | "web_search" => "web_search",
        "webfetch" | "fetch" => "web_extract",
        "task" | "agent" => "delegate_task",
        "skill" => "skill_view",
        _ => name,
    }
}

/// A file tool call as `path +a -d` (path relative to the session folder), from the arguments every agent
/// sends: Claude Code `Write {file_path, content}` / `Edit {file_path, old_string, new_string}` /
/// `MultiEdit {file_path, edits}`, pi `write {path, content}` / `edit {path, edits:[{oldText,newText}]}`.
fn file_call_detail(input: &Value, cwd: &str) -> String {
    let path = ["file_path", "path", "notebook_path"].iter().map(|k| s(input, k)).find(|p| !p.is_empty());
    let Some(path) = path else { return tool_detail(input) };
    let (mut a, mut d) = (0, 0);
    if let Some(c) = input.get("content").and_then(Value::as_str) {
        a += lines_of(c);
    }
    let mut pair = |old: &str, new: &str| {
        d += lines_of(old);
        a += lines_of(new);
    };
    if input.get("old_string").is_some() || input.get("new_string").is_some() {
        pair(&s(input, "old_string"), &s(input, "new_string"));
    }
    for e in input.get("edits").and_then(Value::as_array).into_iter().flatten() {
        let old = if e.get("old_string").is_some() { s(e, "old_string") } else { s(e, "oldText") };
        let new = if e.get("new_string").is_some() { s(e, "new_string") } else { s(e, "newText") };
        pair(&old, &new);
    }
    edit_detail(&[(rel(&path, cwd), a, d)])
}

/// The progress-line detail of a tool call: the diff summary for file tools, else the command / path / query.
fn call_detail(name: &str, input: &Value, cwd: &str) -> String {
    if tool_kind(name) == "patch" {
        file_call_detail(input, cwd)
    } else {
        tool_detail(input)
    }
}

const CHOICES: [&str; 3] = ["deny", "once", "session"];

fn with_cwd(mut f: Value, cwd: &str) -> Value {
    if !cwd.is_empty() {
        f["cwd"] = Value::String(cwd.to_string());
    }
    f
}

/// A clarify answer as text: a plain string, or a JSON array of labels (multi-select) joined with ", ".
fn answer_text(v: &Value) -> String {
    match v {
        Value::String(t) => match serde_json::from_str::<Vec<String>>(t) {
            Ok(list) if t.trim_start().starts_with('[') => list.join(", "),
            _ => t.clone(),
        },
        Value::Array(a) => a.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", "),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// Questions for a clarify card: one question (`question` + `choices`), or several as an interview.
fn clarify_event(request_id: &str, qs: &[(String, String, Vec<String>, bool)]) -> Event {
    // (qid, question, choices, multi)
    if qs.len() == 1 {
        let (_, q, choices, multi) = &qs[0];
        let mut f = json!({"request_id": request_id, "question": q});
        if !choices.is_empty() {
            f["choices"] = json!(choices);
        }
        if *multi {
            f["multi_select"] = Value::Bool(true);
        }
        return ev("clarify.request", f);
    }
    let questions: Vec<Value> = qs
        .iter()
        .map(|(qid, q, choices, multi)| {
            let mut x = json!({"qid": qid, "question": q});
            if !choices.is_empty() {
                x["choices"] = json!(choices);
            }
            if *multi {
                x["multi_select"] = Value::Bool(true);
            }
            x
        })
        .collect();
    ev("clarify.request", json!({"request_id": request_id, "question": qs.first().map(|q| q.1.clone()).unwrap_or_default(), "questions": questions}))
}

/// One answer per question id from a clarify input: a string answers the first (only) question; an object
/// maps question ids to answers (null = skipped).
fn answers_by_qid(answer: &Value, qids: &[String]) -> Vec<(String, Option<String>)> {
    match answer {
        Value::Object(m) => qids.iter().map(|q| (q.clone(), m.get(q).filter(|v| !v.is_null()).map(answer_text))).collect(),
        other => qids.first().map(|q| vec![(q.clone(), Some(answer_text(other)))]).unwrap_or_default(),
    }
}

// ---------------------------------------------------------------------------------------------
// Claude Code (stream-json)
// ---------------------------------------------------------------------------------------------

enum ClaudeAsk {
    /// a tool waiting for permission: tool name, input, permission suggestions
    Tool(String, Value, Value),
    /// AskUserQuestion: its input and the question text per question id
    Question(Value, Vec<(String, String)>),
}

#[derive(Default)]
pub struct Claude {
    cwd: String,
    seq: u64,
    turn: bool,
    /// the running turn was started by Claude Code itself (a background task finished), not by the person
    auto_turn: bool,
    pending: HashMap<String, ClaudeAsk>,
    model: String,
    /// model ids (`haiku`, `claude-haiku-5-5`) -> the name Claude Code shows for them
    labels: HashMap<String, String>,
    /// the last assistant message carried an error kind (`authentication_failed`, …)
    error_kind: String,
}

impl Claude {
    pub fn new(cwd: &str) -> Claude {
        Claude { cwd: cwd.into(), ..Claude::default() }
    }
    fn next_id(&mut self, p: &str) -> String {
        self.seq += 1;
        format!("omher-{p}-{}", self.seq)
    }
    fn control(&mut self, step: &mut Step, p: &str, request: Value) {
        let id = self.next_id(p);
        step.out(json!({"type": "control_request", "request_id": id, "request": request}));
    }
    fn label(&self, model: &str) -> String {
        self.labels.get(model).cloned().unwrap_or_else(|| model.to_string())
    }
    fn begin(&mut self, step: &mut Step, auto: bool) {
        if !self.turn {
            self.turn = true;
            self.auto_turn = auto;
            step.emit(ev("turn.start", json!({})));
        }
    }
    fn end(&mut self, step: &mut Step, outcome: &str, error: Option<String>) {
        if self.turn {
            self.turn = false;
            self.auto_turn = false;
            self.pending.clear();
            let mut f = json!({"outcome": outcome});
            if let Some(e) = error.filter(|e| !e.is_empty()) {
                f["error"] = Value::String(e);
            }
            step.emit(ev("turn.end", f));
        }
    }
}

const CLAUDE_SIGNED_OUT: &str = "Claude Code is not signed in. Sign in from Settings › Accounts (or open Terminal and run /login), then Restart.";

impl Adapter for Claude {
    fn start(&mut self) -> Step {
        let mut st = Step::default();
        self.control(&mut st, "init", json!({"subtype": "initialize", "hooks": null}));
        st
    }

    fn in_turn(&self) -> bool {
        self.turn
    }

    fn on_line(&mut self, line: &str) -> Step {
        let mut st = Step::default();
        let Ok(v) = serde_json::from_str::<Value>(line) else { return st };
        let sub = v.get("parent_tool_use_id").map(|p| !p.is_null()).unwrap_or(false);
        match v.get("type").and_then(Value::as_str).unwrap_or("") {
            "system" if s(&v, "subtype") == "init" => {
                self.model = s(&v, "model");
                let mut f = json!({"agent_session": s(&v, "session_id"), "model": self.label(&self.model)});
                let mode = s(&v, "permissionMode");
                if !mode.is_empty() {
                    f["approval"] = Value::String(mode);
                }
                st.emit(ev("session.info", f));
            }
            // the conversation's name changed (a rename in Claude Code); Claude Code says it on its own
            "system" if s(&v, "subtype") == "session_title_changed" => {
                let t = title_of(&s(&v, "title"));
                if !t.is_empty() {
                    st.emit(ev("session.info", json!({"title": t})));
                }
            }
            "control_response" => {
                let r = &v["response"];
                let id = s(r, "request_id");
                let body = &r["response"];
                if id.starts_with("omher-init-") {
                    if let Some(models) = body.get("models").and_then(Value::as_array) {
                        // the `default` entry first, so a named entry for the same model wins the label
                        let mut sorted: Vec<&Value> = models.iter().collect();
                        sorted.sort_by_key(|m| s(m, "value") != "default");
                        for m in sorted {
                            // "Fable 5.2 · Most capable…": the versioned name, since two entries can share "Fable"
                            let desc = s(m, "description");
                            let named = desc.split(" · ").next().unwrap_or("").trim().to_string();
                            let label = if desc.contains(" · ") && !named.is_empty() { named } else { s(m, "displayName") };
                            if label.is_empty() {
                                continue;
                            }
                            self.labels.insert(s(m, "value"), label.clone());
                            let resolved = s(m, "resolvedModel");
                            if !resolved.is_empty() {
                                self.labels.insert(resolved, label);
                            }
                        }
                        let options: Vec<Value> = models
                            .iter()
                            .map(|m| json!({"id": s(m, "value"), "label": s(m, "displayName"), "detail": s(m, "description")}))
                            .filter(|m| !m["id"].as_str().unwrap_or("").is_empty())
                            .collect();
                        st.emit(ev("session.models", json!({"options": options})));
                        if !self.model.is_empty() {
                            st.emit(ev("session.info", json!({"model": self.label(&self.model)})));
                        }
                    }
                } else if id.starts_with("omher-model-") {
                    if s(r, "subtype") == "success" {
                        let m = s(body, "model");
                        if !m.is_empty() {
                            self.model = m;
                        }
                        st.emit(ev("session.info", json!({"model": self.label(&self.model)})));
                    } else {
                        st.emit(ev("session.error", json!({"message": format!("Model not changed: {}", s(r, "error"))})));
                    }
                }
            }
            "control_request" => {
                let rid = s(&v, "request_id");
                let req = &v["request"];
                if s(req, "subtype") == "can_use_tool" {
                    let name = s(req, "tool_name");
                    let input = req.get("input").cloned().unwrap_or(Value::Null);
                    if name == "AskUserQuestion" {
                        let mut ids = Vec::new();
                        let mut qs = Vec::new();
                        for (i, q) in input.get("questions").and_then(Value::as_array).into_iter().flatten().enumerate() {
                            let text = s(q, "question");
                            let choices: Vec<String> = q.get("options").and_then(Value::as_array).into_iter().flatten().map(|o| s(o, "label")).filter(|l| !l.is_empty()).collect();
                            let qid = format!("q{}", i + 1);
                            ids.push((qid.clone(), text.clone()));
                            qs.push((qid, text, choices, q.get("multiSelect").and_then(Value::as_bool).unwrap_or(false)));
                        }
                        if !qs.is_empty() {
                            self.pending.insert(rid.clone(), ClaudeAsk::Question(input, ids));
                            st.emit(clarify_event(&rid, &qs));
                            return st;
                        }
                    }
                    let shown = if s(req, "display_name").is_empty() { name.clone() } else { s(req, "display_name") };
                    let (title, command) = match tool_kind(&name) {
                        "terminal" => ("Run this command?".to_string(), tool_detail(&input)),
                        "patch" => {
                            let path = ["file_path", "path", "notebook_path"].iter().map(|k| s(&input, k)).find(|p| !p.is_empty()).unwrap_or_default();
                            (format!("Allow {shown} to change {}?", if path.is_empty() { "files".to_string() } else { rel(&path, &self.cwd) }), String::new())
                        }
                        _ => (format!("Allow {shown}?"), tool_detail(&input)),
                    };
                    self.pending.insert(rid.clone(), ClaudeAsk::Tool(name, input, req.get("permission_suggestions").cloned().unwrap_or(Value::Null)));
                    st.emit(ev("approval.request", with_cwd(json!({"request_id": rid, "title": title, "command": command, "choices": CHOICES}), &self.cwd)));
                } else {
                    // hooks, MCP messages …: omher registers none of them
                    st.out(json!({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "not supported by omher"}}));
                }
            }
            // Stop (or Claude Code itself) withdrew a permission request it had asked
            "control_cancel_request" => {
                let rid = s(&v, "request_id");
                if self.pending.remove(&rid).is_some() {
                    st.emit(ev("prompt.expired", json!({"request_id": rid, "reason": "cancelled"})));
                }
            }
            "stream_event" if !sub => {
                let e = &v["event"];
                if s(e, "type") == "content_block_delta" {
                    let d = &e["delta"];
                    match s(d, "type").as_str() {
                        "text_delta" => {
                            let t = s(d, "text");
                            if !t.is_empty() {
                                self.begin(&mut st, true);
                                st.emit(ev("delta", json!({"text": t})));
                            }
                        }
                        "thinking_delta" => st.emit(ev("thinking", json!({}))),
                        _ => {}
                    }
                }
            }
            "assistant" if !sub => {
                let msg = &v["message"];
                let mid = s(msg, "id");
                // an error Claude Code reports as a synthetic message (not signed in, …): the turn's end says it
                let err = s(&v, "error");
                if !err.is_empty() {
                    self.error_kind = err;
                    return st;
                }
                for (i, b) in msg.get("content").and_then(Value::as_array).into_iter().flatten().enumerate() {
                    match s(b, "type").as_str() {
                        "text" => {
                            let t = s(b, "text");
                            if !t.trim().is_empty() {
                                self.begin(&mut st, true);
                                st.emit(ev("message", json!({"id": format!("{mid}-{i}"), "text": t})));
                            }
                        }
                        "tool_use" => {
                            let name = s(b, "name");
                            let input = b.get("input").cloned().unwrap_or(Value::Null);
                            if name == "AskUserQuestion" {
                                continue; // it shows as the question card
                            }
                            self.begin(&mut st, true);
                            st.emit(ev("tool.start", json!({"tool_id": s(b, "id"), "name": tool_kind(&name), "detail": call_detail(&name, &input, &self.cwd)})));
                            if name == "Skill" {
                                let sk = s(&input, "skill");
                                if !sk.is_empty() {
                                    st.emit(ev("skill", json!({"name": sk})));
                                }
                            }
                        }
                        _ => {}
                    }
                }
            }
            "user" if !sub => {
                for b in v["message"].get("content").and_then(Value::as_array).into_iter().flatten() {
                    if s(b, "type") == "tool_result" {
                        let ok = !b.get("is_error").and_then(Value::as_bool).unwrap_or(false);
                        st.emit(ev("tool.end", json!({"tool_id": s(b, "tool_use_id"), "name": "", "ok": ok, "ms": 0})));
                    }
                }
            }
            "result" => {
                // A turn Claude Code started by itself (a background task it ran finished): its result must not
                // end the person's turn, which is still running.
                let origin = v.get("origin").map(|o| s(o, "kind")).unwrap_or_default();
                let auto = !origin.is_empty() && !matches!(origin.as_str(), "human" | "person" | "user");
                if auto && self.turn && !self.auto_turn {
                    return st;
                }
                let reason = s(&v, "terminal_reason");
                if reason.starts_with("aborted") || reason == "interrupted" {
                    self.end(&mut st, "interrupted", None);
                } else if v.get("is_error").and_then(Value::as_bool).unwrap_or(false) {
                    let err = if self.error_kind == "authentication_failed" {
                        CLAUDE_SIGNED_OUT.to_string()
                    } else {
                        v.get("errors")
                            .and_then(Value::as_array)
                            .and_then(|a| a.first())
                            .and_then(Value::as_str)
                            .map(String::from)
                            .unwrap_or_else(|| s(&v, "result"))
                    };
                    self.end(&mut st, "error", Some(clip(&err, 200)));
                } else {
                    self.end(&mut st, "done", None);
                }
                self.error_kind.clear();
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text, images } => {
                self.begin(&mut st, false);
                // the person's message joins a turn Claude Code started itself: it is theirs now
                self.auto_turn = false;
                // pictures as Claude Code's own image content (stream-json: an Anthropic base64 image block)
                let mut content: Vec<Value> = images
                    .iter()
                    .map(|p| json!({"type": "image", "source": {"type": "base64", "media_type": p.mime, "data": p.data}}))
                    .collect();
                if !text.is_empty() || content.is_empty() {
                    content.push(json!({"type": "text", "text": text}));
                }
                st.out(json!({"type": "user", "session_id": "", "parent_tool_use_id": null,
                              "message": {"role": "user", "content": content}}));
            }
            Input::Interrupt => self.control(&mut st, "interrupt", json!({"subtype": "interrupt"})),
            Input::Approve { request_id, choice } => {
                let Some(ClaudeAsk::Tool(name, input, suggestions)) = self.pending.remove(&request_id) else { return Err("no such request".into()) };
                let response = match choice.as_str() {
                    "deny" => json!({"behavior": "deny", "message": "The person denied this in omher."}),
                    "once" => json!({"behavior": "allow", "updatedInput": input}),
                    "session" => {
                        // Claude Code suggests rules saved to the project's .claude/settings.local.json and a switch
                        // to acceptEdits: \"for session\" keeps only the rules, for this session.
                        let mut rules: Vec<Value> = suggestions
                            .as_array()
                            .into_iter()
                            .flatten()
                            .filter(|x| s(x, "type") == "addRules")
                            .map(|x| {
                                let mut x = x.clone();
                                x["destination"] = Value::String("session".into());
                                x
                            })
                            .collect();
                        if rules.is_empty() {
                            rules.push(json!({"type": "addRules", "rules": [{"toolName": name}], "behavior": "allow", "destination": "session"}));
                        }
                        json!({"behavior": "allow", "updatedInput": input, "updatedPermissions": rules})
                    }
                    other => return Err(format!("unknown choice {other}")),
                };
                st.out(json!({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": response}}));
            }
            Input::Clarify { request_id, answer } => {
                let Some(ClaudeAsk::Question(mut input, ids)) = self.pending.remove(&request_id) else { return Err("no such question".into()) };
                let qids: Vec<String> = ids.iter().map(|(q, _)| q.clone()).collect();
                let mut answers = Map::new();
                for (qid, a) in answers_by_qid(&answer, &qids) {
                    if let (Some(text), Some((_, q))) = (a.filter(|t| !t.trim().is_empty()), ids.iter().find(|(id, _)| *id == qid)) {
                        answers.insert(q.clone(), Value::String(text));
                    }
                }
                let response = if answers.is_empty() {
                    json!({"behavior": "deny", "message": "The person did not answer."})
                } else {
                    input["answers"] = Value::Object(answers);
                    json!({"behavior": "allow", "updatedInput": input})
                };
                st.out(json!({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": response}}));
            }
            Input::Model { model } => self.control(&mut st, "model", json!({"subtype": "set_model", "model": model})),
        }
        Ok(st)
    }
}

// ---------------------------------------------------------------------------------------------
// Codex (app-server, JSON-RPC over stdio)
// ---------------------------------------------------------------------------------------------

enum CodexAsk {
    Command(Value),
    File(Value),
    /// `item/tool/requestUserInput`: JSON-RPC id and question ids
    Input(Value, Vec<String>),
    /// a question in an agent message (`questions`), answered by steering the turn
    Message,
}

pub struct Codex {
    cwd: String,
    resume: Option<String>,
    seq: u64,
    /// request id -> method, for matching responses
    calls: HashMap<u64, &'static str>,
    thread: Option<String>,
    turn_id: Option<String>,
    turn: bool,
    model: Option<String>,
    model_id: String,
    labels: HashMap<String, String>,
    queued: Vec<(String, Vec<Picture>)>,
    /// open approvals and questions by our request id
    pending: HashMap<String, CodexAsk>,
    /// diff summaries of fileChange items, shown on their approval card
    changes: HashMap<String, String>,
    /// the last error notification was a 401 (not signed in)
    unauthorized: bool,
}

const CODEX_SIGNED_OUT: &str = "Codex is not signed in. Sign in from Settings › Accounts (or run `codex login`), then Restart.";

impl Codex {
    pub fn new(cwd: &str, resume: Option<&str>) -> Codex {
        Codex {
            cwd: cwd.into(),
            resume: resume.map(String::from),
            seq: 0,
            calls: HashMap::new(),
            thread: None,
            turn_id: None,
            turn: false,
            model: None,
            model_id: String::new(),
            labels: HashMap::new(),
            queued: vec![],
            pending: HashMap::new(),
            changes: HashMap::new(),
            unauthorized: false,
        }
    }
    fn call(&mut self, st: &mut Step, method: &'static str, params: Value) {
        self.seq += 1;
        self.calls.insert(self.seq, method);
        st.out(json!({"id": self.seq, "method": method, "params": params}));
    }
    fn turn_start(&mut self, st: &mut Step, text: String, images: &[Picture]) {
        let thread = self.thread.clone().unwrap_or_default();
        // pictures as app-server `localImage` items: Codex reads the saved copy itself
        let mut input: Vec<Value> = images.iter().map(|p| json!({"type": "localImage", "path": p.path})).collect();
        if !text.is_empty() || input.is_empty() {
            input.push(json!({"type": "text", "text": text}));
        }
        let mut p = json!({"threadId": thread, "input": input});
        if let Some(m) = &self.model {
            p["model"] = Value::String(m.clone());
        }
        self.call(st, "turn/start", p);
    }
    fn label(&self, model: &str) -> String {
        self.labels.get(model).cloned().unwrap_or_else(|| model.to_string())
    }
    fn end(&mut self, st: &mut Step, outcome: &str, error: Option<String>) {
        if self.turn {
            self.turn = false;
            self.turn_id = None;
            // approvals die with the turn; a question asked in a message is answered with the next turn
            self.pending.retain(|_, a| matches!(a, CodexAsk::Message));
            let mut f = json!({"outcome": outcome});
            if let Some(e) = error.filter(|e| !e.is_empty()) {
                f["error"] = Value::String(e);
            }
            st.emit(ev("turn.end", f));
        }
    }
    /// The command an item runs, as the person would type it.
    fn command_of(p: &Value) -> String {
        let raw = s(p, "command");
        let un = unwrap_shell(&raw);
        if un != raw.trim() || raw.is_empty() {
            if !un.is_empty() {
                return un;
            }
        }
        // a single parsed action names the command without its wrapper
        match p.get("commandActions").and_then(Value::as_array) {
            Some(a) if a.len() == 1 && !s(&a[0], "command").is_empty() => s(&a[0], "command"),
            _ => raw,
        }
    }
    fn file_changes(&self, item: &Value) -> String {
        let files: Vec<(String, u64, u64)> = item
            .get("changes")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|c| !s(c, "path").is_empty())
            .map(|c| {
                let diff = s(c, "diff");
                let (a, d) = match c.get("kind").map(|k| s(k, "type")).as_deref() {
                    Some("add") => (lines_of(&diff), 0),
                    Some("delete") => (0, lines_of(&diff)),
                    _ => unified_counts(&diff),
                };
                (rel(&s(c, "path"), &self.cwd), a, d)
            })
            .collect();
        edit_detail(&files)
    }
}

impl Adapter for Codex {
    fn start(&mut self) -> Step {
        let mut st = Step::default();
        self.call(&mut st, "initialize", json!({"clientInfo": {"name": "omher", "title": "omher", "version": env!("CARGO_PKG_VERSION")}, "capabilities": {"experimentalApi": false}}));
        st
    }

    fn in_turn(&self) -> bool {
        self.turn
    }

    fn on_line(&mut self, line: &str) -> Step {
        let mut st = Step::default();
        let Ok(v) = serde_json::from_str::<Value>(line) else { return st };
        let method = s(&v, "method");
        let id = v.get("id").cloned();
        // a response to one of our calls
        if method.is_empty() {
            let Some(n) = id.as_ref().and_then(Value::as_u64) else { return st };
            let what = self.calls.remove(&n).unwrap_or("");
            if let Some(err) = v.get("error") {
                let msg = s(err, "message");
                if what == "turn/start" {
                    self.end(&mut st, "error", Some(clip(&msg, 200)));
                } else {
                    st.emit(ev("session.error", json!({"message": format!("{what}: {msg}")})));
                }
                return st;
            }
            let r = &v["result"];
            match what {
                "initialize" => {
                    st.out(json!({"method": "initialized"}));
                    match self.resume.clone() {
                        Some(thread) => self.call(&mut st, "thread/resume", json!({"threadId": thread})),
                        None => {
                            let cwd = self.cwd.clone();
                            self.call(&mut st, "thread/start", json!({"cwd": cwd}))
                        }
                    }
                    self.call(&mut st, "model/list", json!({}));
                }
                "thread/start" | "thread/resume" => {
                    self.thread = r["thread"].get("id").and_then(Value::as_str).map(String::from);
                    self.model_id = s(r, "model");
                    let mut f = json!({"agent_session": self.thread.clone().unwrap_or_default(), "model": self.label(&self.model_id)});
                    let policy = s(r, "approvalPolicy");
                    if !policy.is_empty() {
                        f["approval"] = Value::String(policy);
                    }
                    if let Some(sb) = r.get("sandbox").map(|x| s(x, "type")).filter(|x| !x.is_empty()) {
                        f["sandbox"] = Value::String(sb);
                    }
                    // a resumed thread carries the name Codex (or the person) gave it
                    let name = title_of(&s(&r["thread"], "name"));
                    if !name.is_empty() {
                        f["title"] = Value::String(name);
                    }
                    st.emit(ev("session.info", f));
                    for (text, images) in std::mem::take(&mut self.queued) {
                        self.turn_start(&mut st, text, &images);
                    }
                }
                "turn/start" => {
                    if let Some(t) = r["turn"].get("id").and_then(Value::as_str) {
                        self.turn_id = Some(t.into());
                    }
                }
                "model/list" => {
                    let list: Vec<&Value> = r.get("data").and_then(Value::as_array).into_iter().flatten().filter(|m| !m.get("hidden").and_then(Value::as_bool).unwrap_or(false)).collect();
                    for m in &list {
                        let label = s(m, "displayName");
                        if !label.is_empty() {
                            self.labels.insert(s(m, "model"), label);
                        }
                    }
                    let options: Vec<Value> = list.iter().map(|m| json!({"id": s(m, "model"), "label": s(m, "displayName"), "detail": s(m, "description")})).collect();
                    st.emit(ev("session.models", json!({"options": options})));
                    if !self.model_id.is_empty() {
                        st.emit(ev("session.info", json!({"model": self.label(&self.model_id)})));
                    }
                }
                _ => {}
            }
            return st;
        }
        let p = v.get("params").cloned().unwrap_or(Value::Null);
        // a request from the server (approvals, questions); anything we do not handle is answered with an error
        if let Some(rpc_id) = id {
            let key = format!("codex-{}", rpc_id);
            match method.as_str() {
                "item/commandExecution/requestApproval" => {
                    let reason = s(&p, "reason");
                    let title = if reason.is_empty() { "Run this command?".to_string() } else { clip(&reason, 120) };
                    let cwd = if s(&p, "cwd").is_empty() { self.cwd.clone() } else { s(&p, "cwd") };
                    self.pending.insert(key.clone(), CodexAsk::Command(rpc_id));
                    st.emit(ev("approval.request", with_cwd(json!({"request_id": key, "title": title, "command": Codex::command_of(&p), "choices": CHOICES}), &cwd)));
                }
                "item/fileChange/requestApproval" => {
                    let files = self.changes.get(&s(&p, "itemId")).cloned().unwrap_or_default();
                    let title = if files.is_empty() { "Allow Codex to change files?".to_string() } else { format!("Allow Codex to change {files}?") };
                    self.pending.insert(key.clone(), CodexAsk::File(rpc_id));
                    st.emit(ev("approval.request", with_cwd(json!({"request_id": key, "title": title, "command": "", "choices": CHOICES}), &self.cwd)));
                }
                "item/tool/requestUserInput" => {
                    let mut qids = Vec::new();
                    let mut qs = Vec::new();
                    for q in p.get("questions").and_then(Value::as_array).into_iter().flatten() {
                        let choices: Vec<String> = q.get("options").and_then(Value::as_array).into_iter().flatten().map(|o| s(o, "label")).filter(|l| !l.is_empty()).collect();
                        let text = if s(q, "question").is_empty() { s(q, "header") } else { s(q, "question") };
                        qids.push(s(q, "id"));
                        qs.push((s(q, "id"), text, choices, false));
                    }
                    if qs.is_empty() {
                        st.out(json!({"id": rpc_id, "result": {"answers": {}}}));
                    } else {
                        self.pending.insert(key.clone(), CodexAsk::Input(rpc_id, qids));
                        st.emit(clarify_event(&key, &qs));
                    }
                }
                _ => st.out(json!({"id": rpc_id, "error": {"code": -32601, "message": "not supported by omher"}})),
            }
            return st;
        }
        let item = p.get("item").cloned().unwrap_or(Value::Null);
        match method.as_str() {
            // the thread got a name (Codex's own, or a rename elsewhere): the session takes it
            "thread/name/updated" if self.thread.as_deref() == Some(s(&p, "threadId").as_str()) => {
                let t = title_of(&s(&p, "threadName"));
                if !t.is_empty() {
                    st.emit(ev("session.info", json!({"title": t})));
                }
            }
            "turn/started" => {
                if let Some(t) = p["turn"].get("id").and_then(Value::as_str) {
                    self.turn_id = Some(t.into());
                }
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
            }
            "item/agentMessage/delta" => {
                let t = s(&p, "delta");
                if !t.is_empty() {
                    st.emit(ev("delta", json!({"text": t})));
                }
            }
            "item/reasoning/textDelta" | "item/reasoning/summaryTextDelta" => st.emit(ev("thinking", json!({}))),
            "item/started" => {
                let iid = s(&item, "id");
                match s(&item, "type").as_str() {
                    "commandExecution" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": "terminal", "detail": clip(&Codex::command_of(&item), 160)}))),
                    "fileChange" => {
                        let detail = self.file_changes(&item);
                        let paths: Vec<String> = item.get("changes").and_then(Value::as_array).into_iter().flatten().map(|c| rel(&s(c, "path"), &self.cwd)).filter(|p| !p.is_empty()).collect();
                        self.changes.insert(iid.clone(), clip(&paths.join(", "), 120));
                        st.emit(ev("tool.start", json!({"tool_id": iid, "name": "patch", "detail": detail})));
                    }
                    "mcpToolCall" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": s(&item, "tool"), "detail": format!("{}.{}", s(&item, "server"), s(&item, "tool"))}))),
                    "dynamicToolCall" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": tool_kind(&s(&item, "tool")), "detail": tool_detail(&item["arguments"])}))),
                    "webSearch" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": "web_search", "detail": s(&item, "query")}))),
                    "imageView" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": "read_file", "detail": rel(&s(&item, "path"), &self.cwd)}))),
                    "sleep" => {
                        let secs = item.get("durationMs").and_then(Value::as_u64).unwrap_or(0) / 1000;
                        st.emit(ev("tool.start", json!({"tool_id": iid, "name": "Waiting", "detail": if secs > 0 { format!("{secs}s") } else { String::new() }})));
                    }
                    _ => {}
                }
            }
            "item/completed" => {
                let iid = s(&item, "id");
                match s(&item, "type").as_str() {
                    "agentMessage" => {
                        // a question in the message: a question card instead of the bubble
                        let qs: Vec<(String, String, Vec<String>, bool)> = item
                            .get("questions")
                            .and_then(Value::as_array)
                            .into_iter()
                            .flatten()
                            .enumerate()
                            .map(|(i, q)| {
                                let choices = q.get("options").and_then(Value::as_array).into_iter().flatten().filter_map(|o| o.as_str().map(String::from)).collect();
                                (format!("q{}", i + 1), s(q, "title"), choices, false)
                            })
                            .filter(|q| !q.1.is_empty())
                            .collect();
                        if !qs.is_empty() {
                            self.pending.insert(iid.clone(), CodexAsk::Message);
                            st.emit(clarify_event(&iid, &qs));
                            return st;
                        }
                        let t = s(&item, "text");
                        if !t.trim().is_empty() {
                            st.emit(ev("message", json!({"id": iid, "text": t})));
                        }
                    }
                    "commandExecution" | "fileChange" | "mcpToolCall" | "dynamicToolCall" | "webSearch" | "imageView" | "sleep" => {
                        let status = s(&item, "status");
                        let ok = !matches!(status.as_str(), "failed" | "declined");
                        st.emit(ev("tool.end", json!({"tool_id": iid, "name": "", "ok": ok, "ms": item.get("durationMs").and_then(Value::as_u64).unwrap_or(0)})));
                    }
                    _ => {}
                }
            }
            // a request we were asked is no longer open (Stop, or answered elsewhere)
            "serverRequest/resolved" => {
                let key = format!("codex-{}", p.get("requestId").cloned().unwrap_or(Value::Null));
                if self.pending.remove(&key).is_some() {
                    st.emit(ev("prompt.expired", json!({"request_id": key, "reason": "cancelled"})));
                }
            }
            "turn/completed" => {
                let t = &p["turn"];
                match s(t, "status").as_str() {
                    "interrupted" => self.end(&mut st, "interrupted", None),
                    "failed" => {
                        let e = t.get("error").map(|e| s(e, "message")).unwrap_or_default();
                        let e = if self.unauthorized || e.contains("401 Unauthorized") { CODEX_SIGNED_OUT.to_string() } else { clip(&e, 200) };
                        self.end(&mut st, "error", Some(e));
                    }
                    _ => self.end(&mut st, "done", None),
                }
                self.unauthorized = false;
            }
            "error" => {
                let e = &p["error"];
                let info = e.get("codexErrorInfo").cloned().unwrap_or(Value::Null);
                if info.to_string().contains("\"httpStatusCode\":401") {
                    self.unauthorized = true;
                }
                if p.get("willRetry").and_then(Value::as_bool).unwrap_or(false) {
                    // "Reconnecting... 2/5": say it on the progress line instead of a silent wait
                    st.emit(ev("status", json!({"text": clip(&s(e, "message"), 120)})));
                } else if !self.unauthorized {
                    st.emit(ev("status", json!({"text": clip(&format!("Error: {}", s(e, "message")), 160)})));
                }
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text, images } => {
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
                if self.thread.is_none() {
                    self.queued.push((text, images));
                } else {
                    self.turn_start(&mut st, text, &images);
                }
            }
            Input::Interrupt => {
                let (Some(thread), Some(turn)) = (self.thread.clone(), self.turn_id.clone()) else { return Err("nothing is running".into()) };
                self.call(&mut st, "turn/interrupt", json!({"threadId": thread, "turnId": turn}));
            }
            Input::Approve { request_id, choice } => {
                let rpc_id = match self.pending.remove(&request_id) {
                    Some(CodexAsk::Command(id)) | Some(CodexAsk::File(id)) => id,
                    Some(other) => {
                        self.pending.insert(request_id, other);
                        return Err("not an approval".into());
                    }
                    None => return Err("no such request".into()),
                };
                let decision = match choice.as_str() {
                    "deny" => "decline",
                    "once" => "accept",
                    "session" => "acceptForSession",
                    other => return Err(format!("unknown choice {other}")),
                };
                st.out(json!({"id": rpc_id, "result": {"decision": decision}}));
            }
            Input::Clarify { request_id, answer } => match self.pending.remove(&request_id) {
                Some(CodexAsk::Input(rpc_id, qids)) => {
                    let mut answers = Map::new();
                    for (qid, a) in answers_by_qid(&answer, &qids) {
                        let list: Vec<String> = a.map(|t| t.split(", ").map(String::from).filter(|x| !x.is_empty()).collect()).unwrap_or_default();
                        answers.insert(qid, json!({"answers": list}));
                    }
                    st.out(json!({"id": rpc_id, "result": {"answers": answers}}));
                }
                Some(CodexAsk::Message) => {
                    let text = answers_by_qid(&answer, &["q1".to_string()]).into_iter().filter_map(|(_, a)| a).collect::<Vec<_>>().join("\n");
                    let thread = self.thread.clone().unwrap_or_default();
                    match self.turn_id.clone() {
                        // the turn is still waiting for the answer: steer it
                        Some(turn) if self.turn => self.call(&mut st, "turn/steer", json!({"threadId": thread, "input": [{"type": "text", "text": text}], "expectedTurnId": turn})),
                        _ => {
                            if !self.turn {
                                self.turn = true;
                                st.emit(ev("turn.start", json!({})));
                            }
                            self.turn_start(&mut st, text, &[]);
                        }
                    }
                }
                Some(other) => {
                    self.pending.insert(request_id, other);
                    return Err("not a question".into());
                }
                None => return Err("no such question".into()),
            },
            Input::Model { model } => {
                // app-server takes the model per turn; the next turn uses it
                self.model = Some(model.clone());
                st.emit(ev("session.info", json!({"model": self.label(&model)})));
            }
        }
        Ok(st)
    }
}

// ---------------------------------------------------------------------------------------------
// pi and oh-my-pi (`--mode rpc`)
// ---------------------------------------------------------------------------------------------

/// An open pi / oh-my-pi dialog.
enum PiAsk {
    Confirm,
    /// a tool approval oh-my-pi asks as a `select`: the option label for each answer
    Approve { once: String, session: Option<String>, deny: String },
    Select,
    Input,
}

#[derive(Default)]
pub struct Pi {
    cwd: String,
    label: String,
    seq: u64,
    calls: HashMap<String, &'static str>,
    turn: bool,
    streaming: bool,
    msg: u64,
    last_stop: String,
    last_error: String,
    pending: HashMap<String, PiAsk>,
}

/// oh-my-pi's tool approval as a select (`Allow tool: bash\nCommand: ls -la` with Approve / Approve bash for this
/// session / Deny): the card title, the command and the labels, or `None` for an ordinary select.
fn pi_approval(title: &str, options: &[String]) -> Option<(String, String, PiAsk)> {
    let mut lines = title.lines();
    let tool = lines.next()?.strip_prefix("Allow tool: ")?.trim().to_string();
    let deny = options.iter().find(|o| o.as_str() == "Deny")?.clone();
    let once = options.iter().find(|o| o.as_str() == "Approve" || o.as_str() == "Approve Once")?.clone();
    let session = options.iter().find(|o| o.ends_with("for this session")).cloned();
    let rest: Vec<&str> = lines.collect();
    let field = |k: &str| rest.iter().find_map(|l| l.strip_prefix(k)).map(|x| x.trim().to_string());
    let (title, command) = match tool_kind(&tool) {
        "terminal" => ("Run this command?".to_string(), field("Command:").or_else(|| field("Code:")).unwrap_or_default()),
        "patch" => {
            let p = field("Path:").or_else(|| field("File:")).unwrap_or_default();
            (if p.is_empty() || p == "(unknown)" { format!("Allow {tool} to change files?") } else { format!("Allow {tool} to change {p}?") }, String::new())
        }
        _ => (format!("Allow {tool}?"), clip(&rest.join(" "), 160)),
    };
    Some((title, command, PiAsk::Approve { once, session, deny }))
}

impl Pi {
    pub fn new(cwd: &str, label: &str) -> Pi {
        Pi { cwd: cwd.into(), label: label.into(), ..Pi::default() }
    }
    fn cmd(&mut self, st: &mut Step, kind: &'static str, mut fields: Value) {
        self.seq += 1;
        let id = format!("omher-{}", self.seq);
        self.calls.insert(id.clone(), kind);
        fields["id"] = Value::String(id);
        fields["type"] = Value::String(kind.into());
        st.out(fields);
    }
    fn end(&mut self, st: &mut Step) {
        if self.turn {
            self.turn = false;
            self.streaming = false;
            self.pending.clear();
            let (outcome, err) = match self.last_stop.as_str() {
                "aborted" => ("interrupted", String::new()),
                "error" => ("error", self.last_error.clone()),
                _ => ("done", String::new()),
            };
            let mut f = json!({"outcome": outcome});
            if !err.is_empty() {
                f["error"] = Value::String(self.friendly(&err));
            }
            st.emit(ev("turn.end", f));
        }
        self.last_stop.clear();
        self.last_error.clear();
    }
    /// A calm line for an error: a missing login names where to sign in, anything else its first line.
    fn friendly(&self, err: &str) -> String {
        let who = if self.label.is_empty() { "pi" } else { &self.label };
        if err.contains("No API key") || err.contains("/login") || err.contains("No default model") {
            return format!("{who} is not signed in. Open Terminal and run /login, then Restart.");
        }
        clip(err.lines().find(|l| !l.trim().is_empty()).unwrap_or(err), 200)
    }
}

fn pi_model(m: &Value) -> Value {
    let provider = s(m, "provider");
    let id = s(m, "id");
    let name = if s(m, "name").is_empty() { id.clone() } else { s(m, "name") };
    json!({"id": format!("{provider}/{id}"), "label": name, "detail": provider})
}

impl Adapter for Pi {
    fn explain(&self, err: &str) -> String {
        self.friendly(err)
    }

    fn start(&mut self) -> Step {
        let mut st = Step::default();
        self.cmd(&mut st, "get_state", json!({}));
        self.cmd(&mut st, "get_available_models", json!({}));
        st
    }

    fn in_turn(&self) -> bool {
        self.turn
    }

    fn on_line(&mut self, line: &str) -> Step {
        let mut st = Step::default();
        let Ok(v) = serde_json::from_str::<Value>(line) else { return st };
        match s(&v, "type").as_str() {
            "response" => {
                let what = self.calls.remove(&s(&v, "id")).unwrap_or("");
                let ok = v.get("success").and_then(Value::as_bool).unwrap_or(false);
                let d = &v["data"];
                if !ok {
                    let e = s(&v, "error");
                    if what == "prompt" {
                        self.last_stop = "error".into();
                        self.last_error = e;
                        self.end(&mut st);
                    } else if !what.is_empty() {
                        st.emit(ev("session.error", json!({"message": format!("{}: {}", s(&v, "command"), self.friendly(&e))})));
                    }
                    return st;
                }
                match what {
                    "get_state" => {
                        let model = d.get("model").map(|m| s(m, "name")).filter(|n| !n.is_empty() && n != "unknown").or_else(|| d.get("model").map(|m| s(m, "id")).filter(|n| n != "unknown")).unwrap_or_default();
                        st.emit(ev("session.info", json!({"agent_session": s(d, "sessionId"), "model": model})));
                    }
                    "get_available_models" => {
                        let options: Vec<Value> = d.get("models").and_then(Value::as_array).into_iter().flatten().map(pi_model).collect();
                        st.emit(ev("session.models", json!({"options": options})));
                    }
                    "set_model" => {
                        let label = pi_model(d)["label"].clone();
                        st.emit(ev("session.info", json!({"model": label})));
                    }
                    "prompt" => {
                        if s(d, "disposition") == "handled" {
                            self.end(&mut st);
                        }
                    }
                    _ => {}
                }
            }
            "agent_start" => {
                self.streaming = true;
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
            }
            "message_update" => {
                let e = &v["assistantMessageEvent"];
                match s(e, "type").as_str() {
                    "text_delta" => {
                        let t = s(e, "delta");
                        if !t.is_empty() {
                            st.emit(ev("delta", json!({"text": t})));
                        }
                    }
                    "thinking_delta" | "thinking_start" => st.emit(ev("thinking", json!({}))),
                    _ => {}
                }
            }
            "message_end" => {
                let m = &v["message"];
                if s(m, "role") == "assistant" {
                    self.last_stop = s(m, "stopReason");
                    self.last_error = s(m, "errorMessage");
                    let text: String = match m.get("content") {
                        Some(Value::String(t)) => t.clone(),
                        Some(Value::Array(a)) => a.iter().filter(|b| s(b, "type") == "text").map(|b| s(b, "text")).collect::<Vec<_>>().join(""),
                        _ => String::new(),
                    };
                    if !text.trim().is_empty() {
                        self.msg += 1;
                        st.emit(ev("message", json!({"id": format!("pi-m{}", self.msg), "text": text})));
                    }
                }
            }
            "tool_execution_start" => {
                let name = s(&v, "toolName");
                let args = v.get("args").cloned().unwrap_or(Value::Null);
                st.emit(ev("tool.start", json!({"tool_id": s(&v, "toolCallId"), "name": tool_kind(&name), "detail": call_detail(&name, &args, &self.cwd)})));
            }
            "tool_execution_end" => {
                let ok = !v.get("isError").and_then(Value::as_bool).unwrap_or(false);
                st.emit(ev("tool.end", json!({"tool_id": s(&v, "toolCallId"), "name": "", "ok": ok, "ms": 0})));
            }
            // Both end a run with agent_end. oh-my-pi then adds prompt_result and session_settled, which can arrive
            // after the person's next prompt was sent, so they never end a turn, except a prompt no agent ran for.
            "agent_end" => self.end(&mut st),
            "prompt_result" if v.get("agentInvoked").and_then(Value::as_bool) == Some(false) => self.end(&mut st),
            "extension_ui_request" => {
                let id = s(&v, "id");
                let method = s(&v, "method");
                let title = s(&v, "title");
                match method.as_str() {
                    "confirm" => {
                        let msg = s(&v, "message");
                        self.pending.insert(id.clone(), PiAsk::Confirm);
                        st.emit(ev("approval.request", with_cwd(json!({"request_id": id, "title": if title.is_empty() { "Allow this?".into() } else { title }, "command": msg, "choices": ["deny", "once"]}), &self.cwd)));
                    }
                    "select" => {
                        let options: Vec<String> = v.get("options").and_then(Value::as_array).into_iter().flatten().filter_map(|o| o.as_str().map(String::from)).collect();
                        if let Some((t, command, ask)) = pi_approval(&title, &options) {
                            let choices: Vec<&str> = if matches!(&ask, PiAsk::Approve { session: Some(_), .. }) { CHOICES.to_vec() } else { vec!["deny", "once"] };
                            self.pending.insert(id.clone(), ask);
                            st.emit(ev("approval.request", with_cwd(json!({"request_id": id, "title": t, "command": command, "choices": choices}), &self.cwd)));
                        } else {
                            self.pending.insert(id.clone(), PiAsk::Select);
                            st.emit(ev("clarify.request", json!({"request_id": id, "question": title, "choices": options})));
                        }
                    }
                    "input" => {
                        self.pending.insert(id.clone(), PiAsk::Input);
                        st.emit(ev("clarify.request", json!({"request_id": id, "question": title})));
                    }
                    "editor" => st.out(json!({"type": "extension_ui_response", "id": id, "cancelled": true})),
                    // oh-my-pi closes a dialog it opened (its own timeout)
                    "cancel" => {
                        let target = s(&v, "targetId");
                        if self.pending.remove(&target).is_some() {
                            st.emit(ev("prompt.expired", json!({"request_id": target, "reason": "timeout"})));
                        }
                    }
                    "setStatus" => {
                        let t = s(&v, "statusText");
                        if !t.is_empty() {
                            st.emit(ev("status", json!({"text": clip(&t, 120)})));
                        }
                    }
                    _ => {}
                }
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text, images } => {
                let mut f = json!({"message": text});
                // pictures as the rpc prompt's own `images` (ImageContent: base64 data and its type)
                if !images.is_empty() {
                    f["images"] = images.iter().map(|p| json!({"type": "image", "data": p.data, "mimeType": p.mime})).collect();
                }
                if self.streaming {
                    f["streamingBehavior"] = Value::String("followUp".into());
                }
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
                self.cmd(&mut st, "prompt", f);
            }
            Input::Interrupt => self.cmd(&mut st, "abort", json!({})),
            Input::Approve { request_id, choice } => {
                let ask = self.pending.remove(&request_id).ok_or("no such request")?;
                let out = match (&ask, choice.as_str()) {
                    (PiAsk::Confirm, "deny") => json!({"confirmed": false}),
                    (PiAsk::Confirm, "once" | "session") => json!({"confirmed": true}),
                    (PiAsk::Approve { deny, .. }, "deny") => json!({"value": deny}),
                    (PiAsk::Approve { once, .. }, "once") => json!({"value": once}),
                    (PiAsk::Approve { session: Some(s), .. }, "session") => json!({"value": s}),
                    (PiAsk::Select | PiAsk::Input, _) => {
                        self.pending.insert(request_id, ask);
                        return Err("not an approval".into());
                    }
                    (_, other) => {
                        self.pending.insert(request_id, ask);
                        return Err(format!("unknown choice {other}"));
                    }
                };
                let mut out = out;
                out["type"] = Value::String("extension_ui_response".into());
                out["id"] = Value::String(request_id);
                st.out(out);
            }
            Input::Clarify { request_id, answer } => {
                let ask = self.pending.remove(&request_id).ok_or("no such request")?;
                if matches!(ask, PiAsk::Confirm | PiAsk::Approve { .. }) {
                    self.pending.insert(request_id, ask);
                    return Err("not a question".into());
                }
                st.out(json!({"type": "extension_ui_response", "id": request_id, "value": answer_text(&answer)}));
            }
            Input::Model { model } => {
                let (provider, id) = model.split_once('/').ok_or("model must be provider/id")?;
                self.cmd(&mut st, "set_model", json!({"provider": provider, "modelId": id}));
            }
        }
        Ok(st)
    }
}

// ---------------------------------------------------------------------------------------------
// Live chat processes
// ---------------------------------------------------------------------------------------------

/// What a chat session sends back: events, then once, the exit (code; `None` after a signal) with the last
/// lines the program wrote to stderr.
#[derive(Debug, Clone, PartialEq)]
pub enum ChatOut {
    Event(Event),
    Exit(Option<i32>, String),
}

type ChatSink = Arc<Mutex<Box<dyn FnMut(ChatOut) + Send>>>;

/// Input for a chat's writer thread, which owns the program's stdin. `None` once the session is stopping:
/// dropping the last sender ends the writer thread, which closes stdin (the agents' orderly shutdown).
type ChatInputQueue = Arc<Mutex<Option<SyncSender<Vec<u8>>>>>;

struct ChatLive {
    stdin: ChatInputQueue,
    adapter: Arc<Mutex<Box<dyn Adapter>>>,
    sink: ChatSink,
    child: Arc<Mutex<Child>>,
    pid: u32,
    exited: Arc<AtomicBool>,
}

/// Every running chat session of this app. [`ChatSessions::close_all`] runs on exit.
#[derive(Default)]
pub struct ChatSessions {
    live: Mutex<HashMap<u32, ChatLive>>,
    next: AtomicU32,
}

/// Queue `lines` for the chat's writer thread. Never blocks (a pipe takes only so much before a write
/// would): an agent that stops reading its input makes this fail once the queue is full.
fn write_lines(stdin: &ChatInputQueue, lines: &[String]) -> Result<(), String> {
    if lines.is_empty() {
        return Ok(());
    }
    let mut chunk = Vec::new();
    for l in lines {
        chunk.extend_from_slice(l.as_bytes());
        chunk.push(b'\n');
    }
    let tx = stdin.lock().unwrap().clone().ok_or("the session has ended")?;
    match tx.try_send(chunk) {
        Ok(()) => Ok(()),
        Err(TrySendError::Full(_)) => Err("the agent is not reading its input".into()),
        Err(TrySendError::Disconnected(_)) => Err("the session has ended".into()),
    }
}

/// Adjacent `delta` events of one read window become one, so a fast token stream is a few UI messages.
fn merge_deltas(events: Vec<Event>) -> Vec<Event> {
    let is_delta = |e: &Event| e.as_object().is_some_and(|m| m.len() == 2 && s(e, "event") == "delta" && m.get("text").is_some_and(Value::is_string));
    let mut out: Vec<Event> = Vec::with_capacity(events.len());
    for e in events {
        if let Some(last) = out.last_mut() {
            if is_delta(last) && is_delta(&e) {
                let joined = s(last, "text") + &s(&e, "text");
                last["text"] = Value::String(joined);
                continue;
            }
        }
        out.push(e);
    }
    out
}

fn deliver(sink: &ChatSink, events: Vec<Event>) {
    if events.is_empty() {
        return;
    }
    if let Ok(mut f) = sink.lock() {
        for e in events {
            f(ChatOut::Event(e));
        }
    }
}

/// The command a chat runs: `argv` in `cwd` on pipes, with the child `PATH` and the chosen account's home
/// variable (`account_env`, empty for the CLI's own login), the same env a terminal session gets. Nothing
/// else is added.
fn command_for(argv: &[OsString], cwd: &Path, path_env: Option<OsString>, account_env: &[(String, String)]) -> Result<Command, String> {
    let (prog, rest) = argv.split_first().ok_or("empty argv")?;
    let mut cmd = Command::new(prog);
    cmd.args(rest).current_dir(cwd).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    if let Some(p) = path_env {
        cmd.env("PATH", p);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0); // its own group, so close stops helpers it started too
        if std::env::var_os("LANG").is_none() {
            cmd.env("LANG", "en_US.UTF-8");
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    for (k, v) in account_env {
        cmd.env(k, v);
    }
    Ok(cmd)
}

impl ChatSessions {
    pub fn new() -> Arc<ChatSessions> {
        Arc::new(ChatSessions::default())
    }

    /// Start allow-listed agent `agent_id` in its chat mode in `cwd`. `resume` (Claude Code, Codex, OmO)
    /// continues that conversation. `account_env` is `accounts::session_env` for that agent, as for a terminal session:
    /// the chosen account's home variable, or nothing. Anything not on the allow-list, or without a chat
    /// mode, is refused before a process exists.
    pub fn start_agent<F>(&self, agent_id: &str, cwd: &Path, resume: Option<&str>, account_env: &[(String, String)], sink: F) -> Result<u32, String>
    where
        F: FnMut(ChatOut) + Send + 'static,
    {
        let a = agent(agent_id).ok_or_else(|| format!("unknown agent \"{agent_id}\""))?;
        if a.mode != Mode::Chat {
            return Err(format!("{} has no chat mode", a.label));
        }
        let args = chat_args(agent_id).ok_or("no chat mode")?;
        // Codex continues a thread over its own protocol (`thread/resume`), not by an argument; the id must
        // still be one Codex reported (a UUID). Claude Code takes `--resume <uuid>` ([`resume_args`]).
        let thread = match (agent_id, resume) {
            ("codex", Some(r)) if is_uuid(r) => Some(r),
            ("codex", Some(_)) => return Err("not a Codex thread id".into()),
            _ => None,
        };
        let adapter = adapter_for(agent_id, &cwd.to_string_lossy(), thread).ok_or("no chat adapter")?;
        let (mut argv, path_env) = launch_for(agent_id)?;
        argv.extend(args.iter().map(OsString::from));
        if let Some(r) = resume.filter(|_| thread.is_none()) {
            argv.extend(resume_args(agent_id, r)?);
        }
        self.spawn(argv, cwd, Some(path_env), account_env, adapter, sink)
    }

    /// Start `argv` on pipes in `cwd` with `adapter`. Crate-internal: the app reaches it only through
    /// [`ChatSessions::start_agent`], so argv always comes from the allow-list (tests use it directly).
    pub(crate) fn spawn<F>(
        &self,
        argv: Vec<OsString>,
        cwd: &Path,
        path_env: Option<OsString>,
        account_env: &[(String, String)],
        mut adapter: Box<dyn Adapter>,
        sink: F,
    ) -> Result<u32, String>
    where
        F: FnMut(ChatOut) + Send + 'static,
    {
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(format!("not a folder: {}", cwd.display()));
        }
        let mut cmd = command_for(&argv, cwd, path_env, account_env)?;
        let mut child = cmd.spawn().map_err(|e| format!("{}: {e}", Path::new(&argv[0]).display()))?;
        let mut stdout = child.stdout.take().ok_or("no stdout")?;
        let stderr = child.stderr.take().ok_or("no stderr")?;
        let mut pipe = child.stdin.take().ok_or("no stdin")?;
        // The writer thread owns stdin, so a write to an agent that is not reading never holds a lock.
        let (tx, queued) = mpsc::sync_channel::<Vec<u8>>(INPUT_QUEUE);
        thread::spawn(move || {
            for chunk in queued {
                if pipe.write_all(&chunk).and_then(|_| pipe.flush()).is_err() {
                    break;
                }
            }
        });
        let stdin: ChatInputQueue = Arc::new(Mutex::new(Some(tx)));
        let pid = child.id();
        let sink: ChatSink = Arc::new(Mutex::new(Box::new(sink)));
        let first = adapter.start();
        let adapter: Arc<Mutex<Box<dyn Adapter>>> = Arc::new(Mutex::new(adapter));
        let exited = Arc::new(AtomicBool::new(false));
        let child = Arc::new(Mutex::new(child));
        let tail = Arc::new(Mutex::new(String::new()));

        write_lines(&stdin, &first.write)?;
        deliver(&sink, first.events);

        let reader_done = Arc::new(AtomicBool::new(false));
        {
            // stdout: one thread reads, another merges what arrives within COALESCE_WINDOW (as PTY output is),
            // splits it on LF only (JSON strings may hold U+2028) and runs one adapter step per line.
            let (chunks, rx) = mpsc::channel::<Vec<u8>>();
            thread::spawn(move || {
                let mut buf = [0u8; 16 * 1024];
                loop {
                    match stdout.read(&mut buf) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => {
                            if chunks.send(buf[..n].to_vec()).is_err() {
                                break;
                            }
                        }
                    }
                }
            });
            let (adapter, stdin, sink, done) = (adapter.clone(), stdin.clone(), sink.clone(), reader_done.clone());
            thread::spawn(move || {
                let mut pending: Vec<u8> = Vec::new();
                let run = |lines: &mut dyn Iterator<Item = &[u8]>| {
                    let mut out = Step::default();
                    {
                        let mut a = adapter.lock().unwrap();
                        for raw in lines {
                            let line = String::from_utf8_lossy(raw);
                            let line = line.trim_end_matches(['\n', '\r']);
                            if line.trim().is_empty() {
                                continue;
                            }
                            let step = a.on_line(line);
                            out.write.extend(step.write);
                            out.events.extend(step.events);
                        }
                    }
                    let _ = write_lines(&stdin, &out.write);
                    deliver(&sink, merge_deltas(out.events));
                };
                coalesce(rx, COALESCE_BYTES, COALESCE_WINDOW, |b| {
                    pending.extend_from_slice(&b);
                    let Some(end) = pending.iter().rposition(|c| *c == b'\n') else { return };
                    let rest = pending.split_off(end + 1);
                    let whole = std::mem::replace(&mut pending, rest);
                    run(&mut whole.split(|c| *c == b'\n'));
                });
                if !pending.is_empty() {
                    run(&mut std::iter::once(&pending[..]));
                }
                done.store(true, Ordering::SeqCst);
            });
        }
        {
            let tail = tail.clone();
            thread::spawn(move || {
                let mut r = stderr;
                let mut buf = [0u8; 4096];
                while let Ok(n) = r.read(&mut buf) {
                    if n == 0 {
                        break;
                    }
                    let mut t = tail.lock().unwrap();
                    t.push_str(&String::from_utf8_lossy(&buf[..n]));
                    if t.len() > 4000 {
                        let cut = t.len() - 2000;
                        let cut = (cut..t.len()).find(|i| t.is_char_boundary(*i)).unwrap_or(t.len());
                        t.drain(..cut);
                    }
                }
            });
        }
        {
            let (child, exited, sink, adapter, done) = (child.clone(), exited.clone(), sink.clone(), adapter.clone(), reader_done.clone());
            thread::spawn(move || {
                let code = loop {
                    if let Ok(Some(st)) = child.lock().unwrap().try_wait() {
                        break st.code();
                    }
                    thread::sleep(Duration::from_millis(40));
                };
                exited.store(true, Ordering::SeqCst);
                // let the reader hand over what the program printed last
                let deadline = Instant::now() + Duration::from_millis(800);
                while !done.load(Ordering::SeqCst) && Instant::now() < deadline {
                    thread::sleep(Duration::from_millis(10));
                }
                let (mid_turn, err) = {
                    let a = adapter.lock().unwrap();
                    let raw = exit_reason(&tail.lock().unwrap());
                    (a.in_turn(), if raw.is_empty() { raw } else { a.explain(&raw) })
                };
                if let Ok(mut f) = sink.lock() {
                    if mid_turn {
                        f(ChatOut::Event(exit_turn_end(code, &err)));
                    }
                    f(ChatOut::Exit(code, err));
                }
            });
        }
        let id = self.next.fetch_add(1, Ordering::SeqCst) + 1;
        self.live.lock().unwrap().insert(id, ChatLive { stdin, adapter, sink, child, pid, exited });
        Ok(id)
    }

    /// One thing the person did in chat `id`.
    pub fn input(&self, id: u32, input: Input) -> Result<(), String> {
        let (adapter, stdin, sink) = {
            let g = self.live.lock().unwrap();
            let s = g.get(&id).ok_or("no such session")?;
            (s.adapter.clone(), s.stdin.clone(), s.sink.clone())
        };
        let step = adapter.lock().unwrap().on_input(input)?;
        write_lines(&stdin, &step.write)?;
        deliver(&sink, step.events);
        Ok(())
    }

    /// Stop the program (stdin closed, then hang-up, then a hard kill after a grace period) and forget it.
    pub fn close(&self, id: u32) {
        let live = self.live.lock().unwrap().remove(&id);
        if let Some(s) = live {
            thread::spawn(move || stop(s, Duration::from_millis(1500)));
        }
    }

    pub fn close_all(&self) {
        let all: Vec<ChatLive> = self.live.lock().unwrap().drain().map(|(_, s)| s).collect();
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

fn stop(s: ChatLive, grace: Duration) {
    // closing stdin is pi's and Codex's orderly shutdown; Claude Code's -p ends on EOF too. The writer
    // thread closes it once it has nothing left to write (a stuck write ends when the program does).
    drop(s.stdin.lock().unwrap().take());
    let deadline = Instant::now() + Duration::from_millis(300).min(grace);
    while !s.exited.load(Ordering::SeqCst) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(20));
    }
    if !s.exited.load(Ordering::SeqCst) {
        signal_group(Some(s.pid), false);
        #[cfg(not(unix))]
        {
            let _ = s.child.lock().unwrap().kill();
        }
    }
    let deadline = Instant::now() + grace;
    while !s.exited.load(Ordering::SeqCst) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(25));
    }
    if !s.exited.load(Ordering::SeqCst) {
        signal_group(Some(s.pid), true);
        let _ = s.child.lock().unwrap().kill();
    }
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    impl Input {
        /// A message with text only.
        pub fn send(text: impl Into<String>) -> Input {
            Input::Send { text: text.into(), images: vec![] }
        }
    }

    fn fixture(name: &str) -> Vec<String> {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join(name);
        std::fs::read_to_string(p).unwrap().lines().filter(|l| !l.trim().is_empty()).map(String::from).collect()
    }

    /// Feed every line, collecting events and what the adapter wrote back.
    fn run(a: &mut dyn Adapter, lines: &[String]) -> Step {
        let mut all = Step::default();
        for l in lines {
            let st = a.on_line(l);
            all.write.extend(st.write);
            all.events.extend(st.events);
        }
        all
    }

    fn names(events: &[Event]) -> Vec<String> {
        events.iter().map(|e| s(e, "event")).collect()
    }

    fn text_of(events: &[Event], name: &str) -> Vec<String> {
        events.iter().filter(|e| s(e, "event") == name).map(|e| s(e, "text")).collect()
    }

    // ---- Claude Code: fixtures recorded from a real `claude -p` stream-json run (2.1.319) -------

    #[test]
    fn claude_start_initializes_and_send_writes_a_user_message() {
        let mut c = Claude::default();
        let st = c.start();
        let init: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(init["type"], "control_request");
        assert_eq!(init["request"]["subtype"], "initialize");
        let st = c.on_input(Input::send("say hi")).unwrap();
        assert_eq!(names(&st.events), ["turn.start"]);
        let msg: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(msg["type"], "user");
        assert_eq!(msg["message"]["content"][0]["text"], "say hi");
        assert!(c.in_turn());
    }

    #[test]
    fn claude_say_hi_streams_deltas_then_one_message_then_done() {
        let mut c = Claude::default();
        c.start();
        c.on_input(Input::send("say hi")).unwrap();
        let st = run(&mut c, &fixture("claude-hi.jsonl"));
        let info = st.events.iter().find(|e| s(e, "event") == "session.info").unwrap();
        assert_eq!(s(info, "agent_session"), "eee5079a-c52e-4526-b633-f3d8cb7d6394");
        assert_eq!(text_of(&st.events, "delta").concat(), "Hi. Ready when you are.");
        assert_eq!(text_of(&st.events, "message"), ["Hi. Ready when you are."]);
        let end = st.events.last().unwrap();
        assert_eq!((s(end, "event"), s(end, "outcome")), ("turn.end".into(), "done".into()));
        assert!(!c.in_turn());
        assert!(st.write.is_empty(), "nothing to answer in a plain turn: {:?}", st.write);
    }

    #[test]
    fn claude_approval_round_trip_from_a_real_write_tool_call() {
        let mut c = Claude::new("/w/t14");
        c.start();
        c.on_input(Input::send("write note.txt")).unwrap();
        let lines = fixture("claude-approve.jsonl");
        let at = lines.iter().position(|l| l.contains("\"can_use_tool\"")).unwrap();
        let st = run(&mut c, &lines[..=at]);
        // the tool shows on the progress line before the card
        let tool = st.events.iter().find(|e| s(e, "event") == "tool.start").unwrap();
        assert_eq!(s(tool, "name"), "patch");
        // the file relative to the session folder, with its line count
        assert_eq!(s(tool, "detail"), "note.txt +1");
        let card = st.events.last().unwrap();
        assert_eq!(s(card, "event"), "approval.request");
        assert_eq!(s(card, "title"), "Allow Write to change note.txt?");
        assert_eq!(s(card, "cwd"), "/w/t14");
        assert_eq!(card["choices"], json!(["deny", "once", "session"]));
        let rid = s(card, "request_id");

        let ans = c.on_input(Input::Approve { request_id: rid.clone(), choice: "once".into() }).unwrap();
        let resp: Value = serde_json::from_str(&ans.write[0]).unwrap();
        assert_eq!(resp["type"], "control_response");
        assert_eq!(resp["response"]["request_id"], rid);
        assert_eq!(resp["response"]["response"]["behavior"], "allow");
        assert_eq!(resp["response"]["response"]["updatedInput"]["content"], "ok");
        // answered once only
        assert!(c.on_input(Input::Approve { request_id: rid, choice: "once".into() }).is_err());

        let rest = run(&mut c, &lines[at + 1..]);
        let ends: Vec<&Event> = rest.events.iter().filter(|e| s(e, "event") == "tool.end").collect();
        assert_eq!(ends.len(), 1);
        assert_eq!(ends[0]["ok"], true);
        assert_eq!(text_of(&rest.events, "message"), ["done"]);
        assert_eq!(s(rest.events.last().unwrap(), "outcome"), "done");
    }

    #[test]
    fn claude_deny_and_allow_for_session_answers() {
        let req = r#"{"type":"control_request","request_id":"r1","request":{"subtype":"can_use_tool","tool_name":"Bash","display_name":"Bash","input":{"command":"rm -rf build"},"permission_suggestions":[{"type":"addRules","rules":[{"toolName":"Bash","ruleContent":"rm -rf build"}],"behavior":"allow","destination":"session"}],"tool_use_id":"t1"}}"#;
        let mut c = Claude::default();
        let card = c.on_line(req).events.remove(0);
        assert_eq!(s(&card, "title"), "Run this command?");
        assert_eq!(s(&card, "command"), "rm -rf build");
        let deny: Value = serde_json::from_str(&c.on_input(Input::Approve { request_id: "r1".into(), choice: "deny".into() }).unwrap().write[0]).unwrap();
        assert_eq!(deny["response"]["response"]["behavior"], "deny");
        c.on_line(req);
        let sess: Value = serde_json::from_str(&c.on_input(Input::Approve { request_id: "r1".into(), choice: "session".into() }).unwrap().write[0]).unwrap();
        assert_eq!(sess["response"]["response"]["behavior"], "allow");
        assert_eq!(sess["response"]["response"]["updatedPermissions"][0]["destination"], "session");
        c.on_line(req);
        assert!(c.on_input(Input::Approve { request_id: "r1".into(), choice: "always".into() }).is_err());
    }

    #[test]
    fn claude_esc_sends_its_own_interrupt_and_the_turn_ends_interrupted() {
        let mut c = Claude::default();
        c.start();
        c.on_input(Input::send("write a long story")).unwrap();
        let st = c.on_input(Input::Interrupt).unwrap();
        let req: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(req["type"], "control_request");
        assert_eq!(req["request"]["subtype"], "interrupt");
        let rest = run(&mut c, &fixture("claude-interrupt.jsonl"));
        let end = rest.events.last().unwrap();
        assert_eq!((s(end, "event"), s(end, "outcome")), ("turn.end".into(), "interrupted".into()));
    }

    #[test]
    fn claude_refuses_unknown_control_requests_and_reads_models_from_initialize() {
        let mut c = Claude::default();
        let st = c.on_line(r#"{"type":"control_request","request_id":"h1","request":{"subtype":"hook_callback","callback_id":"x"}}"#);
        let r: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(r["response"]["subtype"], "error");
        assert!(st.events.is_empty());
        c.start();
        let st = c.on_line(r#"{"type":"control_response","response":{"subtype":"success","request_id":"omher-init-1","response":{"models":[{"value":"opus","displayName":"Opus 5.5","description":"x"},{"value":"haiku","displayName":"Haiku 5.5","description":"y"}]}}}"#);
        assert_eq!(st.events[0]["options"][1], json!({"id": "haiku", "label": "Haiku 5.5", "detail": "y"}));
        let m: Value = serde_json::from_str(&c.on_input(Input::Model { model: "haiku".into() }).unwrap().write[0]).unwrap();
        assert_eq!(m["request"], json!({"subtype": "set_model", "model": "haiku"}));
    }

    #[test]
    fn claude_ignores_subagent_text_and_ends_errors_with_the_reason() {
        let mut c = Claude::default();
        c.on_input(Input::send("x")).unwrap();
        let st = c.on_line(r#"{"type":"assistant","parent_tool_use_id":"toolu_1","message":{"id":"m","content":[{"type":"text","text":"inner"}]}}"#);
        assert!(st.events.is_empty());
        let st = c.on_line(r#"{"type":"result","subtype":"error_during_execution","is_error":true,"terminal_reason":"error","errors":["API Error: 529 overloaded"]}"#);
        assert_eq!(st.events[0], json!({"event": "turn.end", "outcome": "error", "error": "API Error: 529 overloaded"}));
    }

    // ---- Codex app-server (fixture from the protocol schema, codex-rs/app-server-protocol) --------

    #[test]
    fn codex_handshake_thread_then_turn_with_command_approval() {
        let mut x = Codex::new("/w/proj", None);
        let st = x.start();
        let init: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!((init["id"].as_u64(), s(&init, "method")), (Some(1), "initialize".to_string()));
        assert_eq!(init["params"]["clientInfo"]["name"], "omher");
        // text typed before the thread exists waits for it
        let st = x.on_input(Input::send("run the tests")).unwrap();
        assert_eq!(names(&st.events), ["turn.start"]);
        assert!(st.write.is_empty());

        let lines = fixture("codex-turn.jsonl");
        let st = run(&mut x, &lines[..2]);
        let sent: Vec<Value> = st.write.iter().map(|w| serde_json::from_str(w).unwrap()).collect();
        assert_eq!(s(&sent[0], "method"), "initialized");
        assert_eq!(sent[1]["method"], "thread/start");
        assert_eq!(sent[1]["params"]["cwd"], "/w/proj");
        assert_eq!(sent[2]["method"], "model/list");
        assert_eq!(sent[3]["method"], "turn/start");
        assert_eq!(sent[3]["params"]["threadId"], "thr_1");
        assert_eq!(sent[3]["params"]["input"][0]["text"], "run the tests");
        assert_eq!(s(&st.events[0], "agent_session"), "thr_1");
        assert_eq!(s(&st.events[0], "model"), "gpt-6.1-sol");

        let at = lines.iter().position(|l| l.contains("requestApproval")).unwrap();
        let st = run(&mut x, &lines[2..=at]);
        let tool = st.events.iter().find(|e| s(e, "event") == "tool.start").unwrap();
        assert_eq!((s(tool, "name"), s(tool, "detail")), ("terminal".into(), "pnpm test".into()));
        let card = st.events.last().unwrap();
        assert_eq!(s(card, "title"), "Run this command?");
        assert_eq!(s(card, "command"), "pnpm test");
        let ans = x.on_input(Input::Approve { request_id: s(card, "request_id"), choice: "session".into() }).unwrap();
        assert_eq!(serde_json::from_str::<Value>(&ans.write[0]).unwrap(), json!({"id": 90, "result": {"decision": "acceptForSession"}}));

        let st = run(&mut x, &lines[at + 1..]);
        assert_eq!(text_of(&st.events, "delta").concat(), "All 12 tests pass.");
        assert_eq!(text_of(&st.events, "message"), ["All 12 tests pass."]);
        assert_eq!(st.events.iter().find(|e| s(e, "event") == "tool.end").unwrap()["ok"], true);
        assert_eq!(st.events.last().unwrap(), &json!({"event": "turn.end", "outcome": "done"}));
    }

    #[test]
    fn codex_interrupt_decline_and_unknown_requests() {
        let mut x = Codex::new("/w", None);
        x.start();
        run(&mut x, &fixture("codex-turn.jsonl")[..2]);
        x.on_input(Input::send("go")).unwrap();
        x.on_line(r#"{"method":"turn/started","params":{"threadId":"thr_1","turn":{"id":"turn_9","status":"inProgress","items":[]}}}"#);
        let st = x.on_input(Input::Interrupt).unwrap();
        let req: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(req["method"], "turn/interrupt");
        assert_eq!(req["params"], json!({"threadId": "thr_1", "turnId": "turn_9"}));
        let st = x.on_line(r#"{"method":"turn/completed","params":{"threadId":"thr_1","turn":{"id":"turn_9","status":"interrupted","items":[],"error":null}}}"#);
        assert_eq!(st.events[0], json!({"event": "turn.end", "outcome": "interrupted"}));

        let st = x.on_line(r#"{"id":"77","method":"item/fileChange/requestApproval","params":{"threadId":"thr_1","turnId":"t","itemId":"i9","startedAtMs":1}}"#);
        let rid = s(&st.events[0], "request_id");
        let ans: Value = serde_json::from_str(&x.on_input(Input::Approve { request_id: rid, choice: "deny".into() }).unwrap().write[0]).unwrap();
        assert_eq!(ans, json!({"id": "77", "result": {"decision": "decline"}}));
        let st = x.on_line(r#"{"id":5,"method":"item/tool/requestUserInput","params":{}}"#);
        assert_eq!(serde_json::from_str::<Value>(&st.write[0]).unwrap(), json!({"id": 5, "result": {"answers": {}}}));
        let st = x.on_line(r#"{"id":6,"method":"item/permissions/requestApproval","params":{}}"#);
        assert_eq!(serde_json::from_str::<Value>(&st.write[0]).unwrap()["error"]["code"], -32601);
    }

    // ---- pi / oh-my-pi `--mode rpc` (fixture from pi-mono docs/rpc*.md, docs/json.md) -------------

    #[test]
    fn pi_prompt_streams_tools_and_settles() {
        let mut p = Pi::default();
        let st = p.start();
        let w: Vec<Value> = st.write.iter().map(|l| serde_json::from_str(l).unwrap()).collect();
        assert_eq!((s(&w[0], "type"), s(&w[1], "type")), ("get_state".into(), "get_available_models".into()));
        let st = p.on_input(Input::send("list the ts files")).unwrap();
        let cmd: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!((s(&cmd, "type"), s(&cmd, "message")), ("prompt".into(), "list the ts files".into()));
        assert_eq!(names(&st.events), ["turn.start"]);
        let st = run(&mut p, &fixture("pi-turn.jsonl"));
        assert_eq!(s(&st.events[0], "model"), "Claude Sonnet 4");
        assert_eq!(st.events[1]["options"][0]["id"], "anthropic/claude-sonnet-4-20250514");
        let tool = st.events.iter().find(|e| s(e, "event") == "tool.start").unwrap();
        assert_eq!((s(tool, "name"), s(tool, "detail")), ("terminal".into(), "ls src/*.ts".into()));
        assert_eq!(text_of(&st.events, "delta").concat(), "Two files: a.ts and b.ts.");
        assert_eq!(text_of(&st.events, "message"), ["Two files: a.ts and b.ts."]);
        assert_eq!(st.events.iter().filter(|e| s(e, "event") == "turn.end").count(), 1, "agent_end then agent_settled end one turn");
        assert_eq!(st.events.last().unwrap(), &json!({"event": "turn.end", "outcome": "done"}));
    }

    #[test]
    fn pi_dialogs_become_cards_and_abort_is_its_interrupt() {
        let mut p = Pi::default();
        p.on_input(Input::send("x")).unwrap();
        let st = p.on_line(r#"{"type":"extension_ui_request","id":"u1","method":"confirm","title":"Run rm -rf dist?","message":"bash: rm -rf dist"}"#);
        assert_eq!(st.events[0]["choices"], json!(["deny", "once"]));
        let ans: Value = serde_json::from_str(&p.on_input(Input::Approve { request_id: "u1".into(), choice: "deny".into() }).unwrap().write[0]).unwrap();
        assert_eq!(ans, json!({"type": "extension_ui_response", "id": "u1", "confirmed": false}));
        let st = p.on_line(r#"{"type":"extension_ui_request","id":"u2","method":"select","title":"Which branch?","options":["main","dev"]}"#);
        assert_eq!(s(&st.events[0], "event"), "clarify.request");
        let ans: Value = serde_json::from_str(&p.on_input(Input::Clarify { request_id: "u2".into(), answer: "dev".into() }).unwrap().write[0]).unwrap();
        assert_eq!(ans, json!({"type": "extension_ui_response", "id": "u2", "value": "dev"}));
        let ab: Value = serde_json::from_str(&p.on_input(Input::Interrupt).unwrap().write[0]).unwrap();
        assert_eq!(s(&ab, "type"), "abort");
        p.on_line(r#"{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"aborted"}}"#);
        let st = p.on_line(r#"{"type":"agent_end"}"#);
        assert_eq!(st.events[0], json!({"event": "turn.end", "outcome": "interrupted"}));
        // oh-my-pi's prompt_result for a run that already ended draws nothing; for a prompt no agent ran (a
        // command it handled itself) it ends the turn
        assert!(p.on_line(r#"{"type":"prompt_result","id":"omher-3","agentInvoked":true}"#).events.is_empty());
        p.on_input(Input::send("y")).unwrap();
        let st = p.on_line(r#"{"type":"prompt_result","id":"omher-9","agentInvoked":false}"#);
        assert_eq!(s(&st.events[0], "outcome"), "done");
        let m: Value = serde_json::from_str(&p.on_input(Input::Model { model: "anthropic/claude-x".into() }).unwrap().write[0]).unwrap();
        assert_eq!((s(&m, "provider"), s(&m, "modelId")), ("anthropic".into(), "claude-x".into()));
    }

    #[test]
    fn only_chat_agents_have_adapters() {
        for id in ["claude", "codex", "omo", "pi", "omp"] {
            assert!(adapter_for(id, "/w", None).is_some(), "{id}");
        }
        for id in ["omh", "grok", "dsh", "sh", ""] {
            assert!(adapter_for(id, "/w", None).is_none(), "{id}");
        }
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir();
        for bad in ["omh", "grok", "dsh", "/bin/sh", "claude -p"] {
            assert!(c.start_agent(bad, &tmp, None, &[], |_| {}).is_err(), "{bad}");
        }
        assert!(c.start_agent("claude", &tmp, Some("--dangerously-skip-permissions"), &[], |_| {}).is_err());
        assert_eq!(c.count(), 0);
    }

    // ---- the live process: a stand-in agent replays the real claude stream ----------------------

    #[cfg(unix)]
    fn collect() -> (Arc<Mutex<Vec<ChatOut>>>, impl FnMut(ChatOut) + Send + 'static) {
        let out = Arc::new(Mutex::new(Vec::new()));
        let o = out.clone();
        (out, move |x| o.lock().unwrap().push(x))
    }

    #[cfg(unix)]
    fn wait_for(cond: impl Fn() -> bool, secs: u64) -> bool {
        let deadline = Instant::now() + Duration::from_secs(secs);
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
    fn a_stand_in_agent_on_pipes_reaches_the_ui_and_close_kills_it() {
        let c = ChatSessions::default();
        let fx = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("claude-hi.jsonl");
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let mark = tmp.join(format!("omher-chat-stdin-{}", std::process::id()));
        // reads our initialize line (proves stdin works), prints the recorded stream, then hangs
        let script = format!("read l; printf '%s\\n' \"$l\" > '{}'; cat '{}'; trap '' HUP; while :; do sleep 1; done", mark.display(), fx.display());
        let (out, sink) = collect();
        let mut adapter: Box<dyn Adapter> = Box::new(Claude::default());
        adapter.on_input(Input::send("say hi")).unwrap();
        let id = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], adapter, sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end")), 10));
        let first = std::fs::read_to_string(&mark).unwrap();
        assert!(first.contains("\"initialize\""), "{first}");
        let msgs: Vec<String> = out.lock().unwrap().iter().filter_map(|o| match o { ChatOut::Event(e) if s(e, "event") == "message" => Some(s(e, "text")), _ => None }).collect();
        assert_eq!(msgs, ["Hi. Ready when you are."]);
        // input goes through the adapter to the program
        c.input(id, Input::Interrupt).unwrap();
        assert!(c.input(id, Input::Approve { request_id: "nope".into(), choice: "once".into() }).is_err());
        c.close(id);
        assert_eq!(c.count(), 0);
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10), "close did not stop a HUP-ignoring agent");
        assert!(c.input(id, Input::Interrupt).is_err());
        let _ = std::fs::remove_file(mark);
    }

    #[cfg(unix)]
    #[test]
    fn an_agent_that_dies_mid_turn_ends_the_turn_with_its_stderr() {
        let c = ChatSessions::default();
        let (out, sink) = collect();
        let mut adapter: Box<dyn Adapter> = Box::new(Claude::default());
        adapter.on_input(Input::send("x")).unwrap();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), "echo 'Error: not logged in' >&2; exit 2".into()], &tmp, None, &[], adapter, sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let got = out.lock().unwrap().clone();
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end" && s(e, "error").contains("not logged in"))), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(2), e) if e.contains("not logged in"))), "{got:?}");
    }

    #[test]
    fn a_clean_exit_mid_turn_ends_the_turn_without_an_error() {
        assert_eq!(exit_turn_end(Some(0), ""), json!({"event": "turn.end", "outcome": "ended"}));
        assert_eq!(exit_turn_end(Some(0), "boom"), json!({"event": "turn.end", "outcome": "error", "error": "boom"}));
        assert_eq!(exit_turn_end(Some(1), ""), json!({"event": "turn.end", "outcome": "error", "error": "the agent stopped"}));
        assert_eq!(exit_turn_end(None, ""), json!({"event": "turn.end", "outcome": "error", "error": "the agent stopped"}));
    }

    #[cfg(unix)]
    #[test]
    fn an_agent_that_exits_cleanly_mid_turn_ends_the_turn_and_reports_code_0() {
        let c = ChatSessions::default();
        let (out, sink) = collect();
        let mut adapter: Box<dyn Adapter> = Box::new(Claude::default());
        adapter.on_input(Input::send("x")).unwrap();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), "exit 0".into()], &tmp, None, &[], adapter, sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let got = out.lock().unwrap().clone();
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end" && s(e, "outcome") == "ended")), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(0), e) if e.is_empty())), "{got:?}");
    }

    /// A temp home whose `active.json` picks `active` for claude, with that account's folder made.
    fn home_with_claude(name: &str, active: &str) -> std::path::PathBuf {
        let home = std::env::temp_dir().join(format!("omher-chat-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        let root = home.join(".omher").join("accounts");
        std::fs::create_dir_all(root.join("claude").join("work")).unwrap();
        std::fs::write(root.join("active.json"), format!(r#"{{"claude":"{active}"}}"#)).unwrap();
        home
    }

    #[test]
    fn a_claude_chat_carries_the_stacked_account_home_and_this_computer_carries_none() {
        let cwd = std::env::temp_dir();
        // the argv chat_start builds for claude: the program, then the allow-list's chat arguments
        let argv: Vec<OsString> = std::iter::once(OsString::from("/x/claude")).chain(chat_args("claude").unwrap().iter().map(OsString::from)).collect();
        let envs = |cmd: &Command| -> Vec<(String, String)> {
            cmd.get_envs().filter_map(|(k, v)| Some((k.to_string_lossy().into_owned(), v?.to_string_lossy().into_owned()))).collect()
        };
        let base = envs(&command_for(&argv, &cwd, None, &[]).unwrap());

        let home = home_with_claude("stacked", "work");
        let cmd = command_for(&argv, &cwd, None, &crate::accounts::session_env(&home, "claude")).unwrap();
        let work = home.join(".omher").join("accounts").join("claude").join("work");
        assert_eq!(cmd.get_args().collect::<Vec<_>>(), argv[1..].iter().map(|a| a.as_os_str()).collect::<Vec<_>>(), "the account changes no argument");
        // the chosen account's home is the only thing added
        let added: Vec<_> = envs(&cmd).into_iter().filter(|p| !base.contains(p)).collect();
        assert_eq!(added, vec![("CLAUDE_CONFIG_DIR".to_string(), work.to_string_lossy().into_owned())]);

        let mine = home_with_claude("this-computer", "default");
        let cmd = command_for(&argv, &cwd, None, &crate::accounts::session_env(&mine, "claude")).unwrap();
        assert_eq!(envs(&cmd), base);
        assert!(!envs(&cmd).iter().any(|(k, _)| k == "CLAUDE_CONFIG_DIR"));
        let _ = (std::fs::remove_dir_all(home), std::fs::remove_dir_all(mine));
    }

    #[cfg(unix)]
    #[test]
    fn the_account_home_reaches_the_chat_program() {
        let home = home_with_claude("pipes", "work");
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let mark = tmp.join(format!("omher-chat-env-{}", std::process::id()));
        let script = format!("echo \"cfg=${{CLAUDE_CONFIG_DIR-unset}}\" > '{}'", mark.display());
        let (out, sink) = collect();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &crate::accounts::session_env(&home, "claude"), Box::new(Pi::default()), sink)
            .unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let work = home.join(".omher").join("accounts").join("claude").join("work");
        assert_eq!(std::fs::read_to_string(&mark).unwrap().trim(), format!("cfg={}", work.display()));
        let _ = (std::fs::remove_file(mark), std::fs::remove_dir_all(home));
    }

    #[cfg(unix)]
    #[test]
    fn close_all_stops_every_chat() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (out, sink) = collect();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), "trap '' HUP TERM; while :; do sleep 1; done".into()], &tmp, None, &[], Box::new(Pi::default()), sink).unwrap();
        c.close_all();
        assert_eq!(c.count(), 0);
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
    }

    #[test]
    fn adjacent_deltas_merge_and_nothing_else_does() {
        let d = |t: &str| ev("delta", json!({"text": t}));
        let got = merge_deltas(vec![d("a"), d("b"), ev("thinking", json!({})), d("c"), d("d"), ev("message", json!({"id": "m", "text": "abcd"}))]);
        assert_eq!(names(&got), ["delta", "thinking", "delta", "message"]);
        assert_eq!(text_of(&got, "delta"), ["ab", "cd"]);
    }

    #[cfg(unix)]
    #[test]
    fn a_big_send_to_an_agent_that_never_reads_blocks_nothing() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (stuck_out, stuck_sink) = collect();
        let stuck = c.spawn(vec!["/bin/sh".into(), "-c".into(), "sleep 60".into()], &tmp, None, &[], Box::new(Pi::default()), stuck_sink).unwrap();
        let (_, other_sink) = collect();
        let mark = tmp.join(format!("omher-chat-other-{}", std::process::id()));
        let script = format!("while read l; do printf '%s\\n' \"$l\" >> '{}'; done", mark.display());
        let other = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], Box::new(Pi::default()), other_sink).unwrap();
        // 1 MB of prompts: the pipe takes about 64 KB, the rest must not hold anything up
        let started = Instant::now();
        for _ in 0..16 {
            c.input(stuck, Input::send("x".repeat(64 * 1024))).unwrap();
        }
        assert!(started.elapsed() < Duration::from_millis(500), "input blocked: {:?}", started.elapsed());
        // other chats keep working while that one is stuck
        c.input(other, Input::send("pong")).unwrap();
        assert!(wait_for(|| std::fs::read_to_string(&mark).is_ok_and(|t| t.contains("pong")), 10), "other chat stalled");
        let t = Instant::now();
        c.close_all();
        assert!(t.elapsed() < Duration::from_secs(3), "close_all took {:?}", t.elapsed());
        assert_eq!(c.count(), 0);
        assert!(wait_for(|| stuck_out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10), "the stuck agent survived close_all");
        let _ = std::fs::remove_file(mark);
    }

    #[cfg(unix)]
    #[test]
    fn a_fast_token_stream_arrives_in_few_messages_and_split_lines_survive() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (out, sink) = collect();
        let line = r#"{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"x"}}"#;
        // 2000 one-token lines, then one line written in two halves 100 ms apart, then a last line with no LF
        let script = format!(
            "i=0; while [ $i -lt 2000 ]; do printf '%s\\n' '{line}'; i=$((i+1)); done; printf '%s' '{{\"type\":\"message_update\",'; sleep 0.1; printf '%s\\n' '\"assistantMessageEvent\":{{\"type\":\"text_delta\",\"delta\":\"ab\"}}}}'; printf '%s' '{{\"type\":\"message_update\",\"assistantMessageEvent\":{{\"type\":\"text_delta\",\"delta\":\"z\"}}}}'"
        );
        c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], Box::new(Pi::default()), sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 20));
        let got = out.lock().unwrap();
        let deltas: Vec<String> = got.iter().filter_map(|o| match o { ChatOut::Event(e) if s(e, "event") == "delta" => Some(s(e, "text")), _ => None }).collect();
        let text = deltas.concat();
        assert_eq!(text, format!("{}abz", "x".repeat(2000)));
        // one event per line would be 2002
        assert!(deltas.len() < 200, "{} delta events", deltas.len());
    }

    /// The real OmO through `start_agent` (`omo --mode rpc`): "hi" gets an answer, then a second process started
    /// with the session id it reported (`--session`) still knows the first turn. Needs omo signed in.
    #[test]
    #[ignore]
    fn real_omo_chat_says_hi_and_resumes() {
        let dir = std::env::temp_dir().join(format!("omher-real-omo-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let dir = dir.canonicalize().unwrap();
        let turn = |resume: Option<&str>, text: &str| -> (String, Vec<String>) {
            let c = ChatSessions::default();
            let out = Arc::new(Mutex::new(Vec::new()));
            let o = out.clone();
            let id = c.start_agent("omo", &dir, resume, &[], move |x| o.lock().unwrap().push(x)).unwrap();
            c.input(id, Input::send(text)).unwrap();
            let deadline = Instant::now() + Duration::from_secs(150);
            while Instant::now() < deadline && !out.lock().unwrap().iter().any(|x| matches!(x, ChatOut::Event(e) if s(e, "event") == "turn.end")) {
                thread::sleep(Duration::from_millis(100));
            }
            let got = out.lock().unwrap().clone();
            c.close(id);
            thread::sleep(Duration::from_millis(500));
            let session = got.iter().find_map(|x| match x { ChatOut::Event(e) if s(e, "event") == "session.info" && !s(e, "agent_session").is_empty() => Some(s(e, "agent_session")), _ => None }).unwrap_or_default();
            let msgs: Vec<String> = got.iter().filter_map(|x| match x { ChatOut::Event(e) if s(e, "event") == "message" => Some(s(e, "text")), _ => None }).collect();
            println!("omo session {session} (resume {resume:?}): {msgs:?}");
            (session, msgs)
        };
        let (session, first) = turn(None, "hi. reply with just the word pineapple");
        assert!(is_uuid(&session), "{session:?}");
        assert!(first.iter().any(|m| m.to_lowercase().contains("pineapple")), "{first:?}");
        let (again, second) = turn(Some(&session), "which fruit word did you just reply with? one word");
        assert_eq!(again, session);
        assert!(second.iter().any(|m| m.to_lowercase().contains("pineapple")), "{second:?}");
        let _ = std::fs::remove_dir_all(dir);
    }

    /// The real attach check: a picture with a word in it and a small text file, saved and resolved exactly as a
    /// SESSIONS chat does (`session_files::save`, `Input::resolve`, the adapter's own image input; the text file
    /// named by its saved path), sent to the real agent in a temp folder. Approvals are answered `once`. Needs the
    /// agent installed and signed in: `OMHER_REAL_AGENT=codex cargo test real_agent_reads_attached_files --
    /// --ignored --nocapture` (claude, codex or omo; default claude).
    #[test]
    #[ignore]
    fn real_agent_reads_attached_files() {
        let agent = std::env::var("OMHER_REAL_AGENT").unwrap_or_else(|_| "claude".into());
        let base = std::env::temp_dir().join(format!("omher-real-attach-{agent}-{}", std::process::id()));
        let (home, dir) = (base.join("home"), base.join("proj"));
        std::fs::create_dir_all(&home).unwrap();
        std::fs::create_dir_all(&dir).unwrap();
        let (home, dir) = (home.canonicalize().unwrap(), dir.canonicalize().unwrap());
        let png = std::fs::read(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/real/word.png")).unwrap();
        let pic = session_files::save(&home, "s1", "word.png", &png).unwrap();
        let txt = session_files::save(&home, "s1", "notes.txt", b"alpha line\nthe second line is cobalt-42\ngamma line\n").unwrap();
        // what the UI sends (attach.ts wireText): the typed text, then the non-picture file by its saved path
        let text = format!(
            "1) What word is written in the attached picture? 2) What is the second line of the attached text file? Answer as: picture=<word>; line2=<line>\n\nAttached file (a copy omher saved; open it with your tools):\n- {}",
            txt.display()
        );
        let mut input = Input::Send { text, images: vec![Picture::from(pic.to_string_lossy().into_owned())] };
        input.resolve(&home).unwrap();
        let c = Arc::new(ChatSessions::default());
        let out = Arc::new(Mutex::new(Vec::<ChatOut>::new()));
        let (o, c2, me) = (out.clone(), c.clone(), Arc::new(Mutex::new(0u32)));
        let me2 = me.clone();
        let id = c
            .start_agent(&agent, &dir, None, &[], move |x| {
                if let ChatOut::Event(e) = &x {
                    if s(e, "event") == "approval.request" {
                        println!("approval {} {}", s(e, "title"), s(e, "command"));
                        let (c3, rid, id) = (c2.clone(), s(e, "request_id"), *me2.lock().unwrap());
                        thread::spawn(move || {
                            let _ = c3.input(id, Input::Approve { request_id: rid, choice: "once".into() });
                        });
                    }
                }
                o.lock().unwrap().push(x);
            })
            .unwrap();
        *me.lock().unwrap() = id;
        c.input(id, input).unwrap();
        let deadline = Instant::now() + Duration::from_secs(240);
        while Instant::now() < deadline && !out.lock().unwrap().iter().any(|x| matches!(x, ChatOut::Event(e) if s(e, "event") == "turn.end")) {
            thread::sleep(Duration::from_millis(100));
        }
        let got = out.lock().unwrap().clone();
        let msgs: Vec<String> = got.iter().filter_map(|x| match x { ChatOut::Event(e) if s(e, "event") == "message" => Some(s(e, "text")), _ => None }).collect();
        println!("{agent} answered: {msgs:?}");
        c.close(id);
        thread::sleep(Duration::from_millis(500));
        let all = msgs.join(" ").to_lowercase();
        let _ = std::fs::remove_dir_all(&base);
        assert!(all.contains("marigold") && all.contains("cobalt-42"), "{got:?}");
    }

    /// The real check: Claude Code in its chat mode in a temp folder, "reply with the word ok", through the
    /// same allow-list, adapter and pipes a session uses. Needs claude installed and signed in, and spends a
    /// tiny turn: `cargo test real_claude_chat_replies_ok -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_claude_chat_replies_ok() {
        let c = ChatSessions::default();
        let dir = std::env::temp_dir().join(format!("omher-real-chat-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let out = Arc::new(Mutex::new(Vec::new()));
        let o = out.clone();
        let id = c
            .start_agent("claude", &dir.canonicalize().unwrap(), None, &[], move |x| {
                if let ChatOut::Event(e) = &x {
                    if s(e, "event") != "session.models" {
                        println!("event {e}");
                    }
                } else {
                    println!("{x:?}");
                }
                o.lock().unwrap().push(x);
            })
            .unwrap();
        c.input(id, Input::send("reply with the word ok")).unwrap();
        let deadline = Instant::now() + Duration::from_secs(120);
        while Instant::now() < deadline && !out.lock().unwrap().iter().any(|x| matches!(x, ChatOut::Event(e) if s(e, "event") == "turn.end")) {
            thread::sleep(Duration::from_millis(100));
        }
        let got = out.lock().unwrap().clone();
        let msg: Vec<String> = got.iter().filter_map(|x| match x { ChatOut::Event(e) if s(e, "event") == "message" => Some(s(e, "text")), _ => None }).collect();
        println!("bubble: {msg:?}");
        assert!(msg.iter().any(|m| m.to_lowercase().contains("ok")), "{got:?}");
        c.close(id);
        thread::sleep(Duration::from_millis(500));
        let _ = std::fs::remove_dir_all(dir);
    }

    // ---- real streams: every case recorded from the CLIs themselves (tests/fixtures/real/) ---------------
    //
    // Claude Code 2.1.322 and Codex 0.167.0 signed in, in a throwaway folder; pi 0.73.1 and oh-my-pi 18.18.6 with
    // a scripted local model (no login on this machine), so their own RPC framing, tool events and dialogs are
    // real. Paths are rewritten to /w/proj. Each test feeds the agent's stdout lines and checks the events the
    // chat draws, plus what the adapter writes back for the person's answers.

    fn real(name: &str) -> Vec<String> {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("real").join(name);
        std::fs::read_to_string(p).unwrap().lines().filter(|l| !l.trim().is_empty()).map(String::from).collect()
    }

    /// Feed `files`; answer every approval card with the next of `answers` (then "once") and every question with
    /// its first choice. Returns all events and every line written back.
    fn replay(a: &mut dyn Adapter, files: &[&str], answers: &[&str]) -> Step {
        let mut all = Step::default();
        let mut k = 0;
        for f in files {
            for l in real(f) {
                let st = a.on_line(&l);
                all.write.extend(st.write);
                for e in st.events {
                    let name = s(&e, "event");
                    all.events.push(e.clone());
                    if name == "approval.request" {
                        let choice = answers.get(k).copied().unwrap_or("once");
                        k += 1;
                        let w = a.on_input(Input::Approve { request_id: s(&e, "request_id"), choice: choice.into() }).unwrap();
                        all.write.extend(w.write);
                        all.events.extend(w.events);
                    }
                }
            }
        }
        all
    }

    fn of<'a>(events: &'a [Event], name: &str) -> Vec<&'a Event> {
        events.iter().filter(|e| s(e, "event") == name).collect()
    }

    fn ends(events: &[Event]) -> Vec<(String, String)> {
        of(events, "turn.end").iter().map(|e| (s(e, "outcome"), s(e, "error"))).collect()
    }

    fn tools(events: &[Event]) -> Vec<(String, String)> {
        of(events, "tool.start").iter().map(|e| (s(e, "name"), s(e, "detail"))).collect()
    }

    fn written(st: &Step) -> Vec<Value> {
        st.write.iter().map(|w| serde_json::from_str(w).unwrap()).collect()
    }

    fn claude_up() -> Claude {
        let mut c = Claude::new("/w/proj");
        c.start();
        run(&mut c, &real("claude-init.jsonl"));
        c
    }

    fn claude_up_raw() -> Claude {
        let mut c = Claude::new("/w/proj");
        c.start();
        c
    }

    fn codex_up() -> Codex {
        let mut x = Codex::new("/w/proj", None);
        x.start();
        run(&mut x, &real("codex-init.jsonl"));
        x
    }

    fn pi_up(label: &str, init: &[&str]) -> Pi {
        let mut p = Pi::new("/w/proj", label);
        p.start();
        for f in init {
            run(&mut p, &real(f));
        }
        p
    }

    // -- Claude Code --

    #[test]
    fn real_claude_init_names_models_by_their_label_and_session() {
        let mut c = Claude::new("/w/proj");
        c.start();
        let st = run(&mut c, &real("claude-init.jsonl"));
        let models = &of(&st.events, "session.models")[0]["options"];
        assert!(models.as_array().unwrap().iter().any(|m| m["id"] == "haiku"), "{models}");
        // the init line names a model id; the header shows its label
        let st = run(&mut c, &real("claude-1-plain.jsonl")[..1]);
        let info = of(&st.events, "session.info")[0];
        assert_eq!(s(info, "agent_session"), "cc1528d7-7f0b-4bc2-b2fc-ec1e178e4f57");
        assert_eq!(s(info, "model"), "Fable 5.2");
        assert_eq!(s(info, "approval"), "default");
    }

    #[test]
    fn real_claude_1_plain_answer() {
        let mut c = claude_up();
        c.on_input(Input::send("2+2")).unwrap();
        let st = replay(&mut c, &["claude-1-plain.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["2+2 is 4."]);
        assert!(tools(&st.events).is_empty());
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        assert!(!c.in_turn());
    }

    #[test]
    fn real_claude_2_bash_deny_once_session() {
        let mut c = claude_up();
        c.on_input(Input::send("mkdir")).unwrap();
        let st = replay(&mut c, &["claude-2-approvals.jsonl"], &["deny", "once", "session"]);
        // the row shows the command itself, whatever Claude Code calls the tool (Bash)
        assert_eq!(tools(&st.events), [("terminal", "mkdir -p d1"), ("terminal", "mkdir -p d2"), ("terminal", "mkdir -p d3"), ("terminal", "mkdir -p d4")].map(|(a, b)| (a.to_string(), b.to_string())));
        let cards = of(&st.events, "approval.request");
        assert_eq!(cards.len(), 3, "allow for session covers the 4th mkdir? no: Claude Code ran d4 under the session rule");
        for (card, cmd) in cards.iter().zip(["mkdir -p d1", "mkdir -p d2", "mkdir -p d3"]) {
            assert_eq!((s(card, "title"), s(card, "command"), s(card, "cwd")), ("Run this command?".into(), cmd.into(), "/w/proj".into()));
            assert_eq!(card["choices"], json!(["deny", "once", "session"]));
        }
        let w = written(&st);
        assert_eq!(w[0]["response"]["response"]["behavior"], "deny");
        assert_eq!(w[1]["response"]["response"]["behavior"], "allow");
        assert!(w[1]["response"]["response"].get("updatedPermissions").is_none());
        // "for session" keeps only the command rule, for this session: never the project's settings file, never
        // a switch to acceptEdits
        let perms = &w[2]["response"]["response"]["updatedPermissions"];
        assert_eq!(perms.as_array().unwrap().len(), 1, "{perms}");
        assert_eq!(perms[0]["type"], "addRules");
        assert_eq!(perms[0]["destination"], "session");
        assert_eq!(perms[0]["rules"][0], json!({"toolName": "Bash", "ruleContent": "mkdir -p d3"}));
        // the denied call ends red, the others green
        let oks: Vec<bool> = of(&st.events, "tool.end").iter().map(|e| e["ok"].as_bool().unwrap()).collect();
        assert_eq!(oks, [false, true, true, true]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_claude_3_write_and_edit_show_the_file_and_diff_size() {
        let mut c = claude_up();
        c.on_input(Input::send("notes")).unwrap();
        let st = replay(&mut c, &["claude-3-edit.jsonl"], &[]);
        assert_eq!(
            tools(&st.events),
            [("patch", "notes.txt +1"), ("read_file", "/w/proj/README.md"), ("patch", "README.md +1 -1")].map(|(a, b)| (a.to_string(), b.to_string()))
        );
        assert!(of(&st.events, "approval.request").is_empty(), "acceptEdits (set by the earlier session answer) asks nothing");
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_claude_4_stop_mid_command_withdraws_the_card_and_ends_interrupted() {
        let mut c = claude_up();
        let lines = real("claude-4-stop.jsonl");
        // the recording first finishes the resume turn, then the person asks for a slow command
        let second = lines.iter().rposition(|l| l.contains("\"subtype\":\"init\"")).unwrap();
        c.on_input(Input::send("which file")).unwrap();
        run(&mut c, &lines[..second]);
        c.on_input(Input::send("sleep")).unwrap();
        let st = run(&mut c, &lines[second..]);
        let card = of(&st.events, "approval.request")[0].clone();
        assert!(s(&card, "command").starts_with("python3 -c"), "{card}");
        // Stop while the card is open: Claude Code withdraws it (control_cancel_request), the card closes
        let stop = written(&c.on_input(Input::Interrupt).unwrap())[0].clone();
        assert_eq!(stop["request"]["subtype"], "interrupt");
        let rest = run(&mut c, &real("claude-4-stopped.jsonl"));
        assert_eq!(of(&rest.events, "prompt.expired")[0]["request_id"], card["request_id"]);
        assert_eq!(ends(&rest.events), [("interrupted".into(), "".into())]);
        assert!(!c.in_turn());
        // the next message starts a new turn
        assert_eq!(names(&c.on_input(Input::send("again")).unwrap().events), ["turn.start"]);
    }

    #[test]
    fn real_claude_4_a_background_task_finishing_does_not_end_the_next_turn() {
        // Claude Code ran `sleep 25` in the background and answered; while the next turn waited on a question,
        // the task finished and Claude Code started (and ended) a turn of its own.
        let mut c = claude_up();
        c.on_input(Input::send("sleep")).unwrap();
        let st = replay(&mut c, &["claude-4-background.jsonl"], &[]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        assert!(tools(&st.events).iter().any(|t| t.1 == "sleep 25; echo finished"));
        // a result Claude Code started by itself while the person's turn runs leaves that turn running
        c.on_input(Input::send("next")).unwrap();
        let st = run(&mut c, &[r#"{"type":"result","subtype":"success","is_error":false,"terminal_reason":"completed","origin":{"kind":"task-notification"}}"#.into()]);
        assert!(st.events.is_empty() && c.in_turn(), "{:?}", st.events);
        // and on its own it shows as a turn that starts and ends
        let mut idle = claude_up();
        let st = run(&mut idle, &[
            r#"{"type":"assistant","parent_tool_use_id":null,"message":{"id":"m","content":[{"type":"text","text":"The task finished."}]}}"#.into(),
            r#"{"type":"result","subtype":"success","is_error":false,"terminal_reason":"completed","origin":{"kind":"task-notification"}}"#.into(),
        ]);
        assert_eq!(names(&st.events), ["turn.start", "message", "turn.end"]);
    }

    #[test]
    fn real_claude_5_ask_user_question_becomes_a_question_card() {
        let mut c = claude_up();
        c.on_input(Input::send("ask")).unwrap();
        let lines = real("claude-5-question.jsonl");
        let at = lines.iter().position(|l| l.contains("\"can_use_tool\"")).unwrap();
        let st = run(&mut c, &lines[..=at]);
        assert!(of(&st.events, "approval.request").is_empty(), "a question is not an approval");
        assert!(tools(&st.events).is_empty(), "the card stands for the tool call");
        let q = of(&st.events, "clarify.request")[0].clone();
        assert_eq!(s(&q, "question"), "Which greeting should go in greet.txt?");
        assert_eq!(q["choices"], json!(["hello", "hi"]));
        // the answer goes back as the tool's input with `answers`, keyed by the question text
        let w = written(&c.on_input(Input::Clarify { request_id: s(&q, "request_id"), answer: json!("hi") }).unwrap());
        assert_eq!(w[0]["response"]["response"]["behavior"], "allow");
        assert_eq!(w[0]["response"]["response"]["updatedInput"]["answers"], json!({"Which greeting should go in greet.txt?": "hi"}));
        assert_eq!(w[0]["response"]["response"]["updatedInput"]["questions"][0]["header"], "Greeting");
        let rest = run(&mut c, &lines[at + 1..]);
        assert_eq!(text_of(&rest.events, "message"), ["hello"]);
        assert_eq!(ends(&rest.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_claude_6_bad_command_is_a_calm_failed_step_not_a_failed_turn() {
        let mut c = claude_up();
        c.on_input(Input::send("bad")).unwrap();
        let st = replay(&mut c, &["claude-6-error.jsonl"], &["once"]);
        assert_eq!(s(of(&st.events, "approval.request")[0], "command"), "definitely-not-a-command-xyz --flag; echo \"exit=$?\"");
        assert_eq!(text_of(&st.events, "message"), ["exit code 127 (command not found)."]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_claude_7_model_switch_shows_the_label() {
        let mut c = claude_up();
        let w = written(&c.on_input(Input::Model { model: "haiku".into() }).unwrap());
        assert_eq!(w[0]["request"], json!({"subtype": "set_model", "model": "haiku"}));
        let st = run(&mut c, &real("claude-7-model.jsonl").iter().map(|l| l.replace("omher-model-2", s(&w[0], "request_id").as_str())).collect::<Vec<_>>());
        assert_eq!(s(of(&st.events, "session.info")[0], "model"), "Haiku 5.5");
        // the picker keeps Claude Code's own names
        assert!(of(&run(&mut claude_up_raw(), &real("claude-init.jsonl")).events, "session.models")[0]["options"].as_array().unwrap().iter().any(|m| m["label"] == "Default (recommended)"));
        assert!(st.events.iter().all(|e| s(e, "event") != "message"), "the local-command echo is not a bubble");
    }

    #[test]
    fn real_claude_8_resume_reports_the_same_session() {
        let mut c = claude_up();
        c.on_input(Input::send("which file")).unwrap();
        // on resume Claude Code reports the same session and an empty result of a background task from before:
        // the person's turn keeps running until its own result
        let st = replay(&mut c, &["claude-8-resume.jsonl"], &[]);
        assert_eq!(s(of(&st.events, "session.info")[0], "agent_session"), "cc1528d7-7f0b-4bc2-b2fc-ec1e178e4f57");
        assert!(ends(&st.events).is_empty() && c.in_turn());
        let lines = real("claude-4-stop.jsonl");
        let second = lines.iter().rposition(|l| l.contains("\"subtype\":\"init\"")).unwrap();
        let st = run(&mut c, &lines[..second]);
        assert!(text_of(&st.events, "message")[0].contains("notes.txt"), "it remembers the earlier conversation");
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_claude_10_close_mid_command_has_no_turn_end_from_the_agent() {
        // the stream stops mid-command (omher closed stdin); the exit watcher ends the turn, not the adapter
        let mut c = claude_up();
        c.on_input(Input::send("sleep")).unwrap();
        let st = replay(&mut c, &["claude-10-close.jsonl"], &["once"]);
        assert!(ends(&st.events).is_empty());
        assert!(c.in_turn());
    }

    #[test]
    fn real_claude_signed_out_says_how_to_sign_in() {
        let mut c = claude_up();
        c.on_input(Input::send("hi")).unwrap();
        let st = replay(&mut c, &["claude-signed-out.jsonl"], &[]);
        assert!(text_of(&st.events, "message").is_empty(), "\"Not logged in\" is not an answer bubble");
        let e = ends(&st.events);
        assert_eq!(e[0].0, "error");
        assert!(e[0].1.contains("not signed in") && e[0].1.contains("Accounts"), "{e:?}");
    }

    // -- Codex --

    #[test]
    fn real_codex_init_reads_thread_model_label_and_policy() {
        let mut x = Codex::new("/w/proj", None);
        x.start();
        let st = run(&mut x, &real("codex-init.jsonl"));
        let w = written(&st);
        assert_eq!(s(&w[0], "method"), "initialized");
        assert_eq!(w[1]["method"], "thread/start");
        let infos = of(&st.events, "session.info");
        assert_eq!(s(infos[0], "agent_session"), "01a1c3b9-4b7f-7542-900c-c5f4dc80eefa");
        assert_eq!(s(infos[0], "approval"), "untrusted");
        assert_eq!(s(infos.last().unwrap(), "model"), "GPT-6.1-Sol", "the label once model/list arrives");
    }

    #[test]
    fn real_codex_1_plain_answer() {
        let mut x = codex_up();
        x.on_input(Input::send("2+2")).unwrap();
        let st = replay(&mut x, &["codex-1-plain.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["2 + 2 = 4."]);
        assert_eq!(text_of(&st.events, "delta").concat(), "2 + 2 = 4.");
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_codex_2_command_shows_unwrapped_deny_once_session() {
        let mut x = codex_up();
        x.on_input(Input::send("mkdir")).unwrap();
        let st = replay(&mut x, &["codex-2-approvals.jsonl"], &["deny", "once", "session", "once"]);
        // Codex reports `/bin/zsh -lc 'mkdir -p d1'`; the row and the card show the command
        assert_eq!(tools(&st.events), [("terminal", "mkdir -p d1"), ("terminal", "mkdir -p d2"), ("terminal", "mkdir -p d3"), ("terminal", "mkdir -p d4")].map(|(a, b)| (a.to_string(), b.to_string())));
        let cards = of(&st.events, "approval.request");
        assert_eq!(cards.iter().map(|c| s(c, "command")).collect::<Vec<_>>(), ["mkdir -p d1", "mkdir -p d2", "mkdir -p d3", "mkdir -p d4"]);
        assert_eq!(s(cards[0], "cwd"), "/w/proj");
        let decisions: Vec<String> = written(&st).iter().map(|w| s(&w["result"], "decision")).collect();
        assert_eq!(decisions, ["decline", "accept", "acceptForSession", "accept"]);
        let oks: Vec<bool> = of(&st.events, "tool.end").iter().map(|e| e["ok"].as_bool().unwrap()).collect();
        assert_eq!(oks, [false, true, true, true]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_codex_3_file_change_card_and_diff_summary() {
        let mut x = codex_up();
        x.on_input(Input::send("notes")).unwrap();
        let st = replay(&mut x, &["codex-3-edit.jsonl"], &["once"]);
        assert_eq!(tools(&st.events), [("patch".to_string(), "notes.txt +1".to_string())]);
        let card = of(&st.events, "approval.request")[0];
        assert_eq!(s(card, "title"), "Allow Codex to change notes.txt?");
        assert_eq!(s(&written(&st)[0]["result"], "decision"), "accept");
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_codex_4_stop_closes_the_open_card_and_ends_interrupted() {
        let mut x = codex_up();
        x.on_input(Input::send("sleep")).unwrap();
        let st = run(&mut x, &real("codex-4-stop.jsonl"));
        let card = of(&st.events, "approval.request")[0].clone();
        assert_eq!(s(&card, "command"), "sleep 30; echo finished");
        let w = written(&x.on_input(Input::Interrupt).unwrap());
        assert_eq!(w[0]["method"], "turn/interrupt");
        let rest = run(&mut x, &real("codex-4-stopped.jsonl"));
        assert_eq!(ends(&rest.events), [("interrupted".into(), "".into())]);
        assert!(!x.in_turn());
        // the card is gone with its turn: a late answer is refused, nothing is written
        assert!(x.on_input(Input::Approve { request_id: s(&card, "request_id"), choice: "once".into() }).is_err());
    }

    #[test]
    fn real_codex_5_question_in_a_message_becomes_a_question_card() {
        let mut x = codex_up();
        x.on_input(Input::send("ask")).unwrap();
        let lines = real("codex-5-question.jsonl");
        let at = lines.iter().position(|l| l.contains("\"questions\":[{")).unwrap();
        let at = at + lines[at + 1..].iter().position(|l| l.contains("item/completed")).map(|i| i + 1).unwrap_or(0);
        let st = run(&mut x, &lines[..=at]);
        let q = of(&st.events, "clarify.request")[0].clone();
        assert_eq!(s(&q, "question"), "Which greeting should I put in greet.txt?");
        assert_eq!(q["choices"], json!(["hello", "hi"]));
        assert!(text_of(&st.events, "message").is_empty(), "the card stands for the message");
        // Codex then sleeps waiting for the answer: the answer steers the running turn
        let w = written(&x.on_input(Input::Clarify { request_id: s(&q, "request_id"), answer: json!("hi") }).unwrap());
        assert_eq!(w[0]["method"], "turn/steer");
        assert_eq!(w[0]["params"]["input"][0]["text"], "hi");
        assert!(w[0]["params"]["expectedTurnId"].is_string());
        let rest = run(&mut x, &lines[at + 1..]);
        assert_eq!(tools(&rest.events), [("Waiting".to_string(), "60s".to_string())]);
        assert_eq!(ends(&rest.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_codex_5_answer_after_the_turn_ended_starts_a_new_turn() {
        let mut x = codex_up();
        x.on_input(Input::send("ask")).unwrap();
        let st = run(&mut x, &real("codex-5-question.jsonl"));
        let q = of(&st.events, "clarify.request")[0].clone();
        assert!(!x.in_turn());
        let ans = x.on_input(Input::Clarify { request_id: s(&q, "request_id"), answer: json!("hello") }).unwrap();
        assert_eq!(names(&ans.events), ["turn.start"]);
        assert_eq!(written(&ans)[0]["method"], "turn/start");
    }

    #[test]
    fn real_codex_6_bad_command_fails_its_step_only() {
        let mut x = codex_up();
        x.on_input(Input::send("bad")).unwrap();
        let st = replay(&mut x, &["codex-6-error.jsonl"], &["once"]);
        assert_eq!(tools(&st.events), [("terminal".to_string(), "definitely-not-a-command-xyz --flag".to_string())]);
        assert_eq!(of(&st.events, "tool.end")[0]["ok"], false);
        assert_eq!(text_of(&st.events, "message").last().unwrap(), "Exit code: 127.");
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_codex_7_model_applies_to_the_next_turn() {
        let mut x = codex_up();
        let st = x.on_input(Input::Model { model: "gpt-6-astra".into() }).unwrap();
        assert_eq!(s(&st.events[0], "model"), "GPT-6-Astra");
        let w = written(&x.on_input(Input::send("switched")).unwrap());
        assert_eq!((w[0]["method"].as_str(), w[0]["params"]["model"].as_str()), (Some("turn/start"), Some("gpt-6-astra")));
        let st = replay(&mut x, &["codex-7-model.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["switched"]);
    }

    #[test]
    fn real_codex_8_reopen_resumes_the_thread() {
        let id = "01a1c3b9-4b7f-7542-900c-c5f4dc80eefa";
        let mut x = Codex::new("/w/proj", Some(id));
        x.start();
        let st = run(&mut x, &real("codex-8-resume-init.jsonl"));
        let w = written(&st);
        assert_eq!(w[1]["method"], "thread/resume");
        assert_eq!(w[1]["params"]["threadId"], id);
        let st = run(&mut x, &real("codex-8-resume.jsonl"));
        assert_eq!(s(of(&st.events, "session.info")[0], "agent_session"), id);
        let st = x.on_input(Input::send("which file")).unwrap();
        assert_eq!(written(&st)[0]["params"]["threadId"], id);
        let st = replay(&mut x, &["codex-8-resume-turn.jsonl"], &[]);
        assert!(text_of(&st.events, "message")[0].contains("notes.txt"));
    }

    #[test]
    fn titles_the_agents_give_the_conversation_reach_the_session() {
        // Claude Code says a rename (in Claude Code, or from its own titler) as system/session_title_changed
        let mut c = Claude::new("/w");
        let st = c.on_line(r#"{"type":"system","subtype":"session_title_changed","title":"  OAuth redirect\nloop "}"#);
        assert_eq!(st.events, [json!({"event": "session.info", "title": "OAuth redirect loop"})]);
        assert!(c.on_line(r#"{"type":"system","subtype":"session_title_changed","title":"  "}"#).events.is_empty());
        let long = format!(r#"{{"type":"system","subtype":"session_title_changed","title":"{}"}}"#, "x".repeat(300));
        assert_eq!(s(&c.on_line(&long).events[0], "title").chars().count(), 80);

        // Codex names a thread with thread/name/updated; only this session's thread counts
        let mut x = Codex::new("/w/proj", None);
        x.start();
        x.on_line(r#"{"id":1,"result":{}}"#);
        let st = x.on_line(r#"{"id":2,"result":{"thread":{"id":"thr_1","name":null},"model":"gpt-6.1-sol"}}"#);
        assert!(of(&st.events, "session.info")[0].get("title").is_none());
        let st = x.on_line(r#"{"method":"thread/name/updated","params":{"threadId":"thr_1","threadName":"Harden the API"}}"#);
        assert_eq!(st.events, [json!({"event": "session.info", "title": "Harden the API"})]);
        assert!(x.on_line(r#"{"method":"thread/name/updated","params":{"threadId":"thr_other","threadName":"Other"}}"#).events.is_empty());
        assert!(x.on_line(r#"{"method":"thread/name/updated","params":{"threadId":"thr_1"}}"#).events.is_empty());

        // a resumed thread arrives with its name
        let mut r = Codex::new("/w/proj", Some("01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"));
        r.start();
        r.on_line(r#"{"id":1,"result":{}}"#);
        let st = r.on_line(r#"{"id":2,"result":{"thread":{"id":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","name":"Fix the build"},"model":"m"}}"#);
        assert_eq!(s(of(&st.events, "session.info")[0], "title"), "Fix the build");
    }

    #[test]
    fn real_codex_signed_out_says_how_to_sign_in() {
        let mut x = codex_up();
        x.on_input(Input::send("hi")).unwrap();
        let st = replay(&mut x, &["codex-signed-out.jsonl"], &[]);
        // the retries show on the progress line instead of a silent wait
        assert!(of(&st.events, "status").iter().any(|e| s(e, "text").starts_with("Reconnecting")));
        let e = ends(&st.events);
        assert_eq!(e[0].0, "error");
        assert!(e[0].1.contains("not signed in") && !e[0].1.contains("cf-ray"), "{e:?}");
    }

    // -- pi and oh-my-pi --

    #[test]
    fn real_pi_1_plain_answer_ends_on_agent_end() {
        // pi 0.73 ends a prompt with agent_end only (no agent_settled / prompt_result)
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        p.on_input(Input::send("2+2")).unwrap();
        let st = replay(&mut p, &["pi-1-plain.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["4. (model stub-a)"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        assert!(!p.in_turn());
    }

    #[test]
    fn real_omo_plain_answer_through_the_pi_adapter() {
        // omo 5.0.0-beta.65 (`omo --mode rpc`, signed in): pi's RPC plus its own events (settings_source_selected,
        // agent_settled, agent_idle, setStatus/notify dialogs, stdout log lines); the session id is what --session takes
        let mut p = Pi::new("/w/proj", "OmO");
        p.start();
        let st = run(&mut p, &real("omo-init.jsonl"));
        let info = of(&st.events, "session.info");
        assert_eq!(s(info[0], "agent_session"), "01a1c85a-703a-72fe-ae88-c1f9ffb5c249");
        assert_eq!(s(info[0], "model"), "Claude Fable 5.1");
        assert_eq!(of(&st.events, "session.models")[0]["options"].as_array().unwrap().len(), 3);
        assert!(!p.in_turn());
        p.on_input(Input::send("hi. reply with just the word ok")).unwrap();
        let st = replay(&mut p, &["omo-1-plain.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["ok"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        assert!(of(&st.events, "approval.request").is_empty() && of(&st.events, "clarify.request").is_empty());
        assert!(!p.in_turn());
        // the error line names OmO, not pi
        assert!(p.explain("No API key found").starts_with("OmO is not signed in"));
    }

    #[test]
    fn real_pi_2_bash_runs_show_the_commands() {
        // pi has no tool approvals of its own: it runs bash straight away
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        p.on_input(Input::send("ls")).unwrap();
        let st = replay(&mut p, &["pi-2-tools.jsonl"], &[]);
        assert_eq!(tools(&st.events), [("terminal", "ls -la"), ("terminal", "echo hi"), ("terminal", "pwd")].map(|(a, b)| (a.to_string(), b.to_string())));
        assert!(of(&st.events, "approval.request").is_empty());
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_pi_3_write_and_edit() {
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        p.on_input(Input::send("notes")).unwrap();
        let st = replay(&mut p, &["pi-3-edit.jsonl"], &[]);
        assert_eq!(tools(&st.events), [("patch", "notes.txt +1"), ("patch", "README.md +1 -1")].map(|(a, b)| (a.to_string(), b.to_string())));
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_pi_4_abort_ends_interrupted() {
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        p.on_input(Input::send("sleep")).unwrap();
        let st = run(&mut p, &real("pi-4-running.jsonl"));
        assert_eq!(tools(&st.events), [("terminal".to_string(), "sleep 30; echo finished".to_string())]);
        assert!(ends(&st.events).is_empty() && p.in_turn());
        assert_eq!(written(&p.on_input(Input::Interrupt).unwrap())[0]["type"], "abort");
        let st = run(&mut p, &real("pi-4-stopped.jsonl"));
        assert_eq!(of(&st.events, "tool.end")[0]["ok"], false);
        assert_eq!(ends(&st.events), [("interrupted".into(), "".into())]);
        assert!(!p.in_turn());
    }

    #[test]
    fn real_pi_5_question_is_plain_text() {
        // pi has no ask tool: the question is the answer bubble and the turn ends, waiting for the reply
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        p.on_input(Input::send("ask")).unwrap();
        let st = replay(&mut p, &["pi-5-question.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["Which greeting should go in greet.txt: hello or hi?"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_pi_6_bad_command_fails_its_step_only() {
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        p.on_input(Input::send("bad")).unwrap();
        let st = replay(&mut p, &["pi-6-error.jsonl"], &[]);
        assert_eq!(of(&st.events, "tool.end")[0]["ok"], false);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_pi_7_model_switch() {
        let mut p = pi_up("pi", &["pi-init.jsonl"]);
        let w = written(&p.on_input(Input::Model { model: "stub/stub-b".into() }).unwrap());
        assert_eq!((s(&w[0], "provider"), s(&w[0], "modelId")), ("stub".into(), "stub-b".into()));
        let st = run(&mut p, &real("pi-7-model.jsonl").iter().map(|l| l.replace("omher-9", s(&w[0], "id").as_str())).collect::<Vec<_>>());
        assert_eq!(s(&st.events[0], "model"), "Stub B");
        p.on_input(Input::send("2+2")).unwrap();
        let st = replay(&mut p, &["pi-7-after-model.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["4. (model stub-b)"]);
    }

    #[test]
    fn real_pi_signed_out_says_how_to_sign_in() {
        let mut p = Pi::new("/w/proj", "pi");
        p.start();
        let st = run(&mut p, &real("pi-noauth-init.jsonl"));
        assert_eq!(s(of(&st.events, "session.info")[0], "model"), "", "\"unknown\" is not a model name");
        assert_eq!(of(&st.events, "session.models")[0]["options"], json!([]));
        p.on_input(Input::send("2+2")).unwrap();
        let st = run(&mut p, &real("pi-signed-out.jsonl").iter().map(|l| l.replace("omher-3", "omher-3")).collect::<Vec<_>>());
        let e = ends(&st.events);
        assert_eq!(e[0], ("error".to_string(), "pi is not signed in. Open Terminal and run /login, then Restart.".to_string()));
        // a model change it refuses is a note, not a crash
        let st = run(&mut p, &real("pi-noauth-model.jsonl"));
        assert!(st.events.is_empty() || s(&st.events[0], "event") == "session.error");
    }

    #[test]
    fn real_omp_1_plain_ends_once_and_ignores_its_own_extras() {
        let mut p = pi_up("oh-my-pi", &[]);
        // ready, setWidget, advisor_cost_changed and available_commands_update before any prompt: nothing to draw
        let st = run(&mut p, &real("omp-ready.jsonl"));
        assert!(st.events.is_empty() && st.write.is_empty(), "{:?}", st);
        run(&mut p, &real("omp-init.jsonl"));
        p.on_input(Input::send("2+2")).unwrap();
        let st = replay(&mut p, &["omp-1-plain.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["4. (model stub-a)"]);
        // agent_end, prompt_result and session_settled all arrive: one turn.end
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_omp_2_tool_approval_select_maps_to_deny_once_session() {
        let mut p = pi_up("oh-my-pi", &["omp-init.jsonl"]);
        p.on_input(Input::send("ls")).unwrap();
        let st = replay(&mut p, &["omp-2-approvals.jsonl"], &["deny", "once", "session"]);
        let cards = of(&st.events, "approval.request");
        assert_eq!(cards.len(), 3);
        for (card, cmd) in cards.iter().zip(["ls -la", "echo hi", "pwd"]) {
            assert_eq!((s(card, "title"), s(card, "command"), s(card, "cwd")), ("Run this command?".into(), cmd.into(), "/w/proj".into()));
            assert_eq!(card["choices"], json!(["deny", "once", "session"]));
        }
        assert!(of(&st.events, "clarify.request").is_empty(), "an approval select is not a question");
        // each answer is the select's own option label
        let values: Vec<String> = written(&st).iter().filter(|w| w["type"] == "extension_ui_response").map(|w| s(w, "value")).collect();
        assert_eq!(values, ["Deny", "Approve", "Approve bash for this session"]);
        assert_eq!(tools(&st.events).iter().map(|t| t.1.as_str()).collect::<Vec<_>>(), ["ls -la", "echo hi", "pwd"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_omp_3_write_card_names_the_file() {
        let mut p = pi_up("oh-my-pi", &["omp-init.jsonl"]);
        p.on_input(Input::send("notes")).unwrap();
        let st = replay(&mut p, &["omp-3-edit.jsonl"], &["once", "once"]);
        let titles: Vec<String> = of(&st.events, "approval.request").iter().map(|c| s(c, "title")).collect();
        assert_eq!(titles, ["Allow write to change notes.txt?", "Allow edit to change files?"]);
        assert_eq!(tools(&st.events), [("patch", "notes.txt +1"), ("patch", "README.md")].map(|(a, b)| (a.to_string(), b.to_string())));
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_omp_4_abort_ends_interrupted_once() {
        let mut p = pi_up("oh-my-pi", &["omp-init.jsonl"]);
        p.on_input(Input::send("sleep")).unwrap();
        run(&mut p, &real("omp-4-running.jsonl"));
        p.on_input(Input::Interrupt).unwrap();
        let st = run(&mut p, &real("omp-4-stopped.jsonl"));
        assert_eq!(ends(&st.events), [("interrupted".into(), "".into())]);
    }

    #[test]
    fn real_omp_5_6_7_question_error_and_model() {
        let mut p = pi_up("oh-my-pi", &["omp-init.jsonl"]);
        p.on_input(Input::send("ask")).unwrap();
        let st = replay(&mut p, &["omp-5-question.jsonl"], &[]);
        assert_eq!(text_of(&st.events, "message"), ["Which greeting should go in greet.txt: hello or hi?"]);
        let w = written(&p.on_input(Input::Model { model: "stub/stub-b".into() }).unwrap());
        let st = run(&mut p, &real("omp-7-model.jsonl").iter().map(|l| l.replace("omher-9", s(&w[0], "id").as_str())).collect::<Vec<_>>());
        assert_eq!(s(of(&st.events, "session.info")[0], "model"), "Stub B");
        p.on_input(Input::send("2+2")).unwrap();
        assert_eq!(text_of(&replay(&mut p, &["omp-7-after-model.jsonl"], &[]).events, "message"), ["4. (model stub-b)"]);
        p.on_input(Input::send("bad")).unwrap();
        let st = replay(&mut p, &["omp-6-error.jsonl"], &[]);
        assert_eq!(of(&st.events, "tool.end")[0]["ok"], false);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn omp_cancel_closes_its_dialog_and_an_ordinary_select_is_a_question() {
        let mut p = Pi::new("/w/proj", "oh-my-pi");
        p.on_input(Input::send("x")).unwrap();
        let st = p.on_line(r#"{"type":"extension_ui_request","id":"u9","method":"select","title":"Which branch?","options":["main","dev"]}"#);
        assert_eq!(s(&st.events[0], "event"), "clarify.request");
        let st = p.on_line(r#"{"type":"extension_ui_request","id":"c1","method":"cancel","targetId":"u9"}"#);
        assert_eq!(st.events[0], json!({"event": "prompt.expired", "request_id": "u9", "reason": "timeout"}));
        assert!(p.on_input(Input::Clarify { request_id: "u9".into(), answer: json!("dev") }).is_err());
    }

    // -- one shape across agents --

    #[test]
    fn every_agent_names_its_shell_tool_terminal_and_its_file_tools_patch() {
        for name in ["Bash", "bash", "shell", "exec_command", "local_shell", "eval"] {
            assert_eq!(tool_kind(name), "terminal", "{name}");
        }
        for name in ["Write", "Edit", "MultiEdit", "write", "edit", "apply_patch", "ast_edit"] {
            assert_eq!(tool_kind(name), "patch", "{name}");
        }
        assert_eq!(unwrap_shell("/bin/zsh -lc 'mkdir -p d1'"), "mkdir -p d1");
        assert_eq!(unwrap_shell("bash -c \"echo 'hi'\""), "echo 'hi'");
        assert_eq!(unwrap_shell("/bin/zsh -lc 'echo '\\''x'\\'''"), "echo 'x'");
        assert_eq!(unwrap_shell("ls -la"), "ls -la");
        assert_eq!(unwrap_shell("python -c 'x'"), "python -c 'x'");
    }

    #[test]
    fn unknown_events_and_garbage_are_ignored_by_every_adapter() {
        let noise = [
            "",
            "not json",
            "[1,2,3]",
            r#"{"type":"brand_new_event","x":1}"#,
            r#"{"method":"thread/realtime/started","params":{}}"#,
            r#"{"type":"system","subtype":"something_new"}"#,
            r#"{"type":"extension_ui_request","id":"w","method":"setWidget","widgetKey":"k"}"#,
            r#"{"type":"control_request","request_id":"h","request":{"subtype":"mcp_message"}}"#,
            r#"{"id":"77","result":{"weird":true}}"#,
        ];
        let adapters: Vec<Box<dyn Adapter>> = vec![Box::new(Claude::new("/w")), Box::new(Codex::new("/w", None)), Box::new(Pi::new("/w", "pi"))];
        for mut a in adapters {
            for l in noise {
                let st = a.on_line(l);
                assert!(st.events.is_empty(), "{l}: {:?}", st.events);
            }
            assert!(!a.in_turn());
        }
    }

    #[test]
    fn exit_reasons_skip_log_lines_and_name_the_missing_login() {
        let codex = "2026-11-10T05:09:59.797502Z ERROR codex_api::endpoint: failed to connect\n2026-11-10T05:10:03Z ERROR again";
        assert!(exit_reason(codex).starts_with("2026-11-10T05:10:03Z"), "all log lines: the last one");
        let omp = "No default model selected. Use /login, set an API key environment variable, or select a local model with /model or --model.\n\nSet an API key environment variable:\n  ANTHROPIC_API_KEY";
        let raw = exit_reason(omp);
        assert!(raw.starts_with("No default model selected."), "{raw}");
        assert_eq!(Pi::new("/w", "oh-my-pi").explain(&raw), "oh-my-pi is not signed in. Open Terminal and run /login, then Restart.");
        assert_eq!(Claude::new("/w").explain("boom"), "boom");
    }

    #[test]
    fn codex_resume_takes_only_a_thread_uuid() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir();
        for bad in ["x", "--yolo", "01a1c3b9-4b7f-7542-900c-c5f4dc80eef", "../01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"] {
            assert!(c.start_agent("codex", &tmp, Some(bad), &[], |_| {}).is_err(), "{bad}");
        }
        assert!(c.start_agent("pi", &tmp, Some("01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"), &[], |_| {}).is_err());
        assert_eq!(c.count(), 0);
    }

    // ---- attached files: each agent's own image input (shapes checked against claude 2.1.322, codex 0.167,
    // omo 5.0 beta on 2026-11-11: each read a word from a PNG sent this way) -----------------------------------

    fn pic() -> Picture {
        Picture { path: "/h/.omher/session-files/s1/1-word.png".into(), mime: "image/png".into(), data: "iVBORw0KGgo=".into() }
    }
    fn with_pic(text: &str) -> Input {
        Input::Send { text: text.into(), images: vec![pic()] }
    }

    #[test]
    fn the_ui_sends_picture_paths_and_text_only_messages_still_parse() {
        let i: Input = serde_json::from_value(json!({"kind": "send", "text": "hi"})).unwrap();
        assert_eq!(i, Input::send("hi"));
        let i: Input = serde_json::from_value(json!({"kind": "send", "text": "look", "images": ["/h/.omher/session-files/s1/1-a.png"]})).unwrap();
        let Input::Send { images, .. } = i else { panic!() };
        assert_eq!(images, [Picture { path: "/h/.omher/session-files/s1/1-a.png".into(), ..Picture::default() }]);
        // the UI cannot hand the shell bytes or a type: only a path, which resolve() checks and reads
        assert!(serde_json::from_value::<Input>(json!({"kind": "send", "text": "x", "images": [{"path": "/a", "data": "AAAA"}]})).is_err());
    }

    #[test]
    fn claude_gets_pictures_as_base64_image_blocks_before_the_text() {
        let mut c = claude_up_raw();
        let st = c.on_input(with_pic("What does it say?")).unwrap();
        let m: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(
            m["message"]["content"],
            json!([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}, {"type": "text", "text": "What does it say?"}])
        );
        // a picture with nothing typed: no empty text block
        let mut c = claude_up_raw();
        let st = c.on_input(with_pic("")).unwrap();
        let m: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(m["message"]["content"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn codex_gets_pictures_as_local_image_items_even_when_queued_before_the_thread() {
        let mut x = codex_up();
        let st = x.on_input(with_pic("What does it say?")).unwrap();
        let t: Value = serde_json::from_str(st.write.last().unwrap()).unwrap();
        assert_eq!(t["method"], "turn/start");
        assert_eq!(t["params"]["input"], json!([{"type": "localImage", "path": "/h/.omher/session-files/s1/1-word.png"}, {"type": "text", "text": "What does it say?"}]));
        // sent before the thread exists: the picture waits with the text
        let mut x = Codex::new("/w/proj", None);
        x.start();
        assert!(x.on_input(with_pic("")).unwrap().write.is_empty());
        let st = run(&mut x, &real("codex-init.jsonl"));
        let t: Value = st.write.iter().map(|w| serde_json::from_str::<Value>(w).unwrap()).find(|v| v["method"] == "turn/start").unwrap();
        assert_eq!(t["params"]["input"], json!([{"type": "localImage", "path": "/h/.omher/session-files/s1/1-word.png"}]));
    }

    #[test]
    fn pi_and_omo_get_pictures_as_the_prompt_images() {
        let mut p = Pi::new("/w/proj", "OmO");
        p.start();
        let st = p.on_input(with_pic("What does it say?")).unwrap();
        let cmd: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!(s(&cmd, "type"), "prompt");
        assert_eq!(s(&cmd, "message"), "What does it say?");
        assert_eq!(cmd["images"], json!([{"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}]));
        let st = p.on_input(Input::send("no picture")).unwrap();
        let cmd: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert!(cmd.get("images").is_none());
    }

    #[test]
    fn resolve_reads_only_pictures_omher_saved() {
        let home = std::env::temp_dir().join(format!("omher-resolve-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).unwrap();
        let home = home.canonicalize().unwrap();
        let png = session_files::save(&home, "s1", "word.png", b"\x89PNG").unwrap();
        let mut i = Input::Send { text: "x".into(), images: vec![Picture::from(png.to_string_lossy().into_owned())] };
        i.resolve(&home).unwrap();
        let Input::Send { images, .. } = &i else { panic!() };
        assert_eq!((images[0].mime.as_str(), images[0].data.as_str()), ("image/png", "iVBORw=="));
        let txt = session_files::save(&home, "s1", "notes.txt", b"a").unwrap();
        let outside = home.join("secret.png");
        std::fs::write(&outside, b"x").unwrap();
        for bad in [txt.to_string_lossy().into_owned(), outside.to_string_lossy().into_owned(), "/etc/hosts".into(), "relative.png".into()] {
            let mut i = Input::Send { text: "x".into(), images: vec![Picture::from(bad.clone())] };
            assert!(i.resolve(&home).is_err(), "{bad}");
        }
        // other inputs carry no files
        assert!(Input::Interrupt.resolve(&home).is_ok());
        let _ = std::fs::remove_dir_all(&home);
    }
}

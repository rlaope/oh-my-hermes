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
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::sessions::{agent, chat_args, launch_for, resume_args, signal_group, Mode};

/// What the person did in the chat. Mirrors `ChatInput` in src/sessions/host.ts.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Input {
    Send { text: String },
    Interrupt,
    Approve { request_id: String, choice: String },
    Clarify { request_id: String, answer: String },
    Model { model: String },
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
}

/// The adapter for an allow-listed chat agent, or `None` for agents that have no chat mode here.
pub fn adapter_for(id: &str, cwd: &str) -> Option<Box<dyn Adapter>> {
    match id {
        "claude" => Some(Box::new(Claude::default())),
        "codex" => Some(Box::new(Codex::new(cwd))),
        "pi" | "omp" => Some(Box::new(Pi::default())),
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

/// What a tool call is about, for the progress line and the approval card: the command, path, pattern,
/// query or URL from its arguments, else a short JSON.
fn tool_detail(input: &Value) -> String {
    for k in ["command", "cmd", "file_path", "path", "notebook_path", "pattern", "query", "url", "description", "prompt"] {
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
    match input {
        Value::Object(m) if m.is_empty() => String::new(),
        Value::Null => String::new(),
        other => clip(&other.to_string(), 160),
    }
}

/// The bot chat's tool names for the verbs on the progress line ("Running", "Reading", "Editing" …).
fn tool_kind(name: &str) -> &str {
    match name.to_ascii_lowercase().as_str() {
        "bash" | "shell" | "exec" | "powershell" => "terminal",
        "read" | "notebookread" | "view" => "read_file",
        "write" | "edit" | "multiedit" | "notebookedit" | "apply_patch" | "patch" => "patch",
        "grep" | "glob" | "ls" | "find" => "search_files",
        "websearch" | "web_search" => "web_search",
        "webfetch" | "fetch" => "web_extract",
        "task" | "agent" => "delegate_task",
        "skill" => "skill_view",
        _ => name,
    }
}

const CHOICES: [&str; 3] = ["deny", "once", "session"];

// ---------------------------------------------------------------------------------------------
// Claude Code (stream-json)
// ---------------------------------------------------------------------------------------------

#[derive(Default)]
pub struct Claude {
    seq: u64,
    turn: bool,
    /// open `can_use_tool` requests: request id -> (tool name, input, permission suggestions)
    pending: HashMap<String, (String, Value, Value)>,
    model: String,
}

impl Claude {
    fn next_id(&mut self, p: &str) -> String {
        self.seq += 1;
        format!("omher-{p}-{}", self.seq)
    }
    fn control(&mut self, step: &mut Step, p: &str, request: Value) {
        let id = self.next_id(p);
        step.out(json!({"type": "control_request", "request_id": id, "request": request}));
    }
    fn end(&mut self, step: &mut Step, outcome: &str, error: Option<String>) {
        if self.turn {
            self.turn = false;
            self.pending.clear();
            let mut f = json!({"outcome": outcome});
            if let Some(e) = error.filter(|e| !e.is_empty()) {
                f["error"] = Value::String(e);
            }
            step.emit(ev("turn.end", f));
        }
    }
}

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
                st.emit(ev("session.info", json!({"agent_session": s(&v, "session_id"), "model": self.model})));
            }
            "control_response" => {
                let r = &v["response"];
                let id = s(r, "request_id");
                let body = &r["response"];
                if id.starts_with("omher-init-") {
                    if let Some(models) = body.get("models").and_then(Value::as_array) {
                        let options: Vec<Value> = models
                            .iter()
                            .map(|m| json!({"id": s(m, "value"), "label": s(m, "displayName"), "detail": s(m, "description")}))
                            .filter(|m| !m["id"].as_str().unwrap_or("").is_empty())
                            .collect();
                        st.emit(ev("session.models", json!({"options": options})));
                    }
                } else if id.starts_with("omher-model-") {
                    if s(r, "subtype") == "success" {
                        let m = s(body, "model");
                        if !m.is_empty() {
                            self.model = m;
                        }
                        st.emit(ev("session.info", json!({"model": self.model})));
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
                    let shown = if s(req, "display_name").is_empty() { name.clone() } else { s(req, "display_name") };
                    let detail = tool_detail(&input);
                    let title = if tool_kind(&name) == "terminal" {
                        "Run this command?".to_string()
                    } else if tool_kind(&name) == "patch" {
                        format!("Allow {shown} to change {}?", if detail.is_empty() { "files".into() } else { detail.clone() })
                    } else {
                        format!("Allow {shown}?")
                    };
                    let command = if tool_kind(&name) == "patch" { String::new() } else { detail };
                    self.pending.insert(rid.clone(), (name, input, req.get("permission_suggestions").cloned().unwrap_or(Value::Null)));
                    st.emit(ev("approval.request", json!({"request_id": rid, "title": title, "command": command, "choices": CHOICES})));
                } else {
                    // hooks, MCP messages …: omher registers none of them
                    st.out(json!({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "not supported by omher"}}));
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
                for (i, b) in msg.get("content").and_then(Value::as_array).into_iter().flatten().enumerate() {
                    match s(b, "type").as_str() {
                        "text" => {
                            let t = s(b, "text");
                            if !t.trim().is_empty() {
                                st.emit(ev("message", json!({"id": format!("{mid}-{i}"), "text": t})));
                            }
                        }
                        "tool_use" => {
                            let name = s(b, "name");
                            let input = b.get("input").cloned().unwrap_or(Value::Null);
                            st.emit(ev("tool.start", json!({"tool_id": s(b, "id"), "name": tool_kind(&name), "detail": tool_detail(&input)})));
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
                let reason = s(&v, "terminal_reason");
                if reason.starts_with("aborted") || reason == "interrupted" {
                    self.end(&mut st, "interrupted", None);
                } else if v.get("is_error").and_then(Value::as_bool).unwrap_or(false) {
                    let err = v
                        .get("errors")
                        .and_then(Value::as_array)
                        .and_then(|a| a.first())
                        .and_then(Value::as_str)
                        .map(String::from)
                        .unwrap_or_else(|| s(&v, "result"));
                    self.end(&mut st, "error", Some(clip(&err, 200)));
                } else {
                    self.end(&mut st, "done", None);
                }
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text } => {
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
                st.out(json!({"type": "user", "session_id": "", "parent_tool_use_id": null,
                              "message": {"role": "user", "content": [{"type": "text", "text": text}]}}));
            }
            Input::Interrupt => self.control(&mut st, "interrupt", json!({"subtype": "interrupt"})),
            Input::Approve { request_id, choice } => {
                let (name, input, suggestions) = self.pending.remove(&request_id).ok_or("no such request")?;
                let response = match choice.as_str() {
                    "deny" => json!({"behavior": "deny", "message": "The person denied this in omher."}),
                    "once" => json!({"behavior": "allow", "updatedInput": input}),
                    "session" => {
                        let updates = match suggestions {
                            Value::Array(a) if !a.is_empty() => Value::Array(a),
                            _ => json!([{"type": "addRules", "rules": [{"toolName": name}], "behavior": "allow", "destination": "session"}]),
                        };
                        json!({"behavior": "allow", "updatedInput": input, "updatedPermissions": updates})
                    }
                    other => return Err(format!("unknown choice {other}")),
                };
                st.out(json!({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": response}}));
            }
            Input::Clarify { .. } => return Err("Claude Code asks no questions over this stream".into()),
            Input::Model { model } => self.control(&mut st, "model", json!({"subtype": "set_model", "model": model})),
        }
        Ok(st)
    }
}

// ---------------------------------------------------------------------------------------------
// Codex (app-server, JSON-RPC over stdio)
// ---------------------------------------------------------------------------------------------

pub struct Codex {
    cwd: String,
    seq: u64,
    /// request id -> method, for matching responses
    calls: HashMap<u64, &'static str>,
    thread: Option<String>,
    turn_id: Option<String>,
    turn: bool,
    model: Option<String>,
    queued: Vec<String>,
    /// open approvals: our request id -> (JSON-RPC id, kind)
    pending: HashMap<String, (Value, &'static str)>,
    /// file paths of fileChange items, shown on their approval card
    changes: HashMap<String, String>,
}

impl Codex {
    pub fn new(cwd: &str) -> Codex {
        Codex { cwd: cwd.into(), seq: 0, calls: HashMap::new(), thread: None, turn_id: None, turn: false, model: None, queued: vec![], pending: HashMap::new(), changes: HashMap::new() }
    }
    fn call(&mut self, st: &mut Step, method: &'static str, params: Value) {
        self.seq += 1;
        self.calls.insert(self.seq, method);
        st.out(json!({"id": self.seq, "method": method, "params": params}));
    }
    fn turn_start(&mut self, st: &mut Step, text: String) {
        let thread = self.thread.clone().unwrap_or_default();
        let mut p = json!({"threadId": thread, "input": [{"type": "text", "text": text}]});
        if let Some(m) = &self.model {
            p["model"] = Value::String(m.clone());
        }
        self.call(st, "turn/start", p);
    }
    fn end(&mut self, st: &mut Step, outcome: &str, error: Option<String>) {
        if self.turn {
            self.turn = false;
            self.turn_id = None;
            self.pending.clear();
            let mut f = json!({"outcome": outcome});
            if let Some(e) = error.filter(|e| !e.is_empty()) {
                f["error"] = Value::String(e);
            }
            st.emit(ev("turn.end", f));
        }
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
                    self.end(&mut st, "error", Some(msg));
                } else {
                    st.emit(ev("session.error", json!({"message": format!("{what}: {msg}")})));
                }
                return st;
            }
            let r = &v["result"];
            match what {
                "initialize" => {
                    st.out(json!({"method": "initialized"}));
                    let cwd = self.cwd.clone();
                    self.call(&mut st, "thread/start", json!({"cwd": cwd}));
                    self.call(&mut st, "model/list", json!({}));
                }
                "thread/start" => {
                    self.thread = r["thread"].get("id").and_then(Value::as_str).map(String::from);
                    let model = s(r, "model");
                    st.emit(ev("session.info", json!({"agent_session": self.thread.clone().unwrap_or_default(), "model": model})));
                    for text in std::mem::take(&mut self.queued) {
                        self.turn_start(&mut st, text);
                    }
                }
                "turn/start" => {
                    if let Some(t) = r["turn"].get("id").and_then(Value::as_str) {
                        self.turn_id = Some(t.into());
                    }
                }
                "model/list" => {
                    let options: Vec<Value> = r
                        .get("data")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter(|m| !m.get("hidden").and_then(Value::as_bool).unwrap_or(false))
                        .map(|m| json!({"id": s(m, "model"), "label": s(m, "displayName"), "detail": s(m, "description")}))
                        .collect();
                    st.emit(ev("session.models", json!({"options": options})));
                }
                _ => {}
            }
            return st;
        }
        let p = v.get("params").cloned().unwrap_or(Value::Null);
        // a request from the server (approvals); anything we do not handle is answered with an error
        if let Some(rpc_id) = id {
            let key = format!("codex-{}", rpc_id);
            match method.as_str() {
                "item/commandExecution/requestApproval" => {
                    let reason = s(&p, "reason");
                    let title = if reason.is_empty() { "Run this command?".to_string() } else { clip(&reason, 120) };
                    self.pending.insert(key.clone(), (rpc_id, "command"));
                    st.emit(ev("approval.request", json!({"request_id": key, "title": title, "command": s(&p, "command"), "choices": CHOICES})));
                }
                "item/fileChange/requestApproval" => {
                    let files = self.changes.get(&s(&p, "itemId")).cloned().unwrap_or_default();
                    let title = if files.is_empty() { "Apply these edits?".to_string() } else { format!("Change {files}?") };
                    self.pending.insert(key.clone(), (rpc_id, "file"));
                    st.emit(ev("approval.request", json!({"request_id": key, "title": title, "command": "", "choices": CHOICES})));
                }
                _ => st.out(json!({"id": rpc_id, "error": {"code": -32601, "message": "not supported by omher"}})),
            }
            return st;
        }
        let item = p.get("item").cloned().unwrap_or(Value::Null);
        match method.as_str() {
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
                    "commandExecution" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": "terminal", "detail": clip(&s(&item, "command"), 160)}))),
                    "fileChange" => {
                        let files: Vec<String> = item
                            .get("changes")
                            .and_then(Value::as_array)
                            .into_iter()
                            .flatten()
                            .map(|c| s(c, "path"))
                            .filter(|p| !p.is_empty())
                            .collect();
                        let detail = clip(&files.join(", "), 160);
                        self.changes.insert(iid.clone(), detail.clone());
                        st.emit(ev("tool.start", json!({"tool_id": iid, "name": "patch", "detail": detail})));
                    }
                    "mcpToolCall" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": s(&item, "tool"), "detail": format!("{}.{}", s(&item, "server"), s(&item, "tool"))}))),
                    "webSearch" => st.emit(ev("tool.start", json!({"tool_id": iid, "name": "web_search", "detail": s(&item, "query")}))),
                    _ => {}
                }
            }
            "item/completed" => {
                let iid = s(&item, "id");
                match s(&item, "type").as_str() {
                    "agentMessage" => {
                        let t = s(&item, "text");
                        if !t.trim().is_empty() {
                            st.emit(ev("message", json!({"id": iid, "text": t})));
                        }
                    }
                    "commandExecution" | "fileChange" | "mcpToolCall" | "webSearch" => {
                        let status = s(&item, "status");
                        let ok = !matches!(status.as_str(), "failed" | "declined");
                        st.emit(ev("tool.end", json!({"tool_id": iid, "name": "", "ok": ok, "ms": item.get("durationMs").and_then(Value::as_u64).unwrap_or(0)})));
                    }
                    _ => {}
                }
            }
            "turn/completed" => {
                let t = &p["turn"];
                match s(t, "status").as_str() {
                    "interrupted" => self.end(&mut st, "interrupted", None),
                    "failed" => {
                        let e = t.get("error").map(|e| s(e, "message")).unwrap_or_default();
                        self.end(&mut st, "error", Some(clip(&e, 200)));
                    }
                    _ => self.end(&mut st, "done", None),
                }
            }
            "error" => {
                if !p.get("willRetry").and_then(Value::as_bool).unwrap_or(false) {
                    let e = p.get("error").map(|e| s(e, "message")).unwrap_or_default();
                    st.emit(ev("status", json!({"text": clip(&format!("Error: {e}"), 160)})));
                }
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text } => {
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
                if self.thread.is_none() {
                    self.queued.push(text);
                } else {
                    self.turn_start(&mut st, text);
                }
            }
            Input::Interrupt => {
                let (Some(thread), Some(turn)) = (self.thread.clone(), self.turn_id.clone()) else { return Err("nothing is running".into()) };
                self.call(&mut st, "turn/interrupt", json!({"threadId": thread, "turnId": turn}));
            }
            Input::Approve { request_id, choice } => {
                let (rpc_id, _) = self.pending.remove(&request_id).ok_or("no such request")?;
                let decision = match choice.as_str() {
                    "deny" => "decline",
                    "once" => "accept",
                    "session" => "acceptForSession",
                    other => return Err(format!("unknown choice {other}")),
                };
                st.out(json!({"id": rpc_id, "result": {"decision": decision}}));
            }
            Input::Clarify { .. } => return Err("Codex asks no questions over this stream".into()),
            Input::Model { model } => {
                // app-server takes the model per turn; the next turn uses it
                self.model = Some(model.clone());
                st.emit(ev("session.info", json!({"model": model})));
            }
        }
        Ok(st)
    }
}

// ---------------------------------------------------------------------------------------------
// pi and oh-my-pi (`--mode rpc`)
// ---------------------------------------------------------------------------------------------

#[derive(Default)]
pub struct Pi {
    seq: u64,
    calls: HashMap<String, &'static str>,
    turn: bool,
    streaming: bool,
    msg: u64,
    last_stop: String,
    last_error: String,
    /// open dialogs: id -> method (confirm / select / input / editor)
    pending: HashMap<String, String>,
}

impl Pi {
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
                f["error"] = Value::String(clip(&err, 200));
            }
            st.emit(ev("turn.end", f));
        }
        self.last_stop.clear();
        self.last_error.clear();
    }
}

fn pi_model(m: &Value) -> Value {
    let provider = s(m, "provider");
    let id = s(m, "id");
    let name = if s(m, "name").is_empty() { id.clone() } else { s(m, "name") };
    json!({"id": format!("{provider}/{id}"), "label": name, "detail": provider})
}

impl Adapter for Pi {
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
                    } else {
                        st.emit(ev("session.error", json!({"message": format!("{}: {e}", s(&v, "command"))})));
                    }
                    return st;
                }
                match what {
                    "get_state" => {
                        let model = d.get("model").map(|m| s(m, "name")).filter(|n| !n.is_empty()).or_else(|| d.get("model").map(|m| s(m, "id"))).unwrap_or_default();
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
                st.emit(ev("tool.start", json!({"tool_id": s(&v, "toolCallId"), "name": tool_kind(&name), "detail": tool_detail(&args)})));
            }
            "tool_execution_end" => {
                let ok = !v.get("isError").and_then(Value::as_bool).unwrap_or(false);
                st.emit(ev("tool.end", json!({"tool_id": s(&v, "toolCallId"), "name": "", "ok": ok, "ms": 0})));
            }
            "agent_settled" | "prompt_result" => self.end(&mut st),
            "extension_ui_request" => {
                let id = s(&v, "id");
                let method = s(&v, "method");
                let title = s(&v, "title");
                match method.as_str() {
                    "confirm" => {
                        let msg = s(&v, "message");
                        self.pending.insert(id.clone(), method);
                        st.emit(ev("approval.request", json!({"request_id": id, "title": if title.is_empty() { "Allow this?".into() } else { title }, "command": msg, "choices": ["deny", "once"]})));
                    }
                    "select" => {
                        let options: Vec<String> = v.get("options").and_then(Value::as_array).into_iter().flatten().filter_map(|o| o.as_str().map(String::from)).collect();
                        self.pending.insert(id.clone(), method);
                        st.emit(ev("clarify.request", json!({"request_id": id, "question": title, "choices": options})));
                    }
                    "input" => {
                        self.pending.insert(id.clone(), method);
                        st.emit(ev("clarify.request", json!({"request_id": id, "question": title})));
                    }
                    "editor" => st.out(json!({"type": "extension_ui_response", "id": id, "cancelled": true})),
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
            Input::Send { text } => {
                let mut f = json!({"message": text});
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
                let m = self.pending.remove(&request_id).ok_or("no such request")?;
                if m != "confirm" {
                    return Err("not an approval".into());
                }
                let confirmed = match choice.as_str() {
                    "deny" => false,
                    "once" | "session" => true,
                    other => return Err(format!("unknown choice {other}")),
                };
                st.out(json!({"type": "extension_ui_response", "id": request_id, "confirmed": confirmed}));
            }
            Input::Clarify { request_id, answer } => {
                let m = self.pending.remove(&request_id).ok_or("no such request")?;
                if m == "confirm" {
                    return Err("not a question".into());
                }
                st.out(json!({"type": "extension_ui_response", "id": request_id, "value": answer}));
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

struct ChatLive {
    stdin: Arc<Mutex<Option<ChildStdin>>>,
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

fn write_lines(stdin: &Arc<Mutex<Option<ChildStdin>>>, lines: &[String]) -> Result<(), String> {
    if lines.is_empty() {
        return Ok(());
    }
    let mut g = stdin.lock().unwrap();
    let w = g.as_mut().ok_or("the session has ended")?;
    for l in lines {
        w.write_all(l.as_bytes()).and_then(|_| w.write_all(b"\n")).map_err(|e| e.to_string())?;
    }
    w.flush().map_err(|e| e.to_string())
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

impl ChatSessions {
    pub fn new() -> Arc<ChatSessions> {
        Arc::new(ChatSessions::default())
    }

    /// Start allow-listed agent `agent_id` in its chat mode in `cwd`. `resume` (Claude Code only) continues
    /// that conversation. Anything not on the allow-list, or without a chat mode, is refused before a
    /// process exists.
    pub fn start_agent<F>(&self, agent_id: &str, cwd: &Path, resume: Option<&str>, sink: F) -> Result<u32, String>
    where
        F: FnMut(ChatOut) + Send + 'static,
    {
        let a = agent(agent_id).ok_or_else(|| format!("unknown agent \"{agent_id}\""))?;
        if a.mode != Mode::Chat {
            return Err(format!("{} has no chat mode", a.label));
        }
        let args = chat_args(agent_id).ok_or("no chat mode")?;
        let adapter = adapter_for(agent_id, &cwd.to_string_lossy()).ok_or("no chat adapter")?;
        let (mut argv, path_env) = launch_for(agent_id)?;
        argv.extend(args.iter().map(OsString::from));
        if let Some(r) = resume {
            argv.extend(resume_args(agent_id, r)?);
        }
        self.spawn(argv, cwd, Some(path_env), adapter, sink)
    }

    /// Start `argv` on pipes in `cwd` with `adapter`. Crate-internal: the app reaches it only through
    /// [`ChatSessions::start_agent`], so argv always comes from the allow-list (tests use it directly).
    pub(crate) fn spawn<F>(&self, argv: Vec<OsString>, cwd: &Path, path_env: Option<OsString>, mut adapter: Box<dyn Adapter>, sink: F) -> Result<u32, String>
    where
        F: FnMut(ChatOut) + Send + 'static,
    {
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(format!("not a folder: {}", cwd.display()));
        }
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
        let mut child = cmd.spawn().map_err(|e| format!("{}: {e}", Path::new(prog).display()))?;
        let stdout = child.stdout.take().ok_or("no stdout")?;
        let stderr = child.stderr.take().ok_or("no stderr")?;
        let stdin = Arc::new(Mutex::new(child.stdin.take()));
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
            // stdout: split on LF only (JSON strings may hold U+2028), one adapter step per line
            let (adapter, stdin, sink, done) = (adapter.clone(), stdin.clone(), sink.clone(), reader_done.clone());
            thread::spawn(move || {
                let mut r = BufReader::new(stdout);
                let mut buf = Vec::new();
                loop {
                    buf.clear();
                    match r.read_until(b'\n', &mut buf) {
                        Ok(0) | Err(_) => break,
                        Ok(_) => {
                            let line = String::from_utf8_lossy(&buf);
                            let line = line.trim_end_matches(['\n', '\r']);
                            if line.trim().is_empty() {
                                continue;
                            }
                            let step = adapter.lock().unwrap().on_line(line);
                            let _ = write_lines(&stdin, &step.write);
                            deliver(&sink, step.events);
                        }
                    }
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
                let mid_turn = adapter.lock().unwrap().in_turn();
                let err = tail.lock().unwrap().trim().lines().rev().take(3).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
                if let Ok(mut f) = sink.lock() {
                    if mid_turn {
                        let e = if err.is_empty() { "the agent stopped".to_string() } else { clip(&err, 200) };
                        f(ChatOut::Event(ev("turn.end", json!({"outcome": "error", "error": e}))));
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
    // closing stdin is pi's and Codex's orderly shutdown; Claude Code's -p ends on EOF too
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
        let st = c.on_input(Input::Send { text: "say hi".into() }).unwrap();
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
        c.on_input(Input::Send { text: "say hi".into() }).unwrap();
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
        let mut c = Claude::default();
        c.start();
        c.on_input(Input::Send { text: "write note.txt".into() }).unwrap();
        let lines = fixture("claude-approve.jsonl");
        let at = lines.iter().position(|l| l.contains("\"can_use_tool\"")).unwrap();
        let st = run(&mut c, &lines[..=at]);
        // the tool shows on the progress line before the card
        let tool = st.events.iter().find(|e| s(e, "event") == "tool.start").unwrap();
        assert_eq!(s(tool, "name"), "patch");
        assert_eq!(s(tool, "detail"), "/w/t14/note.txt");
        let card = st.events.last().unwrap();
        assert_eq!(s(card, "event"), "approval.request");
        assert_eq!(s(card, "title"), "Allow Write to change /w/t14/note.txt?");
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
        c.on_input(Input::Send { text: "write a long story".into() }).unwrap();
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
        c.on_input(Input::Send { text: "x".into() }).unwrap();
        let st = c.on_line(r#"{"type":"assistant","parent_tool_use_id":"toolu_1","message":{"id":"m","content":[{"type":"text","text":"inner"}]}}"#);
        assert!(st.events.is_empty());
        let st = c.on_line(r#"{"type":"result","subtype":"error_during_execution","is_error":true,"terminal_reason":"error","errors":["API Error: 529 overloaded"]}"#);
        assert_eq!(st.events[0], json!({"event": "turn.end", "outcome": "error", "error": "API Error: 529 overloaded"}));
    }

    // ---- Codex app-server (fixture from the protocol schema, codex-rs/app-server-protocol) --------

    #[test]
    fn codex_handshake_thread_then_turn_with_command_approval() {
        let mut x = Codex::new("/w/proj");
        let st = x.start();
        let init: Value = serde_json::from_str(&st.write[0]).unwrap();
        assert_eq!((init["id"].as_u64(), s(&init, "method")), (Some(1), "initialize".to_string()));
        assert_eq!(init["params"]["clientInfo"]["name"], "omher");
        // text typed before the thread exists waits for it
        let st = x.on_input(Input::Send { text: "run the tests".into() }).unwrap();
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
        assert_eq!(s(&st.events[0], "model"), "gpt-5.5-codex");

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
        let mut x = Codex::new("/w");
        x.start();
        run(&mut x, &fixture("codex-turn.jsonl")[..2]);
        x.on_input(Input::Send { text: "go".into() }).unwrap();
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
        assert_eq!(serde_json::from_str::<Value>(&st.write[0]).unwrap()["error"]["code"], -32601);
    }

    // ---- pi / oh-my-pi `--mode rpc` (fixture from pi-mono docs/rpc*.md, docs/json.md) -------------

    #[test]
    fn pi_prompt_streams_tools_and_settles() {
        let mut p = Pi::default();
        let st = p.start();
        let w: Vec<Value> = st.write.iter().map(|l| serde_json::from_str(l).unwrap()).collect();
        assert_eq!((s(&w[0], "type"), s(&w[1], "type")), ("get_state".into(), "get_available_models".into()));
        let st = p.on_input(Input::Send { text: "list the ts files".into() }).unwrap();
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
        p.on_input(Input::Send { text: "x".into() }).unwrap();
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
        let st = p.on_line(r#"{"type":"agent_settled"}"#);
        assert_eq!(st.events[0], json!({"event": "turn.end", "outcome": "interrupted"}));
        // omp ends each prompt with prompt_result
        p.on_input(Input::Send { text: "y".into() }).unwrap();
        let st = p.on_line(r#"{"type":"prompt_result","id":"omher-9"}"#);
        assert_eq!(s(&st.events[0], "outcome"), "done");
        let m: Value = serde_json::from_str(&p.on_input(Input::Model { model: "anthropic/claude-x".into() }).unwrap().write[0]).unwrap();
        assert_eq!((s(&m, "provider"), s(&m, "modelId")), ("anthropic".into(), "claude-x".into()));
    }

    #[test]
    fn only_chat_agents_have_adapters() {
        for id in ["claude", "codex", "pi", "omp"] {
            assert!(adapter_for(id, "/w").is_some(), "{id}");
        }
        for id in ["omh", "grok", "sh", ""] {
            assert!(adapter_for(id, "/w").is_none(), "{id}");
        }
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir();
        for bad in ["omh", "grok", "/bin/sh", "claude -p"] {
            assert!(c.start_agent(bad, &tmp, None, |_| {}).is_err(), "{bad}");
        }
        assert!(c.start_agent("claude", &tmp, Some("--dangerously-skip-permissions"), |_| {}).is_err());
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
        adapter.on_input(Input::Send { text: "say hi".into() }).unwrap();
        let id = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, adapter, sink).unwrap();
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
        adapter.on_input(Input::Send { text: "x".into() }).unwrap();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), "echo 'Error: not logged in' >&2; exit 2".into()], &tmp, None, adapter, sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let got = out.lock().unwrap().clone();
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end" && s(e, "error").contains("not logged in"))), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(2), e) if e.contains("not logged in"))), "{got:?}");
    }

    #[cfg(unix)]
    #[test]
    fn close_all_stops_every_chat() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (out, sink) = collect();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), "trap '' HUP TERM; while :; do sleep 1; done".into()], &tmp, None, Box::new(Pi::default()), sink).unwrap();
        c.close_all();
        assert_eq!(c.count(), 0);
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
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
            .start_agent("claude", &dir.canonicalize().unwrap(), None, move |x| {
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
        c.input(id, Input::Send { text: "reply with the word ok".into() }).unwrap();
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
}

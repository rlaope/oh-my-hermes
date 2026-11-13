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
//! - DSH (DeepSeek Harness): one `dsh --profile headless --json` run per message, continued by `--session-id`
//!   ([`crate::dsh_chat`]).
//!
//! The UI sends only an agent id, a folder and chat input; the program and its arguments come from the
//! allow-list. Closing the session (or quitting the app) stops the program.

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::mpsc::{self, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::acp_chat::{acp_agent, is_acp_session_id, Acp, RuleProbe, NO_RULES};
use crate::dsh_chat::DshChat;
use crate::session_files;
use crate::sessions::{agent, chat_args, cmd_path_arg, coalesce, is_uuid, launch_for, layout, resume_args, signal_group, unrecognized_program, Mode, ProcessTree, COALESCE_BYTES, COALESCE_WINDOW, INPUT_QUEUE};

/// What the person did in the chat. Mirrors `ChatInput` in src/sessions/host.ts. A message's `images` are the
/// saved copies (`session_files`) of the pictures the person attached, for the agent's own image input; any other
/// file is already named in `text` by its saved copy's path. `id` is omher's own id for the message's bubble: a
/// message sent while a turn runs comes back as `message.queued`, then `message.taken` when the agent takes it (or
/// `message.dropped` when Stop threw it away).
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Input {
    Send { text: String, #[serde(default)] images: Vec<Picture>, #[serde(default)] id: String },
    Interrupt,
    Approve { request_id: String, choice: String },
    /// A string, or per-question answers (`{qid: text|null}`) for several questions at once.
    Clarify { request_id: String, answer: Value },
    Model { model: String },
    /// The session's permission mode, one of [`modes_for`] (never one that skips approvals or lifts the sandbox).
    Mode { mode: String },
    /// Reasoning effort, one of the levels the agent itself reported (`session.efforts`).
    Effort { effort: String },
    /// Take back the person's last message and what came after it, through the agent's own rewind (Claude Code
    /// `rewind_conversation`, Codex `thread/revert`); the UI then offers its text again. Files stay as they are.
    Rewind,
}

/// The permission modes a person can pick for agent `id`: Claude Code's own `default` (ask), `plan` and
/// `acceptEdits`; Codex's read-only, ask and auto-in-the-workspace presets ([`codex_mode`]). No agent is offered a
/// mode that skips every approval (`bypassPermissions`, `dontAsk`, `auto`) or lifts the sandbox
/// (`danger-full-access`); the rpc agents have no mode here.
pub fn modes_for(id: &str) -> &'static [&'static str] {
    match id {
        "claude" => &["default", "plan", "acceptEdits"],
        "codex" => &["read-only", "ask", "auto"],
        _ => &[],
    }
}

/// A Codex mode as its per-turn approval policy and sandbox (`turn/start` `approvalPolicy`, `sandboxPolicy.type`).
fn codex_mode(mode: &str) -> Option<(&'static str, &'static str)> {
    match mode {
        "read-only" => Some(("on-request", "readOnly")),
        "ask" => Some(("untrusted", "workspaceWrite")),
        "auto" => Some(("on-request", "workspaceWrite")),
        _ => None,
    }
}

/// The mode a Codex thread reports (approval policy and sandbox type), when it is one of ours.
fn codex_mode_of(policy: &str, sandbox: &str) -> Option<&'static str> {
    ["read-only", "ask", "auto"].into_iter().find(|m| codex_mode(m) == Some((policy, sandbox)))
}

/// One entry of `session.commands`: a command or skill the agent itself reported, typed after `prefix`.
fn command_entry(name: &str, description: &str, hint: &str, kind: &str, prefix: &str) -> Value {
    json!({"name": name, "description": clip(description, 160), "hint": hint, "kind": kind, "prefix": prefix})
}

/// Messages sent while a turn ran, in order, until the agent takes them. Shared by the adapters.
#[derive(Default)]
struct Waiting {
    /// every message sent and not yet seen taken, oldest first: (id, sent while a turn ran)
    sent: std::collections::VecDeque<(String, bool)>,
}

impl Waiting {
    /// A message went out; `busy` = a turn was running. A queued one is said at once.
    fn push(&mut self, st: &mut Step, id: String, busy: bool) {
        if busy && !id.is_empty() {
            st.emit(ev("message.queued", json!({"id": id})));
        }
        self.sent.push_back((id, busy));
    }
    /// The agent took its oldest message.
    fn take(&mut self, st: &mut Step) {
        if let Some((id, true)) = self.sent.pop_front() {
            if !id.is_empty() {
                st.emit(ev("message.taken", json!({"id": id})));
            }
        }
    }
    /// The agent took a message by id (Codex's `clientId`); older ones were taken before it.
    fn take_id(&mut self, st: &mut Step, id: &str) {
        if self.sent.iter().any(|(i, _)| i == id) {
            while let Some((i, _)) = self.sent.front().cloned() {
                self.take(st);
                if i == id {
                    break;
                }
            }
        }
    }
    /// The turn is over and took everything sent during it.
    fn all_taken(&mut self, st: &mut Step) {
        while !self.sent.is_empty() {
            self.take(st);
        }
    }
    /// What still waits was thrown away (Stop cleared the agent's queue).
    fn all_dropped(&mut self, st: &mut Step) {
        for (id, busy) in std::mem::take(&mut self.sent) {
            if busy && !id.is_empty() {
                st.emit(ev("message.dropped", json!({"id": id})));
            }
        }
    }
    /// Only the queued ones still wait (the agent runs them next).
    fn keep_queued(&mut self) {
        self.sent.retain(|(_, busy)| *busy);
    }
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

pub(crate) fn ev(name: &str, fields: Value) -> Event {
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
    /// The line to show for an exit reason, from the useful lines of the program's stderr ([`exit_why`]): a missing
    /// login in plain words, else the last line.
    fn explain(&self, err: &str) -> String {
        last_line(err).to_string()
    }
    /// The agent's name in a sentence ("Claude Code did not answer …").
    fn name(&self) -> &str {
        "The agent"
    }
    /// The program found is maybe not the agent at all (`Unrecognized`): its own reason wins over "old version".
    fn unrecognized(&self) -> bool {
        false
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
        _ if acp_agent(id).is_some() => Some(Box::new(Acp::new(acp_agent(id)?, cwd, resume))),
        _ => None,
    }
}

/// An agent program found in none of its install layouts (`sessions::LAYOUTS`), so maybe another program with the
/// same name: when it ends before printing one JSON line, its exit reason says so and names the install line,
/// instead of that other program's own stderr. Everything else is the agent's adapter unchanged.
struct Unrecognized {
    inner: Box<dyn Adapter>,
    /// `` `<path>` does not look like <agent> … ``
    note: String,
    spoke: bool,
}

impl Unrecognized {
    fn wrap(inner: Box<dyn Adapter>, id: &str, path: &Path) -> Box<dyn Adapter> {
        let (Some(a), Some(l)) = (agent(id), layout(id)) else { return inner };
        let note = format!("{} does not look like {} (it is not where {} installs, and it ended without answering in its chat mode). Install {}: {}", path.display(), a.label, a.label, a.label, l.install);
        Box::new(Unrecognized { inner, note, spoke: false })
    }
}

impl Adapter for Unrecognized {
    fn start(&mut self) -> Step {
        self.inner.start()
    }
    fn on_line(&mut self, line: &str) -> Step {
        self.spoke |= serde_json::from_str::<Value>(line.trim_start_matches('\u{feff}')).is_ok();
        self.inner.on_line(line)
    }
    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        self.inner.on_input(input)
    }
    fn in_turn(&self) -> bool {
        self.inner.in_turn()
    }
    fn name(&self) -> &str {
        self.inner.name()
    }
    fn unrecognized(&self) -> bool {
        !self.spoke
    }
    fn explain(&self, err: &str) -> String {
        let inner = self.inner.explain(err);
        // a program that spoke the protocol, or said it is not signed in, is the agent after all
        if self.spoke || inner.contains("not signed in") {
            inner
        } else {
            self.note.clone()
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------------------------

pub(crate) fn s(v: &Value, k: &str) -> String {
    v.get(k).and_then(Value::as_str).unwrap_or("").to_string()
}

pub(crate) fn clip(t: &str, n: usize) -> String {
    let one = t.split_whitespace().collect::<Vec<_>>().join(" ");
    if one.chars().count() <= n {
        one
    } else {
        format!("{}…", one.chars().take(n - 1).collect::<String>())
    }
}

// ---------------------------------------------------------------------------------------------
// Subagents: one agent-neutral event for every agent
// ---------------------------------------------------------------------------------------------

/// The subagents a session's agent started, as ONE event shape whatever the agent (Claude Code's Agent/Task tool,
/// Codex sub-agent threads, OmO's `task`; later any ACP agent): `{"event": "subagent", id, agent, name, goal,
/// delegation, index, count, state, model?, tool?, step?, summary?, seconds?}`. `id` is stable for the subagent
/// (a later event with the same id updates its row); `delegation` groups the subagents started together (one fan-out);
/// `state` is queued | running | thinking | done | failed | cancelled. omher only shows these: it never assigns,
/// steers or stops a subagent.
#[derive(Default)]
struct Subagents {
    agent: &'static str,
    subs: HashMap<String, Sub>,
    /// the fan-out filling now: its key and how many it has
    fanout: (String, usize),
}

struct Sub {
    name: String,
    goal: String,
    model: String,
    delegation: String,
    index: usize,
    /// its last message so far: its answer when it ends without one of its own
    text: String,
    ended: bool,
}

impl Subagents {
    fn new(agent: &'static str) -> Subagents {
        Subagents { agent, ..Subagents::default() }
    }
    fn has(&self, id: &str) -> bool {
        self.subs.contains_key(id)
    }
    /// Registers `id` in fan-out `delegation` (a new key starts a new fan-out), or returns it as it is.
    fn add(&mut self, id: &str, delegation: &str, name: &str, goal: &str, model: &str) -> &mut Sub {
        if !self.subs.contains_key(id) {
            if self.fanout.0 != delegation {
                self.fanout = (delegation.to_string(), 0);
            }
            let index = self.fanout.1;
            self.fanout.1 += 1;
            self.subs.insert(id.to_string(), Sub { name: clip(name, 80), goal: clip(goal, 160), model: String::new(), delegation: delegation.to_string(), index, text: String::new(), ended: false });
        }
        let s = self.subs.get_mut(id).unwrap();
        if !model.is_empty() {
            s.model = model.to_string();
        }
        if s.goal.is_empty() && !goal.is_empty() {
            s.goal = clip(goal, 160);
        }
        s
    }
    /// The event for `id` in `state`, with `extra` fields (tool, step, summary, seconds). Unknown ids give none.
    fn event(&self, id: &str, state: &str, extra: Value) -> Option<Event> {
        let s = self.subs.get(id)?;
        let count = if self.fanout.0 == s.delegation { self.fanout.1 } else { s.index + 1 };
        let mut f = json!({"id": id, "agent": self.agent, "name": s.name, "goal": s.goal, "delegation": s.delegation, "index": s.index, "count": count, "state": state});
        if !s.model.is_empty() {
            f["model"] = Value::String(s.model.clone());
        }
        if let (Value::Object(m), Value::Object(x)) = (&mut f, extra) {
            m.extend(x.into_iter().filter(|(_, v)| !v.is_null() && v.as_str() != Some("")));
        }
        Some(ev("subagent", f))
    }
    /// The subagents not yet ended, in the order they started.
    fn open(&self) -> Vec<String> {
        let mut v: Vec<(&String, &Sub)> = self.subs.iter().filter(|(_, s)| !s.ended).collect();
        v.sort_by(|a, b| (&a.1.delegation, a.1.index).cmp(&(&b.1.delegation, b.1.index)));
        v.into_iter().map(|(k, _)| k.clone()).collect()
    }
    /// A step the subagent runs now.
    fn step(&self, st: &mut Step, id: &str, tool: &str, step: &str) {
        st.events.extend(self.event(id, "running", json!({"tool": tool, "step": clip(step, 120)})));
    }
    /// A file edit the subagent runs now, with its change per file (`tool.diff`'s shape): the row's step opens to it.
    /// Said again with the same step when the edit has run, so the change shown is what it finally was.
    fn edit(&self, st: &mut Step, id: &str, step: &str, files: Vec<Value>) {
        st.events.extend(self.event(id, "running", json!({"tool": "patch", "step": clip(step, 120), "diff": files})));
    }
    /// Ends `id` once: done (its answer, else its last message), failed (the error) or cancelled.
    fn end(&mut self, st: &mut Step, id: &str, state: &str, answer: &str, secs: Option<f64>) {
        let Some(s) = self.subs.get_mut(id) else { return };
        if s.ended {
            return;
        }
        s.ended = true;
        let text = if answer.trim().is_empty() { s.text.clone() } else { answer.to_string() };
        // one plain line: a fenced answer ("```\nalpha line\n```") reads as its text
        let mut f = json!({"summary": clip(&text.replace("```", " "), 200)});
        if let Some(x) = secs {
            f["seconds"] = json!((x * 10.0).round() / 10.0);
        }
        st.events.extend(self.event(id, state, f));
    }
}

/// The ask (approval or question) events in `st` from index `from` on carry who asked: `subagent: {id, name}`.
fn tag_asks(st: &mut Step, from: usize, id: &str, name: &str) {
    for e in &mut st.events[from..] {
        if matches!(s(e, "event").as_str(), "approval.request" | "clarify.request") {
            e["subagent"] = json!({"id": id, "name": name});
        }
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

/// How many lines of one file's change the diff view gets, and how long one line may be. The rest is counted
/// (`more`), never sent.
const DIFF_LINES: usize = 400;
const DIFF_LINE_CHARS: usize = 2000;

/// The text's lines (a trailing newline ends the last line, it does not start an empty one).
fn text_lines(t: &str) -> Vec<&str> {
    if t.is_empty() {
        return vec![];
    }
    t.strip_suffix('\n').unwrap_or(t).split('\n').map(|l| l.strip_suffix('\r').unwrap_or(l)).collect()
}

/// One file's change for the diff view (`tool.diff`), in one agent-neutral shape: `lines` start with `+`, `-`,
/// ` ` (context) or `@@` (a hunk), at most [`DIFF_LINES`] of them; `added` / `removed` count every line.
pub(crate) fn diff_file(path: &str, kind: &str, lines: Vec<String>) -> Value {
    let added = lines.iter().filter(|l| l.starts_with('+')).count();
    let removed = lines.iter().filter(|l| l.starts_with('-')).count();
    let more = lines.len().saturating_sub(DIFF_LINES);
    let kept: Vec<String> = lines.into_iter().take(DIFF_LINES).map(|l| if l.chars().count() > DIFF_LINE_CHARS { l.chars().take(DIFF_LINE_CHARS).collect() } else { l }).collect();
    let mut f = json!({"path": path, "kind": kind, "lines": kept, "added": added, "removed": removed});
    if more > 0 {
        f["more"] = json!(more);
    }
    f
}

/// `prefix` before every line of `t`.
fn marked(prefix: char, t: &str) -> Vec<String> {
    text_lines(t).into_iter().map(|l| format!("{prefix}{l}")).collect()
}

/// The change a file tool call asks for, from its input alone: Claude Code `Write {file_path, content}` /
/// `Edit {file_path, old_string, new_string}` / `MultiEdit {file_path, edits}`, pi `write {path, content}` /
/// `edit {path, edits:[{oldText,newText}]}`. `None` for anything else (oh-my-pi's hashline edit has no plain text).
pub(crate) fn input_diff(name: &str, input: &Value, cwd: &str) -> Option<Value> {
    if tool_kind(name) != "patch" {
        return None;
    }
    let path = ["file_path", "path", "notebook_path"].iter().map(|k| s(input, k)).find(|p| !p.is_empty())?;
    let mut lines = Vec::new();
    let mut kind = "update";
    if let Some(c) = input.get("content").and_then(Value::as_str) {
        kind = "add";
        lines.extend(marked('+', c));
    }
    let pair = |old: &str, new: &str, lines: &mut Vec<String>| {
        if !lines.is_empty() {
            lines.push("@@".into());
        }
        lines.extend(marked('-', old));
        lines.extend(marked('+', new));
    };
    if input.get("old_string").is_some() || input.get("new_string").is_some() {
        pair(&s(input, "old_string"), &s(input, "new_string"), &mut lines);
    }
    for e in input.get("edits").and_then(Value::as_array).into_iter().flatten() {
        let old = if e.get("old_string").is_some() { s(e, "old_string") } else { s(e, "oldText") };
        let new = if e.get("new_string").is_some() { s(e, "new_string") } else { s(e, "newText") };
        pair(&old, &new, &mut lines);
    }
    if lines.is_empty() {
        return None;
    }
    Some(diff_file(&rel(&path, cwd), kind, lines))
}

/// The change Claude Code made, from its tool result (`structuredPatch` hunks with context, or a new file's
/// content): what the diff view shows once the edit ran.
fn claude_result_diff(tur: &Value, cwd: &str) -> Option<Value> {
    let path = s(tur, "filePath");
    if path.is_empty() {
        return None;
    }
    let hunks = tur.get("structuredPatch").and_then(Value::as_array).filter(|h| !h.is_empty());
    if let Some(hunks) = hunks {
        let mut lines = Vec::new();
        for h in hunks {
            let n = |k: &str| h.get(k).and_then(Value::as_u64).unwrap_or(0);
            lines.push(format!("@@ -{},{} +{},{} @@", n("oldStart"), n("oldLines"), n("newStart"), n("newLines")));
            lines.extend(h.get("lines").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str).map(String::from));
        }
        return Some(diff_file(&rel(&path, cwd), if s(tur, "type") == "create" { "add" } else { "update" }, lines));
    }
    if s(tur, "type") == "create" {
        return Some(diff_file(&rel(&path, cwd), "add", marked('+', &s(tur, "content"))));
    }
    None
}

/// The files of a Codex `fileChange` item: an added file's diff is its content, a deleted one's its old content,
/// an update's a unified diff (its `---` / `+++` headers dropped).
fn codex_diff(item: &Value, cwd: &str) -> Vec<Value> {
    item.get("changes")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|c| !s(c, "path").is_empty())
        .map(|c| {
            let diff = s(c, "diff");
            let kind = c.get("kind").map(|k| s(k, "type")).unwrap_or_default();
            let (kind, lines) = match kind.as_str() {
                "add" => ("add", marked('+', &diff)),
                "delete" => ("delete", marked('-', &diff)),
                _ => (
                    "update",
                    text_lines(&diff)
                        .into_iter()
                        .filter(|l| !(l.starts_with("+++") || l.starts_with("---") || l.starts_with("diff --git") || l.starts_with("index ")))
                        .map(String::from)
                        .collect(),
                ),
            };
            diff_file(&rel(&s(c, "path"), cwd), kind, lines)
        })
        .collect()
}

/// A `plan` event: the agent's own todo list as it stands now, `status` pending | in_progress | completed.
pub(crate) fn plan_event(items: &[(String, String)]) -> Event {
    let items: Vec<Value> = items.iter().filter(|(t, _)| !t.trim().is_empty()).map(|(t, st)| json!({"text": clip(t, 200), "status": st})).collect();
    ev("plan", json!({"items": items}))
}

/// A `thinking` event, with the text the agent sent (none when it sends only a marker).
pub(crate) fn thinking_event(text: &str) -> Event {
    if text.is_empty() {
        ev("thinking", json!({}))
    } else {
        ev("thinking", json!({"text": text}))
    }
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

/// How a turn ends when its program exits in the middle of it: a clean exit (code 0, nothing on stderr) is
/// "ended", which the UI shows in grey; any other exit is an "error" carrying the reason.
pub(crate) fn exit_turn_end(code: Option<i32>, err: &str) -> Value {
    if code == Some(0) && err.is_empty() {
        return ev("turn.end", json!({"outcome": "ended"}));
    }
    let e = if err.is_empty() { "the agent stopped" } else { err };
    ev("turn.end", json!({"outcome": "error", "error": e}))
}

/// The useful lines of what a program wrote to stderr, in order: colour codes removed; warnings dropped
/// (`Warning: …`, `note: …`, a `WARN`/`INFO` log line, Codex's "ignoring 1 unrecognized configuration setting"), and
/// so are indented lines (the file a start-up warning names under it, a stack's frames, a list under a heading) and
/// help text (`Usage: …`, "For more information …", a heading ending in `:`). Each is at most 200 characters.
fn exit_lines(tail: &str) -> Vec<String> {
    let is_log = |l: &str| l.len() > 11 && l.as_bytes()[..4].iter().all(u8::is_ascii_digit) && l.as_bytes()[4] == b'-' && l.as_bytes()[10] == b'T';
    let skip = |l: &str| {
        let low = l.to_ascii_lowercase();
        low.starts_with("warning:")
            || low.starts_with("warn:")
            || low.starts_with("note:")
            || (is_log(l) && [" WARN ", " INFO ", " DEBUG ", " TRACE "].iter().any(|w| l.contains(w)))
            || low.contains("unrecognized configuration setting")
            || low.starts_with("usage:")
            || low.starts_with("for more information")
            || l.ends_with(':')
    };
    tail.lines().map(strip_ansi).filter(|l| !l.starts_with([' ', '\t'])).map(|l| l.trim().to_string()).filter(|l| !l.is_empty() && !skip(l)).map(|l| clip(&l, 200)).collect()
}

/// The reason in a program's stderr: its last useful line ([`exit_lines`]), else nothing.
pub(crate) fn exit_reason(tail: &str) -> String {
    exit_lines(tail).pop().unwrap_or_default()
}

/// What an exit's stderr says about why the program failed, for [`Adapter::explain`]: every useful line, so a
/// sign-in hint anywhere in it is found (the reason shown is the last one). Nothing when the program ended with
/// code 0: an orderly close, where a warning it printed at start is not why it ended.
pub(crate) fn exit_why(code: Option<i32>, tail: &str) -> String {
    if code == Some(0) {
        String::new()
    } else {
        exit_lines(tail).join("\n")
    }
}

/// The last non-empty line of `text`.
pub(crate) fn last_line(text: &str) -> &str {
    text.lines().rev().map(str::trim).find(|l| !l.is_empty()).unwrap_or("")
}

/// The protocol messages on one line of an agent's stdout, in order: a leading byte-order mark is dropped, and a line
/// holding two JSON objects back to back (`{…}{…}`, a missed newline) yields both. A line that does not start with a
/// JSON object (a banner, a terminal frame) yields nothing; after a bad value the rest of the line is dropped.
pub(crate) fn protocol_lines(line: &str) -> Vec<&str> {
    let line = line.trim_start_matches('\u{feff}');
    let mut out = Vec::new();
    let mut values = serde_json::Deserializer::from_str(line).into_iter::<serde::de::IgnoredAny>();
    let mut from = 0;
    while let Some(Ok(_)) = values.next() {
        let to = values.byte_offset();
        let one = line[from..to].trim();
        if !one.starts_with('{') {
            break;
        }
        out.push(one);
        from = to;
    }
    out
}

/// How long a chat's program has to print its first protocol message. Measured on this Mac (load about 4.5) from
/// start to the first JSON line: Claude Code 0.25 s, Codex 0.11-0.29 s, OmO 0.71-1.48 s. 20 s leaves a slow first
/// start (a cold disk, an antivirus scan of node on Windows) more than ten times the slowest of those.
pub(crate) const START_DEADLINE: Duration = Duration::from_secs(20);

/// The reason a session ends with when its program never spoke its chat protocol: an old version that does not know
/// the structured mode, or a start that hangs. The UI shows its own words for it (with the install line); this text
/// is what reaches the session when it has none.
pub(crate) fn no_chat_mode(agent: &str) -> String {
    format!("{agent} did not answer in chat mode; it may be an old version: update it, then Restart.")
}

/// Whether `reason` (an exit's stderr) says the program refused omher's chat-mode arguments (`--mode rpc`,
/// `app-server`, `--input-format` …): a version that does not have the mode.
pub(crate) fn refused_chat_mode(reason: &str) -> bool {
    let low = reason.to_ascii_lowercase();
    ["unknown option", "unknown argument", "unexpected argument", "unrecognized option", "unrecognized argument", "invalid option", "unknown command", "unrecognized subcommand"]
        .iter()
        .any(|p| low.contains(p))
}

/// `text` without terminal colour and cursor codes (`ESC [ … letter`).
fn strip_ansi(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut it = text.chars().peekable();
    while let Some(c) = it.next() {
        if c == '\u{1b}' {
            if it.peek() == Some(&'[') {
                it.next();
                for d in it.by_ref() {
                    if d.is_ascii_alphabetic() {
                        break;
                    }
                }
            }
            continue;
        }
        out.push(c);
    }
    out
}

/// What a tool call is about, for the progress line and the approval card: the command, path, pattern,
/// query or URL from its arguments, else a short JSON.
fn tool_detail(input: &Value) -> String {
    if let Some(d) = known_detail(input) {
        return d;
    }
    match input {
        Value::Object(m) if m.is_empty() => String::new(),
        Value::Null => String::new(),
        other => clip(&other.to_string(), 160),
    }
}

/// The command, path, pattern, query or URL a tool call's arguments name, when they name one.
fn known_detail(input: &Value) -> Option<String> {
    for k in ["command", "cmd", "file_path", "path", "notebook_path", "pattern", "query", "url", "code", "description", "prompt"] {
        if let Some(v) = input.get(k) {
            if let Some(t) = v.as_str() {
                if !t.trim().is_empty() {
                    return Some(clip(t, 160));
                }
            }
            if let Some(a) = v.as_array() {
                let parts: Vec<String> = a.iter().filter_map(|x| x.as_str().map(String::from)).collect();
                if !parts.is_empty() {
                    return Some(clip(&parts.join(" "), 160));
                }
            }
        }
    }
    // oh-my-pi's hashline edit: `[path#TAG]` on the first line of `input`
    if let Some(t) = input.get("input").and_then(Value::as_str) {
        let first = t.lines().find(|l| !l.trim().is_empty()).unwrap_or("").trim();
        let first = first.trim_start_matches('[').split('#').next().unwrap_or(first).trim_end_matches(']');
        if !first.is_empty() {
            return Some(clip(first, 160));
        }
    }
    None
}

/// How much of a plan (`ExitPlanMode`) the approval card gets; a longer one is cut there.
const PLAN_CHARS: usize = 20_000;

/// The line an approval card shows for a tool that is neither a command nor a file edit: the skill's name (and
/// its arguments) for `Skill`, the command / path / query when the input has one ([`tool_detail`]'s keys), else each
/// top-level field as `name: value`, joined with ` · ` (a nested value as compact JSON), never the whole input as
/// one JSON string.
fn ask_detail(name: &str, input: &Value) -> String {
    if name == "Skill" {
        let line = [s(input, "skill"), s(input, "args")].into_iter().filter(|x| !x.trim().is_empty()).collect::<Vec<_>>().join(" ");
        if !line.is_empty() {
            return clip(&line, 160);
        }
    }
    if let Some(d) = known_detail(input) {
        return d;
    }
    let Value::Object(m) = input else { return tool_detail(input) };
    let parts: Vec<String> = m
        .iter()
        .filter_map(|(k, v)| {
            let t = match v {
                Value::Null => return None,
                Value::String(t) if t.trim().is_empty() => return None,
                Value::String(t) => t.clone(),
                Value::Array(a) if a.iter().all(Value::is_string) => a.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", "),
                other => other.to_string(),
            };
            Some(format!("{k}: {t}"))
        })
        .collect();
    clip(&parts.join(" · "), 160)
}

/// The bot chat's tool names for the verbs on the progress line ("Running", "Reading", "Editing" …).
pub(crate) fn tool_kind(name: &str) -> &str {
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
pub(crate) fn call_detail(name: &str, input: &Value, cwd: &str) -> String {
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
    /// the subagent (tool_use id of its Agent call) that asked each pending request, when one did
    ask_subs: HashMap<String, String>,
    model: String,
    /// a model the person picked while a turn ran: Claude Code uses it from the next turn on, whose init confirms it
    model_next: String,
    /// the turn that ran during that pick has ended: the next init settles the header, whatever it names
    next_due: bool,
    /// model ids (`haiku`, `claude-haiku-5-5`) -> the name Claude Code shows for them
    labels: HashMap<String, String>,
    /// the last assistant message carried an error kind (`authentication_failed`, …)
    error_kind: String,
    /// messages sent and not yet echoed back taken (`--replay-user-messages`)
    waiting: Waiting,
    /// its subagents (Agent/Task calls) by tool_use id
    subs: Subagents,
    /// Claude Code's agent / task id -> the tool_use id of its Agent call (asks and task events name the agent id)
    agent_ids: HashMap<String, String>,
    /// background tasks Claude Code says are still running (`background_tasks_changed`)
    background: usize,
    /// the background commands among them (`task_type` `local_bash`), by task id: Stop with no turn running asks
    /// Claude Code to stop each (`stop_task`); its `interrupt` alone stops the subagents at once but a command only
    /// about ten seconds later (claude-14-background-stop.jsonl)
    bg_commands: Vec<String>,
    /// subagents that run in the background: their task notification ends them (a foreground one ends with its
    /// tool result, which carries its own words and model)
    bg_subs: std::collections::HashSet<String>,
    /// the uuids of the person's messages Claude Code echoed back in this process, oldest first: what a rewind
    /// takes back (the last one)
    sent_uuids: Vec<String>,
    /// its own todo list (TaskCreate / TaskUpdate, or TodoWrite): (task id or the call's id until it has one, text,
    /// status)
    tasks: Vec<(String, String, String)>,
}

/// Claude Code's todo tools: shown as the turn's checklist (`plan`), never as steps.
const CLAUDE_TODO_TOOLS: [&str; 5] = ["TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"];

impl Claude {
    pub fn new(cwd: &str) -> Claude {
        Claude { cwd: cwd.into(), subs: Subagents::new("claude"), ..Claude::default() }
    }
    /// The tool_use id of the subagent a line or request names (`parent_tool_use_id`, `tool_use_id`, an agent id).
    fn sub_of(&self, v: &Value) -> Option<String> {
        for k in ["parent_tool_use_id", "tool_use_id"] {
            let id = s(v, k);
            if self.subs.has(&id) {
                return Some(id);
            }
        }
        for k in ["agent_id", "task_id"] {
            if let Some(id) = self.agent_ids.get(&s(v, k)) {
                return Some(id.clone());
            }
        }
        None
    }
    /// A line of a subagent's own conversation: its steps; its text is held as its answer, never shown as Claude's.
    fn on_sub_line(&mut self, st: &mut Step, id: &str, v: &Value) {
        let aid = s(v, "agent_id");
        if !aid.is_empty() {
            self.agent_ids.insert(aid, id.to_string());
        }
        if s(v, "type") != "assistant" {
            return;
        }
        for b in v["message"].get("content").and_then(Value::as_array).into_iter().flatten() {
            match s(b, "type").as_str() {
                "tool_use" => {
                    let name = s(b, "name");
                    let input = b.get("input").cloned().unwrap_or(Value::Null);
                    self.subs.step(st, id, tool_kind(&name), &call_detail(&name, &input, &self.cwd));
                }
                "text" => {
                    let t = s(b, "text");
                    if !t.trim().is_empty() {
                        if let Some(sub) = self.subs.subs.get_mut(id) {
                            sub.text = t;
                        }
                    }
                }
                _ => {}
            }
        }
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
    fn plan(&self) -> Event {
        let items: Vec<(String, String)> = self.tasks.iter().map(|(_, t, st)| (t.clone(), st.clone())).collect();
        plan_event(&items)
    }
    /// A todo tool call: the list as it will stand (TodoWrite names it whole; TaskCreate adds one, TaskUpdate
    /// changes one). Whether the list changed.
    fn todo_call(&mut self, name: &str, id: &str, input: &Value) -> bool {
        match name {
            "TodoWrite" => {
                self.tasks = input
                    .get("todos")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .enumerate()
                    .map(|(i, t)| (format!("todo-{i}"), s(t, "content"), s(t, "status")))
                    .filter(|t| !t.1.trim().is_empty())
                    .collect();
                true
            }
            "TaskCreate" => {
                let text = s(input, "subject");
                if text.trim().is_empty() {
                    return false;
                }
                self.tasks.push((id.to_string(), text, "pending".into()));
                true
            }
            "TaskUpdate" => {
                let key = s(input, "taskId");
                let Some(at) = self.tasks.iter().position(|t| t.0 == key) else { return false };
                let status = s(input, "status");
                if status == "deleted" {
                    self.tasks.remove(at);
                    return true;
                }
                let subject = s(input, "subject");
                let t = &mut self.tasks[at];
                if !status.is_empty() {
                    t.2 = status;
                }
                if !subject.trim().is_empty() {
                    t.1 = subject;
                }
                true
            }
            _ => false,
        }
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
            // an ask of a background subagent still running outlives the turn: Claude Code keeps waiting for its
            // answer after `result` (claude-13-late-ask-inside.jsonl); every other ask ends with the turn
            let keep: Vec<String> = self.ask_subs.iter().filter(|(_, id)| self.bg_subs.contains(*id) && self.subs.open().contains(id)).map(|(r, _)| r.clone()).collect();
            self.pending.retain(|r, _| keep.contains(r));
            self.ask_subs.retain(|r, _| keep.contains(r));
            // a foreground subagent lives inside the turn: a turn that ends without its hand-back ended it too
            // (Stop, an error); one in the background goes on and ends by its own task notification
            if outcome != "done" {
                let open: Vec<String> = self.subs.open().into_iter().filter(|id| !self.bg_subs.contains(id)).collect();
                for id in open {
                    self.subs.end(step, &id, "cancelled", "", None);
                }
            }
            // a turn that finished took what was sent during it; one that was stopped runs its queued messages next
            if outcome == "interrupted" {
                self.waiting.keep_queued();
            } else {
                self.waiting.all_taken(step);
            }
            self.next_due = !self.model_next.is_empty();
            let mut f = json!({"outcome": outcome});
            if let Some(e) = error.filter(|e| !e.is_empty()) {
                f["error"] = Value::String(e);
            }
            step.emit(ev("turn.end", f));
        }
    }
}

/// A subagent's answer from Claude Code's hand-back: the text blocks of `tool_use_result.content` without the
/// `<tools-used-before-summary>` block; else the tool_result's own text after the frame's "The report follows:".
fn claude_answer(tur: &Value, block: &Value) -> String {
    let texts = |c: &Value| -> Vec<String> {
        match c {
            Value::String(t) => vec![t.clone()],
            Value::Array(a) => a.iter().filter(|b| s(b, "type") == "text").map(|b| s(b, "text")).collect(),
            _ => vec![],
        }
    };
    let own: Vec<String> = texts(&tur["content"]).into_iter().filter(|t| !t.trim_start().starts_with("<tools-used-before-summary>")).collect();
    let text = if own.iter().any(|t| !t.trim().is_empty()) {
        own.join("\n")
    } else {
        let all = texts(&block["content"]).join("\n");
        let body = all.split("The report follows:").nth(1).unwrap_or(&all);
        body.split("\nagentId:").next().unwrap_or(body).to_string()
    };
    text.replace("```", "").trim().to_string()
}

const CLAUDE_SIGNED_OUT: &str = "Claude Code is not signed in. Sign in from Settings › Accounts (or open Terminal and run /login), then Restart.";

impl Adapter for Claude {
    fn name(&self) -> &str {
        "Claude Code"
    }

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
                // the turn after a pick made mid-turn: its init names the model it runs on, which the header now shows
                if !self.model_next.is_empty() && (self.next_due || self.label(&self.model_next) == self.label(&self.model)) {
                    self.model_next.clear();
                    f["model_next"] = Value::String(String::new());
                }
                self.next_due = false;
                let mode = s(&v, "permissionMode");
                if !mode.is_empty() {
                    f["approval"] = Value::String(mode.clone());
                    f["mode"] = Value::String(mode);
                }
                st.emit(ev("session.info", f));
            }
            // a subagent (Agent/Task) or a background command started or ended; what still runs in the background
            "system" if s(&v, "subtype") == "task_started" => {
                if let Some(id) = self.sub_of(&v) {
                    self.agent_ids.insert(s(&v, "task_id"), id);
                }
            }
            "system" if s(&v, "subtype") == "task_notification" => {
                if let Some(id) = self.sub_of(&v).filter(|id| self.bg_subs.contains(id)) {
                    let state = match s(&v, "status").as_str() {
                        "failed" | "error" => "failed",
                        "stopped" | "killed" | "cancelled" | "interrupted" => "cancelled",
                        _ => "done",
                    };
                    let secs = v.get("usage").and_then(|u| u.get("duration_ms")).and_then(Value::as_u64).map(|ms| ms as f64 / 1000.0);
                    self.subs.end(&mut st, &id, state, &s(&v, "summary"), secs);
                    // what it asked and never got answered is no longer waited for
                    let gone: Vec<String> = self.ask_subs.iter().filter(|(_, x)| **x == id).map(|(r, _)| r.clone()).collect();
                    for r in gone {
                        self.ask_subs.remove(&r);
                        if self.pending.remove(&r).is_some() {
                            st.emit(ev("prompt.expired", json!({"request_id": r, "reason": "cancelled"})));
                        }
                    }
                }
            }
            "system" if s(&v, "subtype") == "background_tasks_changed" => {
                let tasks = v.get("tasks").and_then(Value::as_array).cloned().unwrap_or_default();
                self.bg_commands = tasks.iter().filter(|t| s(t, "task_type") == "local_bash").map(|t| s(t, "task_id")).filter(|id| !id.is_empty()).collect();
                let n = tasks.len();
                if n != self.background {
                    self.background = n;
                    st.emit(ev("session.info", json!({"background": n})));
                }
            }
            // a subagent's own conversation
            _ if sub => {
                if let Some(id) = self.sub_of(&v) {
                    self.on_sub_line(&mut st, &id, &v);
                }
            }
            // the permission mode changed (ours, or Claude Code's own ExitPlanMode)
            "system" if s(&v, "subtype") == "status" && !s(&v, "permissionMode").is_empty() => {
                st.emit(ev("session.info", json!({"mode": s(&v, "permissionMode")})));
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
                    // its own slash commands and skills (a skill's description ends with where it lives)
                    let commands: Vec<Value> = body
                        .get("commands")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter(|c| !s(c, "name").is_empty())
                        .map(|c| {
                            let d = s(c, "description");
                            let skill = d.ends_with("(user)") || d.ends_with("(project)");
                            command_entry(&s(c, "name"), &d, &s(c, "argumentHint"), if skill { "skill" } else { "command" }, "/")
                        })
                        .collect();
                    if !commands.is_empty() {
                        st.emit(ev("session.commands", json!({"commands": commands})));
                    }
                    let mode = s(body, "current_permission_mode");
                    if !mode.is_empty() {
                        st.emit(ev("session.info", json!({"mode": mode})));
                    }
                    // the effort levels of the model it runs (the `default` entry until it names one)
                    let levels = body
                        .get("models")
                        .and_then(Value::as_array)
                        .and_then(|ms| ms.iter().find(|m| s(m, "value") == "default").or(ms.first()))
                        .filter(|m| m.get("supportsEffort").and_then(Value::as_bool).unwrap_or(false))
                        .and_then(|m| m.get("supportedEffortLevels").cloned())
                        .unwrap_or(json!([]));
                    if levels.as_array().is_some_and(|l| !l.is_empty()) {
                        st.emit(ev("session.efforts", json!({"levels": levels})));
                        self.control(&mut st, "settings", json!({"subtype": "get_settings"}));
                    }
                    self.control(&mut st, "context", json!({"subtype": "get_context_usage"}));
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
                } else if id.starts_with("omher-settings-") {
                    let effort = s(&body["applied"], "effort");
                    if !effort.is_empty() {
                        st.emit(ev("session.info", json!({"effort": effort})));
                    }
                } else if id.starts_with("omher-context-") {
                    // the CLI's own count of the context in use and its size
                    let (used, max) = (body.get("totalTokens").and_then(Value::as_u64), body.get("maxTokens").and_then(Value::as_u64));
                    if let (Some(used), Some(max)) = (used, max.filter(|m| *m > 0)) {
                        st.emit(ev("session.usage", json!({"used": used, "max": max})));
                    }
                } else if id.starts_with("omher-mode-") || id.starts_with("omher-effort-") {
                    if s(r, "subtype") == "success" {
                        if id.starts_with("omher-effort-") {
                            self.control(&mut st, "settings", json!({"subtype": "get_settings"}));
                        }
                    } else {
                        let what = if id.starts_with("omher-mode-") { "Mode" } else { "Effort" };
                        st.emit(ev("session.error", json!({"message": format!("{what} not changed: {}", s(r, "error"))})));
                    }
                } else if id.starts_with("omher-rewind-") {
                    // the conversation is back to before the person's last message: the chat takes that message
                    // back and offers its text again
                    if s(r, "subtype") == "success" && body.get("rewound").and_then(Value::as_bool) == Some(true) {
                        self.sent_uuids.pop();
                        st.emit(ev("rewound", json!({"text": s(body, "prefillText")})));
                    } else {
                        let why = if s(r, "error").is_empty() { s(body, "error") } else { s(r, "error") };
                        st.emit(ev("session.error", json!({"message": clip(&format!("Not taken back: {}", if why.is_empty() { "Claude Code refused" } else { &why }), 200)})));
                    }
                    st.emit(ev("session.info", json!({"rewind": !self.sent_uuids.is_empty()})));
                } else if id.starts_with("omher-model-") {
                    if s(r, "subtype") == "success" {
                        let m = s(body, "model");
                        if self.turn {
                            // the running turn keeps the model it started on: the header says the pick is for the next
                            // turn, and that turn's init confirms it
                            if !m.is_empty() && self.label(&m) != self.label(&self.model) {
                                self.model_next = m;
                                st.emit(ev("session.info", json!({"model_next": self.label(&self.model_next)})));
                            } else {
                                self.model_next.clear();
                                st.emit(ev("session.info", json!({"model_next": ""})));
                            }
                        } else {
                            if !m.is_empty() {
                                self.model = m;
                            }
                            self.model_next.clear();
                            st.emit(ev("session.info", json!({"model": self.label(&self.model), "model_next": ""})));
                        }
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
                            if let Some(id) = self.sub_of(req) {
                                let name = self.subs.subs.get(&id).map(|x| if x.goal.is_empty() { x.name.clone() } else { x.goal.clone() }).unwrap_or_default();
                                let n = st.events.len() - 1;
                                tag_asks(&mut st, n, &id, &name);
                                self.ask_subs.insert(rid.clone(), id);
                            }
                            return st;
                        }
                    }
                    let shown = if s(req, "display_name").is_empty() { name.clone() } else { s(req, "display_name") };
                    // plan mode's end: the plan the agent wrote (markdown, whole), asked as one yes or no; Claude Code
                    // offers no rule to keep for it, so there is no "for session"
                    let plan = if name == "ExitPlanMode" { input.get("plan").and_then(Value::as_str).map(|p| p.chars().take(PLAN_CHARS).collect::<String>()) } else { None };
                    let (title, command) = match tool_kind(&name) {
                        _ if plan.is_some() => ("Start working on this plan?".to_string(), String::new()),
                        "terminal" => ("Run this command?".to_string(), tool_detail(&input)),
                        "patch" => {
                            let path = ["file_path", "path", "notebook_path"].iter().map(|k| s(&input, k)).find(|p| !p.is_empty()).unwrap_or_default();
                            (format!("Allow {shown} to change {}?", if path.is_empty() { "files".to_string() } else { rel(&path, &self.cwd) }), String::new())
                        }
                        _ => (format!("Allow {shown}?"), ask_detail(&name, &input)),
                    };
                    self.pending.insert(rid.clone(), ClaudeAsk::Tool(name, input, req.get("permission_suggestions").cloned().unwrap_or(Value::Null)));
                    let mut f = json!({"request_id": rid, "title": title, "command": command, "choices": CHOICES});
                    if let Some(p) = plan {
                        f["plan"] = Value::String(p);
                        f["choices"] = json!(["deny", "once"]);
                    }
                    st.emit(ev("approval.request", with_cwd(f, &self.cwd)));
                    // asked inside a subagent (`agent_id`): the card says which one
                    if let Some(id) = self.sub_of(req) {
                        let name = self.subs.subs.get(&id).map(|x| if x.goal.is_empty() { x.name.clone() } else { x.goal.clone() }).unwrap_or_default();
                        let n = st.events.len() - 1;
                        tag_asks(&mut st, n, &id, &name);
                        self.ask_subs.insert(rid.clone(), id);
                    }
                } else {
                    // hooks, MCP messages …: omher registers none of them
                    st.out(json!({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "not supported by omher"}}));
                }
            }
            // Stop (or Claude Code itself) withdrew a permission request it had asked
            "control_cancel_request" => {
                let rid = s(&v, "request_id");
                self.ask_subs.remove(&rid);
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
                        "thinking_delta" => {
                            self.begin(&mut st, true);
                            st.emit(thinking_event(&s(d, "thinking")));
                        }
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
                            // its todo list: one checklist that changes in place, not a step per update
                            if CLAUDE_TODO_TOOLS.contains(&name.as_str()) {
                                if self.todo_call(&name, &s(b, "id"), &input) {
                                    st.emit(self.plan());
                                }
                                continue;
                            }
                            st.emit(ev("tool.start", json!({"tool_id": s(b, "id"), "name": tool_kind(&name), "detail": call_detail(&name, &input, &self.cwd)})));
                            // a file edit: the change it asks for, until its result says what it did
                            if let Some(f) = input_diff(&name, &input, &self.cwd) {
                                st.emit(ev("tool.diff", json!({"tool_id": s(b, "id"), "files": [f]})));
                            }
                            // a subagent: one Agent/Task call; the calls of one message start together (one fan-out)
                            if tool_kind(&name) == "delegate_task" {
                                let id = s(b, "id");
                                let kind = s(&input, "subagent_type");
                                let goal = if s(&input, "description").is_empty() { s(&input, "prompt") } else { s(&input, "description") };
                                self.subs.add(&id, &format!("claude-{mid}"), if kind.is_empty() { "subagent" } else { &kind }, &goal, &s(&input, "model"));
                                if input.get("run_in_background").and_then(Value::as_bool) == Some(true) {
                                    self.bg_subs.insert(id.clone());
                                }
                                st.events.extend(self.subs.event(&id, "running", json!({})));
                            }
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
            // Claude Code took a message the person sent (`--replay-user-messages`): a queued one is not waiting now
            "user" if !sub && v.get("isReplay").and_then(Value::as_bool) == Some(true) => {
                let uuid = s(&v, "uuid");
                if !uuid.is_empty() {
                    self.sent_uuids.push(uuid);
                    if self.sent_uuids.len() == 1 {
                        st.emit(ev("session.info", json!({"rewind": true})));
                    }
                }
                self.waiting.take(&mut st);
                // a message queued behind a stopped turn starts its own
                self.begin(&mut st, false);
            }
            "user" if !sub => {
                let tur = v.get("tool_use_result").or_else(|| v.get("toolUseResult")).cloned().unwrap_or(Value::Null);
                for b in v["message"].get("content").and_then(Value::as_array).into_iter().flatten() {
                    if s(b, "type") == "tool_result" {
                        let ok = !b.get("is_error").and_then(Value::as_bool).unwrap_or(false);
                        let tid = s(b, "tool_use_id");
                        // a task Claude Code created: from now on its own id names it (TaskUpdate's taskId)
                        let task_id = tur.get("task").map(|t| s(t, "id")).unwrap_or_default();
                        if let Some(t) = self.tasks.iter_mut().find(|t| t.0 == tid) {
                            if !task_id.is_empty() {
                                t.0 = task_id;
                            }
                            continue;
                        }
                        // the change the edit made, with the lines around it
                        if ok {
                            if let Some(f) = claude_result_diff(&tur, &self.cwd) {
                                st.emit(ev("tool.diff", json!({"tool_id": tid, "files": [f]})));
                            }
                        }
                        st.emit(ev("tool.end", json!({"tool_id": tid, "name": "", "ok": ok, "ms": 0})));
                        // a subagent's hand-back: its own words (`tool_use_result.content`), not the frame around them;
                        // a background one only launched here and ends with its task notification
                        if self.subs.has(&tid) && matches!(s(&tur, "status").as_str(), "async_launched" | "teammate_spawned") {
                            self.bg_subs.insert(tid.clone());
                            // its launch names the model it runs on (a foreground one names it in its hand-back)
                            let model = s(&tur, "resolvedModel");
                            if let Some(x) = self.subs.subs.get_mut(&tid).filter(|x| !model.is_empty() && x.model != model) {
                                x.model = model;
                                st.events.extend(self.subs.event(&tid, "running", json!({})));
                            }
                        } else if self.subs.has(&tid) {
                            let answer = claude_answer(&tur, b);
                            let secs = tur.get("totalDurationMs").and_then(Value::as_u64).map(|ms| ms as f64 / 1000.0);
                            let model = s(&tur, "resolvedModel");
                            if !model.is_empty() {
                                if let Some(x) = self.subs.subs.get_mut(&tid) {
                                    x.model = model;
                                }
                            }
                            self.subs.end(&mut st, &tid, if ok { "done" } else { "failed" }, &answer, secs);
                        }
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
                // how full the context is now, as Claude Code counts it
                self.control(&mut st, "context", json!({"subtype": "get_context_usage"}));
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text, images, id } => {
                // a message sent while the person's own turn runs waits until Claude Code takes it
                let busy = self.turn && !self.auto_turn;
                self.waiting.push(&mut st, id, busy);
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
            Input::Interrupt => {
                self.control(&mut st, "interrupt", json!({"subtype": "interrupt"}));
                // no turn runs: what is left is background work, and Stop is meant for it (the header's Stop beside
                // "1 still running in the background"); a background command stops at once only by its own stop_task
                if !self.turn {
                    for id in self.bg_commands.clone() {
                        self.control(&mut st, "stoptask", json!({"subtype": "stop_task", "task_id": id}));
                    }
                }
            }
            Input::Approve { request_id, choice } => {
                let Some(ClaudeAsk::Tool(name, input, suggestions)) = self.pending.remove(&request_id) else { return Err("no such request".into()) };
                self.ask_subs.remove(&request_id);
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
                self.ask_subs.remove(&request_id);
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
            // Claude Code's own rewind: the conversation goes back to before the last message it took
            Input::Rewind => {
                if self.turn {
                    return Err("wait until the turn ends".into());
                }
                let Some(uuid) = self.sent_uuids.last().cloned() else { return Err("nothing to take back".into()) };
                self.control(&mut st, "rewind", json!({"subtype": "rewind_conversation", "target_message_uuid": uuid}));
            }
            // Claude Code's own switch; it answers with a status line carrying the new mode
            Input::Mode { mode } => {
                if !modes_for("claude").contains(&mode.as_str()) {
                    return Err(format!("not a mode omher offers: {mode}"));
                }
                self.control(&mut st, "mode", json!({"subtype": "set_permission_mode", "mode": mode}));
            }
            // for this process only (`apply_flag_settings`, never the settings file); omher sets it again on restart
            Input::Effort { effort } => {
                if !["low", "medium", "high", "xhigh", "max"].contains(&effort.as_str()) {
                    return Err(format!("unknown effort {effort}"));
                }
                self.control(&mut st, "effort", json!({"subtype": "apply_flag_settings", "settings": {"effortLevel": effort}}));
            }
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
    queued: Vec<(String, Vec<Picture>, String)>,
    /// open approvals and questions by our request id
    pending: HashMap<String, CodexAsk>,
    /// the sub-agent thread that asked each pending request, when one did
    ask_helpers: HashMap<String, String>,
    /// diff summaries of fileChange items, shown on their approval card
    changes: HashMap<String, String>,
    /// the last error notification was a 401 (not signed in)
    unauthorized: bool,
    /// Stop was pressed before Codex named the turn: interrupt it as soon as it does
    stop_asked: bool,
    /// the person's mode (approval policy, sandbox) and effort, sent with every turn from the next one on
    mode: Option<(&'static str, &'static str)>,
    effort: Option<String>,
    /// effort levels per model, from model/list
    efforts: HashMap<String, Value>,
    /// skill name -> its SKILL.md path (skills/list), for `$name` in a message
    skills: HashMap<String, String>,
    waiting: Waiting,
    /// Codex's sub-agents by their own thread id. The app-server streams their threads on this connection; their
    /// events become `subagent` events and never touch the person's turn, its answer or its Stop.
    helpers: Subagents,
    /// the person's turns Codex named in this process, oldest first: a rewind reverts the thread to before the last
    turns: Vec<String>,
    /// reasoning items that streamed a summary: their raw text is not shown as well
    summarized: std::collections::HashSet<String>,
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
            ask_helpers: HashMap::new(),
            changes: HashMap::new(),
            unauthorized: false,
            stop_asked: false,
            mode: None,
            effort: None,
            efforts: HashMap::new(),
            skills: HashMap::new(),
            waiting: Waiting::default(),
            helpers: Subagents::new("codex"),
            turns: Vec::new(),
            summarized: Default::default(),
        }
    }
    fn call(&mut self, st: &mut Step, method: &'static str, params: Value) {
        self.seq += 1;
        self.calls.insert(self.seq, method);
        st.out(json!({"id": self.seq, "method": method, "params": params}));
    }
    fn turn_start(&mut self, st: &mut Step, text: String, images: &[Picture], id: &str) {
        let thread = self.thread.clone().unwrap_or_default();
        // pictures as app-server `localImage` items: Codex reads the saved copy itself
        let mut input: Vec<Value> = images.iter().map(|p| json!({"type": "localImage", "path": p.path})).collect();
        if !text.is_empty() || input.is_empty() {
            input.push(json!({"type": "text", "text": text}));
        }
        // a skill named as `$name` goes with it as Codex's own skill input, as its TUI sends it
        for w in text.split_whitespace() {
            if let Some(path) = w.strip_prefix('$').and_then(|n| self.skills.get(n).map(|p| (n, p))) {
                input.push(json!({"type": "skill", "name": path.0, "path": path.1}));
            }
        }
        let mut p = json!({"threadId": thread, "input": input});
        if let Some(m) = &self.model {
            p["model"] = Value::String(m.clone());
        }
        if let Some((policy, sandbox)) = self.mode {
            p["approvalPolicy"] = Value::String(policy.into());
            p["sandboxPolicy"] = json!({"type": sandbox});
        }
        if let Some(e) = &self.effort {
            p["effort"] = Value::String(e.clone());
        }
        if !id.is_empty() {
            p["clientUserMessageId"] = Value::String(id.into());
        }
        self.call(st, "turn/start", p);
    }
    /// The effort levels of `model`, as model/list gave them.
    fn efforts_event(&self, model: &str) -> Option<Event> {
        self.efforts.get(model).filter(|l| l.as_array().is_some_and(|a| !a.is_empty())).map(|l| ev("session.efforts", json!({"levels": l})))
    }
    fn label(&self, model: &str) -> String {
        self.labels.get(model).cloned().unwrap_or_else(|| model.to_string())
    }
    /// Codex named the running turn: a Stop pressed before that interrupts it now.
    fn named(&mut self, st: &mut Step, turn: &str) {
        self.turn_id = Some(turn.into());
        if self.turns.last().map(String::as_str) != Some(turn) {
            self.turns.push(turn.into());
            if self.turns.len() == 1 {
                st.emit(ev("session.info", json!({"rewind": true})));
            }
        }
        if std::mem::take(&mut self.stop_asked) && self.turn {
            let thread = self.thread.clone().unwrap_or_default();
            self.call(st, "turn/interrupt", json!({"threadId": thread, "turnId": turn}));
        }
    }
    fn end(&mut self, st: &mut Step, outcome: &str, error: Option<String>) {
        self.stop_asked = false;
        if self.turn {
            self.turn = false;
            self.turn_id = None;
            // approvals die with the turn, except a sub-agent's that still runs (its ask follows it, as Claude Code's
            // background subagents' do); a question asked in a message is answered with the next turn
            let open = self.helpers.open();
            let keep: Vec<String> = self.ask_helpers.iter().filter(|(_, t)| open.contains(t)).map(|(r, _)| r.clone()).collect();
            self.pending.retain(|r, a| matches!(a, CodexAsk::Message) || keep.contains(r));
            self.ask_helpers.retain(|r, _| keep.contains(r));
            let mut f = json!({"outcome": outcome});
            if let Some(e) = error.filter(|e| !e.is_empty()) {
                f["error"] = Value::String(e);
            }
            // a stopped turn's messages that Codex never recorded were not sent; a finished one took them
            if outcome == "interrupted" {
                self.waiting.all_dropped(st);
            } else {
                self.waiting.all_taken(st);
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
    /// A sub-agent's thread: one Codex named as a sub-agent (`subAgentActivity`), or one whose turn belongs to
    /// another turn (`rootTurnId`). Any other thread id is the session's own.
    fn is_helper(&self, thread: &str) -> bool {
        self.helpers.has(thread)
    }
    /// A turn of another thread that belongs to a running turn (a sub-agent of a sub-agent, or one Codex did not
    /// announce): registered as a sub-agent.
    fn adopt(&mut self, thread: &str, method: &str, p: &Value) {
        if thread.is_empty() || self.is_helper(thread) || self.thread.as_deref() == Some(thread) || !method.starts_with("turn/") {
            return;
        }
        let t = &p["turn"];
        let root = s(t, "rootTurnId");
        if !root.is_empty() && root != s(t, "id") {
            self.helper(thread, "", "");
        }
    }
    /// The sub-agent of `thread`, registered on first sight in the fan-out of the person's running turn
    /// ("/root/read_first_line" -> "read first line"). Codex streams no task text for it: its goal stays empty.
    fn helper(&mut self, thread: &str, path: &str, model: &str) -> &mut Sub {
        let delegation = format!("codex-{}", self.turn_id.clone().unwrap_or_default());
        let name = path.rsplit('/').next().unwrap_or("").replace('_', " ");
        self.helpers.add(thread, &delegation, &name, "", model)
    }
    /// `subAgentActivity` (on the session's thread, or a sub-agent's for a nested one): one started or ended.
    fn helper_activity(&mut self, st: &mut Step, item: &Value, done: bool) {
        let thread = s(item, "agentThreadId");
        if thread.is_empty() || self.thread.as_deref() == Some(thread.as_str()) {
            return;
        }
        self.helper(&thread, &s(item, "agentPath"), &s(item, "model"));
        match (s(item, "kind").as_str(), done) {
            ("started", false) => st.events.extend(self.helpers.event(&thread, "running", json!({}))),
            // its thread's own turn/completed normally says so first, with its time
            ("completed", true) => self.helpers.end(st, &thread, "done", "", None),
            _ => {}
        }
    }
    /// A line of a sub-agent's own thread: its steps and its end. Its text is held as its answer, never shown as
    /// Codex's; its deltas, reasoning and warnings are dropped.
    fn on_helper_line(&mut self, st: &mut Step, thread: &str, method: &str, p: &Value) {
        let item = p.get("item").cloned().unwrap_or(Value::Null);
        match method {
            "item/started" => {
                if s(&item, "type") == "subAgentActivity" {
                    return self.helper_activity(st, &item, false);
                }
                if let Some((tool, step)) = self.item_step(&item) {
                    // its file change carries the patch, as the session's own does: the step opens to it
                    let files = if s(&item, "type") == "fileChange" { codex_diff(&item, &self.cwd) } else { vec![] };
                    if files.is_empty() {
                        self.helpers.step(st, thread, &tool, &step);
                    } else {
                        self.helpers.edit(st, thread, &step, files);
                    }
                }
            }
            "item/completed" => match s(&item, "type").as_str() {
                // what the change finally was (it may differ from what it asked)
                "fileChange" => {
                    let files = codex_diff(&item, &self.cwd);
                    if !files.is_empty() {
                        let step = self.file_changes(&item);
                        self.helpers.edit(st, thread, &step, files);
                    }
                }
                "agentMessage" => {
                    let t = s(&item, "text");
                    if !t.trim().is_empty() {
                        self.helper(thread, "", "").text = t;
                    }
                }
                "subAgentActivity" => self.helper_activity(st, &item, true),
                _ => {}
            },
            "turn/completed" => {
                let t = &p["turn"];
                let secs = t.get("durationMs").and_then(Value::as_u64).map(|ms| ms as f64 / 1000.0);
                match s(t, "status").as_str() {
                    "interrupted" => self.helpers.end(st, thread, "cancelled", "", secs),
                    "failed" => {
                        let e = t.get("error").map(|e| s(e, "message")).unwrap_or_default();
                        self.helpers.end(st, thread, "failed", if e.is_empty() { "failed" } else { &e }, secs)
                    }
                    _ => self.helpers.end(st, thread, "done", "", secs),
                }
            }
            _ => {}
        }
    }
    /// The step an item runs, as (tool kind, detail), for the items omher shows as steps.
    fn item_step(&mut self, item: &Value) -> Option<(String, String)> {
        let iid = s(item, "id");
        Some(match s(item, "type").as_str() {
            "commandExecution" => ("terminal".into(), clip(&Codex::command_of(item), 160)),
            "fileChange" => {
                let detail = self.file_changes(item);
                let paths: Vec<String> = item.get("changes").and_then(Value::as_array).into_iter().flatten().map(|c| rel(&s(c, "path"), &self.cwd)).filter(|p| !p.is_empty()).collect();
                self.changes.insert(iid, clip(&paths.join(", "), 120));
                ("patch".into(), detail)
            }
            "mcpToolCall" => (s(item, "tool"), format!("{}.{}", s(item, "server"), s(item, "tool"))),
            "dynamicToolCall" => (tool_kind(&s(item, "tool")).to_string(), tool_detail(&item["arguments"])),
            "webSearch" => ("web_search".into(), s(item, "query")),
            "imageView" => ("read_file".into(), rel(&s(item, "path"), &self.cwd)),
            "sleep" => {
                let secs = item.get("durationMs").and_then(Value::as_u64).unwrap_or(0) / 1000;
                ("Waiting".into(), if secs > 0 { format!("{secs}s") } else { String::new() })
            }
            _ => return None,
        })
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
    fn name(&self) -> &str {
        "Codex"
    }

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
                if what == "thread/resume" {
                    // The thread to continue is gone (deleted or archived: "no rollout found"): start a new one in the
                    // same folder, say so, and send what was queued to it once Codex names it.
                    self.resume = None;
                    st.emit(ev("session.note", json!({"kind": "new_conversation", "text": clip(&format!("The earlier Codex conversation was not found ({msg}); a new one started."), 240)})));
                    let cwd = self.cwd.clone();
                    self.call(&mut st, "thread/start", json!({"cwd": cwd}));
                } else if what == "thread/revert" {
                    st.emit(ev("session.error", json!({"message": clip(&format!("Not taken back: {msg}"), 200)})));
                } else if what == "turn/start" {
                    self.end(&mut st, "error", Some(clip(&msg, 200)));
                } else if what == "turn/interrupt" && self.turn {
                    // a refused Stop says so where the person looks: the running turn's line
                    st.emit(ev("status", json!({"text": clip(&format!("Codex did not stop: {msg}"), 160)})));
                } else if what == "thread/start" {
                    // no thread to send to: a message waiting for one ends its turn with the reason
                    self.queued.clear();
                    let m = clip(&format!("Codex could not start a conversation: {msg}"), 200);
                    if self.turn {
                        self.end(&mut st, "error", Some(m));
                    } else {
                        st.emit(ev("session.error", json!({"message": m})));
                    }
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
                    let cwd = self.cwd.clone();
                    self.call(&mut st, "skills/list", json!({"cwds": [cwd]}));
                }
                "thread/start" | "thread/resume" => {
                    self.thread = r["thread"].get("id").and_then(Value::as_str).map(String::from);
                    self.model_id = s(r, "model");
                    let mut f = json!({"agent_session": self.thread.clone().unwrap_or_default(), "model": self.label(&self.model_id)});
                    let policy = s(r, "approvalPolicy");
                    let sandbox = r.get("sandbox").map(|x| s(x, "type")).unwrap_or_default();
                    // the thread's own mode when it is one of ours; any other (Codex's config) shows as the agent's
                    f["mode"] = Value::String(codex_mode_of(&policy, &sandbox).unwrap_or("").into());
                    if !policy.is_empty() {
                        f["approval"] = Value::String(policy);
                    }
                    if !sandbox.is_empty() {
                        f["sandbox"] = Value::String(sandbox);
                    }
                    let effort = s(r, "reasoningEffort");
                    if !effort.is_empty() {
                        f["effort"] = Value::String(effort);
                    }
                    // a resumed thread carries the name Codex (or the person) gave it
                    let name = title_of(&s(&r["thread"], "name"));
                    if !name.is_empty() {
                        f["title"] = Value::String(name);
                    }
                    st.emit(ev("session.info", f));
                    if let Some(e) = self.efforts_event(&self.model_id) {
                        st.emit(e);
                    }
                    for (text, images, id) in std::mem::take(&mut self.queued) {
                        self.turn_start(&mut st, text, &images, &id);
                    }
                }
                "turn/start" => {
                    if let Some(t) = r["turn"].get("id").and_then(Value::as_str) {
                        self.named(&mut st, t);
                    }
                }
                // the thread is back to before the person's last turn (its files stay as they are)
                "thread/revert" => {
                    self.turns.pop();
                    st.emit(ev("rewound", json!({})));
                    st.emit(ev("session.info", json!({"rewind": !self.turns.is_empty()})));
                }
                "model/list" => {
                    let list: Vec<&Value> = r.get("data").and_then(Value::as_array).into_iter().flatten().filter(|m| !m.get("hidden").and_then(Value::as_bool).unwrap_or(false)).collect();
                    for m in &list {
                        let label = s(m, "displayName");
                        if !label.is_empty() {
                            self.labels.insert(s(m, "model"), label);
                        }
                    }
                    for m in &list {
                        let levels: Vec<Value> = m.get("supportedReasoningEfforts").and_then(Value::as_array).into_iter().flatten().map(|e| Value::String(s(e, "reasoningEffort"))).filter(|e| e != "").collect();
                        self.efforts.insert(s(m, "model"), Value::Array(levels));
                    }
                    let options: Vec<Value> = list.iter().map(|m| json!({"id": s(m, "model"), "label": s(m, "displayName"), "detail": s(m, "description")})).collect();
                    st.emit(ev("session.models", json!({"options": options})));
                    if let Some(e) = self.efforts_event(&self.model_id) {
                        st.emit(e);
                    }
                    if !self.model_id.is_empty() {
                        st.emit(ev("session.info", json!({"model": self.label(&self.model_id)})));
                    }
                }
                "skills/list" => {
                    // Codex's skills, typed as `$name`
                    let mut commands = Vec::new();
                    for sk in r.get("data").and_then(Value::as_array).into_iter().flatten().flat_map(|d| d.get("skills").and_then(Value::as_array).into_iter().flatten()) {
                        let name = s(sk, "name");
                        if name.is_empty() || sk.get("enabled").and_then(Value::as_bool) == Some(false) || self.skills.contains_key(&name) {
                            continue;
                        }
                        self.skills.insert(name.clone(), s(sk, "path"));
                        let d = if s(sk, "shortDescription").is_empty() { s(sk, "description") } else { s(sk, "shortDescription") };
                        commands.push(command_entry(&name, &d, "", "skill", "$"));
                    }
                    if !commands.is_empty() {
                        st.emit(ev("session.commands", json!({"commands": commands})));
                    }
                }
                _ => {}
            }
            return st;
        }
        let p = v.get("params").cloned().unwrap_or(Value::Null);
        // a request from the server (approvals, questions); anything we do not handle is answered with an error
        let thread = s(&p, "threadId");
        if let Some(rpc_id) = id {
            let key = format!("codex-{}", rpc_id);
            let n = st.events.len();
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
            // asked inside a sub-agent: the card says which one
            if self.is_helper(&thread) {
                let name = self.helper(&thread, "", "").name.clone();
                tag_asks(&mut st, n, &thread, &name);
                self.ask_helpers.insert(key, thread.clone());
            }
            return st;
        }
        self.adopt(&thread, &method, &p);
        if self.is_helper(&thread) && method != "serverRequest/resolved" {
            self.on_helper_line(&mut st, &thread, &method, &p);
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
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
                if let Some(t) = p["turn"].get("id").and_then(Value::as_str) {
                    self.named(&mut st, t);
                }
            }
            // how full the context is, as Codex counts it (the last request's tokens against the model's window)
            "thread/tokenUsage/updated" => {
                let u = &p["tokenUsage"];
                if let (Some(used), Some(max)) = (u["last"].get("totalTokens").and_then(Value::as_u64), u.get("modelContextWindow").and_then(Value::as_u64).filter(|m| *m > 0)) {
                    st.emit(ev("session.usage", json!({"used": used, "max": max})));
                }
            }
            "item/agentMessage/delta" => {
                let t = s(&p, "delta");
                if !t.is_empty() {
                    st.emit(ev("delta", json!({"text": t})));
                }
            }
            // its reasoning: the summary when Codex writes one, else the raw text
            "item/reasoning/summaryTextDelta" => {
                self.summarized.insert(s(&p, "itemId"));
                st.emit(thinking_event(&s(&p, "delta")));
            }
            "item/reasoning/summaryPartAdded" => st.emit(thinking_event("\n\n")),
            "item/reasoning/textDelta" => {
                let t = if self.summarized.contains(&s(&p, "itemId")) { String::new() } else { s(&p, "delta") };
                st.emit(thinking_event(&t));
            }
            // its plan: the whole list each time, one checklist that changes in place
            "turn/plan/updated" if self.turn => {
                let items: Vec<(String, String)> = p
                    .get("plan")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .map(|x| {
                        let st = match s(x, "status").as_str() {
                            "inProgress" => "in_progress",
                            "completed" => "completed",
                            _ => "pending",
                        };
                        (s(x, "step"), st.to_string())
                    })
                    .collect();
                st.emit(plan_event(&items));
            }
            // a file change's patch moved before it ran (Codex reworked it): the diff view follows
            "item/fileChange/patchUpdated" => {
                let files = codex_diff(&json!({"changes": p.get("changes").cloned().unwrap_or(Value::Null)}), &self.cwd);
                if !files.is_empty() {
                    st.emit(ev("tool.diff", json!({"tool_id": s(&p, "itemId"), "files": files})));
                }
            }
            "item/started" => {
                match s(&item, "type").as_str() {
                    // Codex recorded a message the person sent (our id as its clientId)
                    "userMessage" => {
                        let cid = s(&item, "clientId");
                        if !cid.is_empty() {
                            self.waiting.take_id(&mut st, &cid);
                        }
                    }
                    "subAgentActivity" => self.helper_activity(&mut st, &item, false),
                    _ => {
                        if let Some((name, detail)) = self.item_step(&item) {
                            st.emit(ev("tool.start", json!({"tool_id": s(&item, "id"), "name": name, "detail": detail})));
                            // a file change carries its patch: the diff view shows it
                            if s(&item, "type") == "fileChange" {
                                let files = codex_diff(&item, &self.cwd);
                                if !files.is_empty() {
                                    st.emit(ev("tool.diff", json!({"tool_id": s(&item, "id"), "files": files})));
                                }
                            }
                        }
                    }
                }
            }
            "item/completed" => {
                let iid = s(&item, "id");
                match s(&item, "type").as_str() {
                    "subAgentActivity" => self.helper_activity(&mut st, &item, true),
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
                        // what the change finally was (it may differ from what it asked)
                        if s(&item, "type") == "fileChange" {
                            let files = codex_diff(&item, &self.cwd);
                            if !files.is_empty() {
                                st.emit(ev("tool.diff", json!({"tool_id": iid, "files": files})));
                            }
                        }
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
                // a status shows only while a turn runs; outside one an error is a note under the chat
                if p.get("willRetry").and_then(Value::as_bool).unwrap_or(false) {
                    // "Reconnecting... 2/5": say it on the progress line instead of a silent wait
                    if self.turn {
                        st.emit(ev("status", json!({"text": clip(&s(e, "message"), 120)})));
                    }
                } else if !self.unauthorized {
                    let text = clip(&format!("Error: {}", s(e, "message")), 160);
                    st.emit(if self.turn { ev("status", json!({"text": text})) } else { ev("session.error", json!({"message": text})) });
                }
            }
            _ => {}
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text, images, id } => {
                // a message sent while a turn runs joins it once Codex records it
                self.waiting.push(&mut st, id.clone(), self.turn);
                if !self.turn {
                    self.turn = true;
                    st.emit(ev("turn.start", json!({})));
                }
                if self.thread.is_none() {
                    self.queued.push((text, images, id));
                } else {
                    self.turn_start(&mut st, text, &images, &id);
                }
            }
            Input::Interrupt => match (self.thread.clone(), self.turn_id.clone()) {
                (Some(thread), Some(turn)) => self.call(&mut st, "turn/interrupt", json!({"threadId": thread, "turnId": turn})),
                _ if !self.turn => return Err("nothing is running".into()),
                // the message still waits for the thread: it is never sent
                (None, _) => {
                    self.queued.clear();
                    self.waiting.all_dropped(&mut st);
                    self.end(&mut st, "interrupted", None);
                }
                // sent, but Codex has not named the turn yet
                (Some(_), None) => self.stop_asked = true,
            },
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
                            self.turn_start(&mut st, text, &[], "");
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
                if let Some(e) = self.efforts_event(&model) {
                    st.emit(e);
                }
            }
            // per turn as well: approval policy and sandbox go with the next turn/start (and Codex keeps them)
            Input::Mode { mode } => {
                let m = codex_mode(&mode).ok_or_else(|| format!("not a mode omher offers: {mode}"))?;
                self.mode = Some(m);
                st.emit(ev("session.info", json!({"mode": mode})));
            }
            // Codex's own revert: the thread goes back to before the person's last turn
            Input::Rewind => {
                if self.turn {
                    return Err("wait until the turn ends".into());
                }
                let (Some(thread), Some(turn)) = (self.thread.clone(), self.turns.last().cloned()) else { return Err("nothing to take back".into()) };
                self.call(&mut st, "thread/revert", json!({"threadId": thread, "beforeTurnId": turn}));
            }
            Input::Effort { effort } => {
                let model = self.model.clone().unwrap_or_else(|| self.model_id.clone());
                let known = self.efforts.get(&model).and_then(Value::as_array).is_some_and(|l| l.iter().any(|e| e == effort.as_str()));
                if !known {
                    return Err(format!("{model} has no effort {effort}"));
                }
                self.effort = Some(effort.clone());
                st.emit(ev("session.info", json!({"effort": effort})));
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
    /// thinking levels it offers (`get_available_thinking_levels`)
    levels: Vec<String>,
    reads: u64,
    waiting: Waiting,
    /// OmO's subagents (`task` tool), by task id once OmO names them (`st_…`), else `<call id>:<n>`
    subs: Subagents,
    /// OmO's task id -> our subagent id; a `task` call id -> its subagents in order
    task_ids: HashMap<String, String>,
    calls_subs: HashMap<String, Vec<String>>,
    /// background work OmO says is still running (`session_lifecycle.waitingOn.background`)
    background: usize,
    /// OmO's own folder (`~/.omo`): its record of each subagent, read when a `task` result names no answer
    omo_home: Option<PathBuf>,
    /// the conversation OmO reported (`get_state`): a subagent record must belong to it
    session: String,
    /// OmO `todo` calls in flight: their list is the turn's checklist, not a step
    todo_calls: std::collections::HashSet<String>,
    /// OmO ended a run with `failure`: the turn's end waits for what OmO says next, a retry of its own
    /// (`auto_retry_start`) or its last word on it (`auto_retry_end`, or the run settling)
    held: bool,
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

/// OmO's own folder: `~/.omo`.
fn omo_home_dir() -> Option<PathBuf> {
    std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).filter(|h| !h.is_empty()).map(|h| PathBuf::from(h).join(".omo"))
}

/// Seconds since the epoch of an ISO time as OmO writes it (`2026-11-12T15:53:23.423Z`, UTC).
fn iso_secs(t: &str) -> Option<f64> {
    let t = t.strip_suffix('Z')?;
    let (date, time) = t.split_once('T')?;
    let d: Vec<i64> = date.split('-').map(|x| x.parse().ok()).collect::<Option<_>>()?;
    let (hms, frac) = time.split_once('.').unwrap_or((time, "0"));
    let h: Vec<i64> = hms.split(':').map(|x| x.parse().ok()).collect::<Option<_>>()?;
    if d.len() != 3 || h.len() != 3 {
        return None;
    }
    let (y, m) = if d[1] <= 2 { (d[0] - 1, d[1] + 9) } else { (d[0], d[1] - 3) };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * m + 2) / 5 + d[2] - 1;
    let days = era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468;
    Some((days * 86400 + h[0] * 3600 + h[1] * 60 + h[2]) as f64 + format!("0.{frac}").parse::<f64>().ok()?)
}

/// OmO's todo list as its `todo` result states it (`details.phases[].tasks[] {content, status}`), in order.
fn omo_todo(d: &Value) -> Option<Vec<(String, String)>> {
    let phases = d.get("phases")?.as_array()?;
    Some(
        phases
            .iter()
            .flat_map(|p| p.get("tasks").and_then(Value::as_array).into_iter().flatten())
            .map(|t| {
                let st = match s(t, "status").as_str() {
                    "in_progress" => "in_progress",
                    "completed" => "completed",
                    _ => "pending",
                };
                (s(t, "content"), st.to_string())
            })
            .collect(),
    )
}

impl Pi {
    pub fn new(cwd: &str, label: &str) -> Pi {
        let agent = match label {
            "OmO" => "omo",
            "oh-my-pi" => "omp",
            _ => "pi",
        };
        let omo_home = if agent == "omo" { omo_home_dir() } else { None };
        Pi { cwd: cwd.into(), label: label.into(), subs: Subagents::new(agent), omo_home, ..Pi::default() }
    }
    /// OmO's own record of subagent `task_id` (`st_…`), read-only: the same `senpi-task/tasks/st_*.json` files the
    /// Plans reader reads (BOUNDARY rule 16), under `<omo>/agent/projects/*/` or this session's own folder's `.omo`,
    /// never through a link, and only a record of this session. `None` when there is none or it does not parse.
    fn omo_record(&self, task_id: &str) -> Option<Value> {
        let ok = task_id.len() <= 67 && task_id.strip_prefix("st_").is_some_and(|r| !r.is_empty() && r.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-'));
        if !ok {
            return None;
        }
        let file = format!("{task_id}.json");
        let mut stores: Vec<PathBuf> = vec![];
        let real_dir = |p: &Path| std::fs::symlink_metadata(p).is_ok_and(|m| m.is_dir());
        if !self.cwd.is_empty() {
            let dot = Path::new(&self.cwd).join(".omo");
            if real_dir(&dot) && real_dir(&dot.join("senpi-task")) {
                stores.push(dot.join("senpi-task").join("tasks"));
            }
        }
        if let Some(root) = self.omo_home.as_ref().map(|h| h.join("agent").join("projects")).filter(|r| real_dir(r)) {
            for e in std::fs::read_dir(&root).ok()?.flatten() {
                if e.file_type().is_ok_and(|t| t.is_dir()) {
                    stores.push(e.path().join("senpi-task").join("tasks"));
                }
            }
        }
        stores.into_iter().filter(|d| real_dir(d)).find_map(|d| {
            let p = d.join(&file);
            let m = std::fs::symlink_metadata(&p).ok()?;
            if !m.is_file() || m.len() > 1 << 20 {
                return None;
            }
            let rec: Value = serde_json::from_str(&std::fs::read_to_string(&p).ok()?).ok()?;
            (s(&rec, "task_id") == task_id && (self.session.is_empty() || s(&rec, "root_session_id") == self.session)).then_some(rec)
        })
    }
    /// A `task` call: one subagent per entry of `tasks` (or the call itself with one task), one fan-out per call.
    fn task_start(&mut self, st: &mut Step, call: &str, args: &Value) {
        let one = [args.clone()];
        let tasks: &[Value] = args.get("tasks").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&one);
        let kind = s(args, "subagent_type");
        let mut ids = vec![];
        for (i, t) in tasks.iter().enumerate() {
            let id = format!("{call}:{i}");
            let name = [s(t, "name"), s(t, "subagent_type"), kind.clone()].into_iter().find(|x| !x.is_empty()).unwrap_or_default();
            let goal = [s(t, "task_summary"), s(t, "description"), s(t, "prompt")].into_iter().find(|x| !x.is_empty()).unwrap_or_default();
            self.subs.add(&id, &format!("pi-{call}"), &name, &goal, "");
            st.events.extend(self.subs.event(&id, "queued", json!({})));
            ids.push(id);
        }
        self.calls_subs.insert(call.to_string(), ids);
    }
    /// The `task` call's result names each subagent's task id, model and state (a background one runs on).
    fn task_end(&mut self, st: &mut Step, call: &str, v: &Value) {
        let Some(ids) = self.calls_subs.remove(call) else { return };
        let d = &v["result"]["details"];
        let one = [d.clone()];
        let items: &[Value] = d.get("items").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&one);
        let failed = v.get("isError").and_then(Value::as_bool).unwrap_or(false);
        for (i, id) in ids.iter().enumerate() {
            let it = items.get(i).cloned().unwrap_or(Value::Null);
            let tid = s(&it, "task_id");
            if !tid.is_empty() {
                self.task_ids.insert(tid, id.clone());
            }
            let status = s(&it, "status");
            // a foreground result (OmO 5.1.56) names no answer: OmO's own record of that task id has it, with the
            // model it ran on and its times, as Plans reads them
            let own = if status == "completed" { "final_response" } else { "error" };
            let rec = if !failed && matches!(status.as_str(), "completed" | "failed" | "error") && s(&it, own).is_empty() { self.omo_record(&s(&it, "task_id")) } else { None };
            let rec = rec.filter(|r| s(r, "status") == status);
            let mut model = it.get("resolved_model").map(|m| s(m, "model_id")).unwrap_or_default();
            let mut secs = None;
            if let Some(r) = &rec {
                let m = r.get("effective_model").map(|m| s(m, "model_id")).filter(|m| !m.is_empty()).unwrap_or_else(|| s(r, "model"));
                if !m.is_empty() {
                    model = m.rsplit('/').next().unwrap_or(&m).to_string();
                }
                if let (Some(a), Some(b)) = (iso_secs(&s(r, "started_at")), iso_secs(&s(r, "terminal_at"))) {
                    secs = (b >= a).then_some(b - a);
                }
            }
            if let Some(x) = self.subs.subs.get_mut(id) {
                if !model.is_empty() {
                    x.model = model;
                }
            }
            let answer = |k: &str| if s(&it, k).is_empty() { rec.as_ref().map(|r| s(r, k)).unwrap_or_default() } else { s(&it, k) };
            match status.as_str() {
                _ if failed => {
                    let e = v["result"]["content"].as_array().and_then(|a| a.first()).map(|b| s(b, "text")).unwrap_or_default();
                    self.subs.end(st, id, "failed", if e.is_empty() { "failed" } else { &e }, None)
                }
                "completed" => self.subs.end(st, id, "done", &answer("final_response"), secs),
                "failed" | "error" => {
                    let e = answer("error");
                    self.subs.end(st, id, "failed", if e.is_empty() { "failed" } else { &e }, secs)
                }
                "cancelled" | "aborted" => self.subs.end(st, id, "cancelled", "", None),
                _ => st.events.extend(self.subs.event(id, "running", json!({}))),
            }
        }
    }
    /// OmO's notice that a background subagent finished (`senpi-task.completion` in a wake message's details).
    fn task_done(&mut self, st: &mut Step, m: &Value) {
        for p in m["details"].get("producerDetails").and_then(Value::as_array).into_iter().flatten() {
            if s(p, "customType") != "senpi-task.completion" {
                continue;
            }
            for d in p.get("details").and_then(Value::as_array).into_iter().flatten() {
                let Some(id) = self.task_ids.get(&s(d, "task_id")).cloned() else { continue };
                let model = s(d, "model");
                if let Some(x) = self.subs.subs.get_mut(&id) {
                    if !model.is_empty() {
                        x.model = model.rsplit('/').next().unwrap_or(&model).to_string();
                    }
                }
                let secs = d.get("duration_ms").and_then(Value::as_u64).map(|ms| ms as f64 / 1000.0);
                let state = match s(d, "status").as_str() {
                    "completed" => "done",
                    "cancelled" | "aborted" => "cancelled",
                    _ => "failed",
                };
                let answer = if state == "failed" { s(d, "error") } else { s(d, "final_response") };
                self.subs.end(st, &id, state, if state == "failed" && answer.is_empty() { "failed" } else { &answer }, secs);
            }
        }
    }
    fn cmd(&mut self, st: &mut Step, kind: &'static str, fields: Value) {
        self.seq += 1;
        let id = format!("omher-{}", self.seq);
        self.send_cmd(st, kind, id, fields);
    }
    /// A read on the side (levels, commands, usage): its own ids, so the person's commands keep theirs.
    fn read(&mut self, st: &mut Step, kind: &'static str) {
        self.reads += 1;
        let id = format!("omher-r{}", self.reads);
        self.send_cmd(st, kind, id, json!({}));
    }
    fn send_cmd(&mut self, st: &mut Step, kind: &'static str, id: String, mut fields: Value) {
        self.calls.insert(id.clone(), kind);
        fields["id"] = Value::String(id);
        fields["type"] = Value::String(kind.into());
        st.out(fields);
    }
    fn end(&mut self, st: &mut Step) {
        self.held = false;
        if self.turn {
            self.turn = false;
            self.streaming = false;
            self.pending.clear();
            // a run takes its follow-ups before it ends; what is left was cleared by Stop
            self.waiting.all_dropped(st);
            // how full the context is now
            self.read(st, "get_session_stats");
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
    /// A calm line for an error: a missing login names where to sign in, a provider's raw reply
    /// (`400 {"type":"error","error":{"message":…}}`) its message, anything else its first line.
    fn friendly(&self, err: &str) -> String {
        let who = if self.label.is_empty() { "pi" } else { &self.label };
        if err.contains("No API key") || err.contains("/login") || err.contains("No default model") {
            return format!("{who} is not signed in. Open Terminal and run /login, then Restart.");
        }
        let line = last_line(err);
        clip(&provider_message(line).unwrap_or_else(|| line.to_string()), 200)
    }
    /// What OmO said after a run that ended with `failure`, while its end waits (`held`). True when the line was
    /// taken here (a retry starts, or its last word ends the turn).
    fn after_failure(&mut self, st: &mut Step, v: &Value) -> bool {
        match s(v, "type").as_str() {
            // OmO tries again by itself: the same turn goes on, and its line says which try this is
            "auto_retry_start" => {
                self.held = false;
                self.last_stop.clear();
                self.last_error.clear();
                let n = v.get("attempt").and_then(Value::as_u64).unwrap_or(1);
                let max = v.get("maxAttempts").and_then(Value::as_u64).unwrap_or(0);
                st.emit(ev("status", json!({"text": format!("Retrying {n} of {max}"), "retry": {"attempt": n, "max": max}})));
                true
            }
            // the retries are over: the turn ends once, with OmO's own words for why
            "auto_retry_end" => {
                self.held = false;
                let why = s(v, "finalError");
                if v.get("success").and_then(Value::as_bool) != Some(true) && !why.is_empty() {
                    self.last_stop = "error".into();
                    self.last_error = why;
                }
                self.end(st);
                true
            }
            // no retry came: the run settled (or the next one starts) on that failure
            "agent_settled" | "agent_idle" | "agent_start" | "model_config_error" | "prompt_result" => {
                self.held = false;
                self.end(st);
                false
            }
            _ => false,
        }
    }
}

/// The message of a provider's raw error reply, `400 {"type":"error","error":{"message":"…"}}`.
fn provider_message(line: &str) -> Option<String> {
    let body: Value = serde_json::from_str(line[line.find('{')?..].trim()).ok()?;
    let m = body.get("error").map(|e| if e.is_string() { e.as_str().unwrap_or_default().to_string() } else { s(e, "message") }).unwrap_or_else(|| s(&body, "message"));
    (!m.trim().is_empty()).then_some(m)
}

/// `session.usage` from an rpc `contextUsage` (`{tokens, contextWindow}`), when it has both.
fn pi_usage(u: &Value) -> Option<Event> {
    let used = u.get("tokens").and_then(Value::as_u64)?;
    let max = u.get("contextWindow").and_then(Value::as_u64).filter(|m| *m > 0)?;
    Some(ev("session.usage", json!({"used": used, "max": max})))
}

/// `session.commands` from an rpc command list: slash commands and prompts as `/name`, skills as `$skill:name`.
fn pi_commands(d: &Value) -> Event {
    let commands: Vec<Value> = d
        .get("commands")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|c| !s(c, "name").is_empty())
        .map(|c| {
            let skill = s(c, "source") == "skill";
            let prefix = if s(c, "syntax") == "dollar" { "$" } else { "/" };
            command_entry(&s(c, "name"), &s(c, "description"), "", if skill { "skill" } else { "command" }, prefix)
        })
        .collect();
    ev("session.commands", json!({"commands": commands}))
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

    fn name(&self) -> &str {
        if self.label.is_empty() {
            "pi"
        } else {
            &self.label
        }
    }

    fn start(&mut self) -> Step {
        let mut st = Step::default();
        self.cmd(&mut st, "get_state", json!({}));
        self.cmd(&mut st, "get_available_models", json!({}));
        self.read(&mut st, "get_available_thinking_levels");
        self.read(&mut st, "get_commands");
        st
    }

    fn in_turn(&self) -> bool {
        self.turn
    }

    fn on_line(&mut self, line: &str) -> Step {
        let mut st = Step::default();
        let Ok(v) = serde_json::from_str::<Value>(line) else { return st };
        if self.held && self.after_failure(&mut st, &v) {
            return st;
        }
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
                    } else if !what.is_empty() && !matches!(what, "get_available_thinking_levels" | "get_commands" | "get_session_stats") {
                        // (an agent without those reads simply has no levels, commands or usage)
                        st.emit(ev("session.error", json!({"message": format!("{}: {}", s(&v, "command"), self.friendly(&e))})));
                    }
                    return st;
                }
                match what {
                    "get_state" => {
                        let model = d.get("model").map(|m| s(m, "name")).filter(|n| !n.is_empty() && n != "unknown").or_else(|| d.get("model").map(|m| s(m, "id")).filter(|n| n != "unknown")).unwrap_or_default();
                        self.session = s(d, "sessionId");
                        let mut f = json!({"agent_session": s(d, "sessionId"), "model": model});
                        let level = s(d, "thinkingLevel");
                        if !level.is_empty() {
                            f["effort"] = Value::String(level);
                        }
                        st.emit(ev("session.info", f));
                        if let Some(u) = pi_usage(&d["contextUsage"]) {
                            st.emit(u);
                        }
                    }
                    "get_available_thinking_levels" => {
                        self.levels = d.get("levels").and_then(Value::as_array).into_iter().flatten().filter_map(|l| l.as_str().map(String::from)).collect();
                        if !self.levels.is_empty() {
                            st.emit(ev("session.efforts", json!({"levels": self.levels})));
                        }
                    }
                    "get_commands" => st.emit(pi_commands(d)),
                    "get_session_stats" => {
                        if let Some(u) = pi_usage(&d["contextUsage"]) {
                            st.emit(u);
                        }
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
                    "thinking_delta" => st.emit(thinking_event(&s(e, "delta"))),
                    "thinking_start" => st.emit(thinking_event("")),
                    _ => {}
                }
            }
            // the agent took the person's message (a follow-up leaves its queue here)
            "message_end" if s(&v["message"], "role") == "user" => self.waiting.take(&mut st),
            "thinking_level_changed" => st.emit(ev("session.info", json!({"effort": s(&v, "level")}))),
            "commands_changed" => st.emit(pi_commands(&v)),
            "message_start" if s(&v["message"], "role") == "custom" => {
                let m = v["message"].clone();
                self.task_done(&mut st, &m);
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
                let call = s(&v, "toolCallId");
                if name == "todo" && self.label == "OmO" {
                    // OmO's todo list: the turn's checklist once its result says how the list stands, never a step
                    self.todo_calls.insert(call);
                } else if name == "task" {
                    // the step names its subagents, never the call's raw JSON; each one gets its own row
                    let names: Vec<String> = args.get("tasks").and_then(Value::as_array).into_iter().flatten().map(|t| s(t, "name")).filter(|n| !n.is_empty()).collect();
                    let detail = if names.is_empty() { tool_detail(&args) } else { names.join(", ") };
                    st.emit(ev("tool.start", json!({"tool_id": call, "name": "delegate_task", "detail": clip(&detail, 160)})));
                    self.task_start(&mut st, &call, &args);
                } else {
                    st.emit(ev("tool.start", json!({"tool_id": call, "name": tool_kind(&name), "detail": call_detail(&name, &args, &self.cwd)})));
                    // pi's write / edit name the text they change: the diff view shows it
                    if let Some(f) = input_diff(&name, &args, &self.cwd) {
                        st.emit(ev("tool.diff", json!({"tool_id": call, "files": [f]})));
                    }
                }
            }
            "tool_execution_end" => {
                let ok = !v.get("isError").and_then(Value::as_bool).unwrap_or(false);
                let call = s(&v, "toolCallId");
                if self.todo_calls.remove(&call) {
                    if let Some(items) = omo_todo(&v["result"]["details"]) {
                        st.emit(plan_event(&items));
                    }
                    return st;
                }
                st.emit(ev("tool.end", json!({"tool_id": call, "name": "", "ok": ok, "ms": 0})));
                self.task_end(&mut st, &call, &v);
            }
            // what still runs after the turn: background commands (subagents have their own rows)
            "session_lifecycle" => {
                let w = &v["lifecycle"]["waitingOn"];
                let n: usize = w.get("background").and_then(Value::as_array).into_iter().flatten()
                    .filter(|b| !s(b, "source").starts_with("delivery:"))
                    .map(|b| b.get("activeCount").and_then(Value::as_u64).unwrap_or(1) as usize).sum();
                if n != self.background {
                    self.background = n;
                    st.emit(ev("session.info", json!({"background": n})));
                }
            }
            // Both end a run with agent_end. oh-my-pi then adds prompt_result and session_settled, which can arrive
            // after the person's next prompt was sent, so they never end a turn, except a prompt no agent ran for.
            "agent_end" => {
                // a Stop that hit a running tool leaves the last message at stopReason "toolUse": agent_end itself
                // says the run was aborted
                if v.get("aborted").and_then(Value::as_bool) == Some(true) {
                    self.last_stop = "aborted".into();
                } else if self.turn && v.get("failure").is_some_and(Value::is_object) {
                    // OmO may retry this by itself (`auto_retry_start` comes after agent_end, whatever its
                    // `willRetry` says): one message stays one turn until OmO says how it went
                    self.held = true;
                    return st;
                }
                self.end(&mut st)
            }
            "prompt_result" if v.get("agentInvoked").and_then(Value::as_bool) == Some(false) => self.end(&mut st),
            // OmO's own retry worked (it says so before that run's agent_end): the line stops saying it retries
            "auto_retry_end" if self.turn && v.get("success").and_then(Value::as_bool) == Some(true) => {
                st.emit(ev("status", json!({"text": ""})));
            }
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
                    // OmO sets its own statuses (memory, goal, web search) after agent_end too: those are not a turn
                    "setStatus" => {
                        let t = s(&v, "statusText");
                        if !t.is_empty() && self.turn {
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
            Input::Send { text, images, id } => {
                self.waiting.push(&mut st, id, self.streaming);
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
                self.read(&mut st, "get_available_thinking_levels");
            }
            Input::Mode { mode } => return Err(format!("{} has no permission mode here ({mode})", self.label)),
            Input::Rewind => return Err(format!("{} cannot take a message back here", self.label)),
            Input::Effort { effort } => {
                if !self.levels.contains(&effort) {
                    return Err(format!("unknown thinking level {effort}"));
                }
                self.cmd(&mut st, "set_thinking_level", json!({"level": effort}));
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
    /// the program and everything it started (`cmd.exe` and its `node.exe` on Windows)
    tree: Arc<Option<ProcessTree>>,
    exited: Arc<AtomicBool>,
}

/// Every running chat session of this app. [`ChatSessions::close_all`] runs on exit.
#[derive(Default)]
pub struct ChatSessions {
    live: Mutex<HashMap<u32, ChatLive>>,
    /// DSH chats: no process between messages, a run per message ([`DshChat`])
    dsh: Mutex<HashMap<u32, DshChat>>,
    next: AtomicU32,
    /// tests: a shorter [`START_DEADLINE`]
    start_deadline: Option<Duration>,
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
    // streamed answer text, and streamed thinking text, each joined with the piece right before it of its own kind
    let joinable = |e: &Event| e.as_object().is_some_and(|m| m.len() == 2 && matches!(s(e, "event").as_str(), "delta" | "thinking") && m.get("text").is_some_and(Value::is_string));
    let mut out: Vec<Event> = Vec::with_capacity(events.len());
    for e in events {
        if let Some(last) = out.last_mut() {
            if joinable(last) && joinable(&e) && s(last, "event") == s(&e, "event") {
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
    crate::appimage::host_env(&mut cmd);
    Ok(cmd)
}

/// `--add-dir <dir>` with `dir` as one argument. A Windows `.cmd` shim runs through `cmd.exe /c`, which parses the
/// line itself: there the folder goes in as [`cmd_path_arg`] allows it, and a folder it refuses adds nothing (the
/// person then answers a card per read, as before).
fn add_dir_args(program: &OsString, dir: &Path) -> Vec<OsString> {
    let dir = dir.as_os_str().to_owned();
    if program == "cmd.exe" {
        return match cmd_path_arg(&dir.to_string_lossy()) {
            Ok(d) => vec!["--add-dir".into(), d.into()],
            Err(_) => vec![],
        };
    }
    vec!["--add-dir".into(), dir]
}

/// How long an agent's rule listing ([`RuleProbe`]) may take before the chat is refused.
const RULES_DEADLINE: Duration = Duration::from_secs(30);

/// `probe`'s variable and value for a chat of the program `argv` in `cwd`: the program's fixed rule listing runs on
/// pipes with no input, with the same `PATH` and account variable the chat gets; `probe.build` turns its output into
/// the value, and a second listing with the value set must satisfy `probe.kept`. Any doubt (the variable already set
/// in omher's own environment, a failed or slow listing, output it cannot read, rules that did not hold) is
/// [`NO_RULES`], and the chat does not start.
fn agent_rules(probe: &RuleProbe, argv: &[OsString], cwd: &Path, path_env: &OsString, account_env: &[(String, String)]) -> Result<(String, String), String> {
    if !cwd.is_absolute() || !cwd.is_dir() {
        return Err(format!("not a folder: {}", cwd.display()));
    }
    if std::env::var_os(probe.var).is_some() {
        return Err(NO_RULES.into());
    }
    let mut argv = argv.to_vec();
    argv.extend(probe.args.iter().map(OsString::from));
    let list = |env: &[(String, String)]| -> Option<String> {
        let mut cmd = command_for(&argv, cwd, Some(path_env.clone()), env).ok()?;
        cmd.stdin(Stdio::null());
        let child = cmd.spawn().ok()?;
        let tree = ProcessTree::adopt(&child);
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let _ = tx.send(child.wait_with_output());
        });
        match rx.recv_timeout(RULES_DEADLINE) {
            Ok(Ok(o)) if o.status.success() => Some(String::from_utf8_lossy(&o.stdout).into_owned()),
            Err(_) => {
                if let Some(t) = tree {
                    t.kill();
                }
                None
            }
            _ => None,
        }
    };
    let value = list(account_env).and_then(|l| (probe.build)(&l)).ok_or(NO_RULES)?;
    let mut env = account_env.to_vec();
    env.push((probe.var.to_string(), value.clone()));
    match list(&env) {
        Some(again) if (probe.kept)(&value, &again) => Ok((probe.var.to_string(), value)),
        _ => Err(NO_RULES.into()),
    }
}

impl ChatSessions {
    pub fn new() -> Arc<ChatSessions> {
        Arc::new(ChatSessions::default())
    }

    /// Start allow-listed agent `agent_id` in its chat mode in `cwd`. `resume` (Claude Code, Codex, OmO)
    /// continues that conversation. `account_env` is `accounts::session_env` for that agent, as for a terminal session:
    /// the chosen account's home variable, or nothing. Anything not on the allow-list, or without a chat
    /// mode, is refused before a process exists.
    pub fn start_agent<F>(&self, agent_id: &str, cwd: &Path, resume: Option<&str>, account_env: &[(String, String)], files: Option<&Path>, sink: F) -> Result<u32, String>
    where
        F: FnMut(ChatOut) + Send + 'static,
    {
        let a = agent(agent_id).ok_or_else(|| format!("unknown agent \"{agent_id}\""))?;
        if a.mode != Mode::Chat {
            return Err(format!("{} has no chat mode", a.label));
        }
        if agent_id == "dsh" {
            // DeepSeek Harness: `resume` is the `session-<uuid>` it reported (resume_args checks it)
            let chat = DshChat::start(cwd, resume, sink)?;
            let id = self.next.fetch_add(1, Ordering::SeqCst) + 1;
            self.dsh.lock().unwrap().insert(id, chat);
            return Ok(id);
        }
        let args = chat_args(agent_id).ok_or("no chat mode")?;
        // Codex continues a thread over its own protocol (`thread/resume`), not by an argument; the id must
        // still be one Codex reported (a UUID). Claude Code takes `--resume <uuid>` ([`resume_args`]).
        // An ACP agent (`acp_chat`) continues over its protocol too (`session/resume`), with an id it reported.
        let acp = acp_agent(agent_id);
        let thread = match (agent_id, resume) {
            ("codex", Some(r)) if is_uuid(r) => Some(r),
            ("codex", Some(_)) => return Err("not a Codex thread id".into()),
            (_, Some(r)) if acp.is_some() && is_acp_session_id(r) => Some(r),
            (_, Some(_)) if acp.is_some() => return Err("not a conversation id".into()),
            _ => None,
        };
        let mut adapter = adapter_for(agent_id, &cwd.to_string_lossy(), thread).ok_or("no chat adapter")?;
        let (mut argv, path_env) = launch_for(agent_id)?;
        let program = argv.clone();
        if let Some(path) = unrecognized_program(agent_id) {
            adapter = Unrecognized::wrap(adapter, agent_id, &path);
        }
        argv.extend(args.iter().map(OsString::from));
        if let Some(r) = resume.filter(|_| thread.is_none()) {
            argv.extend(resume_args(agent_id, r)?);
        }
        // Claude Code reads the files the person attached without a card: the session's own attachment folder
        // (`session_files::session_dir`, made before the start; a folder made later is not honoured) is its one
        // extra working directory, as one argument. Reads anywhere else outside `cwd` still ask.
        if let Some(dir) = files.filter(|_| agent_id == "claude") {
            argv.extend(add_dir_args(&argv[0], dir));
        }
        // an agent whose own default runs tools unasked (OpenCode) gets ask rules built from its own resolved rules,
        // so nothing the person allows runs unasked and nothing they deny becomes askable; or it does not start
        let mut env = account_env.to_vec();
        if let Some(probe) = acp.and_then(|a| a.rules.as_ref()) {
            env.push(agent_rules(probe, &program, cwd, &path_env, account_env)?);
        }
        self.spawn(argv, cwd, Some(path_env), &env, adapter, sink)
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
        let tree = Arc::new(ProcessTree::adopt(&child));
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
        // the program printed a protocol message (it speaks its chat mode); until then a start deadline runs
        let answered = Arc::new(AtomicBool::new(false));
        // why omher ended the session itself (the start deadline): the exit reports this instead of stderr
        let verdict: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));

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
            let (adapter, stdin, sink, done, answered) = (adapter.clone(), stdin.clone(), sink.clone(), reader_done.clone(), answered.clone());
            thread::spawn(move || {
                let mut pending: Vec<u8> = Vec::new();
                let run = |lines: &mut dyn Iterator<Item = &[u8]>| {
                    let mut out = Step::default();
                    {
                        let mut a = adapter.lock().unwrap();
                        for raw in lines {
                            let line = String::from_utf8_lossy(raw);
                            // a BOM, or two messages on one line, still reach the adapter one message at a time
                            for msg in protocol_lines(line.trim_end_matches(['\n', '\r'])) {
                                answered.store(true, Ordering::SeqCst);
                                let step = a.on_line(msg);
                                out.write.extend(step.write);
                                out.events.extend(step.events);
                            }
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
        // set once stderr reached its end: the exit reason is read from all of it
        let err_done = Arc::new(AtomicBool::new(false));
        {
            let (tail, err_done) = (tail.clone(), err_done.clone());
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
                err_done.store(true, Ordering::SeqCst);
            });
        }
        {
            // the start deadline: a program that has printed no protocol message by then is not in its chat mode (an
            // old version showing its terminal UI, a hung start), so the session ends with that reason, all of it
            let (child, exited, sink, adapter, answered, verdict, tree) = (child.clone(), exited.clone(), sink.clone(), adapter.clone(), answered.clone(), verdict.clone(), tree.clone());
            let deadline = Instant::now() + self.start_deadline.unwrap_or(START_DEADLINE);
            thread::spawn(move || {
                while Instant::now() < deadline {
                    if answered.load(Ordering::SeqCst) || exited.load(Ordering::SeqCst) {
                        return;
                    }
                    thread::sleep(Duration::from_millis(50));
                }
                if answered.load(Ordering::SeqCst) || exited.load(Ordering::SeqCst) {
                    return;
                }
                let why = no_chat_mode(adapter.lock().unwrap().name());
                *verdict.lock().unwrap() = Some(why.clone());
                deliver(&sink, vec![ev("session.error", json!({"kind": "no_chat_mode", "message": why}))]);
                match tree.as_ref() {
                    Some(t) => t.kill(),
                    None => {
                        let _ = child.lock().unwrap().kill();
                    }
                }
            });
        }
        {
            let (child, exited, sink, adapter, done, answered, verdict) = (child.clone(), exited.clone(), sink.clone(), adapter.clone(), reader_done.clone(), answered.clone(), verdict.clone());
            let err_done = err_done.clone();
            thread::spawn(move || {
                let code = loop {
                    if let Ok(Some(st)) = child.lock().unwrap().try_wait() {
                        break st.code();
                    }
                    thread::sleep(Duration::from_millis(40));
                };
                exited.store(true, Ordering::SeqCst);
                // let the readers hand over what the program printed last (stdout's events, stderr's reason)
                let deadline = Instant::now() + Duration::from_millis(800);
                while !(done.load(Ordering::SeqCst) && err_done.load(Ordering::SeqCst)) && Instant::now() < deadline {
                    thread::sleep(Duration::from_millis(10));
                }
                let (mid_turn, err, said) = {
                    let a = adapter.lock().unwrap();
                    // code 0 is an orderly close: what it printed at start (a config warning) is no reason
                    let raw = exit_why(code, &tail.lock().unwrap());
                    match verdict.lock().unwrap().take() {
                        // the start deadline ended it, and already said so
                        Some(why) => (a.in_turn(), why, true),
                        // it never spoke its protocol and refused omher's chat-mode arguments: an old version
                        // an orderly close (code 0) failed nothing: no reason, whatever it printed
                        None if code == Some(0) => (a.in_turn(), String::new(), true),
                        None if !answered.load(Ordering::SeqCst) && !a.unrecognized() && refused_chat_mode(&raw) => (a.in_turn(), no_chat_mode(a.name()), false),
                        None => (a.in_turn(), a.explain(&raw), true),
                    }
                };
                if let Ok(mut f) = sink.lock() {
                    if !said {
                        f(ChatOut::Event(ev("session.error", json!({"kind": "no_chat_mode", "message": err}))));
                    }
                    if mid_turn {
                        f(ChatOut::Event(exit_turn_end(code, &err)));
                    }
                    f(ChatOut::Exit(code, err));
                }
            });
        }
        let id = self.next.fetch_add(1, Ordering::SeqCst) + 1;
        self.live.lock().unwrap().insert(id, ChatLive { stdin, adapter, sink, child, pid, tree, exited });
        Ok(id)
    }

    /// One thing the person did in chat `id`.
    pub fn input(&self, id: u32, input: Input) -> Result<(), String> {
        let dsh = self.dsh.lock().unwrap().get(&id).cloned();
        if let Some(chat) = dsh {
            return chat.input(input);
        }
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
        if let Some(chat) = self.dsh.lock().unwrap().remove(&id) {
            thread::spawn(move || chat.stop(Duration::from_millis(1500)));
        }
        let live = self.live.lock().unwrap().remove(&id);
        if let Some(s) = live {
            thread::spawn(move || stop(s, Duration::from_millis(1500)));
        }
    }

    pub fn close_all(&self) {
        let all: Vec<ChatLive> = self.live.lock().unwrap().drain().map(|(_, s)| s).collect();
        let dsh: Vec<DshChat> = self.dsh.lock().unwrap().drain().map(|(_, c)| c).collect();
        let mut handles: Vec<_> = all.into_iter().map(|s| thread::spawn(move || stop(s, Duration::from_millis(400)))).collect();
        handles.extend(dsh.into_iter().map(|c| thread::spawn(move || c.stop(Duration::from_millis(400)))));
        for h in handles {
            let _ = h.join();
        }
    }

    #[cfg(test)]
    pub fn count(&self) -> usize {
        self.live.lock().unwrap().len() + self.dsh.lock().unwrap().len()
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
        // Windows has no hang-up: the whole tree goes now (cmd.exe and the node.exe behind an npm shim)
        #[cfg(not(unix))]
        {
            match s.tree.as_ref() {
                Some(t) => t.kill(),
                None => {
                    let _ = s.child.lock().unwrap().kill();
                }
            }
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
    // whatever the program started and left behind (a helper that ignores hang-up, the node.exe behind cmd.exe) goes
    // with it, also when the program itself already ended
    if let Some(t) = s.tree.as_ref() {
        t.kill();
    }
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// A stand-in rule listing: `/bin/sh -c <script>` prints its first listing, or with the variable set its second.
    #[cfg(unix)]
    fn rules_with(script: &str) -> Result<(String, String), String> {
        fn build(l: &str) -> Option<String> {
            l.strip_prefix("rules:").map(|r| r.trim().to_string())
        }
        fn kept(rules: &str, again: &str) -> bool {
            again.trim() == format!("kept {rules}")
        }
        let probe = RuleProbe { args: &[], var: "OMHER_TEST_RULES_VAR", build, kept };
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let argv: Vec<OsString> = vec!["/bin/sh".into(), "-c".into(), script.into()];
        agent_rules(&probe, &argv, &tmp, &std::env::var_os("PATH").unwrap(), &[])
    }

    #[test]
    #[cfg(unix)]
    fn an_agent_starts_only_with_rules_it_listed_and_kept() {
        let ok = r#"if [ -n "$OMHER_TEST_RULES_VAR" ]; then echo "kept $OMHER_TEST_RULES_VAR"; else echo "rules: R1"; fi"#;
        assert_eq!(rules_with(ok), Ok(("OMHER_TEST_RULES_VAR".to_string(), "R1".to_string())));
        // each doubt refuses the start with the one plain sentence
        for bad in [
            "exit 1",                                                                                // the listing failed
            "echo 'Error: Config file is not valid JSON'",                                           // nothing it can read
            r#"if [ -n "$OMHER_TEST_RULES_VAR" ]; then echo "kept other"; else echo "rules: R1"; fi"#, // not kept
            r#"if [ -n "$OMHER_TEST_RULES_VAR" ]; then exit 1; else echo "rules: R1"; fi"#,           // second listing failed
        ] {
            assert_eq!(rules_with(bad), Err(NO_RULES.to_string()), "{bad}");
        }
    }

    impl Input {
        /// A message with text only.
        pub fn send(text: impl Into<String>) -> Input {
            Input::Send { text: text.into(), images: vec![], id: String::new() }
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
        // nothing to answer in a plain turn; only the context read after it
        let w: Vec<Value> = st.write.iter().map(|l| serde_json::from_str(l).unwrap()).collect();
        assert_eq!(w.iter().map(|v| v["request"]["subtype"].clone()).collect::<Vec<_>>(), [json!("get_context_usage")], "{:?}", st.write);
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
        assert_eq!(sent[3]["method"], "skills/list");
        assert_eq!(sent[4]["method"], "turn/start");
        assert_eq!(sent[4]["params"]["threadId"], "thr_1");
        assert_eq!(sent[4]["params"]["input"][0]["text"], "run the tests");
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

    /// H10, recorded from the real Claude Code started with `--add-dir` on the session's attachment folder (made before
    /// the start): reading the attached copy needs no card; reading a file in another folder still asks.
    #[test]
    fn claude_reads_an_attached_file_without_a_card_and_asks_for_anything_else() {
        let mut c = claude_up();
        let lines = real("claude-12-attach-read.jsonl");
        let second = lines.iter().rposition(|l| l.contains("\"subtype\":\"init\"")).unwrap();
        c.on_input(Input::send("first line of the attached file?")).unwrap();
        let one = run(&mut c, &lines[..second]);
        assert!(!names(&one.events).contains(&"approval.request".to_string()), "{:?}", one.events);
        assert!(one.events.iter().any(|e| s(e, "event") == "tool.start" && s(e, "detail").ends_with("/.omher/session-files/s1/1-meeting notes.txt")));
        assert!(one.events.iter().any(|e| s(e, "event") == "message" && s(e, "text") == "PERIWINKLE is the first line"));
        c.on_input(Input::send("read /w/elsewhere/plan.txt")).unwrap();
        let two = run(&mut c, &lines[second..]);
        let asks: Vec<&Event> = two.events.iter().filter(|e| s(e, "event") == "approval.request").collect();
        assert_eq!(asks.len(), 1, "{:?}", two.events);
        assert!(serde_json::to_string(asks[0]).unwrap().contains("/w/elsewhere/plan.txt"));
    }

    #[test]
    fn the_attachment_folder_is_one_add_dir_argument() {
        // one argv element, spaces and all, exactly the folder given: never split, never a parent
        let dir = Path::new("/Users/me/.omher/session-files/s12");
        assert_eq!(add_dir_args(&OsString::from("/opt/bin/claude"), dir), [OsString::from("--add-dir"), OsString::from("/Users/me/.omher/session-files/s12")]);
        let spaced = Path::new("/Users/Jane Doe/.omher/session-files/s3");
        assert_eq!(add_dir_args(&OsString::from("/opt/bin/claude"), spaced), [OsString::from("--add-dir"), OsString::from("/Users/Jane Doe/.omher/session-files/s3")]);
        // through `cmd.exe /c` (a Windows .cmd shim) the folder goes as cmd allows it, or not at all
        assert_eq!(add_dir_args(&OsString::from("cmd.exe"), Path::new(r"C:\Users\a&b\.omher\session-files\s1")), [OsString::from("--add-dir"), OsString::from(r"C:\Users\a^&b\.omher\session-files\s1")]);
        assert!(add_dir_args(&OsString::from("cmd.exe"), Path::new(r"C:\Users\50%\.omher\session-files\s1")).is_empty());
    }

    #[test]
    fn only_chat_agents_have_adapters() {
        for id in ["claude", "codex", "omo", "pi", "omp", "opencode"] {
            assert!(adapter_for(id, "/w", None).is_some(), "{id}");
        }
        // DSH has no adapter: its chat is a run per message (dsh_chat)
        for id in ["omh", "grok", "dsh", "sh", ""] {
            assert!(adapter_for(id, "/w", None).is_none(), "{id}");
        }
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir();
        assert!(c.start_agent("dsh", &tmp, Some("eee5079a-c52e-4526-b633-f3d8cb7d6394"), &[], None, |_| {}).is_err());
        for bad in ["omh", "grok", "/bin/sh", "claude -p"] {
            assert!(c.start_agent(bad, &tmp, None, &[], None, |_| {}).is_err(), "{bad}");
        }
        assert!(c.start_agent("claude", &tmp, Some("--dangerously-skip-permissions"), &[], None, |_| {}).is_err());
        assert!(c.start_agent("opencode", &tmp, Some("ses_x --yolo"), &[], None, |_| {}).is_err());
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
            let id = c.start_agent("omo", &dir, resume, &[], None, move |x| o.lock().unwrap().push(x)).unwrap();
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

    /// The real OmO, Claude Code and Codex, one short message each through `start_agent`: every event the chat
    /// gets (and the ones that come within 4 s after the answer) leaves no turn open and says nothing outside one.
    /// `OMHER_REAL_OUT=<dir>` keeps each agent's events as `<agent>.json` for a replay through the store.
    /// Spends one small turn per agent: `cargo test real_agents_answer_and_go_idle -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_agents_answer_and_go_idle() {
        let dir = std::env::temp_dir().join(format!("omher-real-idle-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let dir = dir.canonicalize().unwrap();
        for agent in ["omo", "claude", "codex"] {
            let c = ChatSessions::default();
            let out = Arc::new(Mutex::new(Vec::new()));
            let o = out.clone();
            let id = c.start_agent(agent, &dir, None, &[], None, move |x| o.lock().unwrap().push(x)).unwrap();
            if agent == "omo" {
                // OmO's own default can be a model its provider refuses on this machine: pick one it serves
                thread::sleep(Duration::from_secs(3));
                c.input(id, Input::Model { model: std::env::var("OMHER_REAL_OMO_MODEL").unwrap_or("anthropic/claude-fable-5-1".into()) }).unwrap();
                thread::sleep(Duration::from_secs(1));
            }
            c.input(id, Input::Send { text: "hi. reply with just the word ok".into(), images: vec![], id: String::new() }).unwrap();
            let deadline = Instant::now() + Duration::from_secs(150);
            while Instant::now() < deadline && !out.lock().unwrap().iter().any(|x| matches!(x, ChatOut::Event(e) if s(e, "event") == "turn.end")) {
                thread::sleep(Duration::from_millis(100));
            }
            // what the agent says after its turn (OmO's setStatus, agent_settled, …)
            thread::sleep(Duration::from_secs(4));
            let events: Vec<Event> = out.lock().unwrap().iter().filter_map(|x| match x { ChatOut::Event(e) => Some(e.clone()), _ => None }).collect();
            c.close(id);
            thread::sleep(Duration::from_millis(500));
            let mut open = false;
            for e in &events {
                match s(e, "event").as_str() {
                    "turn.start" => open = true,
                    "turn.end" => open = false,
                    "status" | "thinking" | "tool.start" | "tool.end" | "delta" | "skill" => assert!(open, "{agent}: {e} outside a turn"),
                    _ => {}
                }
            }
            let msgs: Vec<String> = events.iter().filter(|e| s(e, "event") == "message").map(|e| s(e, "text")).collect();
            let after = events.iter().skip_while(|e| s(e, "event") != "turn.end").skip(1).map(|e| s(e, "event")).collect::<Vec<_>>();
            println!("{agent}: answer {msgs:?}; {} events; after turn.end: {after:?}", events.len());
            assert!(!open, "{agent}: the turn never ended");
            assert!(msgs.iter().any(|m| m.to_lowercase().contains("ok")), "{agent}: {events:?}");
            if let Some(d) = std::env::var_os("OMHER_REAL_OUT") {
                std::fs::write(Path::new(&d).join(format!("{agent}.json")), serde_json::to_string_pretty(&events).unwrap()).unwrap();
            }
        }
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
        let mut input = Input::Send { text, images: vec![Picture::from(pic.to_string_lossy().into_owned())], id: String::new() };
        input.resolve(&home).unwrap();
        let c = Arc::new(ChatSessions::default());
        let out = Arc::new(Mutex::new(Vec::<ChatOut>::new()));
        let (o, c2, me) = (out.clone(), c.clone(), Arc::new(Mutex::new(0u32)));
        let me2 = me.clone();
        let id = c
            .start_agent(&agent, &dir, None, &[], None, move |x| {
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

    /// The real check for a session's transcript: the agent (OMHER_REAL_AGENT, default claude) in a temp folder through
    /// omher's own start, asked for a two-file edit with its todo list; prints what the chat got (each edit's change,
    /// the todo list, the thinking text), then takes the message back with the agent's own rewind and asks whether it
    /// remembers it. Approvals for files inside the folder are answered `once`. Spends two short turns:
    /// `cargo test real_agent_shows_its_work -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_agent_shows_its_work() {
        let agent = std::env::var("OMHER_REAL_AGENT").unwrap_or_else(|_| "claude".into());
        let base = std::env::var("OMHER_REAL_DIR").map(std::path::PathBuf::from).unwrap_or_else(|_| std::env::temp_dir().join(format!("omher-real-work-{agent}-{}", std::process::id())));
        let dir = base.join("proj");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("calc.py"), "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n").unwrap();
        std::fs::write(dir.join("README.md"), "# calc\n\nTiny math helpers.\n").unwrap();
        let dir = dir.canonicalize().unwrap();
        let c = Arc::new(ChatSessions::default());
        let out = Arc::new(Mutex::new(Vec::<ChatOut>::new()));
        let (o, c2, me) = (out.clone(), c.clone(), Arc::new(Mutex::new(0u32)));
        let me2 = me.clone();
        let inside = dir.to_string_lossy().into_owned();
        let id = c
            .start_agent(&agent, &dir, None, &[], None, move |x| {
                if let ChatOut::Event(e) = &x {
                    if s(e, "event") == "approval.request" {
                        let ok = s(e, "title").contains("calc.py") || s(e, "title").contains("README.md") || s(e, "command").contains(&inside);
                        let (c3, rid, id) = (c2.clone(), s(e, "request_id"), *me2.lock().unwrap());
                        thread::spawn(move || {
                            let _ = c3.input(id, Input::Approve { request_id: rid, choice: if ok { "once".into() } else { "deny".into() } });
                        });
                    }
                }
                o.lock().unwrap().push(x);
            })
            .unwrap();
        *me.lock().unwrap() = id;
        let ends = |out: &Arc<Mutex<Vec<ChatOut>>>| out.lock().unwrap().iter().filter(|x| matches!(x, ChatOut::Event(e) if s(e, "event") == "turn.end")).count();
        let wait = |n: usize| {
            let deadline = Instant::now() + Duration::from_secs(300);
            while Instant::now() < deadline && ends(&out) < n {
                thread::sleep(Duration::from_millis(200));
            }
        };
        let text = "Make a 3-item todo list with your task tools first, then do it, updating each item as you go: in calc.py add a mul(a, b) function and give add a one-line docstring; in README.md add a line listing the functions. Think briefly first.";
        c.input(id, Input::Send { text: text.into(), images: vec![], id: "local-1".into() }).unwrap();
        wait(1);
        thread::sleep(Duration::from_millis(500));
        // the rewind, then a question about the message it took back
        let r = c.input(id, Input::Rewind);
        let deadline = Instant::now() + Duration::from_secs(60);
        while Instant::now() < deadline && !out.lock().unwrap().iter().any(|x| matches!(x, ChatOut::Event(e) if s(e, "event") == "rewound" || s(e, "event") == "session.error")) {
            thread::sleep(Duration::from_millis(200));
        }
        c.input(id, Input::Send { text: "Did I ask you for anything earlier in this conversation? Answer yes or no, then say what in five words.".into(), images: vec![], id: "local-2".into() }).unwrap();
        wait(2);
        let got: Vec<Value> = out.lock().unwrap().iter().filter_map(|x| match x { ChatOut::Event(e) => Some(e.clone()), _ => None }).collect();
        c.close(id);
        let dump = base.join("events.jsonl");
        std::fs::write(&dump, got.iter().map(|e| e.to_string() + "\n").collect::<String>()).unwrap();
        println!("rewind input: {r:?}; events: {}", dump.display());
        for e in &got {
            match s(e, "event").as_str() {
                "tool.diff" => println!("DIFF {}", e["files"]),
                "plan" => println!("PLAN {}", e["items"]),
                "rewound" | "message" | "turn.end" | "session.error" => println!("{e}"),
                _ => {}
            }
        }
        let thinking: String = got.iter().filter(|e| s(e, "event") == "thinking").map(|e| s(e, "text")).collect();
        println!("THINKING {thinking:?}");
        assert!(got.iter().any(|e| s(e, "event") == "tool.diff"), "no diff");
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
            .start_agent("claude", &dir.canonicalize().unwrap(), None, &[], None, move |x| {
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

    /// The OmO records recorded with the omo-13 streams (never the person's own `~/.omo`).
    fn fixture_omo_home() -> Option<PathBuf> {
        Some(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("omo-home"))
    }

    fn omo_pi() -> Pi {
        Pi { omo_home: fixture_omo_home(), ..Pi::new("/w/proj", "OmO") }
    }

    fn pi_up(label: &str, init: &[&str]) -> Pi {
        let mut p = if label == "OmO" { omo_pi() } else { Pi::new("/w/proj", label) };
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
    fn real_claude_late_subagent_ask_after_the_turn_is_answered_with_no_turn_running() {
        // claude-13-late-ask.jsonl (Claude Code 2.1.322): `result` ends the turn, then the background subagent asks
        let mut c = claude_up();
        let lines = real("claude-13-late-ask.jsonl");
        c.on_input(Input::send("start one")).unwrap();
        let st = run(&mut c, &lines[..15]);
        let end = st.events.iter().position(|e| s(e, "event") == "turn.end").unwrap();
        let ask = st.events.iter().position(|e| s(e, "event") == "approval.request").unwrap();
        assert!(end < ask, "the ask comes after the turn's end");
        assert!(!c.in_turn());
        let card = &st.events[ask];
        assert_eq!(s(card, "command"), "echo gamma > c.txt");
        assert_eq!(card["subagent"]["name"], "Write gamma to c.txt");
        // the person's answer, with no turn running, is written to Claude Code as its control_response
        let ans = written(&c.on_input(Input::Approve { request_id: s(card, "request_id"), choice: "once".into() }).unwrap());
        assert_eq!(ans[0]["type"], "control_response");
        assert_eq!(ans[0]["response"]["request_id"], card["request_id"]);
        assert_eq!(ans[0]["response"]["response"]["behavior"], "allow");
        // the subagent runs on and ends with its answer; Claude Code's own turn tells of it
        let rest = run(&mut c, &lines[15..]);
        let sub = of(&rest.events, "subagent").into_iter().find(|e| s(e, "state") == "done").unwrap();
        assert_eq!(s(sub, "summary"), "WROTE");
        assert_eq!(ends(&rest.events), [("done".into(), "".into())]);
    }

    #[test]
    fn real_claude_ask_a_background_subagent_left_open_at_the_turns_end_can_still_be_answered() {
        // claude-13-late-ask-inside.jsonl: the subagent asks during the turn, `result` comes with the ask open, and
        // Claude Code still waits: it took the person's answer 15 s later and the subagent wrote d.txt
        let mut c = claude_up();
        let lines = real("claude-13-late-ask-inside.jsonl");
        c.on_input(Input::send("two things")).unwrap();
        let st = run(&mut c, &lines[..21]);
        let ask = st.events.iter().position(|e| s(e, "event") == "approval.request").unwrap();
        let end = st.events.iter().position(|e| s(e, "event") == "turn.end").unwrap();
        assert!(ask < end, "asked inside the turn");
        assert!(of(&st.events, "prompt.expired").is_empty(), "the turn's end does not withdraw a background subagent's ask");
        let rid = s(&st.events[ask], "request_id");
        let ans = written(&c.on_input(Input::Approve { request_id: rid.clone(), choice: "once".into() }).unwrap());
        assert_eq!(ans[0]["response"]["request_id"], rid.as_str());
        let rest = run(&mut c, &lines[21..]);
        assert_eq!(of(&rest.events, "subagent").iter().find(|e| s(e, "state") == "done").map(|e| s(e, "summary")).as_deref(), Some("WROTE"));
    }

    #[test]
    fn real_claude_late_subagent_ask_is_withdrawn_by_stop_and_by_the_subagents_end() {
        // claude-13-late-ask-stop.jsonl: Stop with no turn running; Claude Code cancels the ask and stops the subagent
        let mut c = claude_up();
        let lines = real("claude-13-late-ask-stop.jsonl");
        c.on_input(Input::send("start one")).unwrap();
        let st = run(&mut c, &lines[..15]);
        let rid = s(of(&st.events, "approval.request")[0], "request_id");
        assert_eq!(written(&c.on_input(Input::Interrupt).unwrap())[0]["request"]["subtype"], "interrupt");
        let rest = run(&mut c, &lines[15..]);
        assert_eq!(of(&rest.events, "prompt.expired")[0]["request_id"], rid.as_str());
        assert_eq!(of(&rest.events, "subagent").iter().map(|e| s(e, "state")).collect::<Vec<_>>(), ["cancelled"]);
        assert!(c.on_input(Input::Approve { request_id: rid, choice: "once".into() }).is_err());
        // a subagent that ends with its ask unanswered takes the ask with it (no cancel came: the notification did)
        let mut c = claude_up();
        c.on_input(Input::send("start one")).unwrap();
        run(&mut c, &lines[..15]);
        let rest = run(&mut c, &lines[16..21]);
        assert_eq!(of(&rest.events, "prompt.expired")[0]["request_id"], rid_of(&lines[14]).as_str());
    }

    #[test]
    fn real_claude_stop_after_the_turn_stops_its_background_command() {
        // claude-14-background-stop.jsonl (Claude Code 2.1.323): `sleep 45; …` runs in the background, the turn ends,
        // then Stop: Claude Code's own interrupt plus its stop_task for that command; the command ends at once
        let mut c = claude_up();
        let lines = real("claude-14-background-stop.jsonl");
        c.on_input(Input::send("start it")).unwrap();
        let st = run(&mut c, &lines[..35]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        assert!(st.events.iter().any(|e| s(e, "event") == "session.info" && e["background"] == 1));
        let w = written(&c.on_input(Input::Interrupt).unwrap());
        assert_eq!(w.iter().map(|x| x["request"].clone()).collect::<Vec<_>>(), [json!({"subtype": "interrupt"}), json!({"subtype": "stop_task", "task_id": "be81yjkbr"})]);
        let rest = run(&mut c, &lines[35..]);
        assert_eq!(rest.events, [json!({"event": "session.info", "background": 0})]);
        assert!(!c.in_turn());
        // while a turn runs, Stop is that turn's interrupt only
        c.on_input(Input::send("again")).unwrap();
        assert_eq!(written(&c.on_input(Input::Interrupt).unwrap()).len(), 1);
    }

    #[test]
    fn real_claude_background_subagent_row_names_its_model() {
        // claude-13-late-ask-stop.jsonl: the Agent call's launch result says `resolvedModel` (a foreground subagent's
        // hand-back says it too); the row carries it from then on
        let mut c = claude_up();
        c.on_input(Input::send("start one")).unwrap();
        let st = run(&mut c, &real("claude-13-late-ask-stop.jsonl")[..15]);
        let rows = of(&st.events, "subagent");
        assert_eq!(s(rows.last().unwrap(), "model"), "claude-opus-5-5", "{rows:?}");
    }

    fn rid_of(line: &str) -> String {
        s(&serde_json::from_str::<Value>(line).unwrap(), "request_id")
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

    /// H5, recorded from the real Codex 0.167 (`thread/resume` onto a deleted thread): omher starts a new thread in the
    /// same folder, says so, and the message the person sent while it waited goes to the new thread.
    #[test]
    fn codex_resume_onto_a_gone_thread_starts_a_new_one_and_sends_what_waited() {
        let gone = "0badbeef-0000-4000-8000-000000000000";
        let mut x = Codex::new("/w/proj", Some(gone));
        x.start();
        let lines = real("codex-11-resume-gone.jsonl");
        // the person's message is sent before Codex has answered anything (omher reopened the chat by itself)
        let sent = x.on_input(Input::send("Reply with exactly: ok")).unwrap();
        assert_eq!(names(&sent.events), ["turn.start"]);
        assert!(sent.write.is_empty(), "no thread yet: the message waits");
        let st = run(&mut x, &lines[..5]);
        let w = written(&st);
        assert_eq!(w.iter().filter(|c| c["method"] == "thread/resume").count(), 1);
        // the resume error is said in the chat and answered with a new thread in the same folder, not a popover note
        let note = of(&st.events, "session.note");
        assert_eq!(note.len(), 1, "{:?}", st.events);
        assert_eq!(s(note[0], "kind"), "new_conversation");
        assert!(of(&st.events, "session.error").is_empty(), "{:?}", st.events);
        let start = w.iter().find(|c| c["method"] == "thread/start").expect("a new thread");
        assert_eq!(start["params"]["cwd"], "/w/proj");
        assert!(x.in_turn(), "the message is still on its way");
        let st = run(&mut x, &lines[5..]);
        let new = "01a1cb4b-0d4e-7751-aae4-9d65216fa4e6";
        assert_eq!(s(of(&st.events, "session.info")[0], "agent_session"), new);
        let w = written(&st);
        let turn = w.iter().find(|c| c["method"] == "turn/start").expect("the waiting message is sent");
        assert_eq!(turn["params"]["threadId"], new);
        assert_eq!(turn["params"]["input"][0]["text"], "Reply with exactly: ok");
        // Stop works on it like on any turn
        x.on_line(r#"{"method":"turn/started","params":{"threadId":"01a1cb4b-0d4e-7751-aae4-9d65216fa4e6","turn":{"id":"t1"}}}"#);
        assert_eq!(written(&x.on_input(Input::Interrupt).unwrap())[0]["method"], "turn/interrupt");
    }

    /// H5: when the new thread cannot start either, the waiting message ends its turn with the reason (no Working).
    #[test]
    fn codex_resume_and_new_thread_both_refused_end_the_waiting_turn() {
        let mut x = Codex::new("/w/proj", Some("0badbeef-0000-4000-8000-000000000000"));
        x.start();
        x.on_input(Input::send("hi")).unwrap();
        run(&mut x, &real("codex-11-resume-gone.jsonl")[..5]);
        let st = x.on_line(r#"{"id":5,"error":{"code":-32600,"message":"not signed in"}}"#);
        assert_eq!(ends(&st.events), [("error".into(), "Codex could not start a conversation: not signed in".into())]);
        assert!(!x.in_turn());
    }

    /// H7, recorded from the real Claude Code 2.1.322: Haiku picked between turns, Sonnet picked right after the next
    /// message went out. That turn still runs on Haiku (its init and its answer say so); the header keeps Haiku and
    /// says "next turn: Sonnet", never Sonnet, Haiku, Sonnet; the next turn's init confirms Sonnet.
    #[test]
    fn real_claude_11_a_model_picked_mid_turn_is_for_the_next_turn() {
        let mut c = claude_up();
        let lines = real("claude-11-model-mid-turn.jsonl");
        let haiku = written(&c.on_input(Input::Model { model: "haiku".into() }).unwrap())[0].clone();
        assert_eq!(s(&haiku, "request_id"), "omher-model-3");
        let st = run(&mut c, &lines[..1]);
        assert_eq!(of(&st.events, "session.info").iter().map(|e| s(e, "model")).collect::<Vec<_>>(), ["Haiku 5.5"]);
        c.on_input(Input::send("Reply with exactly: ok")).unwrap();
        let sonnet = written(&c.on_input(Input::Model { model: "sonnet".into() }).unwrap())[0].clone();
        assert_eq!(s(&sonnet, "request_id"), "omher-model-4");
        // everything until the turn's end, then the next turn
        let first_end = lines.iter().position(|l| l.contains("\"type\":\"result\"")).unwrap();
        let st = run(&mut c, &lines[1..=first_end]);
        let models: Vec<String> = of(&st.events, "session.info").iter().filter_map(|e| e.get("model").and_then(Value::as_str).map(String::from)).collect();
        assert!(models.iter().all(|m| m == "Haiku 5.5"), "the header flips: {models:?}");
        let next: Vec<String> = of(&st.events, "session.info").iter().filter_map(|e| e.get("model_next").and_then(Value::as_str).map(String::from)).collect();
        assert_eq!(next, ["Sonnet 5.5"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        c.on_input(Input::send("Reply with exactly: ok")).unwrap();
        let st = run(&mut c, &lines[first_end + 1..]);
        let info = of(&st.events, "session.info")[0];
        assert_eq!(s(info, "model"), "Sonnet 5.5");
        assert_eq!(info["model_next"], "", "the next turn's init confirms the pick");
        // a pick between turns still applies at once
        let st = run(&mut c, &[r#"{"type":"control_response","response":{"subtype":"success","request_id":"omher-model-9","response":{"model":"claude-haiku-5-5"}}}"#.to_string()]);
        assert_eq!(s(of(&st.events, "session.info")[0], "model"), "Haiku 5.5");
    }

    /// H11: a byte-order mark before a line, and two messages on one line, reach the adapter as protocol messages,
    /// one at a time, in order. A banner or a terminal frame is still nothing.
    #[test]
    fn protocol_lines_drop_a_bom_and_split_two_messages_on_one_line() {
        assert_eq!(protocol_lines("\u{feff}{\"a\":1}"), [r#"{"a":1}"#]);
        assert_eq!(protocol_lines(r#"{"type":"agent_end"}{"type":"agent_start"}"#), [r#"{"type":"agent_end"}"#, r#"{"type":"agent_start"}"#]);
        assert_eq!(protocol_lines(r#"{"a":1}  {"b":"}{"}"#), [r#"{"a":1}"#, r#"{"b":"}{"}"#]);
        assert!(protocol_lines("Welcome to OmO 3.0 (press q)").is_empty());
        assert!(protocol_lines("\u{1b}[?1049h\u{1b}[2J omo 3.0 interactive").is_empty());
        // a value cut short (a truncated line) yields what came before it
        assert_eq!(protocol_lines(r#"{"a":1}{"b":"#), [r#"{"a":1}"#]);
        assert!(protocol_lines("").is_empty());
    }

    /// H11 on pipes, every adapter: the QA's `pipe-bom` stub (a BOM before pi's get_state answer, agent_end and the
    /// next agent_start on one line) and the same drift in Claude Code's and Codex's first lines.
    #[cfg(unix)]
    #[test]
    fn a_bom_or_two_messages_on_one_line_do_not_hang_any_chat() {
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        // the stub answers once it has read what omher wrote at start and the person's message (`reads` lines)
        let run_stub = |adapter: Box<dyn Adapter>, reads: usize, out: &str| {
            let c = ChatSessions::default();
            let (got, sink) = collect();
            let script = format!("{}printf '{out}'; sleep 0.3", "read l; ".repeat(reads));
            let id = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], adapter, sink).unwrap();
            c.input(id, Input::send("hi")).unwrap();
            assert!(wait_for(|| got.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
            let events: Vec<Event> = got.lock().unwrap().iter().filter_map(|o| match o { ChatOut::Event(e) => Some(e.clone()), _ => None }).collect();
            events
        };
        // pi (the QA stub's bytes): the session id arrives, and the turn ends done at agent_end, not at the exit
        let ev = run_stub(Box::new(Pi::new("/w", "pi")), 3, r#"\357\273\277{"id":"omher-1","type":"response","command":"get_state","success":true,"data":{"model":{"id":"m","name":"M"},"sessionId":"s-bom"}}\r\n{"type":"agent_start"}\r\n{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"crlf ok"}],"stopReason":"stop"}}\r\n{"type":"agent_end"}{"type":"agent_start"}\n"#);
        assert_eq!(s(of(&ev, "session.info")[0], "agent_session"), "s-bom");
        assert_eq!(ends(&ev)[0], ("done".into(), "".into()), "{ev:?}");
        // Claude Code: its init behind a BOM, and the turn's result glued to the line before it
        let ev = run_stub(Box::new(Claude::new("/w")), 2, r#"\357\273\277{"type":"system","subtype":"init","session_id":"c-bom","model":"m"}\n{"type":"assistant","parent_tool_use_id":null,"message":{"id":"m1","content":[{"type":"text","text":"ok"}]}}{"type":"result","subtype":"success","is_error":false,"result":"ok"}\n"#);
        assert_eq!(s(of(&ev, "session.info")[0], "agent_session"), "c-bom");
        assert_eq!(ends(&ev)[0], ("done".into(), "".into()), "{ev:?}");
        // Codex: the initialize answer behind a BOM still opens the thread (the message waiting for it goes out)
        let c = ChatSessions::default();
        let (got, sink) = collect();
        let mark = tmp.join(format!("omher-chat-bom-{}", std::process::id()));
        let script = format!("read l; printf '\\357\\273\\277{{\"id\":1,\"result\":{{}}}}\\n'; while read l; do printf '%s\\n' \"$l\" >> '{}'; done", mark.display());
        let id = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], Box::new(Codex::new("/w", None)), sink).unwrap();
        assert!(wait_for(|| std::fs::read_to_string(&mark).is_ok_and(|t| t.contains("thread/start")), 10), "Codex's handshake stalled on a BOM");
        c.close(id);
        assert!(wait_for(|| got.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let _ = std::fs::remove_file(mark);
    }

    /// H4: the QA's `old-omo` stub (an old OmO that ignores `--mode rpc`, draws its terminal UI and waits). The start
    /// deadline ends the session with the plain reason, the message sent meanwhile ends with it, nothing stays
    /// Working, and the program (and what it started) is stopped.
    #[cfg(unix)]
    #[test]
    fn a_program_that_never_answers_in_chat_mode_ends_with_the_reason() {
        let mut c = ChatSessions::default();
        c.start_deadline = Some(Duration::from_millis(600));
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (out, sink) = collect();
        let script = "trap '' HUP; printf '\\033[?1049h\\033[2J omo 3.0 interactive  (press q)\\n'; sleep 30 & cat >/dev/null; wait";
        let id = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], Box::new(Pi::new("/w", "OmO")), sink).unwrap();
        c.input(id, Input::send("hi")).unwrap();
        let started = Instant::now();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10), "still Working");
        assert!(started.elapsed() < Duration::from_secs(5), "{:?}", started.elapsed());
        let got = out.lock().unwrap().clone();
        let why = "OmO did not answer in chat mode; it may be an old version: update it, then Restart.";
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "session.error" && s(e, "kind") == "no_chat_mode" && s(e, "message") == why)), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end" && s(e, "outcome") == "error" && s(e, "error") == why)), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(_, e) if e == why)), "{got:?}");
    }

    /// H4: a slow but healthy start is not cut: an agent whose first protocol line comes after a while (within the
    /// deadline) keeps its session and answers.
    #[cfg(unix)]
    #[test]
    fn a_slow_start_within_the_deadline_still_works() {
        let mut c = ChatSessions::default();
        c.start_deadline = Some(Duration::from_millis(1500));
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (out, sink) = collect();
        let script = r#"sleep 0.8; printf '{"id":"omher-1","type":"response","command":"get_state","success":true,"data":{"model":{"name":"M"},"sessionId":"slow"}}\n'; sleep 1.5; printf '{"type":"agent_start"}\n{"type":"agent_end"}\n'; sleep 0.2"#;
        let mut a: Box<dyn Adapter> = Box::new(Pi::new("/w", "pi"));
        a.on_input(Input::send("hi")).unwrap();
        c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], a, sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let got = out.lock().unwrap().clone();
        assert!(!got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "kind") == "no_chat_mode")), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end" && s(e, "outcome") == "done")), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(0), e) if e.is_empty())), "{got:?}");
    }

    /// H4: the QA's `old-pi` stub (exits at once with `error: unknown option '--mode'`): the same plain reason, not
    /// the raw flag error.
    #[cfg(unix)]
    #[test]
    fn an_old_version_that_refuses_the_chat_mode_flag_says_so_plainly() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let (out, sink) = collect();
        let script = "echo \"error: unknown option '--mode'\" >&2; echo 'Usage: pi [options] [message]' >&2; exit 1";
        c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], Box::new(Pi::new("/w", "pi")), sink).unwrap();
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        let got = out.lock().unwrap().clone();
        let why = "pi did not answer in chat mode; it may be an old version: update it, then Restart.";
        assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "kind") == "no_chat_mode")), "{got:?}");
        assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(1), e) if e == why)), "{got:?}");
        // a program that did speak its protocol keeps its own reason (a login, a crash)
        assert!(refused_chat_mode("error: unknown option '--mode'") && refused_chat_mode("error: unexpected argument 'app-server' found"));
        assert!(!refused_chat_mode("Error: not logged in"));
    }

    /// H12: closing a chat stops what its program started too (Unix: the process group; Windows: the Job Object
    /// that holds `cmd.exe` and the `node.exe` behind an npm shim). Here a child that ignores hang-up and outlives
    /// its parent stands in for node behind cmd.exe.
    #[cfg(unix)]
    #[test]
    fn closing_a_chat_stops_the_processes_its_program_started() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let mark = tmp.join(format!("omher-chat-tree-{}", std::process::id()));
        let (out, sink) = collect();
        // the grandchild writes its pid, ignores HUP and TERM, and lives on alone once the shell above it is gone
        let script = format!("sh -c 'trap \"\" HUP TERM; echo $$ > \"{}\"; while :; do sleep 1; done' & printf '{{\"type\":\"agent_start\"}}\\n'; wait", mark.display());
        let id = c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], Box::new(Pi::new("/w", "pi")), sink).unwrap();
        assert!(wait_for(|| std::fs::read_to_string(&mark).is_ok_and(|t| !t.trim().is_empty()), 10));
        let pid: i32 = std::fs::read_to_string(&mark).unwrap().trim().parse().unwrap();
        c.close(id);
        assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
        assert!(wait_for(|| unsafe { libc::kill(pid, 0) } != 0, 10), "pid {pid} kept running after close");
        let _ = std::fs::remove_file(mark);
    }

    /// H12 on Windows (runs on the Windows CI job only): a chat started through `cmd.exe /c` — as an npm `.cmd` shim
    /// is — whose child outlives cmd.exe; closing the chat ends that child too.
    #[cfg(windows)]
    #[test]
    fn closing_a_chat_stops_the_node_behind_a_cmd_shim() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir();
        let mark = tmp.join(format!("omher-chat-tree-{}.txt", std::process::id()));
        let _ = std::fs::remove_file(&mark);
        let (out, sink) = {
            let out = Arc::new(Mutex::new(Vec::new()));
            let o = out.clone();
            (out, move |x| o.lock().unwrap().push(x))
        };
        // cmd.exe starts a PowerShell that writes its own pid and sleeps; cmd.exe itself waits on it, as on node
        let ps = format!("$PID | Out-File -Encoding ascii '{}'; Start-Sleep -Seconds 120", mark.display());
        let argv: Vec<OsString> = vec!["cmd.exe".into(), "/c".into(), "powershell".into(), "-NoProfile".into(), "-Command".into(), ps.into()];
        let id = c.spawn(argv, &tmp, None, &[], Box::new(Pi::new("/w", "pi")), sink).unwrap();
        let deadline = Instant::now() + Duration::from_secs(30);
        while Instant::now() < deadline && !std::fs::read_to_string(&mark).is_ok_and(|t| !t.trim().is_empty()) {
            thread::sleep(Duration::from_millis(100));
        }
        let pid: u32 = std::fs::read_to_string(&mark).unwrap().trim().parse().unwrap();
        c.close(id);
        let deadline = Instant::now() + Duration::from_secs(15);
        while Instant::now() < deadline && !out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))) {
            thread::sleep(Duration::from_millis(50));
        }
        let alive = || {
            let o = Command::new("tasklist").args(["/FI", &format!("PID eq {pid}"), "/NH"]).output().unwrap();
            String::from_utf8_lossy(&o.stdout).contains(&pid.to_string())
        };
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline && alive() {
            thread::sleep(Duration::from_millis(100));
        }
        assert!(!alive(), "the process behind cmd.exe (pid {pid}) kept running after close");
        let _ = std::fs::remove_file(mark);
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
        // its startup thinking_level_changed says the effort first; get_state then names the session
        let info = of(&st.events, "session.info");
        assert_eq!(s(info[0], "effort"), "high");
        let state = info.iter().find(|e| !s(e, "agent_session").is_empty()).unwrap();
        assert_eq!(s(state, "agent_session"), "01a1c85a-703a-72fe-ae88-c1f9ffb5c249");
        assert_eq!(s(state, "model"), "Claude Fable 5.1");
        assert_eq!(s(state, "effort"), "high");
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

    // -- session controls: permission mode, effort, the agent's own commands, context use, queued messages --

    fn sent_with(text: &str, id: &str) -> Input {
        Input::Send { text: text.into(), images: vec![], id: id.into() }
    }

    #[test]
    fn modes_never_include_one_that_skips_approvals_or_lifts_the_sandbox() {
        assert_eq!(modes_for("claude"), ["default", "plan", "acceptEdits"]);
        assert_eq!(modes_for("codex"), ["read-only", "ask", "auto"]);
        for id in ["omo", "pi", "omp", "dsh", "grok", "omh", ""] {
            assert!(modes_for(id).is_empty(), "{id}");
        }
        for m in ["bypassPermissions", "dontAsk", "auto", "danger-full-access", "dangerFullAccess", "never"] {
            assert!(!modes_for("claude").contains(&m), "{m}");
        }
        // Codex's "auto" is omher's name for auto inside the workspace sandbox (checked below), not a bypass
        for m in ["bypassPermissions", "danger-full-access", "dangerFullAccess", "never", "full-auto"] {
            assert!(!modes_for("codex").contains(&m), "{m}");
        }
        let mut c = claude_up();
        for bad in ["bypassPermissions", "dontAsk", "auto", "manual", "PLAN", ""] {
            assert!(c.on_input(Input::Mode { mode: bad.into() }).is_err(), "{bad}");
        }
        let mut x = codex_up();
        for bad in ["danger-full-access", "dangerFullAccess", "never", "full", ""] {
            assert!(x.on_input(Input::Mode { mode: bad.into() }).is_err(), "{bad}");
        }
        // every Codex preset keeps a sandbox and an approval policy that can ask
        for m in modes_for("codex") {
            let (policy, sandbox) = codex_mode(m).unwrap();
            assert_ne!(policy, "never");
            assert_ne!(sandbox, "dangerFullAccess");
        }
        let mut p = pi_up("OmO", &[]);
        assert!(p.on_input(Input::Mode { mode: "plan".into() }).is_err());
    }

    #[test]
    fn real_claude_9_init_reports_commands_mode_efforts_and_context() {
        // Claude Code 2.1.322: initialize (its commands trimmed), a `set_permission_mode plan` status
        // line and a get_context_usage answer
        let mut c = Claude::new("/w/proj");
        c.start();
        let lines = real("claude-9-controls.jsonl");
        let st = run(&mut c, &lines[..1]);
        let cmds = &of(&st.events, "session.commands")[0]["commands"];
        // (trimmed to 8 of the 282 it reported)
        let rows: Vec<(String, String, String)> = cmds.as_array().unwrap().iter().map(|c| (s(c, "name"), s(c, "kind"), s(c, "prefix"))).collect();
        assert_eq!(rows.len(), 8);
        assert!(rows.contains(&("compact".into(), "command".into(), "/".into())), "{rows:?}");
        assert!(rows.iter().filter(|r| r.1 == "skill").count() >= 3, "a `(user)` skill is marked a skill: {rows:?}");
        assert_eq!(s(&cmds[0], "hint"), "<optional custom summarization instructions>");
        assert!(s(&cmds[0], "description").chars().count() <= 161);
        assert_eq!(s(of(&st.events, "session.info")[0], "mode"), "default");
        assert_eq!(of(&st.events, "session.efforts")[0]["levels"], json!(["low", "medium", "high", "xhigh", "max"]));
        // it then asks for its settings (the effort in use) and how full the context is
        let asked: Vec<String> = written(&st).iter().map(|w| s(&w["request"], "subtype")).collect();
        assert_eq!(asked, ["get_settings", "get_context_usage"]);
        // Claude Code says the new mode on its own status line
        let st = run(&mut c, &lines[1..2]);
        assert_eq!(s(of(&st.events, "session.info")[0], "mode"), "plan");
        // the context in use, as Claude Code counts it (never estimated)
        let st = run(&mut c, &lines[2..3]);
        assert_eq!(of(&st.events, "session.usage")[0], &json!({"event": "session.usage", "used": 23386, "max": 1000000}));
        // the effort applied, from get_settings
        let st = run(&mut c, &[r#"{"type":"control_response","response":{"subtype":"success","request_id":"omher-settings-2","response":{"applied":{"model":"claude-fable-5-2","effort":"high"}}}}"#.into()]);
        assert_eq!(s(of(&st.events, "session.info")[0], "effort"), "high");
    }

    #[test]
    fn claude_mode_and_effort_use_its_own_control_requests() {
        let mut c = claude_up();
        let w = written(&c.on_input(Input::Mode { mode: "plan".into() }).unwrap());
        assert_eq!(w[0]["request"], json!({"subtype": "set_permission_mode", "mode": "plan"}));
        let w = written(&c.on_input(Input::Effort { effort: "low".into() }).unwrap());
        // for this process only: never Claude Code's settings file
        assert_eq!(w[0]["request"], json!({"subtype": "apply_flag_settings", "settings": {"effortLevel": "low"}}));
        assert!(c.on_input(Input::Effort { effort: "ultra".into() }).is_err());
        // Claude Code refusing a mode is said under the chat
        let st = run(&mut c, &[r#"{"type":"control_response","response":{"subtype":"error","request_id":"omher-mode-9","error":"Cannot set permission mode"}}"#.into()]);
        assert_eq!(s(of(&st.events, "session.error")[0], "message"), "Mode not changed: Cannot set permission mode");
        // an effort that took is read back
        let st = run(&mut c, &[r#"{"type":"control_response","response":{"subtype":"success","request_id":"omher-effort-10","response":{}}}"#.into()]);
        assert_eq!(s(&written(&st)[0]["request"], "subtype"), "get_settings");
    }

    #[test]
    fn real_claude_9_a_message_sent_mid_turn_waits_until_claude_code_takes_it() {
        // Claude Code 2.1.322 with --replay-user-messages: "sleep 8, then FIRST" and, 4 s in, "SECOND". The first
        // is echoed at once; the second only after the running tool, when Claude Code reads it into the turn.
        let mut c = claude_up();
        let lines = real("claude-9-queued.jsonl");
        let st = c.on_input(sent_with("sleep then FIRST", "local-s1")).unwrap();
        assert_eq!(names(&st.events), ["turn.start"], "the first message is not queued");
        let first_echo = lines.iter().position(|l| l.contains("\"isReplay\":true")).unwrap();
        run(&mut c, &lines[..=first_echo]);
        let st = c.on_input(sent_with("SECOND", "local-s2")).unwrap();
        assert_eq!(st.events, [json!({"event": "message.queued", "id": "local-s2"})]);
        let second_echo = lines.iter().rposition(|l| l.contains("\"isReplay\":true")).unwrap();
        let st = run(&mut c, &lines[first_echo + 1..second_echo]);
        assert!(of(&st.events, "message.taken").is_empty(), "still waiting while the tool runs");
        let st = run(&mut c, &lines[second_echo..=second_echo]);
        assert_eq!(of(&st.events, "message.taken")[0]["id"], "local-s2");
        let st = run(&mut c, &lines[second_echo + 1..]);
        assert_eq!(text_of(&st.events, "message"), ["FIRST\nSECOND"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn claude_stop_with_a_queued_message_runs_it_next_as_its_own_turn() {
        // recorded: Stop while "SECOND" waited ends the turn aborted_tools, then Claude Code echoes SECOND and
        // answers it in a new turn
        let mut c = claude_up();
        c.on_input(sent_with("sleep", "a")).unwrap();
        c.on_input(sent_with("SECOND", "b")).unwrap();
        c.on_input(Input::Interrupt).unwrap();
        let st = run(&mut c, &[r#"{"type":"result","subtype":"error_during_execution","is_error":true,"terminal_reason":"aborted_tools"}"#.into()]);
        assert_eq!(ends(&st.events), [("interrupted".into(), "".into())]);
        assert!(of(&st.events, "message.taken").is_empty() && of(&st.events, "message.dropped").is_empty());
        let st = run(&mut c, &[r#"{"type":"user","isReplay":true,"message":{"role":"user","content":[{"type":"text","text":"SECOND"}]},"parent_tool_use_id":null}"#.into()]);
        assert_eq!(names(&st.events), ["message.taken", "turn.start"]);
        assert_eq!(st.events[0]["id"], "b");
    }

    #[test]
    fn codex_mode_and_effort_go_with_every_turn() {
        let mut x = codex_up();
        // model/list as Codex 0.167 sends it on this Mac (supportedReasoningEfforts per model)
        x.call(&mut Step::default(), "model/list", json!({}));
        let (n, mid) = (x.seq, x.model_id.clone());
        run(&mut x, &[format!(r#"{{"id":{n},"result":{{"data":[{{"model":"{}","displayName":"GPT","description":"","hidden":false,"supportedReasoningEfforts":[{{"reasoningEffort":"low","description":""}},{{"reasoningEffort":"high","description":""}}]}}]}}}}"#, mid)]);
        let st = x.on_input(Input::Mode { mode: "read-only".into() }).unwrap();
        assert_eq!(s(of(&st.events, "session.info")[0], "mode"), "read-only");
        // the recorded model/list offers these efforts for the thread's model
        let model = x.model_id.clone();
        let levels = x.efforts.get(&model).cloned().unwrap();
        let level = levels.as_array().unwrap()[0].as_str().unwrap().to_string();
        x.on_input(Input::Effort { effort: level.clone() }).unwrap();
        assert!(x.on_input(Input::Effort { effort: "turbo".into() }).is_err());
        let t = written(&x.on_input(sent_with("make a file", "local-s7")).unwrap())[0].clone();
        assert_eq!(t["method"], "turn/start");
        assert_eq!(t["params"]["approvalPolicy"], "on-request");
        assert_eq!(t["params"]["sandboxPolicy"], json!({"type": "readOnly"}));
        assert_eq!(t["params"]["effort"], level.as_str());
        assert_eq!(t["params"]["clientUserMessageId"], "local-s7");
        for (mode, policy, sandbox) in [("ask", "untrusted", "workspaceWrite"), ("auto", "on-request", "workspaceWrite")] {
            x.on_input(Input::Mode { mode: mode.into() }).unwrap();
            run(&mut x, &[r#"{"method":"turn/completed","params":{"turn":{"id":"t","status":"completed"}}}"#.into()]);
            let t = written(&x.on_input(Input::send("next")).unwrap())[0].clone();
            assert_eq!((s(&t["params"], "approvalPolicy"), s(&t["params"]["sandboxPolicy"], "type")), (policy.to_string(), sandbox.to_string()));
        }
    }

    #[test]
    fn codex_reports_its_threads_mode_effort_usage_and_skills() {
        // the shapes Codex 0.167 sent on this Mac: thread/resume after a turn ran read-only, a token usage update,
        // skills/list
        let mut x = Codex::new("/w/proj", Some("01a1cad5-b3bb-7f52-9de5-0bfc4cd293f4"));
        x.start();
        let st = run(&mut x, &[
            r#"{"id":1,"result":{}}"#.into(),
            r#"{"id":2,"result":{"thread":{"id":"01a1cad5-b3bb-7f52-9de5-0bfc4cd293f4"},"model":"gpt-6.1-sol","approvalPolicy":"untrusted","sandbox":{"type":"readOnly","networkAccess":false},"reasoningEffort":"low"}}"#.into(),
        ]);
        let info = of(&st.events, "session.info")[0];
        // untrusted + readOnly is none of omher's presets: the agent's own setting, shown as such
        assert_eq!((s(info, "mode"), s(info, "effort")), ("".into(), "low".into()));
        let st = run(&mut x, &[r#"{"id":2,"result":{"thread":{"id":"t"},"model":"m","approvalPolicy":"on-request","sandbox":{"type":"readOnly"}}}"#.into()]);
        let _ = st;
        assert_eq!(codex_mode_of("on-request", "readOnly"), Some("read-only"));
        assert_eq!(codex_mode_of("never", "dangerFullAccess"), None);
        let st = run(&mut x, &[r#"{"method":"thread/tokenUsage/updated","params":{"threadId":"t","turnId":"u","tokenUsage":{"last":{"totalTokens":41250,"inputTokens":41000,"cachedInputTokens":0,"outputTokens":250,"reasoningOutputTokens":0},"total":{"totalTokens":90000,"inputTokens":1,"cachedInputTokens":0,"outputTokens":1,"reasoningOutputTokens":0},"modelContextWindow":258400}}}"#.into()]);
        assert_eq!(of(&st.events, "session.usage")[0], &json!({"event": "session.usage", "used": 41250, "max": 258400}));
        let st = run(&mut x, &[r#"{"id":4,"result":{"data":[{"cwd":"/w/proj","skills":[{"name":"review","description":"Long text","shortDescription":"Review a change","enabled":true,"path":"/home/u/.codex/skills/review/SKILL.md","scope":"user"},{"name":"off","description":"x","enabled":false,"path":"/p","scope":"user"}],"errors":[]}]}}"#.into()]);
        assert_eq!(of(&st.events, "session.commands")[0]["commands"], json!([{"name": "review", "description": "Review a change", "hint": "", "kind": "skill", "prefix": "$"}]));
        // a `$name` in the message goes with it as Codex's own skill input
        let t = written(&x.on_input(Input::send("please $review this")).unwrap())[0].clone();
        assert_eq!(t["params"]["input"][1], json!({"type": "skill", "name": "review", "path": "/home/u/.codex/skills/review/SKILL.md"}));
    }

    #[test]
    fn codex_a_message_sent_mid_turn_waits_until_codex_records_it() {
        // recorded on Codex 0.167: a second turn/start while one runs becomes a userMessage item of the same turn,
        // with our clientUserMessageId as its clientId
        let mut x = codex_up();
        x.on_input(sent_with("first", "local-s1")).unwrap();
        run(&mut x, &[r#"{"method":"turn/started","params":{"turn":{"id":"T1","status":"inProgress","items":[]}}}"#.into()]);
        let st = x.on_input(sent_with("second", "local-s2")).unwrap();
        assert_eq!(names(&st.events), ["message.queued"]);
        let st = run(&mut x, &[r#"{"method":"item/started","params":{"item":{"type":"userMessage","id":"u2","clientId":"local-s2","content":[]}}}"#.into()]);
        assert_eq!(st.events, [json!({"event": "message.taken", "id": "local-s2"})]);
        // Stop before Codex records one: it was never sent, and says so
        x.on_input(sent_with("third", "local-s3")).unwrap();
        x.on_input(Input::Interrupt).unwrap();
        let st = run(&mut x, &[r#"{"method":"turn/completed","params":{"turn":{"id":"T1","status":"interrupted"}}}"#.into()]);
        assert_eq!(names(&st.events), ["message.dropped", "turn.end"]);
        assert_eq!(st.events[0]["id"], "local-s3");
    }

    #[test]
    fn real_omo_9_reports_levels_commands_and_context() {
        // omo 5.0.0-beta.65: get_available_thinking_levels, get_commands (trimmed), get_session_stats after a turn
        let mut p = Pi::new("/w/proj", "OmO");
        let w = written(&p.start());
        assert_eq!(w.iter().map(|v| s(v, "type")).collect::<Vec<_>>(), ["get_state", "get_available_models", "get_available_thinking_levels", "get_commands"]);
        // the session-stats read the recording answers is the one asked after a turn
        p.read(&mut Step::default(), "get_session_stats");
        let st = run(&mut p, &real("omo-9-controls.jsonl"));
        assert_eq!(of(&st.events, "session.efforts")[0]["levels"], json!(["minimal", "low", "medium", "high", "xhigh", "max"]));
        let cmds = of(&st.events, "session.commands")[0]["commands"].as_array().unwrap().clone();
        assert_eq!(cmds.iter().map(|c| (s(c, "kind"), s(c, "prefix"))).collect::<Vec<_>>(), [("command", "/"), ("command", "/"), ("command", "/"), ("skill", "$"), ("skill", "$")].map(|(a, b)| (a.to_string(), b.to_string())));
        assert!(s(&cmds[3], "name").starts_with("skill:"));
        assert_eq!(of(&st.events, "session.usage")[0], &json!({"event": "session.usage", "used": 82335, "max": 1000000}));
        // a level it offers goes as its own set_thinking_level; anything else is refused
        let w = written(&p.on_input(Input::Effort { effort: "low".into() }).unwrap());
        assert_eq!((s(&w[0], "type"), s(&w[0], "level")), ("set_thinking_level".into(), "low".into()));
        assert!(p.on_input(Input::Effort { effort: "off".into() }).is_err());
        let st = run(&mut p, &[r#"{"type":"thinking_level_changed","level":"low"}"#.into()]);
        assert_eq!(s(of(&st.events, "session.info")[0], "effort"), "low");
    }

    #[test]
    fn real_omo_9_a_follow_up_waits_in_its_queue_until_omo_takes_it() {
        // omo 5.0.0-beta.65: "numbers 1..80", then (3 s in) "SECOND" as a followUp: queue_update, then after the
        // first answer a new turn_start, an empty queue and SECOND's own message_end
        let mut p = pi_up("OmO", &[]);
        let lines = real("omo-9-queued.jsonl");
        p.on_input(sent_with("numbers", "a")).unwrap();
        let start = lines.iter().position(|l| l.contains("\"agent_start\"")).unwrap();
        let first_user = lines.iter().position(|l| l.contains("\"message_end\"") && l.contains("\"role\":\"user\"")).unwrap();
        run(&mut p, &lines[..=first_user]);
        assert!(start < first_user);
        let st = p.on_input(sent_with("SECOND", "b")).unwrap();
        assert_eq!(names(&st.events), ["message.queued"]);
        assert_eq!(written(&st)[0]["streamingBehavior"], "followUp");
        let second_user = lines.iter().rposition(|l| l.contains("\"message_end\"") && l.contains("\"role\":\"user\"")).unwrap();
        let st = run(&mut p, &lines[first_user + 1..second_user]);
        assert!(of(&st.events, "message.taken").is_empty());
        let st = run(&mut p, &lines[second_user..]);
        assert_eq!(of(&st.events, "message.taken")[0]["id"], "b");
        assert_eq!(text_of(&st.events, "message"), ["SECOND"]);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        // Stop with a follow-up waiting: omo clears its queue, so the message is dropped
        p.on_input(sent_with("long", "c")).unwrap();
        run(&mut p, &[r#"{"type":"agent_start"}"#.into()]);
        p.on_input(sent_with("later", "d")).unwrap();
        let st = run(&mut p, &[r#"{"type":"agent_end","aborted":true}"#.into()]);
        assert_eq!(names(&st.events)[..2], ["message.dropped", "turn.end"]);
        assert_eq!(st.events[0]["id"], "d");
    }

    // -- every recorded stream ends with the turn over --

    /// One step of a replay: a recorded file (or the part of it before / from its last `init`), or what the person
    /// (or the exit watcher) does in between.
    enum Do {
        File(&'static str),
        Head(&'static str),
        Tail(&'static str),
        /// lines `from..to` of a file, as recorded
        Lines(&'static str, usize, usize),
        Send,
        Stop,
        Model(&'static str),
        /// the person takes the last message back (edit and resend)
        Rewind,
        /// the program exits: the watcher's `turn.end` when it was mid-turn
        Exit,
        /// lines `from..to` of a file with its approvals left open (the person answers later, [`Do::Answer`])
        Held(&'static str, usize, usize),
        /// the person answers the approvals left open, once each
        Answer,
    }

    /// Each sequence: a name, the adapter, then its steps. Every file in tests/fixtures/real/ is in one of them.
    fn sequences() -> Vec<(&'static str, &'static str, Vec<Do>)> {
        use Do::*;
        let turn = |f: &'static str| vec![Send, File(f)];
        let mut out: Vec<(&'static str, &'static str, Vec<Do>)> = Vec::new();
        for f in ["claude-1-plain.jsonl", "claude-2-approvals.jsonl", "claude-3-edit.jsonl", "claude-4-background.jsonl", "claude-5-question.jsonl", "claude-6-error.jsonl", "claude-signed-out.jsonl"] {
            out.push((f, "claude", turn(f)));
        }
        // the recording finishes a turn, then the person asks for a slow command and presses Stop
        out.push(("claude-4-stop.jsonl", "claude", vec![Send, Head("claude-4-stop.jsonl"), Send, Tail("claude-4-stop.jsonl"), Stop, File("claude-4-stopped.jsonl")]));
        out.push(("claude-7-model.jsonl", "claude", vec![Model("haiku"), File("claude-7-model.jsonl")]));
        // a two-file edit with its todo list (TaskCreate/TaskUpdate), and one with thinking text (Claude Code 2.1.322)
        out.push(("claude-12-work.jsonl", "claude", turn("claude-12-work.jsonl")));
        out.push(("claude-12-thinking.jsonl", "claude", turn("claude-12-thinking.jsonl")));
        // a turn, then edit and resend: Claude Code's own rewind, then the next message
        out.push(("claude-12-rewind.jsonl", "claude", vec![Send, Lines("claude-12-rewind.jsonl", 0, 5), Rewind, Lines("claude-12-rewind.jsonl", 5, 6), Send, Lines("claude-12-rewind.jsonl", 6, 11)]));
        // a model picked between turns, then one picked right after the next message went out (QA H7)
        out.push(("claude-11-model-mid-turn.jsonl", "claude", vec![Model("haiku"), Lines("claude-11-model-mid-turn.jsonl", 0, 1), Send, Model("sonnet"), Lines("claude-11-model-mid-turn.jsonl", 1, 6), Send, Tail("claude-11-model-mid-turn.jsonl")]));
        // H10: started with `--add-dir <the session's attachment folder>`; turn 1 reads the attached copy, turn 2 a file elsewhere
        out.push(("claude-12-attach-read.jsonl", "claude", vec![Model("haiku"), Lines("claude-12-attach-read.jsonl", 0, 1), Send, Head("claude-12-attach-read.jsonl"), Send, Tail("claude-12-attach-read.jsonl")]));
        // a resumed conversation: an old background task's empty result, then the person's answer
        out.push(("claude-8-resume.jsonl", "claude", vec![Send, File("claude-8-resume.jsonl"), Head("claude-4-stop.jsonl")]));
        // omher closed the chat mid-command: the exit watcher ends the turn
        out.push(("claude-10-close.jsonl", "claude", vec![Send, File("claude-10-close.jsonl"), Exit]));
        // a background subagent asks after the turn ended; the person answers with no turn running, the subagent
        // finishes and Claude Code's own turn tells of it (Claude Code 2.1.322)
        out.push(("claude-13-late-ask.jsonl", "claude", vec![Send, Held("claude-13-late-ask.jsonl", 0, 15), Answer, Lines("claude-13-late-ask.jsonl", 15, 29)]));
        // the background subagent asks during the turn and the turn ends with the ask open: Claude Code still waits
        // for it, and takes the answer 15 s after its `result`
        out.push(("claude-13-late-ask-inside.jsonl", "claude", vec![Send, Held("claude-13-late-ask-inside.jsonl", 0, 21), Answer, Lines("claude-13-late-ask-inside.jsonl", 21, 31)]));
        // a late ask, then Stop with no turn running: Claude Code withdraws the ask and stops the subagent
        out.push(("claude-13-late-ask-stop.jsonl", "claude", vec![Send, Held("claude-13-late-ask-stop.jsonl", 0, 15), Stop, Lines("claude-13-late-ask-stop.jsonl", 15, 21)]));
        // a background command still runs after the turn; Stop with no turn running stops it (Claude Code 2.1.323)
        out.push(("claude-14-background-stop.jsonl", "claude", vec![Send, Lines("claude-14-background-stop.jsonl", 0, 35), Stop, Lines("claude-14-background-stop.jsonl", 35, 40)]));
        for f in ["codex-1-plain.jsonl", "codex-2-approvals.jsonl", "codex-3-edit.jsonl", "codex-5-question.jsonl", "codex-6-error.jsonl", "codex-signed-out.jsonl"] {
            out.push((f, "codex", turn(f)));
        }
        out.push(("codex-4-stop.jsonl", "codex", vec![Send, File("codex-4-stop.jsonl"), Stop, File("codex-4-stopped.jsonl")]));
        out.push(("codex-7-model.jsonl", "codex", vec![Model("gpt-6-astra"), Send, File("codex-7-model.jsonl")]));
        out.push(("codex-8-resume.jsonl", "codex-resume", vec![File("codex-8-resume-init.jsonl"), File("codex-8-resume.jsonl"), Send, File("codex-8-resume-turn.jsonl")]));
        // reopened onto a thread that is gone, with a message waiting: a new thread takes it (QA H5)
        out.push(("codex-11-resume-gone.jsonl", "codex-resume-gone", vec![Send, File("codex-11-resume-gone.jsonl"), File("codex-1-plain.jsonl")]));
        // two subagents in parallel (Claude Code 2.1.322, real run), then a subagent whose command needs approval
        out.push(("claude-9-subagents.jsonl", "claude", vec![Send, File("claude-9-subagents.jsonl"), Send, File("claude-9-subagent-ask.jsonl")]));
        // OmO 5.1.56: two background subagents (`task`), then the next turn during which their completions arrive
        out.push(("omo-9-subagents.jsonl", "omo", vec![Send, File("omo-9-subagents.jsonl"), Send, File("omo-9-subagents-after.jsonl")]));
        // two sub-agents in parallel (their threads stream on the same connection), then Stop while one runs
        out.push(("codex-9-helpers.jsonl", "codex-helpers", vec![Send, File("codex-9-helpers.jsonl")]));
        out.push(("codex-10-helper-stop.jsonl", "codex-helper-stop", vec![Send, File("codex-10-helper-stop.jsonl"), Stop, File("codex-10-helper-stopped.jsonl")]));
        out.push(("omo-1-plain.jsonl", "omo", turn("omo-1-plain.jsonl")));
        for f in ["omp-1-plain.jsonl", "omp-2-approvals.jsonl", "omp-3-edit.jsonl", "omp-5-question.jsonl", "omp-6-error.jsonl"] {
            out.push((f, "omp", turn(f)));
        }
        out.push(("omp-4-running.jsonl", "omp", vec![Send, File("omp-4-running.jsonl"), Stop, File("omp-4-stopped.jsonl")]));
        out.push(("omp-7-model.jsonl", "omp", vec![Model("stub/stub-b"), File("omp-7-model.jsonl"), Send, File("omp-7-after-model.jsonl")]));
        for f in ["pi-1-plain.jsonl", "pi-2-tools.jsonl", "pi-3-edit.jsonl", "pi-5-question.jsonl", "pi-6-error.jsonl"] {
            out.push((f, "pi", turn(f)));
        }
        out.push(("pi-4-running.jsonl", "pi", vec![Send, File("pi-4-running.jsonl"), Stop, File("pi-4-stopped.jsonl")]));
        out.push(("pi-7-model.jsonl", "pi", vec![Model("stub/stub-b"), File("pi-7-model.jsonl"), Send, File("pi-7-after-model.jsonl")]));
        out.push(("pi-signed-out.jsonl", "pi-noauth", vec![File("pi-noauth-init.jsonl"), Send, File("pi-signed-out.jsonl"), File("pi-noauth-model.jsonl")]));
        // the session controls' recordings: start-up reads, and a message sent while a turn ran
        out.push(("claude-9-controls.jsonl", "claude", vec![File("claude-9-controls.jsonl")]));
        out.push(("claude-9-queued.jsonl", "claude", turn("claude-9-queued.jsonl")));
        out.push(("omo-9-controls.jsonl", "omo", vec![File("omo-9-controls.jsonl")]));
        out.push(("omo-9-queued.jsonl", "omo", turn("omo-9-queued.jsonl")));
        // OmO 5.1.56 (audit O5): a run fails, OmO retries it once by itself, the retry fails too
        out.push(("omo-12-retry.jsonl", "omo", turn("omo-12-retry.jsonl")));
        // OmO 5.1.56: a foreground `task` with two subagents in one call (a batch), with a todo list; then a single
        // foreground `task`. Neither result names an answer: OmO's own records (tests/fixtures/omo-home) do
        out.push(("omo-13-batch.jsonl", "omo-batch", turn("omo-13-batch.jsonl")));
        out.push(("omo-13-single.jsonl", "omo-single", turn("omo-13-single.jsonl")));
        // Codex 0.167 (audit O11/O13): its own config runs without approvals and with full disk access; Stop during
        // `sleep 40`, the next turn, then the stopped command's end 37 s after Stop
        out.push(("codex-12-late-step.jsonl", "codex-late", vec![Send, File("codex-12-late-step.jsonl"), Stop, File("codex-12-late-step-stopped.jsonl"), Send, File("codex-12-late-step-after.jsonl")]));
        // Claude Code 2.1.323 in plan mode: the plan's approval (ExitPlanMode), denied (Claude asks what to change) and
        // allowed (plan mode ends; the edits after it are approved here)
        out.push(("claude-14-plan-deny.jsonl", "claude", turn("claude-14-plan-deny.jsonl")));
        out.push(("claude-14-plan-allow.jsonl", "claude", turn("claude-14-plan-allow.jsonl")));
        // Codex 0.167: the edit handed to a sub-agent, whose own thread carries the patch
        out.push(("codex-15-sub-edit.jsonl", "codex-sub-edit", turn("codex-15-sub-edit.jsonl")));
        out
    }

    /// The adapter of a sequence, after its own start-up recording (the files each one reads before any turn).
    fn adapter_up(kind: &str) -> (Box<dyn Adapter>, Vec<&'static str>) {
        match kind {
            "claude" => (Box::new(Claude::new("/w/proj")), vec!["claude-init.jsonl"]),
            "codex" => (Box::new(Codex::new("/w/proj", None)), vec!["codex-init.jsonl"]),
            "codex-resume" => (Box::new(Codex::new("/w/proj", Some("01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"))), vec![]),
            "codex-resume-gone" => (Box::new(Codex::new("/w/proj", Some("0badbeef-0000-4000-8000-000000000000"))), vec![]),
            "codex-helpers" => (Box::new(Codex::new("/w/proj", None)), vec!["codex-9-helpers-init.jsonl"]),
            "codex-helper-stop" => (Box::new(Codex::new("/w/proj", None)), vec!["codex-10-helper-stop-init.jsonl"]),
            "codex-late" => (Box::new(Codex::new("/w/proj", Some("01a1ca24-1047-7ee0-aac2-faf093d44dbe"))), vec!["codex-12-late-step-init.jsonl"]),
            "codex-sub-edit" => (Box::new(Codex::new("/w/proj", None)), vec!["codex-15-sub-edit-init.jsonl"]),
            "omo" => (Box::new(omo_pi()), vec!["omo-init.jsonl"]),
            "omo-batch" => (Box::new(omo_pi()), vec!["omo-13-batch-init.jsonl"]),
            "omo-single" => (Box::new(omo_pi()), vec!["omo-13-single-init.jsonl"]),
            "omp" => (Box::new(Pi::new("/w/proj", "oh-my-pi")), vec!["omp-ready.jsonl", "omp-init.jsonl"]),
            "pi" => (Box::new(Pi::new("/w/proj", "pi")), vec!["pi-init.jsonl"]),
            "pi-noauth" => (Box::new(Pi::new("/w/proj", "pi")), vec![]),
            other => panic!("{other}"),
        }
    }

    /// Replays one sequence: every event the chat gets, in order (start-up included), with the person's approvals
    /// answered as `replay` does. Also returns whether the adapter still thinks a turn runs.
    fn replay_sequence(kind: &str, steps: &[Do], used: &mut std::collections::BTreeSet<String>) -> (Vec<Event>, bool) {
        let (mut a, init) = adapter_up(kind);
        let mut events = a.start().events;
        for f in init {
            used.insert(f.into());
            events.extend(run(a.as_mut(), &real(f)).events);
        }
        let split = |name: &str| {
            let lines = real(name);
            let at = lines.iter().rposition(|l| l.contains("\"subtype\":\"init\"")).unwrap();
            (lines[..at].to_vec(), lines[at..].to_vec())
        };
        let mut last_write: Vec<String> = Vec::new();
        let mut exited = false;
        let mut held: Vec<String> = Vec::new();
        for step in steps {
            let mut hold = false;
            let lines: Vec<String> = match step {
                Do::Send => {
                    events.extend(a.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap().events);
                    continue;
                }
                Do::Stop => {
                    events.extend(a.on_input(Input::Interrupt).unwrap().events);
                    continue;
                }
                Do::Model(m) => {
                    let st = a.on_input(Input::Model { model: (*m).into() }).unwrap();
                    last_write = st.write.clone();
                    events.extend(st.events);
                    continue;
                }
                Do::Rewind => {
                    let st = a.on_input(Input::Rewind).unwrap();
                    last_write = st.write.clone();
                    events.extend(st.events);
                    continue;
                }
                Do::Exit => {
                    if a.in_turn() {
                        events.push(exit_turn_end(Some(0), ""));
                    }
                    exited = true;
                    continue;
                }
                Do::Answer => {
                    for rid in std::mem::take(&mut held) {
                        events.extend(a.on_input(Input::Approve { request_id: rid, choice: "once".into() }).unwrap().events);
                    }
                    continue;
                }
                Do::Held(f, from, to) => {
                    used.insert((*f).into());
                    hold = true;
                    real(f)[*from..*to].to_vec()
                }
                Do::File(f) => {
                    used.insert((*f).into());
                    // a model answer names the request it answers: the one this replay sent
                    let id = last_write.first().and_then(|w| serde_json::from_str::<Value>(w).ok()).map(|w| if w["request_id"].is_string() { s(&w, "request_id") } else { s(&w, "id") }).unwrap_or_default();
                    real(f).into_iter().map(|l| if id.is_empty() { l } else { l.replace("omher-model-2", &id).replace("omher-9", &id) }).collect()
                }
                Do::Head(f) => {
                    used.insert((*f).into());
                    split(f).0
                }
                Do::Tail(f) => {
                    used.insert((*f).into());
                    split(f).1
                }
                Do::Lines(f, from, to) => {
                    used.insert((*f).into());
                    // a recorded answer to a request this replay sent names that request
                    let id = last_write.first().and_then(|w| serde_json::from_str::<Value>(w).ok()).map(|w| s(&w, "request_id")).unwrap_or_default();
                    real(f)[*from..*to].iter().map(|l| if id.is_empty() { l.clone() } else { l.replace("omher-rewind-REQ", &id) }).collect()
                }
            };
            for l in lines {
                for e in a.on_line(&l).events {
                    let ask = s(&e, "event") == "approval.request";
                    let rid = s(&e, "request_id");
                    events.push(e);
                    if ask && hold {
                        held.push(rid);
                    } else if ask {
                        events.extend(a.on_input(Input::Approve { request_id: rid, choice: "once".into() }).unwrap().events);
                    }
                }
            }
        }
        // a program that exited runs nothing, whatever its adapter last thought
        (events, a.in_turn() && !exited)
    }

    /// Every recorded stream, replayed through its adapter, leaves no turn running, and the events of a turn
    /// (status, thinking, steps, streamed text) never come outside one. The events go to
    /// `src/state/__fixtures__/real-agent-replay.json`, which the store's own test replays through the reducer
    /// (`OMHER_WRITE_REPLAY=1 cargo test real_streams` rewrites it after an adapter change).
    #[test]
    fn real_streams_end_their_turns_and_say_nothing_outside_one() {
        let mut used = std::collections::BTreeSet::new();
        let mut out = Vec::new();
        for (name, kind, steps) in sequences() {
            let (events, running) = replay_sequence(kind, &steps, &mut used);
            assert!(!running, "{name}: the adapter still thinks a turn runs");
            let mut open = false;
            // steps still running when a turn was stopped: the agent may say later that one ended (Codex runs a
            // command on after Stop), and the reducer gives that end to the stopped step
            let (mut steps, mut stopped) = (std::collections::BTreeSet::new(), std::collections::BTreeSet::new());
            for e in &events {
                match s(e, "event").as_str() {
                    "turn.start" => open = true,
                    "turn.end" => {
                        open = false;
                        if s(e, "outcome") == "interrupted" {
                            stopped.append(&mut steps);
                        }
                        steps.clear();
                    }
                    "tool.end" if !open => assert!(stopped.remove(&s(e, "tool_id")), "{name}: {e} outside a turn"),
                    "status" | "thinking" | "tool.start" | "tool.end" | "delta" | "skill" => {
                        assert!(open, "{name}: {e} outside a turn");
                        match s(e, "event").as_str() {
                            "tool.start" => {
                                steps.insert(s(e, "tool_id"));
                            }
                            "tool.end" => {
                                steps.remove(&s(e, "tool_id"));
                            }
                            _ => {}
                        }
                    }
                    _ => {}
                }
            }
            assert!(!open, "{name}: the last turn never ended");
            out.push(json!({"name": name, "agent": kind, "events": events}));
        }
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("real");
        // DSH has no adapter (a run per message): dsh_chat.rs's own tests replay its dsh-*.jsonl streams
        let all: std::collections::BTreeSet<String> = std::fs::read_dir(&dir).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).filter(|n| n.ends_with(".jsonl") && !n.starts_with("dsh-")).collect();
        assert_eq!(all.difference(&used).collect::<Vec<_>>(), Vec::<&String>::new(), "a recorded stream no sequence replays");
        let golden = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("src").join("state").join("__fixtures__").join("real-agent-replay.json");
        let text = serde_json::to_string_pretty(&Value::Array(out)).unwrap() + "\n";
        if std::env::var_os("OMHER_WRITE_REPLAY").is_some() {
            std::fs::create_dir_all(golden.parent().unwrap()).unwrap();
            std::fs::write(&golden, &text).unwrap();
        }
        let saved = std::fs::read_to_string(&golden).unwrap_or_default().replace("\r\n", "\n");
        assert!(saved == text, "{} is out of date: run OMHER_WRITE_REPLAY=1 cargo test real_streams", golden.display());
    }

    #[test]
    fn omo_status_after_its_turn_ended_is_not_shown() {
        // omo-1-plain.jsonl: agent_end, then setStatus "(😺 OmO Native)", agent_settled, agent_idle, more setStatus
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        p.on_input(Input::Send { text: "hi".into(), images: vec![], id: String::new() }).unwrap();
        let lines = real("omo-1-plain.jsonl");
        let end = lines.iter().position(|l| l.contains("\"type\":\"agent_end\"")).unwrap();
        run(&mut p, &lines[..=end]);
        let late = run(&mut p, &lines[end + 1..]);
        assert!(late.events.is_empty(), "{:?}", late.events);
        // while a turn runs, its status shows as the agent wrote it
        p.on_input(Input::Send { text: "again".into(), images: vec![], id: String::new() }).unwrap();
        let st = p.on_line(r#"{"type":"extension_ui_request","id":"s1","method":"setStatus","statusKey":"memory","statusText":"mem:khope-sionic-ai-d09472c9 9d ago (+1)"}"#);
        assert_eq!(st.events, [json!({"event": "status", "text": "mem:khope-sionic-ai-d09472c9 9d ago (+1)"})]);
    }

    /// codex-9-helpers: the person's turn spawns two sub-agents (`write_one`, `read_first_line`); their threads'
    /// own turns, steps and answers stream on the same connection (recorded with Codex 0.167.0-alpha.3.2).
    fn codex_helpers_up() -> Codex {
        let mut x = Codex::new("/w/proj", None);
        x.start();
        run(&mut x, &real("codex-9-helpers-init.jsonl"));
        x
    }

    fn subs_of<'a>(events: &'a [Event], id: &str) -> Vec<&'a Event> {
        events.iter().filter(|e| s(e, "event") == "subagent" && s(e, "id").ends_with(id)).collect()
    }

    #[test]
    fn claude_subagents_come_out_as_one_row_each_with_their_own_answer() {
        // claude-9-subagents: one message, two Agent calls in parallel (Claude Code 2.1.322, a real run)
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        let st = run(&mut c, &real("claude-9-subagents.jsonl"));
        let a = subs_of(&st.events, "NdJyEL");
        let b = subs_of(&st.events, "4hw1eo");
        assert_eq!((s(a[0], "agent"), s(a[0], "name"), s(a[0], "goal")), ("claude".into(), "general-purpose".into(), "Read a.txt first line".into()));
        assert_eq!(s(b[0], "goal"), "Count lines of b.txt");
        // one fan-out of two (the same message), its steps, then done with its own words and time
        assert_eq!(s(a[0], "delegation"), s(b[0], "delegation"));
        assert_eq!((a[0]["index"].clone(), b[0]["index"].clone(), b[0]["count"].clone()), (json!(0), json!(1), json!(2)));
        assert!(a.iter().any(|e| s(e, "tool") == "read_file" && s(e, "step").ends_with("a.txt")), "{a:?}");
        let end = a.last().unwrap();
        assert_eq!((s(end, "state"), s(end, "summary")), ("done".into(), "alpha line".into()));
        assert_eq!(end["seconds"], json!(3.7));
        assert_eq!(s(end, "model"), "claude-fable-5-2");
        assert_eq!(s(b.last().unwrap(), "state"), "done");
        // a subagent's own text and steps are never Claude's: one answer bubble, steps only of the main thread
        assert_eq!(text_of(&st.events, "message").len(), 1);
        assert!(st.events.iter().filter(|e| s(e, "event") == "tool.start").all(|e| s(e, "name") == "delegate_task"));
        assert_eq!(names(&st.events).iter().filter(|n| *n == "turn.end").count(), 1);
    }

    #[test]
    fn a_claude_turn_stopped_with_a_subagent_out_ends_that_subagent_cancelled() {
        // claude-9-subagents up to the first hand-back, then Stop: Claude Code ends the turn with
        // error_during_execution and the second subagent never hands back
        let lines = real("claude-9-subagents.jsonl");
        let cut = lines.iter().position(|l| l.contains("\"tool_use_id\":\"toolu_01ScWBRPwx9MFSuupGNdJyEL\"") && l.contains("tool_result")).unwrap();
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        run(&mut c, &lines[..=cut]);
        let st = c.on_line(r#"{"type":"result","subtype":"error_during_execution","is_error":true,"result":""}"#);
        let b = subs_of(&st.events, "4hw1eo");
        assert_eq!(b.iter().map(|e| s(e, "state")).collect::<Vec<_>>(), ["cancelled"]);
        assert!(subs_of(&st.events, "NdJyEL").is_empty(), "the subagent that handed back stays done");
        assert_eq!(names(&st.events).last().map(String::as_str), Some("turn.end"));
    }

    #[test]
    fn a_claude_subagents_approval_names_the_subagent() {
        // claude-9-subagent-ask: the subagent's Bash needs permission; Claude Code sends `agent_id` on can_use_tool
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        run(&mut c, &real("claude-9-subagents.jsonl"));
        c.on_input(Input::send("again")).unwrap();
        let st = replay(&mut c, &["claude-9-subagent-ask.jsonl"], &[]);
        let ask = st.events.iter().find(|e| s(e, "event") == "approval.request").unwrap();
        assert_eq!(ask["subagent"], json!({"id": "toolu_016YS2cG1AUHFFq9nBfbkv9e", "name": "Write c.txt via echo"}));
        assert!(s(ask, "command").starts_with("echo three"));
        let sub = subs_of(&st.events, "fbkv9e");
        assert_eq!(s(sub.last().unwrap(), "summary"), "done");
    }

    #[test]
    fn claude_says_how_much_still_runs_in_the_background() {
        // claude-4-background: background_tasks_changed with one task, then with none (audit O10)
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        let mut st = run(&mut c, &real("claude-4-background.jsonl"));
        // the same event when the task ended (claude-A in the audit's capture): its list is empty
        st.events.extend(c.on_line(r#"{"type":"system","subtype":"background_tasks_changed","tasks":[]}"#).events);
        let bg: Vec<Value> = st.events.iter().filter(|e| s(e, "event") == "session.info" && e.get("background").is_some()).map(|e| e["background"].clone()).collect();
        assert_eq!(bg, [json!(1), json!(0)]);
    }

    #[test]
    fn omo_subagents_come_out_as_rows_and_end_when_omo_says_they_finished() {
        // omo-9: one `task` call with two background subagents (OmO 5.1.56, a real run); their completions arrive in
        // OmO's next turn as `senpi-task.completion`
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        p.on_input(Input::send("go")).unwrap();
        let st = run(&mut p, &real("omo-9-subagents.jsonl"));
        let subs: Vec<&Event> = st.events.iter().filter(|e| s(e, "event") == "subagent").collect();
        assert_eq!((s(subs[0], "agent"), s(subs[0], "name"), s(subs[0], "goal"), s(subs[0], "state")), ("omo".into(), "first-line".into(), "Report the first line of a.txt".into(), "queued".into()));
        assert_eq!(s(subs[1], "name"), "line-count");
        // the call's result: both running in the background, on their resolved model
        let running: Vec<&&Event> = subs.iter().filter(|e| s(e, "state") == "running").collect();
        assert_eq!(running.len(), 2);
        assert_eq!(s(running[0], "model"), "gpt-6-luna-fast");
        // the `task` step names them, never the raw call JSON
        let step = st.events.iter().find(|e| s(e, "event") == "tool.start" && s(e, "name") == "delegate_task").unwrap();
        assert_eq!(s(step, "detail"), "first-line, line-count");
        p.on_input(Input::send("next")).unwrap();
        let st = replay(&mut p, &["omo-9-subagents-after.jsonl"], &[]);
        let done: Vec<&Event> = st.events.iter().filter(|e| s(e, "event") == "subagent").collect();
        assert_eq!(done.iter().map(|e| (s(e, "name"), s(e, "state"), s(e, "summary"))).collect::<Vec<_>>(), [
            ("first-line".into(), "done".into(), "alpha line".into()),
            ("line-count".into(), "done".into(), "2".into()),
        ]);
        assert_eq!(done[0]["seconds"], json!(9.9));
        assert_eq!(s(done[0], "model"), "claude-haiku-5-5");
    }

    /// The rows a recorded OmO 5.1.56 turn ends with: (name, state, summary, model, seconds).
    fn omo_rows(p: &mut Pi, file: &str) -> (Step, Vec<(String, String, String, String, Value)>) {
        p.on_input(Input::send("go")).unwrap();
        let st = run(p, &real(file));
        let rows = st.events.iter().filter(|e| s(e, "event") == "subagent" && s(e, "state") != "queued" && s(e, "state") != "running").map(|e| (s(e, "name"), s(e, "state"), s(e, "summary"), s(e, "model"), e["seconds"].clone())).collect();
        (st, rows)
    }

    #[test]
    fn an_omo_foreground_batch_ends_each_row_with_its_own_answer_and_model() {
        // omo-13-batch (OmO 5.1.56, a real run): one foreground `task` with two subagents. Its result's items carry
        // only {task_id, name, status}; each answer, model and time is in OmO's own record of that task id
        let mut p = pi_up("OmO", &["omo-13-batch-init.jsonl"]);
        let (st, rows) = omo_rows(&mut p, "omo-13-batch.jsonl");
        assert_eq!(rows, [
            ("helper-a-first-line".into(), "done".into(), "FIRST_LINE: alpha line".into(), "claude-haiku-5-5".into(), json!(19.9)),
            ("helper-b-line-count".into(), "done".into(), "LINE_COUNT: 3".into(), "claude-haiku-5-5".into(), json!(28.6)),
        ]);
        assert_eq!(st.events.iter().filter(|e| s(e, "event") == "turn.end").count(), 1);
    }

    #[test]
    fn an_omo_single_foreground_task_ends_with_its_answer() {
        // omo-13-single (OmO 5.1.56, a real run): one task, no `tasks` array; the result names its model, no answer
        let mut p = pi_up("OmO", &["omo-13-single-init.jsonl"]);
        let (_, rows) = omo_rows(&mut p, "omo-13-single.jsonl");
        assert_eq!(rows, [("helper-single".into(), "done".into(), "FIRST_LINE: alpha line".into(), "claude-haiku-5-5".into(), json!(23.0))]);
    }

    #[test]
    fn an_omo_row_without_its_own_record_ends_with_no_answer_never_another_ones() {
        // no record to read: the rows end done with no answer, and the turn still ends
        let mut p = pi_up("OmO", &["omo-13-batch-init.jsonl"]);
        p.omo_home = Some(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("no-such-home"));
        let (st, rows) = omo_rows(&mut p, "omo-13-batch.jsonl");
        assert_eq!(rows.iter().map(|r| (r.1.as_str(), r.2.as_str())).collect::<Vec<_>>(), [("done", ""), ("done", "")]);
        assert_eq!(st.events.iter().filter(|e| s(e, "event") == "turn.end").count(), 1);
        // records of another conversation (the single run's session) are never taken for this one's rows
        let mut p = pi_up("OmO", &["omo-13-single-init.jsonl"]);
        let (_, rows) = omo_rows(&mut p, "omo-13-batch.jsonl");
        assert_eq!(rows.iter().map(|r| r.2.as_str()).collect::<Vec<_>>(), ["", ""]);
        // a task id that is not OmO's shape is never looked up
        let p = pi_up("OmO", &["omo-13-batch-init.jsonl"]);
        for bad in ["../st_01a1d076", "st_01a1d076/..", "st_", "x_01a1d076", "st_01a1d076.json"] {
            assert!(p.omo_record(bad).is_none(), "{bad}");
        }
        assert_eq!(s(&p.omo_record("st_01a1d076").unwrap(), "final_response"), "FIRST_LINE: alpha line");
    }

    #[test]
    fn omos_todo_list_is_the_turns_checklist_never_a_step_with_its_json() {
        // omo-13-batch: OmO's `todo` init and two `done` calls
        let mut p = pi_up("OmO", &["omo-13-batch-init.jsonl"]);
        let (st, _) = omo_rows(&mut p, "omo-13-batch.jsonl");
        assert!(!st.events.iter().any(|e| s(e, "event") == "tool.start" && (s(e, "name") == "todo" || s(e, "detail").contains("{\""))), "a todo step");
        let plans: Vec<Vec<(String, String)>> = st.events.iter().filter(|e| s(e, "event") == "plan").map(|e| e["items"].as_array().unwrap().iter().map(|i| (s(i, "text"), s(i, "status"))).collect()).collect();
        assert_eq!(plans.first().unwrap(), &[("Spawn foreground batch of two helper tasks".to_string(), "in_progress".to_string()), ("Give one-line summary of batch results".into(), "pending".into())]);
        assert!(plans.last().unwrap().iter().all(|(_, st)| st == "completed"));
    }

    #[test]
    fn omo_says_what_still_runs_in_the_background() {
        // omo-B: session_lifecycle waiting_background with one bash (audit O10); subagents are not counted here
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        let st = p.on_line(r#"{"type":"session_lifecycle","lifecycle":{"state":"waiting_background","waitingOn":{"children":0,"background":[{"source":"terminal-background-sessions","activeCount":1,"items":[{"id":"bash_1","label":"sleep 20"}]}],"human":[]}}}"#);
        assert_eq!(st.events, [json!({"event": "session.info", "background": 1})]);
        assert!(p.on_line(r#"{"type":"session_lifecycle","lifecycle":{"state":"waiting_background","waitingOn":{"children":0,"background":[{"source":"terminal-background-sessions","activeCount":1}],"human":[]}}}"#).events.is_empty());
        let st = p.on_line(r#"{"type":"session_lifecycle","lifecycle":{"state":"done","waitingOn":{"children":0,"background":[{"source":"delivery:omo-senpi:wake:x","activeCount":1}],"human":[]}}}"#);
        assert_eq!(st.events, [json!({"event": "session.info", "background": 0})]);
    }

    #[test]
    fn a_codex_helper_finishing_does_not_end_the_persons_turn() {
        let mut x = codex_helpers_up();
        x.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap();
        let lines = real("codex-9-helpers.jsonl");
        // the first helper's own turn/completed: the person's turn is still running
        let child_end = lines.iter().position(|l| l.contains("\"turn/completed\"") && l.contains("01a1ca24-539f")).unwrap();
        let st = run(&mut x, &lines[..=child_end]);
        assert!(x.in_turn(), "a helper's turn/completed ended the person's turn");
        assert!(!names(&st.events).contains(&"turn.end".to_string()), "{:?}", names(&st.events));
        let st = run(&mut x, &lines[child_end + 1..]);
        assert!(!x.in_turn());
        assert_eq!(names(&st.events).iter().filter(|n| *n == "turn.end").count(), 1);
        assert_eq!(st.events.iter().filter(|e| s(e, "event") == "turn.start").count(), 0, "a helper's step started a turn of its own");
    }

    #[test]
    fn a_codex_helpers_text_is_never_codexs_own_answer() {
        let mut x = codex_helpers_up();
        x.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap();
        let st = run(&mut x, &real("codex-9-helpers.jsonl"));
        let said = text_of(&st.events, "message");
        assert!(!said.iter().any(|t| t == "done" || t == "alpha line"), "{said:?}");
        assert!(said.iter().any(|t| t.starts_with("Agent 1 wrote one.txt")), "{said:?}");
        // no streamed helper text either (only the session's own thread's deltas), and none of the helpers'
        // commands is a step of Codex's turn
        let own = real("codex-9-helpers.jsonl").iter().filter(|l| l.contains("item/agentMessage/delta") && l.contains("\"threadId\":\"01a1ca24-1047")).count();
        assert_eq!(text_of(&st.events, "delta").len(), own);
        let steps: Vec<String> = st.events.iter().filter(|e| s(e, "event") == "tool.start").map(|e| s(e, "detail")).collect();
        assert!(!steps.iter().any(|d| d.contains("echo one") || d.contains("head -n 1")), "{steps:?}");
    }

    #[test]
    fn codex_helpers_come_out_as_subagent_lines() {
        let mut x = codex_helpers_up();
        x.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap();
        let st = run(&mut x, &real("codex-9-helpers.jsonl"));
        let subs: Vec<&Event> = st.events.iter().filter(|e| s(e, "event") == "subagent").collect();
        let of = |id: &str| subs.iter().filter(|e| s(e, "id").ends_with(id)).map(|e| (*e).clone()).collect::<Vec<_>>();
        let one = of("e39bedaf4545");
        let two = of("13c7f1bb6917");
        // started, its step, done with its own answer and time
        assert_eq!(one.iter().map(|e| s(e, "state")).collect::<Vec<_>>(), ["running", "running", "done"]);
        assert_eq!((s(&one[0], "agent"), s(&one[0], "name"), s(&one[0], "goal")), ("codex".into(), "write one".into(), String::new()));
        assert_eq!(s(&one[0], "model"), "gpt-6.1-sol");
        assert_eq!(s(&one[1], "step"), "echo one > one.txt");
        assert_eq!(s(&one[2], "summary"), "done");
        assert_eq!(one[2]["seconds"], json!(4.8));
        assert_eq!(s(&two[0], "name"), "read first line");
        assert_eq!(s(two.last().unwrap(), "summary"), "alpha line");
        // one fan-out of two: the same delegation (the person's turn), index 0 and 1
        let deleg = s(&one[0], "delegation");
        assert!(deleg.starts_with("codex-") && subs.iter().all(|e| s(e, "delegation") == deleg));
        assert_eq!((one[0]["index"].clone(), two[0]["index"].clone(), two[0]["count"].clone()), (json!(0), json!(1), json!(2)));
        // every subagent line comes while the person's turn runs (they belong to it)
        let end = st.events.iter().position(|e| s(e, "event") == "turn.end").unwrap();
        assert!(st.events.iter().rposition(|e| s(e, "event") == "subagent").unwrap() < end);
    }

    #[test]
    fn codex_stop_while_a_helper_runs_names_the_persons_turn() {
        // codex-10: one helper runs `sleep 45`; the person presses Stop while it runs
        let mut x = Codex::new("/w/proj", None);
        x.start();
        run(&mut x, &real("codex-10-helper-stop-init.jsonl"));
        x.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap();
        run(&mut x, &real("codex-10-helper-stop.jsonl"));
        let st = x.on_input(Input::Interrupt).unwrap();
        let w = written(&st);
        assert_eq!(w[0]["method"], "turn/interrupt");
        // the session's own thread and turn, not the helper's (`…fa6d…`, which Codex refuses)
        assert_eq!(w[0]["params"]["threadId"], "01a1ca32-da48-7f42-adc1-3469420bbfa8");
        assert_eq!(w[0]["params"]["turnId"], "01a1ca32-e30e-7312-bc08-818ebbf0e1b3");
        // the recording holds Codex's refusal of the old (helper's) id: a refused Stop shows on the turn's line
        let st = run(&mut x, &real("codex-10-helper-stopped.jsonl")[..1]);
        assert_eq!(names(&st.events), ["status"]);
        assert!(s(&st.events[0], "text").starts_with("Codex did not stop: expected active turn id"));
        // the helper's message is its summary, not Codex's
        let st = run(&mut x, &real("codex-10-helper-stopped.jsonl")[1..]);
        let said = text_of(&st.events, "message");
        assert_eq!(said.len(), 1, "{said:?}");
        assert!(said[0].starts_with("The sub-agent completed"));
        assert_eq!(names(&st.events).last().unwrap(), "turn.end");
    }

    #[test]
    fn an_ask_inside_a_codex_helper_names_the_helper() {
        // shape from codex-rs app-server-protocol (v2 CommandExecutionRequestApprovalParams); this Mac's Codex runs
        // with approval_policy = never, so no helper approval was recorded
        let mut x = codex_helpers_up();
        x.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap();
        let lines = real("codex-9-helpers.jsonl");
        let spawned = lines.iter().position(|l| l.contains("\"subAgentActivity\"") && l.contains("write_one")).unwrap();
        run(&mut x, &lines[..=spawned]);
        let st = x.on_line(r#"{"id":91,"method":"item/commandExecution/requestApproval","params":{"threadId":"01a1ca24-539f-7e51-ad88-e39bedaf4545","turnId":"01a1ca24-53f9-72c0-a436-7edf958315cf","itemId":"exec-1","command":"/bin/zsh -lc 'rm one.txt'","cwd":"/w/proj"}}"#);
        assert_eq!(s(&st.events[0], "event"), "approval.request");
        assert_eq!(st.events[0]["subagent"], json!({"id": "01a1ca24-539f-7e51-ad88-e39bedaf4545", "name": "write one"}));
        // the answer goes back to the same request
        let st = x.on_input(Input::Approve { request_id: "codex-91".into(), choice: "deny".into() }).unwrap();
        assert_eq!(written(&st)[0], json!({"id": 91, "result": {"decision": "decline"}}));
        // an ask on the session's own thread names no helper
        let st = x.on_line(r#"{"id":92,"method":"item/commandExecution/requestApproval","params":{"threadId":"01a1ca24-1047-7ee0-aac2-faf093d44dbe","turnId":"t","itemId":"exec-2","command":"ls"}}"#);
        assert!(st.events[0].get("subagent").is_none());
    }

    #[test]
    fn a_codex_helpers_ask_outlives_the_persons_turn_while_the_helper_runs() {
        // not observed on this Mac (its Codex runs with approval: never): a helper still running when the person's
        // turn completes keeps its approval answerable, as Claude Code's background subagents do; the turn's own
        // approval does not
        let mut x = codex_helpers_up();
        x.on_input(Input::Send { text: "go".into(), images: vec![], id: String::new() }).unwrap();
        let lines = real("codex-9-helpers.jsonl");
        let spawned = lines.iter().position(|l| l.contains("\"subAgentActivity\"") && l.contains("write_one")).unwrap();
        run(&mut x, &lines[..=spawned]);
        x.on_line(r#"{"id":91,"method":"item/commandExecution/requestApproval","params":{"threadId":"01a1ca24-539f-7e51-ad88-e39bedaf4545","turnId":"01a1ca24-53f9-72c0-a436-7edf958315cf","itemId":"exec-1","command":"rm one.txt","cwd":"/w/proj"}}"#);
        x.on_line(r#"{"id":92,"method":"item/commandExecution/requestApproval","params":{"threadId":"01a1ca24-1047-7ee0-aac2-faf093d44dbe","turnId":"t","itemId":"exec-2","command":"ls"}}"#);
        let st = x.on_line(r#"{"method":"turn/completed","params":{"threadId":"01a1ca24-1047-7ee0-aac2-faf093d44dbe","turn":{"id":"t","status":"completed","items":[]}}}"#);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        assert_eq!(written(&x.on_input(Input::Approve { request_id: "codex-91".into(), choice: "once".into() }).unwrap())[0], json!({"id": 91, "result": {"decision": "accept"}}));
        assert!(x.on_input(Input::Approve { request_id: "codex-92".into(), choice: "once".into() }).is_err());
    }

    #[test]
    fn codex_stop_before_the_turn_has_an_id_still_stops_it() {
        // before the thread exists the message only waits: Stop drops it and ends the turn
        let mut x = Codex::new("/w/proj", None);
        x.start();
        x.on_input(Input::Send { text: "hi".into(), images: vec![], id: String::new() }).unwrap();
        let st = x.on_input(Input::Interrupt).unwrap();
        assert_eq!(st.events, [json!({"event": "turn.end", "outcome": "interrupted"})]);
        assert!(!x.in_turn() && run(&mut x, &real("codex-init.jsonl")).write.iter().all(|w| !w.contains("turn/start")));
        // sent, but Codex has not named the turn yet: Stop waits for the name, then interrupts it
        let mut x = codex_up();
        x.on_input(Input::Send { text: "sleep".into(), images: vec![], id: String::new() }).unwrap();
        assert!(x.on_input(Input::Interrupt).unwrap().write.is_empty());
        let st = x.on_line(r#"{"method":"turn/started","params":{"threadId":"t","turn":{"id":"turn_7","status":"inProgress","items":[]}}}"#);
        assert_eq!(written(&st)[0]["method"], "turn/interrupt");
        assert_eq!(written(&st)[0]["params"]["turnId"], "turn_7");
        // an error outside a turn is a note, not a progress line
        let mut idle = codex_up();
        let st = idle.on_line(r#"{"method":"error","params":{"error":{"message":"boom"},"willRetry":false}}"#);
        assert_eq!(names(&st.events), ["session.error"]);
        assert!(idle.on_line(r#"{"method":"error","params":{"error":{"message":"Reconnecting... 1/5"},"willRetry":true}}"#).events.is_empty());
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

    /// H1: a same-named other program (the QA report's shadow stub) ends at once with its own usage text; the
    /// person reads that the path does not look like the agent, with the install line, not the stub's stderr.
    #[cfg(unix)]
    #[test]
    fn a_program_that_is_not_the_agent_is_named_with_the_install_line() {
        let stub = "echo \"pi: impostor program (not the agent) args: $*\" >&2; echo 'usage: pi [-v] host...' >&2; exit 64";
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let path = Path::new("/Users/k/shadow/pi");
        for (label, id) in [("pi", "pi"), ("oh-my-pi", "omp"), ("OmO", "omo")] {
            let c = ChatSessions::default();
            let (out, sink) = collect();
            let mut adapter = Unrecognized::wrap(Box::new(Pi::new("/w", label)), id, path);
            adapter.on_input(Input::send("hi")).unwrap();
            c.spawn(vec!["/bin/sh".into(), "-c".into(), stub.into(), "pi".into(), "--mode".into(), "rpc".into()], &tmp, None, &[], adapter, sink).unwrap();
            assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10));
            let got = out.lock().unwrap().clone();
            let install = crate::sessions::layout(id).unwrap().install;
            let want = format!("/Users/k/shadow/pi does not look like {label} (it is not where {label} installs, and it ended without answering in its chat mode). Install {label}: {install}");
            assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(64), e) if *e == want)), "{got:?}");
            assert!(got.iter().any(|o| matches!(o, ChatOut::Event(e) if s(e, "event") == "turn.end" && s(e, "error") == want)), "{got:?}");
            assert!(!got.iter().any(|o| format!("{o:?}").contains("impostor")), "{got:?}");
        }
        // Claude Code and Codex: the same, with their own install line; and with nothing on stderr at all
        for (id, adapter) in [("claude", Box::new(Claude::new("/w")) as Box<dyn Adapter>), ("codex", Box::new(Codex::new("/w", None)))] {
            let a = Unrecognized::wrap(adapter, id, path);
            assert!(a.explain("").ends_with(crate::sessions::layout(id).unwrap().install), "{id}");
        }
        // the agent after all: it printed protocol, or it says it is not signed in
        let mut a = Unrecognized::wrap(Box::new(Pi::new("/w", "oh-my-pi")), "omp", path);
        assert_eq!(a.explain("No API key found"), "oh-my-pi is not signed in. Open Terminal and run /login, then Restart.");
        a.on_line("\u{feff}{\"type\":\"response\",\"command\":\"get_state\",\"success\":true,\"data\":{}}");
        assert_eq!(a.explain("boom"), "boom");
        // a banner is not protocol
        let mut b = Unrecognized::wrap(Box::new(Claude::new("/w")), "claude", path);
        b.on_line("Welcome to some tool v1.2");
        assert!(b.explain("boom").contains("does not look like Claude Code"));
        // DSH and oh-my-hermes have no layout row: no wrapper
        assert_eq!(Unrecognized::wrap(Box::new(Claude::new("/w")), "dsh", path).explain("boom"), "boom");
    }

    #[test]
    fn exit_reasons_drop_colour_codes_and_config_warnings() {
        // Codex 0.167 (audit O8): a coloured log line that only warns about a config setting is no reason
        let codex = "\u{1b}[2m2026-11-11T10:25:23.520926Z\u{1b}[0m \u{1b}[31mERROR\u{1b}[0m \u{1b}[2mcodex_app_server\u{1b}[2m:\u{1b}[0m Codex is ignoring 1 unrecognized configuration setting. Check for typos or deprecated settings.";
        assert_eq!(exit_reason(codex), "");
        let codex = format!("{codex}\n\u{1b}[2m2026-11-11T10:25:24Z\u{1b}[0m \u{1b}[31mERROR\u{1b}[0m codex_api: failed to connect");
        assert_eq!(exit_reason(&codex), "2026-11-11T10:25:24Z ERROR codex_api: failed to connect");
        // OmO's skills-catalog warning, then the real reason
        let omo = "Warning: The skills catalog uses one-line descriptions to limit request size (above 100 skills, 16 KiB of descriptions, or 48 KiB rendered). Remove unused skills to shrink every request.";
        assert_eq!(exit_reason(omo), "");
        assert_eq!(exit_reason(&format!("{omo}\nError: model not found")), "Error: model not found");
        assert_eq!(exit_turn_end(Some(0), &exit_reason(omo)), json!({"event": "turn.end", "outcome": "ended"}));
    }

    /// Codex 0.167's stderr at start (recorded with codex-15): a coloured config warning and, indented under it,
    /// the file it names. An orderly close (code 0) has no reason; a failure gives its last line, not that warning.
    const CODEX_START_WARNING: &str = "\u{1b}[2m2026-11-13T01:15:36.955056Z\u{1b}[0m \u{1b}[31mERROR\u{1b}[0m \u{1b}[2mcodex_app_server\u{1b}[0m\u{1b}[2m:\u{1b}[0m Codex is ignoring 1 unrecognized configuration setting. Check for typos or deprecated settings.\n  user (/Users/me/.codex/config.toml): `mcp_servers.playwright.type` is ignored.\n";

    #[test]
    fn a_start_up_warning_is_not_why_a_session_ended() {
        // before: the indented line under the warning came through as the reason of a clean close
        assert_eq!(exit_reason(CODEX_START_WARNING), "");
        assert_eq!(exit_why(Some(0), CODEX_START_WARNING), "");
        assert_eq!(exit_why(Some(0), &format!("{CODEX_START_WARNING}Error: boom")), "", "code 0 failed nothing");
        // a real failure: its last line, not the warning at the top
        let failed = format!("{CODEX_START_WARNING}2026-11-13T01:16:00Z ERROR codex_api: failed to connect\nError: stream disconnected before completion");
        assert_eq!(exit_reason(&failed), "Error: stream disconnected before completion");
        assert_eq!(Codex::new("/w", None).explain(&exit_why(Some(1), &failed)), "Error: stream disconnected before completion");
        // help text after the reason is not the reason (clap: error, blank, Usage, For more information)
        assert_eq!(exit_reason("error: unexpected argument 'app-server' found\n\nUsage: codex [OPTIONS]\n\nFor more information, try '--help'."), "error: unexpected argument 'app-server' found");
        // a sign-in hint above other lines is still found: oh-my-pi's signed-out exit (code 1)
        let omp = "No default model selected. Use /login, set an API key environment variable, or select a local model with /model or --model.\n\nSet an API key environment variable:\n  ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, etc.\n\nOr create /Users/me/.omp/agent/models.yml";
        assert_eq!(Pi::new("/w", "oh-my-pi").explain(&exit_why(Some(1), omp)), "oh-my-pi is not signed in. Open Terminal and run /login, then Restart.");
    }

    /// claude-14-plan-*: Claude Code 2.1.323 in plan mode ends its plan with `ExitPlanMode {plan, planFilePath}` and
    /// no rule to keep. The card asks in plain words, carries the plan's markdown whole, and offers Deny and Allow once.
    #[test]
    fn the_plan_approval_shows_the_plan_as_text() {
        let mut c = Claude::new("/w/proj");
        let st = replay(&mut c, &["claude-14-plan-deny.jsonl"], &["deny"]);
        let card = of(&st.events, "approval.request")[0];
        assert_eq!(s(card, "title"), "Start working on this plan?");
        assert_eq!(s(card, "command"), "", "no JSON string on the card");
        let plan = s(card, "plan");
        assert!(plan.starts_with("# Plan: calc.py에 mul(a, b) 추가\n\n1. `calc.py`"), "{plan}");
        assert!(plan.contains("\n2. `README.md`"), "the whole plan, line breaks kept: {plan}");
        assert_eq!(card["choices"], json!(["deny", "once"]));
        // denied: Claude Code asks what to change (a question card), the turn ends done
        assert_eq!(of(&st.events, "clarify.request").len(), 1);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
        // allowed: the plan goes back as Claude Code sent it, plan mode ends
        let mut c = Claude::new("/w/proj");
        let lines = real("claude-14-plan-allow.jsonl");
        let at = lines.iter().position(|l| l.contains("\"ExitPlanMode\"") && l.contains("can_use_tool")).unwrap();
        let st = run(&mut c, &lines[..=at]);
        let card = of(&st.events, "approval.request")[0].clone();
        let w = c.on_input(Input::Approve { request_id: s(&card, "request_id"), choice: "once".into() }).unwrap();
        let sent: Value = serde_json::from_str(&w.write[0]).unwrap();
        let input: Value = serde_json::from_str(&lines[at]).unwrap();
        assert_eq!(sent["response"]["response"], json!({"behavior": "allow", "updatedInput": input["request"]["input"]}));
        let st = run(&mut c, &lines[at + 1..]);
        assert!(st.events.iter().any(|e| s(e, "event") == "session.info" && s(e, "mode") == "default"), "plan mode ended");
    }

    /// A tool that is neither a command nor a file edit gets one readable line on its card, never its input as JSON.
    #[test]
    fn other_tools_ask_in_readable_lines() {
        let card = |name: &str, input: Value| {
            let mut c = Claude::new("/w/proj");
            let req = json!({"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": name, "input": input}});
            let st = c.on_line(&req.to_string());
            let e = of(&st.events, "approval.request")[0].clone();
            (s(&e, "title"), s(&e, "command"))
        };
        assert_eq!(card("Skill", json!({"skill": "omh-plan", "args": "a todo app"})), ("Allow Skill?".into(), "omh-plan a todo app".into()));
        assert_eq!(card("WebFetch", json!({"url": "https://example.com", "prompt": "title"})), ("Allow WebFetch?".into(), "https://example.com".into()));
        assert_eq!(card("EnterWorktree", json!({"name": "fix-a"})), ("Allow EnterWorktree?".into(), "name: fix-a".into()));
        assert_eq!(card("CronCreate", json!({"cron": "0 9 * * *", "recurring": true})), ("Allow CronCreate?".into(), "cron: 0 9 * * * · recurring: true".into()));
        assert_eq!(card("mcp__x__y", json!({"ids": [1, 2], "opts": {"a": 1}})), ("Allow mcp__x__y?".into(), "ids: [1,2] · opts: {\"a\":1}".into()));
    }

    /// codex-15-sub-edit: Codex 0.167 hands the edit to a sub-agent; the main thread has no file change, the
    /// sub-agent's thread has one with its patch. The sub-agent's row gets that step with its change per file.
    #[test]
    fn an_edit_codex_hands_to_its_subagent_has_its_diff() {
        let (mut a, init) = adapter_up("codex-sub-edit");
        for f in init {
            run(a.as_mut(), &real(f));
        }
        a.on_input(Input::send("go")).unwrap();
        let st = run(a.as_mut(), &real("codex-15-sub-edit.jsonl"));
        assert!(of(&st.events, "tool.diff").is_empty(), "the main thread edited nothing");
        let edits: Vec<&Event> = of(&st.events, "subagent").into_iter().filter(|e| s(e, "tool") == "patch").collect();
        assert!(!edits.is_empty());
        let last = edits.last().unwrap();
        assert_eq!(s(last, "step"), "README.md +2, calc.py +4");
        let files = last["diff"].as_array().unwrap();
        let paths: Vec<String> = files.iter().map(|f| s(f, "path")).collect();
        assert_eq!(paths, ["README.md", "calc.py"]);
        assert_eq!(files[1]["lines"], json!(["@@ -6 +6,5 @@", "     return a - b", "+", "+", "+def mul(a, b):", "+    return a * b"]));
        assert_eq!((files[1]["added"].as_u64(), files[1]["removed"].as_u64()), (Some(4), Some(0)));
        assert!(edits.iter().all(|e| e["diff"].is_array()), "every edit step carries its change");
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    /// The same through the real exit path, for every chat agent's adapter: a program that printed a start-up warning
    /// and closed in order ends with no reason; one that failed ends with its last line.
    #[cfg(unix)]
    #[test]
    fn every_chat_agent_ends_a_clean_close_without_a_reason() {
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        let warn = "printf '\\033[31mERROR\\033[0m Codex is ignoring 1 unrecognized configuration setting.\\n  user (~/.codex/config.toml): `mcp_servers.playwright.type` is ignored.\\n' >&2";
        let adapters: Vec<(&str, fn() -> Box<dyn Adapter>)> = vec![
            ("claude", || Box::new(Claude::new("/w"))),
            ("codex", || Box::new(Codex::new("/w", None))),
            ("omo", || Box::new(Pi::new("/w", "OmO"))),
            ("pi", || Box::new(Pi::new("/w", "pi"))),
            ("opencode", || adapter_for("opencode", "/w", None).unwrap()),
        ];
        for (name, make) in adapters {
            for (script, code, want) in [(format!("{warn}; exit 0"), 0, String::new()), (format!("{warn}; echo 'Error: it broke' >&2; exit 3"), 3, "Error: it broke".to_string())] {
                let c = ChatSessions::default();
                let (out, sink) = collect();
                c.spawn(vec!["/bin/sh".into(), "-c".into(), script.into()], &tmp, None, &[], make(), sink).unwrap();
                assert!(wait_for(|| out.lock().unwrap().iter().any(|o| matches!(o, ChatOut::Exit(..))), 10), "{name}");
                let got = out.lock().unwrap().clone();
                assert!(got.iter().any(|o| matches!(o, ChatOut::Exit(Some(c), e) if *c == code && *e == want)), "{name} exit {code}: {got:?}");
            }
        }
    }

    #[test]
    fn omo_stop_during_a_command_ends_interrupted() {
        // omo (audit O4): the abort hit the tool, so the last message ended with stopReason "toolUse"; agent_end
        // carries aborted: true
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        p.on_input(Input::Send { text: "sleep".into(), images: vec![], id: String::new() }).unwrap();
        p.on_line(r#"{"type":"agent_start"}"#);
        p.on_line(r#"{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"toolUse"}}"#);
        let st = p.on_line(r#"{"type":"agent_end","messages":[],"willRetry":false,"aborted":true,"abortSource":"user"}"#);
        assert_eq!(ends(&st.events), [("interrupted".into(), "".into())]);
        // an ordinary end stays done
        p.on_input(Input::Send { text: "hi".into(), images: vec![], id: String::new() }).unwrap();
        p.on_line(r#"{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ok"}],"stopReason":"stop"}}"#);
        let st = p.on_line(r#"{"type":"agent_end","messages":[],"willRetry":false}"#);
        assert_eq!(ends(&st.events), [("done".into(), "".into())]);
    }

    #[test]
    fn omo_retry_of_its_own_is_one_turn_that_ends_once_with_omos_reason() {
        // omo-12-retry (audit O5, OmO 5.1.56): agent_end with `failure`, auto_retry_start, a second run, agent_end,
        // auto_retry_end {finalError}, model_config_error. One message: one turn, one end, OmO's words, no raw JSON
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        let mut events = p.on_input(Input::send("which model?")).unwrap().events;
        events.extend(run(&mut p, &real("omo-12-retry.jsonl")).events);
        let kinds: Vec<String> = events.iter().map(|e| s(e, "event")).filter(|k| k.starts_with("turn.")).collect();
        assert_eq!(kinds, ["turn.start", "turn.end"], "{events:?}");
        let why = "Anthropic rejected this conversation's request format, even after retrying without web search replay data. Run /compact or start a new session to continue, and report it if it happens again.";
        assert_eq!(ends(&events), [("error".into(), why.into())]);
        // while OmO retried, the line said so, from OmO's own numbers
        let retry: Vec<&Event> = events.iter().filter(|e| s(e, "event") == "status" && e.get("retry").is_some()).collect();
        assert_eq!(retry.len(), 1);
        assert_eq!((retry[0]["retry"]["attempt"].as_u64(), retry[0]["retry"]["max"].as_u64()), (Some(1), Some(5)));
        assert!(!p.in_turn());
    }

    #[test]
    fn omo_failure_with_no_retry_ends_once_with_the_providers_message() {
        // the same recorded lines without OmO's retry: the run's end waits for OmO's next word, then ends once; the
        // raw `400 {"type":"error",…}` reads as the provider's message
        let lines = real("omo-12-retry.jsonl");
        let first_end = lines.iter().position(|l| l.contains("\"type\":\"agent_end\"")).unwrap();
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        let mut events = p.on_input(Input::send("which model?")).unwrap().events;
        let held = run(&mut p, &lines[..=first_end]).events;
        assert!(held.iter().all(|e| s(e, "event") != "turn.end"), "{held:?}");
        assert!(p.in_turn());
        events.extend(held);
        let rest: Vec<String> = lines[first_end + 1..].iter().filter(|l| l.contains("model_config_error") || l.contains("agent_settled")).cloned().collect();
        events.extend(run(&mut p, &rest).events);
        assert_eq!(ends(&events), [("error".into(), "unknown provider for model claude-haiku-4-5".into())]);
        // a retry that works clears the retry line and the turn goes on to its answer
        let mut p = pi_up("OmO", &["omo-init.jsonl"]);
        p.on_input(Input::send("again")).unwrap();
        run(&mut p, &lines[..=first_end + 2]);
        let st = p.on_line(r#"{"type":"auto_retry_end","success":true,"attempt":1}"#);
        assert_eq!(st.events, [json!({"event": "status", "text": ""})]);
        assert!(p.in_turn());
    }

    #[test]
    fn codex_stop_leaves_the_command_running_and_its_late_end_comes_after_the_turn() {
        // codex-12-late-step (audit O11/O13, Codex 0.167): Stop during `sleep 40; echo late`; Codex ends the turn
        // at once and reports the command's end 37 s later, after the next turn. The adapter passes that end on.
        let steps = &sequences().into_iter().find(|x| x.0 == "codex-12-late-step.jsonl").unwrap().2;
        let (events, running) = replay_sequence("codex-late", steps, &mut Default::default());
        assert!(!running);
        let info = events.iter().find(|e| s(e, "event") == "session.info" && e.get("approval").is_some()).unwrap();
        assert_eq!((s(info, "approval"), s(info, "sandbox"), s(info, "mode")), ("never".into(), "dangerFullAccess".into(), "".into()));
        let id = "exec-54fee470-b15c-41fa-bca7-76d78c82fc5c";
        let at = |pred: &dyn Fn(&Event) -> bool| events.iter().position(|e| pred(e)).unwrap();
        let stop = at(&|e| s(e, "event") == "turn.end" && s(e, "outcome") == "interrupted");
        let late = at(&|e| s(e, "event") == "tool.end" && s(e, "tool_id") == id);
        let next_end = events.iter().rposition(|e| s(e, "event") == "turn.end").unwrap();
        assert!(stop < next_end && next_end < late, "the command's end comes after both turns");
        assert_eq!((events[late]["ok"].as_bool(), events[late]["ms"].as_u64()), (Some(true), Some(39887)));
    }

    #[test]
    fn codex_resume_takes_only_a_thread_uuid() {
        let c = ChatSessions::default();
        let tmp = std::env::temp_dir();
        for bad in ["x", "--yolo", "01a1c3b9-4b7f-7542-900c-c5f4dc80eef", "../01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"] {
            assert!(c.start_agent("codex", &tmp, Some(bad), &[], None, |_| {}).is_err(), "{bad}");
        }
        assert!(c.start_agent("pi", &tmp, Some("01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"), &[], None, |_| {}).is_err());
        assert_eq!(c.count(), 0);
    }

    // ---- attached files: each agent's own image input (shapes checked against claude 2.1.322, codex 0.167,
    // omo 5.0 beta on 2026-11-11: each read a word from a PNG sent this way) -----------------------------------

    fn pic() -> Picture {
        Picture { path: "/h/.omher/session-files/s1/1-word.png".into(), mime: "image/png".into(), data: "iVBORw0KGgo=".into() }
    }
    fn with_pic(text: &str) -> Input {
        Input::Send { text: text.into(), images: vec![pic()], id: String::new() }
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
        let mut i = Input::Send { text: "x".into(), images: vec![Picture::from(png.to_string_lossy().into_owned())], id: String::new() };
        i.resolve(&home).unwrap();
        let Input::Send { images, .. } = &i else { panic!() };
        assert_eq!((images[0].mime.as_str(), images[0].data.as_str()), ("image/png", "iVBORw=="));
        let txt = session_files::save(&home, "s1", "notes.txt", b"a").unwrap();
        let outside = home.join("secret.png");
        std::fs::write(&outside, b"x").unwrap();
        for bad in [txt.to_string_lossy().into_owned(), outside.to_string_lossy().into_owned(), "/etc/hosts".into(), "relative.png".into()] {
            let mut i = Input::Send { text: "x".into(), images: vec![Picture::from(bad.clone())], id: String::new() };
            assert!(i.resolve(&home).is_err(), "{bad}");
        }
        // other inputs carry no files
        assert!(Input::Interrupt.resolve(&home).is_ok());
        let _ = std::fs::remove_dir_all(&home);
    }

    // ---- what a session shows of the agent's work: diffs, its todo list, thinking, edit and resend ----

    fn of_kind<'a>(events: &'a [Event], name: &str) -> Vec<&'a Event> {
        events.iter().filter(|e| s(e, "event") == name).collect()
    }

    #[test]
    fn claude_two_file_edit_shows_each_change_and_one_todo_list_that_updates_in_place() {
        // claude-12-work: Claude Code 2.1.322 (sonnet), TaskCreate x3, then per item TaskUpdate in_progress, an Edit,
        // TaskUpdate completed; calc.py twice and README.md once
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        let st = run(&mut c, &real("claude-12-work.jsonl"));
        // the todo tools are the checklist, never steps
        let steps: Vec<String> = of_kind(&st.events, "tool.start").iter().map(|e| s(e, "name")).collect();
        assert!(!steps.iter().any(|n| n.starts_with("Task") || n.starts_with("Todo")), "{steps:?}");
        let plans = of_kind(&st.events, "plan");
        assert_eq!(plans.len(), 3 + 6, "one plan event per change of the list");
        let last = &plans.last().unwrap()["items"];
        let rows: Vec<(String, String)> = last.as_array().unwrap().iter().map(|i| (s(i, "text"), s(i, "status"))).collect();
        assert_eq!(rows.len(), 3);
        assert!(rows.iter().all(|r| r.1 == "completed"), "{rows:?}");
        assert_eq!(rows[1].0, "Add mul(a, b) function to calc.py");
        // midway the second is in progress and the first done
        let mid: Vec<String> = plans[5]["items"].as_array().unwrap().iter().map(|i| s(i, "status")).collect();
        assert_eq!(mid, ["completed", "in_progress", "pending"]);
        // every edit carries its change, the input's first and the result's (hunks with context) last
        let diffs = of_kind(&st.events, "tool.diff");
        let edits = of_kind(&st.events, "tool.start").into_iter().filter(|e| s(e, "name") == "patch").count();
        assert_eq!(edits, 3);
        assert_eq!(diffs.len(), 6);
        let files: Vec<String> = diffs.iter().map(|d| s(&d["files"][0], "path")).collect();
        assert_eq!(files, ["calc.py", "calc.py", "calc.py", "calc.py", "README.md", "README.md"]);
        let mul = &diffs[3]["files"][0];
        let lines: Vec<String> = mul["lines"].as_array().unwrap().iter().map(|l| l.as_str().unwrap().to_string()).collect();
        assert_eq!(lines[0], "@@ -5,3 +5,7 @@");
        assert!(lines.contains(&"+def mul(a, b):".to_string()) && lines.contains(&" def sub(a, b):".to_string()), "{lines:?}");
        assert_eq!((mul["added"].as_u64(), mul["removed"].as_u64()), (Some(4), Some(0)));
    }

    #[test]
    fn claude_thinking_text_is_kept_and_a_marker_without_text_stays_empty() {
        // claude-12-thinking: Claude Code 2.1.322 (fable) streams its thinking as text deltas
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        let st = run(&mut c, &real("claude-12-thinking.jsonl"));
        let text: String = of_kind(&st.events, "thinking").iter().map(|e| s(e, "text")).collect();
        assert!(text.starts_with("No todo tool is available, so I'll track the three steps inline"), "{text}");
        // claude-3-edit: an older recording with the thinking text stripped; the events say only that it thinks
        let mut c = claude_up();
        c.on_input(Input::send("go")).unwrap();
        let st = run(&mut c, &real("claude-3-edit.jsonl"));
        let t = of_kind(&st.events, "thinking");
        assert!(!t.is_empty() && t.iter().all(|e| e.get("text").is_none()));
        // joined in delivery like answer text, never across kinds
        let got = merge_deltas(vec![thinking_event("a"), thinking_event("b"), ev("delta", json!({"text": "c"})), thinking_event("d")]);
        assert_eq!(got, vec![thinking_event("ab"), ev("delta", json!({"text": "c"})), thinking_event("d")]);
    }

    #[test]
    fn claude_rewind_takes_back_the_last_message_through_its_own_rewind_conversation() {
        // claude-12-rewind: a real turn, then `rewind_conversation` to its message (Claude Code answered rewound:true
        // and the next turn had no memory of it: "NONE")
        let mut c = claude_up();
        assert!(c.on_input(Input::Rewind).is_err(), "nothing sent yet");
        c.on_input(Input::send("Remember the word ORCHID. Reply only: ok")).unwrap();
        let lines = real("claude-12-rewind.jsonl");
        run(&mut c, &lines[..5]);
        let st = c.on_input(Input::Rewind).unwrap();
        let w = written(&st);
        assert_eq!(w[0]["request"], json!({"subtype": "rewind_conversation", "target_message_uuid": "de0a73ab-5879-4e81-b093-fb2cdb29704a"}));
        let rid = s(&w[0], "request_id");
        let st = c.on_line(&lines[5].replace("omher-rewind-REQ", &rid));
        assert_eq!(st.events[0], json!({"event": "rewound", "text": "Remember the word ORCHID. Reply only: ok"}));
        assert_eq!(st.events[1], json!({"event": "session.info", "rewind": false}));
        // a refusal says so and keeps the message
        c.on_input(Input::send("again")).unwrap();
        run(&mut c, &lines[6..]);
        let st = c.on_input(Input::Rewind).unwrap();
        let rid = s(&written(&st)[0], "request_id");
        let st = c.on_line(&format!(r#"{{"type":"control_response","response":{{"subtype":"error","request_id":"{rid}","error":"turn running"}}}}"#));
        assert_eq!(names(&st.events), ["session.error", "session.info"]);
        assert_eq!(st.events[1]["rewind"], json!(true));
        // never while a turn runs
        c.on_input(Input::send("x")).unwrap();
        assert!(c.on_input(Input::Rewind).is_err());
    }

    #[test]
    fn codex_plan_reasoning_and_file_changes_come_out_in_the_same_shapes() {
        // shapes from codex-rs app-server-protocol v2 (codex 0.167 `generate-ts`): turn/plan/updated, reasoning
        // summary and raw deltas, a fileChange update with a unified diff; Codex has no credit on this Mac, so the
        // turn is built from the schema, the item/started of a real fileChange (codex-3-edit) is real
        let mut x = codex_up();
        x.on_input(Input::send("go")).unwrap();
        let t = r#"{"method":"turn/started","params":{"threadId":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","turn":{"id":"t9","items":[],"status":"inProgress"}}}"#;
        let plan = r#"{"method":"turn/plan/updated","params":{"threadId":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","turnId":"t9","explanation":null,"plan":[{"step":"Add mul to calc.py","status":"completed"},{"step":"List functions in README.md","status":"inProgress"},{"step":"Run a check","status":"pending"}]}}"#;
        let sum = r#"{"method":"item/reasoning/summaryTextDelta","params":{"threadId":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","turnId":"t9","itemId":"rs1","delta":"Two files to touch.","summaryIndex":0}}"#;
        let raw = r#"{"method":"item/reasoning/textDelta","params":{"threadId":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","turnId":"t9","itemId":"rs1","delta":"raw","contentIndex":0}}"#;
        let raw2 = r#"{"method":"item/reasoning/textDelta","params":{"threadId":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","turnId":"t9","itemId":"rs2","delta":"only raw","contentIndex":0}}"#;
        let fc = r##"{"method":"item/started","params":{"threadId":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa","turnId":"t9","item":{"type":"fileChange","id":"fc1","status":"inProgress","changes":[{"path":"/w/proj/calc.py","kind":{"type":"update","move_path":null},"diff":"--- a/calc.py\n+++ b/calc.py\n@@ -5,2 +5,5 @@\n def sub(a, b):\n     return a - b\n+\n+def mul(a, b):\n+    return a * b\n"},{"path":"/w/proj/README.md","kind":{"type":"add"},"diff":"# calc\nFunctions: add, sub, mul\n"}]}}}"##;
        let st = run(&mut x, &[t.into(), plan.into(), sum.into(), raw.into(), raw2.into(), fc.into()]);
        let p = of_kind(&st.events, "plan");
        assert_eq!(p[0]["items"], json!([{"text": "Add mul to calc.py", "status": "completed"}, {"text": "List functions in README.md", "status": "in_progress"}, {"text": "Run a check", "status": "pending"}]));
        let th: Vec<String> = of_kind(&st.events, "thinking").iter().map(|e| s(e, "text")).collect();
        assert_eq!(th, ["Two files to touch.", "", "only raw"], "a summarized item's raw text is not shown twice");
        let d = of_kind(&st.events, "tool.diff");
        assert_eq!(s(d[0], "tool_id"), "fc1");
        let f = d[0]["files"].as_array().unwrap();
        assert_eq!((s(&f[0], "path"), s(&f[0], "kind")), ("calc.py".into(), "update".into()));
        assert_eq!(f[0]["lines"][0], "@@ -5,2 +5,5 @@");
        assert_eq!((f[0]["added"].as_u64(), f[0]["removed"].as_u64()), (Some(3), Some(0)));
        assert_eq!((s(&f[1], "kind"), f[1]["lines"].clone()), ("add".into(), json!(["+# calc", "+Functions: add, sub, mul"])));
        // a real recording (codex-3-edit): the new file's content is its change
        let mut x = codex_up();
        x.on_input(Input::send("go")).unwrap();
        let st = run(&mut x, &real("codex-3-edit.jsonl"));
        let d = of_kind(&st.events, "tool.diff");
        assert!(!d.is_empty());
        assert_eq!(d[0]["files"][0]["lines"], json!(["+hello from qa"]));
    }

    #[test]
    fn codex_rewind_reverts_the_thread_before_the_last_turn() {
        // thread/revert {threadId, beforeTurnId} answered and followed by thread/reverted, as Codex 0.167 did in a
        // scratch thread (two failed turns, no credit; the revert itself needs none)
        let mut x = codex_up();
        assert!(x.on_input(Input::Rewind).is_err());
        x.on_input(Input::send("go")).unwrap();
        run(&mut x, &real("codex-1-plain.jsonl"));
        let st = x.on_input(Input::Rewind).unwrap();
        let w = written(&st);
        assert_eq!(s(&w[0], "method"), "thread/revert");
        assert_eq!(w[0]["params"]["threadId"], json!("01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"));
        assert!(!s(&w[0]["params"], "beforeTurnId").is_empty());
        let id = w[0]["id"].as_u64().unwrap();
        let st = x.on_line(&format!(r#"{{"id":{id},"result":{{"thread":{{"id":"01a1c3b9-4b7f-7542-900c-c5f4dc80eefa"}},"turnsBackwardsCursor":null,"itemsBackwardsCursor":null}}}}"#));
        assert_eq!(st.events, vec![json!({"event": "rewound"}), json!({"event": "session.info", "rewind": false})]);
        assert!(x.on_input(Input::Rewind).is_err(), "nothing left to take back");
    }

    #[test]
    fn diff_lines_are_capped_and_counted() {
        let big: String = (0..450).map(|i| format!("line {i}\n")).collect();
        let f = input_diff("Write", &json!({"file_path": "/w/proj/big.txt", "content": big}), "/w/proj").unwrap();
        assert_eq!(f["lines"].as_array().unwrap().len(), DIFF_LINES);
        assert_eq!((f["added"].as_u64(), f["more"].as_u64()), (Some(450), Some(50)));
        assert_eq!(s(&f, "path"), "big.txt");
        // MultiEdit: one hunk per edit; a non-file tool has none
        let m = input_diff("MultiEdit", &json!({"file_path": "/w/proj/a.ts", "edits": [{"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "d"}]}), "/w/proj").unwrap();
        assert_eq!(m["lines"], json!(["-a", "+b", "@@", "-c", "+d"]));
        assert!(input_diff("Bash", &json!({"command": "ls"}), "/w/proj").is_none());
        // the rpc and acp agents have no rewind; DSH neither
        assert!(Pi::new("/w/proj", "OmO").on_input(Input::Rewind).is_err());
    }
}

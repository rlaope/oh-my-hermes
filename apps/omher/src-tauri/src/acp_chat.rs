//! One chat adapter for every agent that speaks the Agent Client Protocol (ACP: JSON-RPC 2.0, one object per
//! line on stdio), plus a table row per agent ([`ACP_AGENTS`]). OpenCode (`opencode acp`) is the first row.
//!
//! - start: `initialize` with the client's file-system and terminal capabilities OFF, so the agent uses its
//!   own tools and omher reads and writes nothing new; then `session/resume` when the agent offers it and omher
//!   holds a conversation id, else `session/load`, else `session/new`.
//! - Send -> `session/prompt`; Stop -> `session/cancel`; model -> `session/set_config_option`.
//! - `session/update` notifications -> the bot chat's events (delta, message, thinking, tool.start / tool.end
//!   with a duration measured here, turn.end from `stopReason`, session.info, session.models,
//!   session.commands).
//! - `session/request_permission` -> an approval card offering only what the request offers. `allow_always`
//!   is never offered: OpenCode saves it as a permanent project rule, which is not omher's "for this session".
//!   A Stop while a card is open answers `cancelled` and expires the card.
//! - An unknown request from the agent gets a JSON-RPC error answer so the agent never waits on omher; unknown
//!   notifications, fields and lines are ignored and nothing raw reaches the chat.
//!
//! Checked against OpenCode 1.19.5 (`tests/fixtures/acp/opencode-*.jsonl`, recorded from real runs).

use std::collections::HashMap;
use std::time::Instant;

use serde_json::{json, Map, Value};

use crate::agent_chat::{Adapter, Event, Input, Step};

fn ev(name: &str, fields: Value) -> Event {
    let mut m = Map::new();
    m.insert("event".into(), Value::String(name.into()));
    if let Value::Object(f) = fields {
        m.extend(f);
    }
    Value::Object(m)
}

fn s(v: &Value, k: &str) -> String {
    v.get(k).and_then(Value::as_str).unwrap_or("").to_string()
}

/// One line, at most `n` characters.
fn clip(t: &str, n: usize) -> String {
    let one = t.split_whitespace().collect::<Vec<_>>().join(" ");
    if one.chars().count() <= n {
        one
    } else {
        format!("{}…", one.chars().take(n - 1).collect::<String>())
    }
}

/// `path` relative to the session folder when it is inside it.
fn rel(path: &str, cwd: &str) -> String {
    let c = cwd.trim_end_matches(['/', '\\']);
    for sep in ['/', '\\'] {
        if let Some(r) = path.strip_prefix(&format!("{c}{sep}")).filter(|_| !c.is_empty()) {
            return r.to_string();
        }
    }
    path.to_string()
}

fn out(st: &mut Step, v: Value) {
    st.write.push(v.to_string());
}

fn emit(st: &mut Step, e: Event) {
    st.events.push(e);
}

/// What omher knows about one ACP agent. The program and its fixed argument live in the allow-list
/// (`sessions::AGENTS`, `sessions::chat_args`); this row holds what the protocol cannot say.
#[derive(Debug)]
pub struct AcpAgent {
    pub id: &'static str,
    pub label: &'static str,
    /// The sign-in line omher shows when the agent answers `-32000` (auth required). Fixed here: never the
    /// command the agent itself suggests.
    pub login: &'static str,
    /// The agent's own tool that loads a skill (its `tool_call` title), whose `rawInput.name` names the skill.
    pub skill_tool: Option<&'static str>,
    /// How the agent is made to ask before edits and shell commands without loosening a rule of the person's own
    /// (see [`RuleProbe`]); `None` adds nothing.
    pub rules: Option<RuleProbe>,
}

/// An agent whose own default runs tools without asking. Before the chat starts, the shell runs the agent's fixed
/// rule listing (`args`) in the session folder with the environment the chat gets, sets `var` to what `build` makes
/// of it, lists again with `var` set and starts the chat only when `kept` says the agent took the rules as meant.
/// Anything else (the listing fails, times out or does not parse, the rules did not hold, or `var` is already set
/// in omher's own environment) refuses the chat with [`NO_RULES`].
#[derive(Debug)]
pub struct RuleProbe {
    pub args: &'static [&'static str],
    pub var: &'static str,
    pub build: fn(&str) -> Option<String>,
    pub kept: fn(&str, &str) -> bool,
}

/// Why an agent with a [`RuleProbe`] did not start (the UI shows it translated, `ss.noRules`).
pub const NO_RULES: &str = "OpenCode did not start because omher could not confirm it would keep your own OpenCode permission rules.";

pub const ACP_AGENTS: [AcpAgent; 1] = [AcpAgent {
    id: "opencode",
    label: "OpenCode",
    login: "opencode auth login",
    skill_tool: Some("skill"),
    rules: Some(RuleProbe { args: &["agent", "list"], var: "OPENCODE_CONFIG_CONTENT", build: opencode_ask, kept: opencode_kept }),
}];

/// OpenCode's `permission` / `pattern` match (`Wildcard.match`, 1.19.5): `*` any run, `?` one character, `\\` read
/// as `/`, and a pattern ending in `" *"` also matches without that tail.
fn wildcard(text: &str, pattern: &str) -> bool {
    fn m(t: &[char], p: &[char]) -> bool {
        match p.split_first() {
            None => t.is_empty(),
            Some(('*', rest)) => (0..=t.len()).any(|i| m(&t[i..], rest)),
            Some(('?', rest)) => !t.is_empty() && m(&t[1..], rest),
            Some((c, rest)) => t.first() == Some(c) && m(&t[1..], rest),
        }
    }
    let t: Vec<char> = text.replace('\\', "/").chars().collect();
    let p: Vec<char> = pattern.replace('\\', "/").chars().collect();
    m(&t, &p) || (p.ends_with(&[' ', '*']) && m(&t, &p[..p.len() - 2]))
}

/// The tools omher's approval card stands for, and the key their ask rules go under. OpenCode files a write or a
/// patch under `edit`. The key is not the tool's own name, so OpenCode's config merge cannot fold these rules into
/// the person's own `bash` / `edit` entry (which would keep the person's key order and let their `"*": "allow"`
/// come after an ask); `"bash *"` matches the tool `bash` and nothing else.
const ASKED: [(&str, &str); 2] = [("bash", "bash *"), ("edit", "edit *")];

/// Each agent's rules for `bash` and `edit` as OpenCode resolved them, from what `opencode agent list` printed
/// (each agent's name and mode on its own line, then its ruleset as JSON, where the last matching rule decides):
/// per tool, each pattern once at its last place with its action, in order. `None` when the listing has no `build`
/// agent or holds a line or rule this does not know.
fn resolved(listing: &str) -> Option<Vec<(String, Vec<Vec<(String, String)>>)>> {
    let mut agents: Vec<(String, String)> = Vec::new();
    for line in listing.lines() {
        let head = !line.starts_with([' ', '\t', '[', ']', '{', '}']) && line.ends_with(')') && line.contains(" (");
        if head {
            agents.push((line[..line.rfind(" (")?].to_string(), String::new()));
        } else {
            let last = agents.last_mut()?;
            last.1.push_str(line);
            last.1.push('\n');
        }
    }
    if !agents.iter().any(|(n, _)| n == "build") {
        return None;
    }
    let mut out = Vec::new();
    for (name, body) in agents {
        let rules: Vec<Value> = serde_json::from_str(&body).ok()?;
        let mut per = Vec::new();
        for (tool, _) in ASKED {
            let mut seen: Vec<(String, String)> = Vec::new();
            for r in rules.iter().rev() {
                let (perm, pattern, action) = (r.get("permission")?.as_str()?, r.get("pattern")?.as_str()?, r.get("action")?.as_str()?);
                if !matches!(action, "allow" | "ask" | "deny") {
                    return None;
                }
                if wildcard(tool, perm) && !seen.iter().any(|(p, _)| p == pattern) {
                    seen.push((pattern.to_string(), action.to_string()));
                }
            }
            seen.reverse();
            per.push(seen);
        }
        out.push((name, per));
    }
    Some(out)
}

/// The ask rules for an OpenCode chat, from what `opencode agent list` printed without them: for every agent and
/// each of `bash` and `edit`, the person's own resolved rules repeated after theirs, in the same order, with allow
/// turned into ask. What they allow asks, what asks still asks, what they deny stays denied, for blanket and
/// pattern rules alike.
pub fn opencode_ask(listing: &str) -> Option<String> {
    let q = |v: &str| Value::String(v.into()).to_string();
    let agents = resolved(listing)?
        .iter()
        .map(|(name, per)| {
            let tools = ASKED
                .iter()
                .zip(per)
                .map(|((_, key), rules)| {
                    let pairs: Vec<String> = rules.iter().map(|(p, a)| format!("{}:{}", q(p), q(if a == "deny" { "deny" } else { "ask" }))).collect();
                    format!("{}:{{{}}}", q(key), pairs.join(","))
                })
                .collect::<Vec<_>>();
            format!("{}:{{\"permission\":{{{}}}}}", q(name), tools.join(","))
        })
        .collect::<Vec<_>>();
    Some(format!("{{\"agent\":{{{}}}}}", agents.join(",")))
}

/// Whether OpenCode, listed again with `rules` set (`listing`), took them as meant: no agent lets `bash` or `edit`
/// run unasked anywhere, and its rules are exactly the ones `rules` was built from. A later config layer that
/// put an allow back after them fails this, and the chat does not start.
pub fn opencode_kept(rules: &str, listing: &str) -> bool {
    resolved(listing).is_some_and(|agents| agents.iter().all(|(_, per)| per.iter().flatten().all(|(_, a)| a != "allow")))
        && opencode_ask(listing).as_deref() == Some(rules)
}

pub fn acp_agent(id: &str) -> Option<&'static AcpAgent> {
    ACP_AGENTS.iter().find(|a| a.id == id)
}

/// A conversation id an ACP agent reported (`ses_…` for OpenCode, a UUID for others): letters, digits, `_` and
/// `-`, 1 to 128 of them. It travels in the protocol (`session/resume`), never on the command line.
pub fn is_acp_session_id(id: &str) -> bool {
    (1..=128).contains(&id.len()) && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// The objects in one line of output: a leading BOM dropped, and two objects printed on one line (`}{`) split.
/// Anything that does not parse is dropped.
pub fn json_objects(line: &str) -> Vec<Value> {
    let t = line.trim_start_matches('\u{feff}').trim();
    let mut out = Vec::new();
    for v in serde_json::Deserializer::from_str(t).into_iter::<Value>() {
        match v {
            Ok(v) => out.push(v),
            Err(_) => break,
        }
    }
    out
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Call {
    Initialize,
    Open,
    Prompt,
    Config,
}

/// An open permission request: its JSON-RPC id and the option id for each answer omher offers.
struct Ask {
    rpc_id: Value,
    once: Option<String>,
    deny: Option<String>,
}

struct Tool {
    started: Instant,
    /// the omher tool name it started as (OpenCode retitles a call with its description once input arrives)
    name: String,
    /// a skill tool whose skill is not named yet
    skill: bool,
    /// its step is shown (`tool.start` sent): once, as soon as the call says what it does
    shown: bool,
}

pub struct Acp {
    agent: &'static AcpAgent,
    cwd: String,
    resume: Option<String>,
    seq: u64,
    calls: HashMap<u64, Call>,
    session: Option<String>,
    turn: bool,
    prompt_id: Option<u64>,
    queued: Vec<String>,
    pending: HashMap<String, Ask>,
    tools: HashMap<String, Tool>,
    /// text of the agent message being streamed, and its id
    text: String,
    text_id: String,
    model_labels: HashMap<String, String>,
    model: String,
    can_resume: bool,
    can_load: bool,
    msg_seq: u64,
}

impl Acp {
    pub fn new(agent: &'static AcpAgent, cwd: &str, resume: Option<&str>) -> Acp {
        Acp {
            agent,
            cwd: cwd.into(),
            resume: resume.filter(|r| is_acp_session_id(r)).map(String::from),
            seq: 0,
            calls: HashMap::new(),
            session: None,
            turn: false,
            prompt_id: None,
            queued: vec![],
            pending: HashMap::new(),
            tools: HashMap::new(),
            text: String::new(),
            text_id: String::new(),
            model_labels: HashMap::new(),
            model: String::new(),
            can_resume: false,
            can_load: false,
            msg_seq: 0,
        }
    }

    fn call(&mut self, st: &mut Step, what: Call, method: &str, params: Value) -> u64 {
        self.seq += 1;
        self.calls.insert(self.seq, what);
        out(st, json!({"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params}));
        self.seq
    }

    fn signed_out(&self) -> String {
        format!("{} is not signed in. Open Terminal and run `{}`, then Restart.", self.agent.label, self.agent.login)
    }

    fn prompt(&mut self, st: &mut Step, text: String) {
        let sid = self.session.clone().unwrap_or_default();
        let id = self.call(st, Call::Prompt, "session/prompt", json!({"sessionId": sid, "prompt": [{"type": "text", "text": text}]}));
        self.prompt_id = Some(id);
    }

    /// The streamed text so far as one finished message.
    fn flush(&mut self, st: &mut Step) {
        let t = std::mem::take(&mut self.text);
        let id = std::mem::take(&mut self.text_id);
        if !t.trim().is_empty() {
            self.msg_seq += 1;
            let id = if id.is_empty() { format!("acp-m{}", self.msg_seq) } else { format!("{id}-{}", self.msg_seq) };
            emit(st, ev("message", json!({"id": id, "text": t})));
        }
    }

    fn end(&mut self, st: &mut Step, outcome: &str, error: Option<String>) {
        self.flush(st);
        self.prompt_id = None;
        if !self.turn {
            return;
        }
        self.turn = false;
        // a step still open when the turn ends ended with it
        for (id, tool) in self.tools.drain() {
            if tool.shown {
                emit(st, ev("tool.end", json!({"tool_id": id, "name": "", "ok": outcome == "done", "ms": 0})));
            }
        }
        for (rid, _) in self.pending.drain() {
            emit(st, ev("prompt.expired", json!({"request_id": rid, "reason": "cancelled"})));
        }
        let mut f = json!({"outcome": outcome});
        if let Some(e) = error.filter(|e| !e.is_empty()) {
            f["error"] = Value::String(e);
        }
        emit(st, ev("turn.end", f));
    }

    /// `configOptions` from new/load/resume/set_config_option or a `config_option_update`: the model list and the
    /// current model.
    fn config(&mut self, st: &mut Step, opts: &Value) {
        let Some(model) = opts.as_array().into_iter().flatten().find(|o| s(o, "category") == "model" || s(o, "id") == "model") else { return };
        let mut options = Vec::new();
        for o in model.get("options").and_then(Value::as_array).into_iter().flatten() {
            // a group (`{group, name, options:[…]}`) is flattened, its name as the detail
            if let Some(inner) = o.get("options").and_then(Value::as_array) {
                let group = s(o, "name");
                for x in inner {
                    options.push((s(x, "value"), s(x, "name"), group.clone()));
                }
            } else {
                options.push((s(o, "value"), s(o, "name"), String::new()));
            }
        }
        options.retain(|o| !o.0.is_empty());
        for (v, n, _) in &options {
            if !n.is_empty() {
                self.model_labels.insert(v.clone(), n.clone());
            }
        }
        let list: Vec<Value> = options.iter().map(|(v, n, g)| json!({"id": v, "label": if n.is_empty() { v } else { n }, "detail": g})).collect();
        emit(st, ev("session.models", json!({"options": list})));
        let cur = s(model, "currentValue");
        if !cur.is_empty() && cur != self.model {
            self.model = cur.clone();
            let label = self.model_labels.get(&cur).cloned().unwrap_or(cur);
            emit(st, ev("session.info", json!({"model": label})));
        }
    }

    fn tool_detail(&self, kind: &str, title: &str, raw: &Value) -> String {
        let pick = |k: &str| raw.get(k).and_then(Value::as_str).map(str::trim).filter(|x| !x.is_empty()).map(String::from);
        let d = match kind {
            "terminal" => pick("command"),
            "patch" | "read_file" => pick("filePath").or_else(|| pick("path")).or_else(|| pick("file_path")).map(|p| rel(&p, &self.cwd)),
            "search_files" => pick("pattern").or_else(|| pick("query")),
            "web_extract" => pick("url"),
            "web_search" => pick("query"),
            _ => pick("description"),
        };
        // the title stands in only when it says more than the tool's name (`Reply with kiwi`, not `bash`)
        let d = d.unwrap_or_else(|| if title.trim().contains(' ') { title.to_string() } else { String::new() });
        clip(&d, 160)
    }

    /// The omher tool name for an ACP tool call: from its `kind`, else its title (OpenCode titles a call by the
    /// tool name until it has input).
    fn kind_of(kind: &str, title: &str) -> String {
        match kind {
            "execute" => "terminal".into(),
            "read" => "read_file".into(),
            "edit" | "delete" | "move" => "patch".into(),
            "search" => "search_files".into(),
            "fetch" => "web_extract".into(),
            _ => match title.to_ascii_lowercase().as_str() {
                "task" => "delegate_task".into(),
                "todowrite" | "todoread" => "todo".into(),
                "bash" | "shell" => "terminal".into(),
                "read" => "read_file".into(),
                "write" | "edit" | "patch" | "apply_patch" | "multiedit" => "patch".into(),
                "grep" | "glob" | "list" | "ls" => "search_files".into(),
                "webfetch" => "web_extract".into(),
                "websearch" => "web_search".into(),
                "skill" => "skill_view".into(),
                _ => title.to_string(),
            },
        }
    }

    /// Show tool call `id`'s step once its input says what it does (OpenCode sends the call first with only the
    /// folder, then its input with the first update), and the skill a skill tool loads.
    fn show(&mut self, st: &mut Step, id: &str, u: &Value) {
        let raw = u.get("rawInput").cloned().unwrap_or(Value::Null);
        let title = s(u, "title");
        let Some(tool) = self.tools.get(id) else { return };
        let (name, shown, skill) = (tool.name.clone(), tool.shown, tool.skill);
        let known = raw.as_object().is_some_and(|m| m.keys().any(|k| k != "cwd"));
        if !shown && known {
            let detail = self.tool_detail(&name, &title, &raw);
            emit(st, ev("tool.start", json!({"tool_id": id, "name": name, "detail": detail})));
            self.tools.get_mut(id).unwrap().shown = true;
        }
        let sk = raw.get("name").and_then(Value::as_str).unwrap_or("").trim().to_string();
        if skill && !sk.is_empty() {
            emit(st, ev("skill", json!({"name": clip(&sk, 80)})));
            self.tools.get_mut(id).unwrap().skill = false;
        }
    }

    fn update(&mut self, st: &mut Step, u: &Value) {
        match s(u, "sessionUpdate").as_str() {
            "agent_message_chunk" => {
                let t = u.get("content").map(|c| s(c, "text")).unwrap_or_default();
                let id = s(u, "messageId");
                if !self.text_id.is_empty() && !id.is_empty() && id != self.text_id {
                    self.flush(st);
                }
                if !id.is_empty() {
                    self.text_id = id;
                }
                if !t.is_empty() && self.turn {
                    self.text.push_str(&t);
                    emit(st, ev("delta", json!({"text": t})));
                }
            }
            "agent_thought_chunk" if self.turn => emit(st, crate::agent_chat::thinking_event(&u.get("content").map(|c| s(c, "text")).unwrap_or_default())),
            "tool_call" if self.turn => {
                let id = s(u, "toolCallId");
                if id.is_empty() || self.tools.contains_key(&id) {
                    return;
                }
                // text before a tool call is its own message, as in the other adapters
                self.flush(st);
                let title = s(u, "title");
                let name = Acp::kind_of(&s(u, "kind"), &title);
                let skill = self.agent.skill_tool.is_some_and(|t| t == title);
                self.tools.insert(id.clone(), Tool { started: Instant::now(), name, skill, shown: false });
                self.show(st, &id, u);
            }
            "tool_call_update" => {
                let id = s(u, "toolCallId");
                if !self.tools.contains_key(&id) {
                    return;
                }
                self.show(st, &id, u);
                if matches!(s(u, "status").as_str(), "completed" | "failed") {
                    let tool = self.tools.remove(&id).unwrap();
                    if !tool.shown {
                        emit(st, ev("tool.start", json!({"tool_id": id, "name": tool.name, "detail": ""})));
                    }
                    let ms = tool.started.elapsed().as_millis() as u64;
                    emit(st, ev("tool.end", json!({"tool_id": id, "name": "", "ok": s(u, "status") == "completed", "ms": ms})));
                }
            }
            "config_option_update" => {
                let opts = u.get("configOptions").cloned().unwrap_or(Value::Null);
                self.config(st, &opts);
            }
            "session_info_update" => {
                let t = clip(&s(u, "title").replace(|c: char| c.is_control(), " "), 80);
                if !t.is_empty() {
                    emit(st, ev("session.info", json!({"title": t})));
                }
            }
            "available_commands_update" => {
                let commands: Vec<Value> = u
                    .get("availableCommands")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter(|c| !s(c, "name").trim().is_empty())
                    .take(500)
                    .map(|c| {
                        let hint = c.get("input").map(|i| s(i, "hint")).unwrap_or_default();
                        json!({"name": clip(s(c, "name").trim(), 80), "description": clip(&s(c, "description"), 200), "hint": clip(&hint, 80), "kind": "command", "prefix": "/"})
                    })
                    .collect();
                emit(st, ev("session.commands", json!({"commands": commands})));
            }
            _ => {}
        }
    }

    fn request(&mut self, st: &mut Step, rpc_id: Value, method: &str, p: &Value) {
        if method != "session/request_permission" || !self.turn {
            out(st, json!({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "not supported by omher"}}));
            return;
        }
        let options: Vec<&Value> = p.get("options").and_then(Value::as_array).into_iter().flatten().collect();
        let opt = |kind: &str| options.iter().find(|o| s(o, "kind") == kind).map(|o| s(o, "optionId")).filter(|x| !x.is_empty());
        let (once, deny) = (opt("allow_once"), opt("reject_once").or_else(|| opt("reject_always")));
        let mut choices = Vec::new();
        if deny.is_some() {
            choices.push("deny");
        }
        if once.is_some() {
            choices.push("once");
        }
        if choices.is_empty() {
            // nothing omher can offer honestly (only "always"): refuse rather than leave the agent waiting
            out(st, json!({"jsonrpc": "2.0", "id": rpc_id, "result": {"outcome": {"outcome": "cancelled"}}}));
            return;
        }
        let tc = p.get("toolCall").cloned().unwrap_or(Value::Null);
        let raw = tc.get("rawInput").cloned().unwrap_or(Value::Null);
        let title = s(&tc, "title");
        let kind = Acp::kind_of(&s(&tc, "kind"), &title);
        let detail = self.tool_detail(&kind, &title, &raw);
        let (title, command) = match kind.as_str() {
            "terminal" => ("Run this command?".to_string(), detail),
            "patch" => (if detail.is_empty() { format!("Allow {} to change files?", self.agent.label) } else { format!("Allow {} to change {detail}?", self.agent.label) }, String::new()),
            _ => (if title.is_empty() { format!("Allow {}?", self.agent.label) } else { clip(&title, 120) }, String::new()),
        };
        let key = format!("acp-{}", rpc_id);
        self.pending.insert(key.clone(), Ask { rpc_id, once, deny });
        let mut f = json!({"request_id": key, "title": title, "command": command, "choices": choices});
        if !self.cwd.is_empty() {
            f["cwd"] = Value::String(self.cwd.clone());
        }
        emit(st, ev("approval.request", f));
    }

    fn response(&mut self, st: &mut Step, id: u64, v: &Value) {
        let Some(what) = self.calls.remove(&id) else { return };
        if let Some(err) = v.get("error") {
            let code = err.get("code").and_then(Value::as_i64).unwrap_or(0);
            let msg = clip(&s(err, "message"), 200);
            match what {
                Call::Open if code == -32000 => {
                    emit(st, ev("session.error", json!({"message": self.signed_out()})));
                    if self.turn {
                        let e = self.signed_out();
                        self.queued.clear();
                        self.end(st, "error", Some(e));
                    }
                }
                Call::Open => {
                    // a conversation that can no longer be continued: start a new one rather than none
                    if self.session.is_none() && self.resume.take().is_some() {
                        emit(st, ev("session.error", json!({"message": format!("{} could not continue the conversation ({msg}); this is a new one.", self.agent.label)})));
                        let cwd = self.cwd.clone();
                        self.call(st, Call::Open, "session/new", json!({"cwd": cwd, "mcpServers": []}));
                    } else {
                        emit(st, ev("session.error", json!({"message": msg})));
                        if self.turn {
                            self.queued.clear();
                            self.end(st, "error", Some(msg));
                        }
                    }
                }
                Call::Prompt => {
                    let e = if code == -32000 { self.signed_out() } else { msg };
                    self.end(st, "error", Some(e));
                }
                Call::Config => emit(st, ev("session.error", json!({"message": msg}))),
                Call::Initialize => emit(st, ev("session.error", json!({"message": msg}))),
            }
            return;
        }
        let r = v.get("result").cloned().unwrap_or(Value::Null);
        match what {
            Call::Initialize => {
                let caps = r.get("agentCapabilities").cloned().unwrap_or(Value::Null);
                self.can_load = caps.get("loadSession").and_then(Value::as_bool).unwrap_or(false);
                self.can_resume = caps.get("sessionCapabilities").and_then(|c| c.get("resume")).is_some_and(|x| !x.is_null());
                let cwd = self.cwd.clone();
                match self.resume.clone() {
                    Some(sid) if self.can_resume => {
                        self.call(st, Call::Open, "session/resume", json!({"sessionId": sid, "cwd": cwd, "mcpServers": []}));
                    }
                    Some(sid) if self.can_load => {
                        self.call(st, Call::Open, "session/load", json!({"sessionId": sid, "cwd": cwd, "mcpServers": []}));
                    }
                    _ => {
                        self.resume = None;
                        self.call(st, Call::Open, "session/new", json!({"cwd": cwd, "mcpServers": []}));
                    }
                }
            }
            Call::Open => {
                let sid = r.get("sessionId").and_then(Value::as_str).map(String::from).or_else(|| self.resume.clone()).filter(|x| is_acp_session_id(x));
                let Some(sid) = sid else {
                    emit(st, ev("session.error", json!({"message": format!("{} did not name the conversation", self.agent.label)})));
                    return;
                };
                self.session = Some(sid.clone());
                emit(st, ev("session.info", json!({"agent_session": sid})));
                let opts = r.get("configOptions").cloned().unwrap_or(Value::Null);
                self.config(st, &opts);
                if let Some(text) = (!self.queued.is_empty()).then(|| std::mem::take(&mut self.queued).join("\n\n")) {
                    self.prompt(st, text);
                }
            }
            Call::Prompt => {
                if self.prompt_id != Some(id) {
                    return;
                }
                match s(&r, "stopReason").as_str() {
                    "cancelled" => self.end(st, "interrupted", None),
                    "max_tokens" => self.end(st, "error", Some(format!("{} stopped: the answer reached its length limit.", self.agent.label))),
                    "max_turn_requests" => self.end(st, "error", Some(format!("{} stopped: too many steps in one turn.", self.agent.label))),
                    "refusal" => self.end(st, "error", Some(format!("{} declined to answer.", self.agent.label))),
                    _ => self.end(st, "done", None),
                }
            }
            Call::Config => {
                let opts = r.get("configOptions").cloned().unwrap_or(Value::Null);
                self.config(st, &opts);
            }
        }
    }
}

impl Adapter for Acp {
    fn start(&mut self) -> Step {
        let mut st = Step::default();
        self.call(
            &mut st,
            Call::Initialize,
            "initialize",
            json!({"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": false, "writeTextFile": false}, "terminal": false}, "clientInfo": {"name": "omher", "title": "omher", "version": env!("CARGO_PKG_VERSION")}}),
        );
        st
    }

    fn in_turn(&self) -> bool {
        self.turn
    }

    fn explain(&self, err: &str) -> String {
        let low = err.to_ascii_lowercase();
        if low.contains("auth") && (low.contains("required") || low.contains("login")) {
            return self.signed_out();
        }
        err.to_string()
    }

    fn on_line(&mut self, line: &str) -> Step {
        let mut st = Step::default();
        for v in json_objects(line) {
            let Value::Object(m) = &v else { continue };
            let method = m.get("method").and_then(Value::as_str).map(String::from);
            let id = m.get("id").cloned();
            match (method, id) {
                (None, Some(id)) => {
                    if let Some(n) = id.as_u64() {
                        self.response(&mut st, n, &v);
                    }
                }
                (Some(method), Some(rpc_id)) => {
                    let p = v.get("params").cloned().unwrap_or(Value::Null);
                    self.request(&mut st, rpc_id, &method, &p);
                }
                (Some(method), None) if method == "session/update" => {
                    let p = v.get("params").cloned().unwrap_or(Value::Null);
                    // another conversation's updates (a helper's own session) are not this chat's
                    if self.session.as_deref().is_some_and(|sid| !s(&p, "sessionId").is_empty() && s(&p, "sessionId") != sid) {
                        continue;
                    }
                    if let Some(u) = p.get("update") {
                        self.update(&mut st, u);
                    }
                }
                _ => {}
            }
        }
        st
    }

    fn on_input(&mut self, input: Input) -> Result<Step, String> {
        let mut st = Step::default();
        match input {
            Input::Send { text, images, .. } => {
                if !images.is_empty() {
                    return Err(format!("{} chats take text only here", self.agent.label));
                }
                if self.turn {
                    return Err(format!("{} is still answering; Stop first", self.agent.label));
                }
                self.turn = true;
                emit(&mut st, ev("turn.start", json!({})));
                if self.session.is_none() {
                    self.queued.push(text);
                } else {
                    self.prompt(&mut st, text);
                }
            }
            Input::Interrupt => {
                if !self.turn {
                    return Err("nothing is running".into());
                }
                // an open card is answered `cancelled` and expires; the turn ends when the prompt answers
                for (rid, a) in self.pending.drain() {
                    out(&mut st, json!({"jsonrpc": "2.0", "id": a.rpc_id, "result": {"outcome": {"outcome": "cancelled"}}}));
                    emit(&mut st, ev("prompt.expired", json!({"request_id": rid, "reason": "cancelled"})));
                }
                match self.session.clone() {
                    Some(sid) if self.prompt_id.is_some() => out(&mut st, json!({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}})),
                    // the message still waits for the conversation: it is never sent
                    _ => {
                        self.queued.clear();
                        self.end(&mut st, "interrupted", None);
                    }
                }
            }
            Input::Approve { request_id, choice } => {
                let Some(a) = self.pending.get(&request_id) else { return Err("no such request".into()) };
                let option = match choice.as_str() {
                    "once" => a.once.clone(),
                    "deny" => a.deny.clone(),
                    _ => None,
                }
                .ok_or_else(|| format!("{} did not offer {choice}", self.agent.label))?;
                let a = self.pending.remove(&request_id).unwrap();
                out(&mut st, json!({"jsonrpc": "2.0", "id": a.rpc_id, "result": {"outcome": {"outcome": "selected", "optionId": option}}}));
            }
            Input::Clarify { .. } => return Err("no such question".into()),
            // the agent picks its own permission mode and effort; omher offers no switch for them here
            Input::Mode { .. } | Input::Effort { .. } => return Err(format!("{} has no mode or effort switch here", self.agent.label)),
            Input::Rewind => return Err(format!("{} cannot take a message back here", self.agent.label)),
            Input::Model { model } => {
                let Some(sid) = self.session.clone() else { return Err(format!("{} has not started yet", self.agent.label)) };
                let mut p = Map::new();
                p.insert("sessionId".into(), Value::String(sid));
                p.insert("configId".into(), Value::String("model".into()));
                p.insert("value".into(), Value::String(model));
                self.call(&mut st, Call::Config, "session/set_config_option", Value::Object(p));
            }
        }
        Ok(st)
    }
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn real(name: &str) -> Vec<String> {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("acp").join(name);
        std::fs::read_to_string(p).unwrap().lines().filter(|l| !l.trim().is_empty()).map(String::from).collect()
    }

    fn opencode() -> &'static AcpAgent {
        acp_agent("opencode").unwrap()
    }

    fn written(st: &Step) -> Vec<Value> {
        st.write.iter().map(|w| serde_json::from_str(w).unwrap()).collect()
    }

    fn of<'a>(events: &'a [Event], name: &str) -> Vec<&'a Event> {
        events.iter().filter(|e| s(e, "event") == name).collect()
    }

    fn names(events: &[Event]) -> Vec<String> {
        events.iter().map(|e| s(e, "event")).collect()
    }

    /// Feed the recorded agent lines of `file` in order. The person's Send goes in right after the conversation is
    /// open (line 2), as in the recording; each approval card is answered with the next of `answers` ("stop" =
    /// Stop while the card is open). Returns every event and every line omher wrote.
    fn replay(a: &mut Acp, file: &str, send: Option<&str>, answers: &[&str]) -> Step {
        let mut all = Step::default();
        let st = a.start();
        all.write.extend(st.write);
        let mut k = 0;
        for (i, l) in real(file).iter().enumerate() {
            let st = a.on_line(l);
            all.write.extend(st.write);
            for e in st.events {
                all.events.push(e.clone());
                if s(&e, "event") == "approval.request" {
                    let answer = answers.get(k).copied().unwrap_or("once");
                    k += 1;
                    let w = if answer == "stop" {
                        a.on_input(Input::Interrupt).unwrap()
                    } else {
                        a.on_input(Input::Approve { request_id: s(&e, "request_id"), choice: answer.into() }).unwrap()
                    };
                    all.write.extend(w.write);
                    all.events.extend(w.events);
                }
            }
            if i == 1 {
                if let Some(text) = send {
                    let w = a.on_input(Input::Send { text: text.into(), images: vec![], id: String::new() }).unwrap();
                    all.write.extend(w.write);
                    all.events.extend(w.events);
                }
            }
        }
        all
    }

    /// No event outside a turn but session ones, exactly one turn.end, and nothing raw.
    fn one_clean_turn(events: &[Event]) {
        let mut open = false;
        let mut ends = 0;
        for e in events {
            match s(e, "event").as_str() {
                "turn.start" => open = true,
                "turn.end" => {
                    open = false;
                    ends += 1
                }
                "delta" | "message" | "thinking" | "tool.start" | "tool.end" | "skill" | "approval.request" | "prompt.expired" => assert!(open, "{e} outside the turn"),
                "session.info" | "session.models" | "session.commands" | "session.error" => {}
                other => panic!("unexpected event {other}: {e}"),
            }
        }
        assert_eq!(ends, 1, "{events:?}");
        assert!(!open);
    }

    #[test]
    fn start_turns_off_the_clients_files_and_terminal() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let w = written(&a.start());
        assert_eq!(w[0]["method"], "initialize");
        assert_eq!(w[0]["params"]["clientCapabilities"], json!({"fs": {"readTextFile": false, "writeTextFile": false}, "terminal": false}));
    }

    #[test]
    fn real_opencode_1_plain_answer() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-1-plain.jsonl", Some("Reply with just the word pineapple."), &[]);
        one_clean_turn(&st.events);
        let w = written(&st);
        assert_eq!(w.iter().map(|x| s(x, "method")).collect::<Vec<_>>(), ["initialize", "session/new", "session/prompt"]);
        assert_eq!(w[1]["params"], json!({"cwd": "/w/proj", "mcpServers": []}));
        assert_eq!(w[2]["params"]["prompt"], json!([{"type": "text", "text": "Reply with just the word pineapple."}]));
        let info = of(&st.events, "session.info");
        assert_eq!(s(info[0], "agent_session"), "ses_e34e28c01ffeKlpLA61p3XV1cy");
        assert_eq!(s(info[1], "model"), "OpenCode/Big Pickle");
        let models = &of(&st.events, "session.models")[0]["options"];
        assert_eq!(models.as_array().unwrap().len(), 12);
        assert_eq!(models[0], json!({"id": "opencode/beam-free", "label": "OpenCode/Beam Free", "detail": ""}));
        let msgs: Vec<String> = of(&st.events, "message").iter().map(|e| s(e, "text")).collect();
        assert_eq!(msgs, ["pineapple"]);
        assert_eq!(s(of(&st.events, "turn.end")[0], "outcome"), "done");
        // OpenCode's own commands and skills reach the session's `/` list
        let cmds = &of(&st.events, "session.commands")[0]["commands"];
        let names: Vec<String> = cmds.as_array().unwrap().iter().map(|c| s(c, "name")).collect();
        assert_eq!(names, ["customize-opencode", "init", "review"]);
        assert_eq!(cmds[1]["kind"], "command");
        assert_eq!(cmds[1]["prefix"], "/");
    }

    #[test]
    fn real_opencode_2_allow_once_runs_the_command() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-2-allow-once.jsonl", Some("run echo hi"), &["once"]);
        one_clean_turn(&st.events);
        let card = of(&st.events, "approval.request")[0];
        assert_eq!(s(card, "title"), "Run this command?");
        assert_eq!(s(card, "command"), "echo hi > a.txt");
        assert_eq!(s(card, "cwd"), "/w/proj");
        // OpenCode offers once / always / reject: omher offers Deny and Allow once, never "always"
        assert_eq!(card["choices"], json!(["deny", "once"]));
        let answer = written(&st).into_iter().find(|w| w.get("result").is_some()).unwrap();
        assert_eq!(answer["result"], json!({"outcome": {"outcome": "selected", "optionId": "once"}}));
        // one step per call, shown once its input names the command (before the card asks)
        let tools: Vec<(String, String)> = of(&st.events, "tool.start").iter().map(|e| (s(e, "name"), s(e, "detail"))).collect();
        assert_eq!(tools, [("terminal".to_string(), "echo hi > a.txt".to_string())]);
        let at = |n: &str| names(&st.events).iter().position(|x| x == n).unwrap();
        assert!(at("tool.start") < at("approval.request"));
        let end = of(&st.events, "tool.end");
        assert_eq!(end.len(), 1);
        assert_eq!(end[0]["ok"], true);
        assert!(end[0]["ms"].is_u64());
    }

    #[test]
    fn real_opencode_3_deny_fails_the_step_not_the_turn() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-3-deny.jsonl", Some("run echo bye"), &["deny"]);
        one_clean_turn(&st.events);
        let answer = written(&st).into_iter().find(|w| w.get("result").is_some()).unwrap();
        assert_eq!(answer["result"], json!({"outcome": {"outcome": "selected", "optionId": "reject"}}));
        assert_eq!(of(&st.events, "tool.end")[0]["ok"], false);
        assert_eq!(s(of(&st.events, "turn.end")[0], "outcome"), "done");
        assert!(!of(&st.events, "thinking").is_empty());
    }

    #[test]
    fn real_opencode_4_stop_with_a_card_open_answers_cancelled_and_ends_interrupted() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-4-stop.jsonl", Some("sleep 30"), &["stop"]);
        one_clean_turn(&st.events);
        let w = written(&st);
        let answer = w.iter().find(|w| w.get("result").is_some()).unwrap();
        assert_eq!(answer["result"], json!({"outcome": {"outcome": "cancelled"}}));
        assert!(w.iter().any(|x| x["method"] == "session/cancel" && x["params"]["sessionId"] == "ses_e34e1ef3dffeI56JYYGEpYsDF9"));
        let expired = of(&st.events, "prompt.expired");
        assert_eq!(expired.len(), 1);
        assert_eq!(s(expired[0], "request_id"), s(of(&st.events, "approval.request")[0], "request_id"));
        assert_eq!(s(of(&st.events, "turn.end")[0], "outcome"), "interrupted");
        // the answer to a card already withdrawn is refused
        assert!(a.on_input(Input::Approve { request_id: s(expired[0], "request_id"), choice: "once".into() }).is_err());
    }

    #[test]
    fn real_opencode_5_a_second_process_resumes_the_conversation() {
        let mut a = Acp::new(opencode(), "/w/proj", Some("ses_e34e28c01ffeKlpLA61p3XV1cy"));
        let st = replay(&mut a, "opencode-5-resume.jsonl", Some("Which fruit word did you reply with earlier?"), &[]);
        one_clean_turn(&st.events);
        let w = written(&st);
        assert_eq!(w[1]["method"], "session/resume");
        assert_eq!(w[1]["params"], json!({"sessionId": "ses_e34e28c01ffeKlpLA61p3XV1cy", "cwd": "/w/proj", "mcpServers": []}));
        assert_eq!(s(of(&st.events, "session.info")[0], "agent_session"), "ses_e34e28c01ffeKlpLA61p3XV1cy");
        let msgs: Vec<String> = of(&st.events, "message").iter().map(|e| s(e, "text")).collect();
        assert_eq!(msgs, ["pineapple"], "the second process knew the first turn");
    }

    #[test]
    fn real_opencode_6_a_skill_shows_as_the_skill_in_use() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-6-skill.jsonl", Some("load customize-opencode"), &[]);
        one_clean_turn(&st.events);
        assert_eq!(of(&st.events, "skill").iter().map(|e| s(e, "name")).collect::<Vec<_>>(), ["customize-opencode"]);
        assert_eq!(s(of(&st.events, "tool.start")[0], "name"), "skill_view");
        assert_eq!(of(&st.events, "tool.end").len(), 1);
    }

    #[test]
    fn real_opencode_7_a_subagent_is_one_step_never_the_answer() {
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-7-subagent.jsonl", Some("start a subagent"), &[]);
        one_clean_turn(&st.events);
        // OpenCode 1.19.5 reports a subagent as one `task` tool call on the parent session: no child session's
        // updates arrive over ACP
        let starts = of(&st.events, "tool.start");
        assert_eq!(starts.len(), 1);
        assert_eq!((s(starts[0], "name"), s(starts[0], "detail")), ("delegate_task".to_string(), "Reply with kiwi".to_string()));
        assert_eq!(of(&st.events, "tool.end").len(), 1);
        let msgs: Vec<String> = of(&st.events, "message").iter().map(|e| s(e, "text")).collect();
        assert_eq!(msgs, ["The subagent replied with: **kiwi**"]);
        assert!(!msgs[0].contains("task_result"));
        let at = |n: &str| names(&st.events).iter().position(|x| x == n).unwrap();
        assert!(at("tool.end") < at("turn.end"));
    }

    #[test]
    fn real_opencode_0_without_the_ask_rules_a_command_runs_unasked() {
        // the same request with OpenCode's own defaults (no ask rules): no card, the command ran. This is why the row
        // starts OpenCode with ask rules (`RuleProbe`).
        let mut a = Acp::new(opencode(), "/w/proj", None);
        let st = replay(&mut a, "opencode-0-default-runs-unasked.jsonl", Some("run echo raw"), &[]);
        one_clean_turn(&st.events);
        assert!(of(&st.events, "approval.request").is_empty());
        assert_eq!(of(&st.events, "tool.end")[0]["ok"], true);
        let probe = opencode().rules.as_ref().unwrap();
        assert_eq!((probe.args, probe.var), (&["agent", "list"][..], "OPENCODE_CONFIG_CONTENT"));
    }

    /// `opencode agent list` from OpenCode 1.19.5 (scratch HOME, `opencode-rules.json`) for one person's config:
    /// as it is, with omher's rules in `OPENCODE_CONFIG_CONTENT`, and with the earlier fixed `OPENCODE_PERMISSION`.
    fn rules_case(case: &str) -> (String, String, String) {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("acp").join("opencode-rules.json");
        let all: Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
        let c = &all[case];
        (s(c, "agent_list"), s(c, "agent_list_in_omher"), s(c, "agent_list_with_old_rule"))
    }

    /// What OpenCode decides for `tool` on `input` under agent `agent` of `listing` (its `Permission.evaluate`: the
    /// last rule whose permission and pattern match, else ask).
    fn decides(listing: &str, agent: &str, tool: &str, input: &str) -> String {
        let mut cur = None;
        let mut body = String::new();
        for line in listing.lines() {
            if !line.starts_with([' ', '[', ']']) && line.ends_with(')') {
                if cur.as_deref() == Some(agent) {
                    break;
                }
                cur = Some(line[..line.rfind(" (").unwrap()].to_string());
                body.clear();
            } else if cur.as_deref() == Some(agent) {
                body.push_str(line);
            }
        }
        let rules: Vec<Value> = serde_json::from_str(&body).unwrap();
        rules.iter().rev().find(|r| wildcard(tool, &s(r, "permission")) && wildcard(input, &s(r, "pattern"))).map(|r| s(r, "action")).unwrap_or_else(|| "ask".into())
    }

    /// For each recorded config: (tool, input, the person's own decision, the decision inside omher).
    fn check_rules(case: &str, want: &[(&str, &str, &str, &str)]) {
        let (base, in_omher, old) = rules_case(case);
        let rules = opencode_ask(&base).unwrap();
        // the very rules the recording started OpenCode with
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("acp").join("opencode-rules.json");
        let all: Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
        assert_eq!(rules, s(&all[case], "env_sent"), "{case}");
        // OpenCode, started with these rules, resolved exactly them, and nothing in bash or edit is allowed unasked
        assert!(opencode_kept(&rules, &in_omher), "{case}");
        assert!(!opencode_kept(&rules, &base), "{case}: without the rules OpenCode runs tools unasked");
        for agent in ["build", "general", "plan", "explore"] {
            for (tool, input, own, inside) in want {
                if agent == "build" {
                    assert_eq!(decides(&base, agent, tool, input), *own, "{case} build {tool} {input}: the person's own rule");
                }
                let got = decides(&in_omher, agent, tool, input);
                let never_looser = match decides(&base, agent, tool, input).as_str() {
                    "deny" => got == "deny",
                    _ => got == "ask" || got == "deny",
                };
                assert!(never_looser, "{case} {agent} {tool} {input}: {got}");
                if agent == "build" {
                    assert_eq!(got, *inside, "{case} build {tool} {input}");
                }
            }
        }
        // the earlier fixed rule turned this person's deny into ask
        if want.iter().any(|w| w.2 == "deny") {
            assert!(want.iter().any(|(t, i, own, _)| *own == "deny" && decides(&old, "build", t, i) == "ask"), "{case}");
        }
    }

    #[test]
    fn real_opencode_rules_a_blanket_string_deny_stays_deny() {
        // `"permission": {"bash": "deny"}`
        check_rules("string-deny", &[("bash", "echo hi", "deny", "deny"), ("bash", "rm -rf x", "deny", "deny"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_opencode_rules_a_blanket_map_deny_stays_deny() {
        // `"permission": {"bash": {"*": "deny"}}`
        check_rules("map-deny", &[("bash", "echo hi", "deny", "deny"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_opencode_rules_a_star_deny_stays_deny_for_both() {
        // `"permission": {"*": "deny"}`
        check_rules("star-deny", &[("bash", "echo hi", "deny", "deny"), ("edit", "a.md", "deny", "deny")]);
    }

    #[test]
    fn real_opencode_rules_a_pattern_deny_stays_deny_and_the_rest_asks() {
        // `"permission": {"bash": {"rm *": "deny"}}`
        check_rules("pattern-deny", &[("bash", "rm -rf x", "deny", "deny"), ("bash", "echo hi", "allow", "ask"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_opencode_rules_an_allow_becomes_ask() {
        // `"permission": {"bash": "allow", "edit": "allow"}`
        check_rules("allow", &[("bash", "echo hi", "allow", "ask"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_opencode_rules_with_nothing_set_everything_asks() {
        check_rules("none", &[("bash", "echo hi", "allow", "ask"), ("bash", "rm -rf x", "allow", "ask"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn opencode_rules_refuse_what_they_cannot_read() {
        assert_eq!(opencode_ask(""), None);
        assert_eq!(opencode_ask("Error: Config file is not valid JSON"), None);
        let (base, _, _) = rules_case("none");
        // no build agent, a truncated ruleset, an action this does not know
        assert_eq!(opencode_ask(&base.replace("build (primary)", "builder (primary)")), None);
        assert_eq!(opencode_ask(&base[..base.len() / 2]), None);
        assert_eq!(opencode_ask(&base.replacen("\"action\": \"allow\"", "\"action\": \"maybe\"", 1)), None);
        // rules OpenCode did not keep (a later layer put an allow back) refuse the start
        let rules = opencode_ask(&base).unwrap();
        assert!(!opencode_kept(&rules, &base));
        assert!(!opencode_kept(&rules, ""));
    }

    #[test]
    fn wildcard_matches_as_opencode_does() {
        assert!(wildcard("bash", "*") && wildcard("bash", "bash") && wildcard("bash", "bash *") && wildcard("bash", "ba?h"));
        assert!(wildcard("rm -rf x", "rm *") && wildcard("rm", "rm *") && !wildcard("rmdir x", "rm *"));
        assert!(!wildcard("bash", "edit *") && !wildcard("bashful", "bash *"));
        assert!(wildcard("a\\b.md", "a/*.md"));
    }

    #[test]
    fn real_opencode_8_model_switch_load_and_errors() {
        // a protocol run without prompts: new, set_config_option, an unknown model, resume of an unknown id, load
        let lines = real("opencode-8-lifecycle.jsonl");
        let mut a = Acp::new(opencode(), "/w/proj", None);
        a.start();
        let mut st = Step::default();
        for l in &lines[..2] {
            st.events.extend(a.on_line(l).events);
        }
        assert_eq!(s(of(&st.events, "session.info")[0], "agent_session"), "ses_e34bc851affeH2b2CqEwrigRFX");
        let w = written(&a.on_input(Input::Model { model: "opencode/beam-free".into() }).unwrap());
        assert_eq!(w[0]["method"], "session/set_config_option");
        assert_eq!(w[0]["params"], json!({"sessionId": "ses_e34bc851affeH2b2CqEwrigRFX", "configId": "model", "value": "opencode/beam-free"}));
        let mut st = Step::default();
        for l in &lines[2..4] {
            st.events.extend(a.on_line(l).events);
        }
        assert_eq!(of(&st.events, "session.info").iter().map(|e| s(e, "model")).collect::<Vec<_>>(), ["OpenCode/Beam Free"]);
        // an unknown model: a note under the chat, the model stays
        a.on_input(Input::Model { model: "opencode/no-such-model".into() }).unwrap();
        let mut st = Step::default();
        for l in &lines[4..6] {
            st.events.extend(a.on_line(l).events);
        }
        let err = of(&st.events, "session.error");
        assert_eq!(err.len(), 1);
        assert!(s(err[0], "message").contains("model not found"), "{err:?}");
        assert!(of(&st.events, "session.info").is_empty());
    }

    #[test]
    fn a_conversation_that_cannot_be_resumed_starts_a_new_one_and_says_so() {
        let lines = real("opencode-8-lifecycle.jsonl");
        let mut a = Acp::new(opencode(), "/w/proj", Some("ses_doesnotexist0000000000000"));
        a.start();
        let w = written(&a.on_line(&lines[0]));
        assert_eq!(w[0]["method"], "session/resume");
        // the real answer to resuming an id OpenCode does not know (line 6 of the run: -32603)
        let err = lines.iter().find(|l| l.contains("\"id\":5")).unwrap().replace("\"id\":5", &format!("\"id\":{}", w[0]["id"]));
        let st = a.on_line(&err);
        assert!(s(of(&st.events, "session.error")[0], "message").contains("could not continue"));
        assert_eq!(written(&st)[0]["method"], "session/new");
    }

    #[test]
    fn load_when_the_agent_cannot_resume_and_new_when_it_can_do_neither() {
        let init = |caps: Value| json!({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "agentCapabilities": caps}}).to_string();
        let mut a = Acp::new(opencode(), "/w", Some("ses_abc"));
        a.start();
        assert_eq!(written(&a.on_line(&init(json!({"loadSession": true}))))[0]["method"], "session/load");
        let mut a = Acp::new(opencode(), "/w", Some("ses_abc"));
        a.start();
        assert_eq!(written(&a.on_line(&init(json!({}))))[0]["method"], "session/new");
        // an id that is not one an agent reports is never sent
        let mut a = Acp::new(opencode(), "/w", Some("../x --flag"));
        a.start();
        assert_eq!(written(&a.on_line(&init(json!({"loadSession": true, "sessionCapabilities": {"resume": {}}}))))[0]["method"], "session/new");
    }

    #[test]
    fn signed_out_names_the_tables_login_line_not_the_agents() {
        // the survey's real Kimi answer to session/new (`-32000`), with a terminal-auth hint omher must not use
        let mut a = Acp::new(opencode(), "/w", None);
        a.start();
        a.on_line(r#"{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{},"authMethods":[{"id":"x","_meta":{"terminal-auth":{"command":"rm","args":["-rf","/"]}}}]}}"#);
        a.on_input(Input::send("hi")).unwrap();
        let st = a.on_line(r#"{"jsonrpc":"2.0","id":2,"error":{"code":-32000,"message":"Authentication required"}}"#);
        let want = "OpenCode is not signed in. Open Terminal and run `opencode auth login`, then Restart.";
        assert_eq!(s(of(&st.events, "session.error")[0], "message"), want);
        assert_eq!(s(of(&st.events, "turn.end")[0], "error"), want);
        assert!(!format!("{:?}", st.events).contains("-rf"));
        assert_eq!(a.explain("Error: provider authentication required"), want);
        assert_eq!(a.explain("boom"), "boom");
    }

    #[test]
    fn protocol_drift_unknown_updates_truncated_lines_and_two_objects_on_a_line() {
        let mut a = Acp::new(opencode(), "/w", None);
        a.start();
        a.on_line(&real("opencode-1-plain.jsonl")[0]);
        a.on_line(&real("opencode-1-plain.jsonl")[1]);
        a.on_input(Input::send("hi")).unwrap();
        let sid = "ses_e34e28c01ffeKlpLA61p3XV1cy";
        let upd = |u: Value| json!({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": u}}).to_string();
        // an unknown update kind, an unknown notification, a truncated line, garbage: nothing reaches the chat
        for l in [
            upd(json!({"sessionUpdate": "brand_new_kind", "x": 1})),
            r#"{"jsonrpc":"2.0","method":"_vendor/thing","params":{}}"#.to_string(),
            r#"{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"ses_e34e28c01ffeKlpLA61p3XV1cy","update":{"sessionUpdate":"agent_message_chu"#.to_string(),
            "not json".into(),
            "[1,2]".into(),
            r#"{"id":"77","result":{}}"#.into(),
        ] {
            let st = a.on_line(&l);
            assert!(st.events.is_empty() && st.write.is_empty(), "{l}: {st:?}");
        }
        // a blocking request omher does not know gets an error answer at once
        let st = a.on_line(r#"{"jsonrpc":"2.0","id":"x9","method":"fs/read_text_file","params":{"path":"/etc/passwd"}}"#);
        assert_eq!(written(&st)[0], json!({"jsonrpc": "2.0", "id": "x9", "error": {"code": -32601, "message": "not supported by omher"}}));
        assert!(st.events.is_empty());
        // two objects on one line, after a BOM, are both read
        let two = format!("\u{feff}{}{}", upd(json!({"sessionUpdate": "agent_message_chunk", "messageId": "m1", "content": {"type": "text", "text": "a"}})), upd(json!({"sessionUpdate": "agent_message_chunk", "messageId": "m1", "content": {"type": "text", "text": "b"}})));
        let st = a.on_line(&two);
        assert_eq!(st.events.iter().map(|e| s(e, "text")).collect::<Vec<_>>(), ["a", "b"]);
        // another session's updates (a helper's own) are not this chat's
        let other = json!({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "ses_other", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "x"}}}}).to_string();
        assert!(a.on_line(&other).events.is_empty());
        // a permission request that offers only "always" is refused, never shown as a card
        let st = a.on_line(r#"{"jsonrpc":"2.0","id":"p1","method":"session/request_permission","params":{"sessionId":"ses_e34e28c01ffeKlpLA61p3XV1cy","toolCall":{"toolCallId":"t","title":"x"},"options":[{"optionId":"always","kind":"allow_always","name":"Always allow"}]}}"#);
        assert!(st.events.is_empty());
        assert_eq!(written(&st)[0]["result"], json!({"outcome": {"outcome": "cancelled"}}));
    }

    /// The real OpenCode started exactly as omher starts it (`ChatSessions::start_agent("opencode", …)`: the
    /// allow-listed program found on PATH, `acp`, the ask rules built from its own `agent list`), with no prompt, so no model is
    /// called: the conversation opens with its models and commands, a model switch applies, the child carries the
    /// ask rule, and a second process continues `OMHER_REAL_OPENCODE_SESSION` (a conversation with a turn). Run
    /// with a scratch HOME and the scratch install first on PATH:
    /// `cargo test real_opencode_through_start_agent -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_opencode_through_start_agent() {
        use crate::agent_chat::{ChatOut, ChatSessions};
        use std::sync::{Arc, Mutex};
        use std::time::Duration;
        let dir = std::env::var("OMHER_REAL_OPENCODE_DIR").map(std::path::PathBuf::from).unwrap();
        type Out = Arc<Mutex<Vec<Value>>>;
        let wait = |out: &Out, cond: &dyn Fn(&[Value]) -> bool| {
            let deadline = std::time::Instant::now() + Duration::from_secs(60);
            while std::time::Instant::now() < deadline && !cond(&out.lock().unwrap()) {
                std::thread::sleep(Duration::from_millis(100));
            }
        };
        let open = |resume: Option<&str>| {
            let c = ChatSessions::default();
            let out: Out = Arc::new(Mutex::new(Vec::new()));
            let o = out.clone();
            let id = c
                .start_agent("opencode", &dir, resume, &[], None, move |x| {
                    if let ChatOut::Event(e) = x {
                        o.lock().unwrap().push(e)
                    }
                })
                .unwrap();
            wait(&out, &|ev: &[Value]| ev.iter().any(|e| s(e, "event") == "session.commands"));
            (c, id, out)
        };
        let (c, id, out) = open(None);
        let ev = out.lock().unwrap().clone();
        let sid = ev.iter().map(|e| s(e, "agent_session")).find(|x| !x.is_empty()).unwrap();
        let models = ev.iter().find(|e| s(e, "event") == "session.models").unwrap()["options"].as_array().unwrap().len();
        let cmds: Vec<String> = ev.iter().find(|e| s(e, "event") == "session.commands").unwrap()["commands"].as_array().unwrap().iter().map(|c| s(c, "name")).collect();
        println!("new: session {sid}, {models} models, commands {cmds:?}, model {:?}", ev.iter().map(|e| s(e, "model")).filter(|m| !m.is_empty()).collect::<Vec<_>>());
        assert!(sid.starts_with("ses_") && is_acp_session_id(&sid));
        // the child process carries the row's ask rule (ps shows a process's environment to its own user)
        let ps = std::process::Command::new("ps").args(["-E", "-ww", "-o", "command=", "-ax"]).output().unwrap();
        let ps = String::from_utf8_lossy(&ps.stdout);
        let line = ps.lines().find(|l| l.contains(" acp ") && l.contains("OPENCODE_CONFIG_CONTENT=")).unwrap_or("");
        let at = line.find("OPENCODE_CONFIG_CONTENT=").unwrap();
        println!("child env: {}…", &line[at..(at + 120).min(line.len())]);
        assert!(line[at..].starts_with(r#"OPENCODE_CONFIG_CONTENT={"agent":{"build":{"permission":{"bash *":{"#));
        assert!(!line.contains("OPENCODE_PERMISSION="));
        c.input(id, Input::Model { model: "opencode/beam-free".into() }).unwrap();
        wait(&out, &|ev: &[Value]| ev.iter().any(|e| s(e, "model") == "OpenCode/Beam Free"));
        assert!(out.lock().unwrap().iter().any(|e| s(e, "model") == "OpenCode/Beam Free"));
        println!("model switch: OpenCode/Beam Free");
        c.close(id);
        std::thread::sleep(Duration::from_millis(800));
        let earlier = std::env::var("OMHER_REAL_OPENCODE_SESSION").unwrap();
        let (c, id, out) = open(Some(&earlier));
        let ev = out.lock().unwrap().clone();
        let again = ev.iter().map(|e| s(e, "agent_session")).find(|x| !x.is_empty()).unwrap_or_default();
        println!("second process: session {again}; errors {:?}", ev.iter().filter(|e| s(e, "event") == "session.error").collect::<Vec<_>>());
        assert_eq!(again, earlier);
        assert!(!ev.iter().any(|e| s(e, "event") == "session.error"));
        c.close(id);
        std::thread::sleep(Duration::from_millis(800));
    }

    /// One real OpenCode turn through `ChatSessions::start_agent` for a person whose own OpenCode config says
    /// `"permission": {"bash": "deny"}` (put it in the scratch HOME's `~/.config/opencode/opencode.json` first): asked
    /// to run a command, OpenCode is refused by that rule inside omher (1.19.5 does not even offer the model its
    /// `bash` tool). A command never becomes an approval card, so the person cannot approve it by mistake, and it
    /// never runs. Edits still ask (each card is
    /// answered Deny here). With `"bash": "allow"` instead and `OMHER_REAL_OPENCODE_OWN_BASH=allow`, the same turn
    /// shows the command's card first. One model turn on a free model, no login:
    /// `OMHER_REAL_OPENCODE_DIR=<scratch folder> cargo test real_opencode_a_bash_deny_still_refuses -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_opencode_a_bash_deny_still_refuses() {
        use crate::agent_chat::{ChatOut, ChatSessions};
        use std::sync::{Arc, Mutex};
        use std::time::Duration;
        let dir = std::env::var("OMHER_REAL_OPENCODE_DIR").map(std::path::PathBuf::from).unwrap();
        let c = Arc::new(ChatSessions::default());
        let out: Arc<Mutex<Vec<Value>>> = Arc::new(Mutex::new(Vec::new()));
        let o = out.clone();
        let id = c
            .start_agent("opencode", &dir, None, &[], None, move |x| match x {
                ChatOut::Event(e) => o.lock().unwrap().push(e),
                ChatOut::Exit(code, err) => o.lock().unwrap().push(json!({"event": "exit", "code": code, "error": err})),
            })
            .unwrap();
        let wait = |cond: &dyn Fn(&[Value]) -> bool, secs: u64| {
            let deadline = std::time::Instant::now() + Duration::from_secs(secs);
            while std::time::Instant::now() < deadline && !cond(&out.lock().unwrap()) {
                std::thread::sleep(Duration::from_millis(200));
            }
        };
        wait(&|ev: &[Value]| ev.iter().any(|e| s(e, "event") == "session.commands"), 60);
        c.input(id, Input::send("Run this shell command with your bash tool and nothing else: echo denied > d.txt   If it is refused, do not try any other way; just reply refused.")).unwrap();
        let mut answered = 0;
        let deadline = std::time::Instant::now() + Duration::from_secs(240);
        while std::time::Instant::now() < deadline {
            let ev = out.lock().unwrap().clone();
            if ev.iter().any(|e| matches!(s(e, "event").as_str(), "turn.end" | "exit")) {
                break;
            }
            let cards = of(&ev, "approval.request");
            for card in &cards[answered..] {
                c.input(id, Input::Approve { request_id: s(card, "request_id"), choice: "deny".into() }).unwrap();
            }
            answered = cards.len();
            std::thread::sleep(Duration::from_millis(200));
        }
        let ev = out.lock().unwrap().clone();
        for e in &ev {
            if !matches!(s(e, "event").as_str(), "delta" | "thinking" | "session.models" | "session.commands") {
                println!("{e}");
            }
        }
        assert!(ev.iter().any(|e| s(e, "event") == "turn.end"), "the turn ended");
        let starts = of(&ev, "tool.start");
        let terminal: Vec<String> = starts.iter().filter(|e| s(e, "name") == "terminal").map(|e| s(e, "tool_id")).collect();
        let command_cards = of(&ev, "approval.request").iter().filter(|e| s(e, "title") == "Run this command?").count();
        println!("command steps tried: {}, command cards: {command_cards}", terminal.len());
        if std::env::var("OMHER_REAL_OPENCODE_OWN_BASH").as_deref() == Ok("allow") {
            // the contrast: the person's own `"bash": "allow"` asks inside omher (answered Deny here)
            assert!(command_cards >= 1, "an allowed command asks first");
        } else {
            // OpenCode 1.19.5 takes a tool whose last rule is a blanket deny away from the model, so it may never try
            assert_eq!(command_cards, 0, "a denied command never becomes a card");
        }
        for e in of(&ev, "tool.end").iter().filter(|e| terminal.contains(&s(e, "tool_id"))) {
            assert_eq!(e["ok"], false, "the command step was refused: {e}");
        }
        assert!(!dir.join("d.txt").exists(), "the command never ran");
        c.close(id);
        std::thread::sleep(Duration::from_millis(800));
    }

    #[test]
    fn json_objects_strips_a_bom_and_splits_joined_objects() {
        assert_eq!(json_objects("\u{feff}{\"a\":1}"), [json!({"a": 1})]);
        assert_eq!(json_objects("{\"a\":1}{\"b\":2}"), [json!({"a": 1}), json!({"b": 2})]);
        assert_eq!(json_objects("{\"a\":1} {\"b\":"), [json!({"a": 1})]);
        assert!(json_objects("").is_empty());
    }

    #[test]
    fn a_send_before_the_conversation_is_open_waits_and_stop_drops_it() {
        let mut a = Acp::new(opencode(), "/w", None);
        a.start();
        let st = a.on_input(Input::send("hi")).unwrap();
        assert!(st.write.is_empty());
        assert_eq!(names(&st.events), ["turn.start"]);
        assert!(a.on_input(Input::send("again")).is_err(), "one turn at a time");
        let st = a.on_input(Input::Interrupt).unwrap();
        assert!(st.write.is_empty());
        assert_eq!(names(&st.events), ["turn.end"]);
        assert!(a.on_input(Input::Interrupt).is_err());
        assert!(a.on_input(Input::Mode { mode: "plan".into() }).is_err());
        assert!(a.on_input(Input::Effort { effort: "high".into() }).is_err());
        assert!(a.on_input(Input::Send { text: "x".into(), images: vec![crate::agent_chat::Picture::from("/p.png".to_string())], id: String::new() }).is_err());
    }

    #[test]
    fn session_ids_are_letters_digits_dash_and_underscore() {
        for ok in ["ses_e34e28c01ffeKlpLA61p3XV1cy", "eee5079a-c52e-4526-b633-f3d8cb7d6394", "a"] {
            assert!(is_acp_session_id(ok), "{ok}");
        }
        for bad in ["", "../x", "ses x", "--yolo ", "a;b", "ses_é", &"a".repeat(129)] {
            assert!(!is_acp_session_id(bad), "{bad}");
        }
    }
}

//! One chat adapter for every agent that speaks the Agent Client Protocol (ACP: JSON-RPC 2.0, one object per
//! line on stdio), plus a table row per agent ([`ACP_AGENTS`]): OpenCode (`opencode acp`), Kilo Code (`kilo acp`),
//! Gemini CLI (`gemini --acp`), Qwen Code (`qwen --acp`), Kimi Code (`kimi acp`), Copilot CLI (`copilot --acp`) and
//! Cline (`cline --acp`).
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
//! - An agent that is not signed in (`-32000` on `session/new`) ends in one `session.error` of kind `signed_out`
//!   with the sign-in line from its row; omher never calls `authenticate` (Cline's opens a browser by itself).
//! - An unknown request from the agent gets a JSON-RPC error answer so the agent never waits on omher; unknown
//!   notifications, fields and lines are ignored and nothing raw reaches the chat.
//!
//! Checked against OpenCode 1.19.5 and Kilo Code 7.8.27 (`tests/fixtures/acp/opencode-*.jsonl`, `kilo-*.jsonl`,
//! recorded from real runs); Gemini CLI 0.68.0, Qwen Code 0.27.2, Kimi Code 2.6.0, Copilot CLI 1.0.110 and Cline
//! 3.0.74 up to their signed-out `session/new` (`<agent>-signed-out.jsonl`).

use std::collections::HashMap;
use std::time::Instant;

use serde_json::{json, Map, Value};

use crate::agent_chat::{last_line, Adapter, Event, Input, Step};

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
    /// The command a person runs in a terminal to sign the agent in, shown when it answers `-32000` (auth
    /// required). Fixed here: never the command the agent itself suggests, and omher never runs it.
    pub login: &'static str,
    /// The agent's own tool that loads a skill (its `tool_call` title), whose `rawInput.name` names the skill.
    pub skill_tool: Option<&'static str>,
    /// How the agent is made to ask before edits and shell commands without loosening a rule of the person's own
    /// (see [`RuleProbe`]); `None` adds nothing.
    pub rules: Option<RuleProbe>,
}

/// An agent whose own default runs tools without asking. Before the chat starts, the shell runs the agent's fixed
/// rule listing (`args`) in the session folder with the environment the chat gets, sets `var` to what `build` makes
/// of it, lists again with `var` set and starts the chat only when `kept` (first listing, rules, second listing) says
/// the agent took the rules as meant.
/// Anything else (the listing fails, times out or does not parse, the rules did not hold, or `var` is already set
/// in omher's own environment) refuses the chat with [`no_rules`].
#[derive(Debug)]
pub struct RuleProbe {
    pub args: &'static [&'static str],
    pub var: &'static str,
    pub build: fn(&str) -> Option<String>,
    pub kept: fn(&str, &str, &str) -> bool,
}

/// Why OpenCode did not start (the UI shows it translated, `ss.noRules`).
pub const NO_RULES: &str = "OpenCode did not start because omher could not confirm it would keep your own OpenCode permission rules.";

/// Why an agent with a [`RuleProbe`] did not start: [`NO_RULES`] for OpenCode, the same sentence for any other.
pub fn no_rules(label: &str) -> String {
    NO_RULES.replace("OpenCode", label)
}

pub const ACP_AGENTS: [AcpAgent; 7] = [
    AcpAgent {
        id: "opencode",
        label: "OpenCode",
        login: "opencode auth login",
        skill_tool: Some("skill"),
        rules: Some(RuleProbe { args: &["agent", "list"], var: "OPENCODE_CONFIG_CONTENT", build: opencode_ask, kept: opencode_kept }),
    },
    // Kilo Code is an OpenCode fork: the same rule listing, its own variable, and `code` as its default agent
    AcpAgent {
        id: "kilo",
        label: "Kilo Code",
        login: "kilo auth login",
        skill_tool: None,
        rules: Some(RuleProbe { args: &["agent", "list"], var: "KILO_CONFIG_CONTENT", build: kilo_ask, kept: kilo_kept }),
    },
    AcpAgent { id: "gemini", label: "Gemini CLI", login: "gemini", skill_tool: None, rules: None },
    AcpAgent { id: "qwen", label: "Qwen Code", login: "qwen", skill_tool: None, rules: None },
    AcpAgent { id: "kimi", label: "Kimi Code", login: "kimi login", skill_tool: None, rules: None },
    AcpAgent { id: "copilot", label: "Copilot CLI", login: "copilot login", skill_tool: None, rules: None },
    AcpAgent { id: "cline", label: "Cline", login: "cline auth", skill_tool: None, rules: None },
];

/// One UTF-16 unit as the agents' matcher compares it. On Windows (`fold`) the agents match without case, as a
/// JavaScript RegExp with the `i` flag does: a unit stands for its upper case when that is one unit too, and a unit
/// outside ASCII never stands for an ASCII one.
fn unit(u: u16, fold: bool) -> u16 {
    let Some(c) = char::from_u32(u32::from(u)).filter(|_| fold) else { return u };
    let mut upper = c.to_uppercase();
    match (upper.next(), upper.next()) {
        (Some(x), None) if x as u32 <= 0xFFFF && !(u >= 128 && (x as u32) < 128) => x as u16,
        _ => u,
    }
}

/// A text or a pattern as the agents' matcher reads it: UTF-16 units, `\\` read as `/`, and with `fold` (Windows)
/// without case. Two patterns with the same units are the same rule.
fn units(s: &str, fold: bool) -> Vec<u16> {
    s.encode_utf16().map(|u| if u == u16::from(b'\\') { u16::from(b'/') } else { unit(u, fold) }).collect()
}

/// The match itself, on [`units`]: `*` any run, `?` one unit, and a pattern ending in `" *"` also matches without
/// that tail.
fn glob(t: &[u16], p: &[u16]) -> bool {
    fn m(t: &[u16], p: &[u16]) -> bool {
        match p.split_first() {
            None => t.is_empty(),
            Some((42, rest)) => (0..=t.len()).any(|i| m(&t[i..], rest)),
            Some((63, rest)) => !t.is_empty() && m(&t[1..], rest),
            Some((c, rest)) => t.first() == Some(c) && m(&t[1..], rest),
        }
    }
    m(t, p) || (p.ends_with(&[32, 42]) && m(t, &p[..p.len() - 2]))
}

/// OpenCode's and Kilo Code's `permission` / `pattern` match (`Wildcard.match`, OpenCode 1.19.5 and Kilo 7.8.27,
/// the same file): `*` any run, `?` one UTF-16 unit, `\\` read as `/`, a pattern ending in `" *"` also matches
/// without that tail, and on Windows (`fold`) case does not count.
fn wildcard(text: &str, pattern: &str, fold: bool) -> bool {
    glob(&units(text, fold), &units(pattern, fold))
}

/// The tools omher's approval card stands for, and the key their ask rules go under. OpenCode files a write or a
/// patch under `edit`. The key is not the tool's own name, so OpenCode's config merge cannot fold these rules into
/// the person's own `bash` / `edit` entry (which would keep the person's key order and let their `"*": "allow"`
/// come after an ask); `"bash *"` matches `bash`. It also matches names beginning `bash `: extra denies
/// ([`guard_keys`]) keep those other permissions from becoming askable.
const ASKED: [(&str, &str); 2] = [("bash", "bash *"), ("edit", "edit *")];

/// Kilo Code's: OpenCode's two, and `write`, which Kilo's image tool asks under (its file tools ask under `edit`), each
/// under the tool's own key. Kilo 7.8.27 merges these after the person's own rules (checked against recorded configs,
/// `kilo-rules.json`); the `" *"` keys OpenCode needs would let Kilo's own plan-file allows outrank a person's
/// blanket deny.
const KILO_ASKED: [(&str, &str); 3] = [("bash", "bash"), ("edit", "edit"), ("write", "write")];

/// One agent of an `agent list` (its name and mode on one line, `name (mode)`, then its ruleset as JSON, where the
/// last matching rule decides).
struct Listed {
    name: String,
    /// `primary`, `subagent` or `all`: what the agent may be used as.
    mode: String,
    /// Per tool of `asked`: each pattern once at its last place with its action, in order. Patterns the agent's
    /// matcher reads as one ([`units`]) are one pattern.
    tools: Vec<Vec<(String, String)>>,
    /// Every rule (permission, pattern, action) under a key omher does not write (`asked`'s keys), in order, without
    /// the rules a later one replaces for every input: what decides every other permission.
    rest: Vec<(String, String, String)>,
    rules: Vec<(String, String, String)>,
}

/// `rules` without each one that a later rule replaces for every input: the later rule has the same permission key
/// or `*`, and the same pattern or `*`. Taking those out changes no decision.
fn effective(rules: Vec<(String, String, String)>) -> Vec<(String, String, String)> {
    let dead = |i: usize| rules[i + 1..].iter().any(|(p, q, _)| (p == "*" || *p == rules[i].0) && (q == "*" || *q == rules[i].1));
    (0..rules.len()).filter(|&i| !dead(i)).map(|i| rules[i].clone()).collect()
}

/// Every agent of what `agent list` printed, as the agent resolved it (`fold`: as it matches on Windows). `None` when the listing has no `primary`
/// agent (the default one: OpenCode's `build`, Kilo's `code`) or holds a line, a mode or a rule this does not know.
fn resolved(listing: &str, primary: &str, asked: &[(&str, &str)], fold: bool) -> Option<Vec<Listed>> {
    let mut agents: Vec<(String, String, String)> = Vec::new();
    for line in listing.lines() {
        let head = !line.starts_with([' ', '\t', '[', ']', '{', '}']) && line.ends_with(')') && line.contains(" (");
        if head {
            let at = line.rfind(" (")?;
            let mode = &line[at + 2..line.len() - 1];
            if !matches!(mode, "primary" | "subagent" | "all") {
                return None;
            }
            agents.push((line[..at].to_string(), mode.to_string(), String::new()));
        } else {
            let last = agents.last_mut()?;
            last.2.push_str(line);
            last.2.push('\n');
        }
    }
    if !agents.iter().any(|(n, _, _)| n == primary) {
        return None;
    }
    let mut out = Vec::new();
    for (name, mode, body) in agents {
        let listed: Vec<Value> = serde_json::from_str(&body).ok()?;
        let mut rules = Vec::new();
        for r in &listed {
            let (perm, pattern, action) = (r.get("permission")?.as_str()?, r.get("pattern")?.as_str()?, r.get("action")?.as_str()?);
            if !matches!(action, "allow" | "ask" | "deny") {
                return None;
            }
            rules.push((perm.to_string(), pattern.to_string(), action.to_string()));
        }
        let mut tools = Vec::new();
        for (tool, _) in asked {
            let mut seen: Vec<(String, String)> = Vec::new();
            for (perm, pattern, action) in rules.iter().rev() {
                if wildcard(tool, perm, fold) && !seen.iter().any(|(p, _)| units(p, fold) == units(pattern, fold)) {
                    seen.push((pattern.clone(), action.clone()));
                }
            }
            seen.reverse();
            tools.push(seen);
        }
        let rest = effective(rules.iter().filter(|(perm, _, _)| !asked.iter().any(|(_, key)| key == perm || guard_keys(key).contains(perm))).cloned().collect());
        out.push(Listed { name, mode, tools, rest, rules });
    }
    Some(out)
}

/// OpenCode's `bash *` key also matches names beginning `bash `, not just `bash`. Those are not the tool omher
/// asks about: deny them, rather than let its wildcard ask override a restriction for another permission. Kilo's
/// exact keys need no such guard. The two guards cover the empty suffix and every nonempty suffix.
fn guard_keys(key: &str) -> Vec<String> {
    key.strip_suffix(" *").map(|tool| vec![format!("{tool} "), format!("{tool} ?*")]).unwrap_or_default()
}

/// The guards are blanket denies, and no later non-deny could match their permission names. This also checks a
/// later config layer cannot undo them; conservative overlap is enough, and any uncertainty refuses the chat.
fn guards_kept(agent: &Listed, asked: &[(&str, &str)], fold: bool) -> bool {
    asked.iter().flat_map(|(_, key)| guard_keys(key)).all(|guard| {
        agent.rules.iter().rposition(|(p, q, a)| *p == guard && q == "*" && a == "deny").is_some_and(|at| {
            agent.rules[at + 1..].iter().all(|(p, _, a)| a == "deny" || !may_overlap(p, &guard, fold))
        })
    })

/// The ask rules for a chat, from what the agent's `agent list` printed without them: for every agent and each of
/// `asked`, the person's own resolved rules repeated after theirs, in the same order, with allow turned into ask.
/// What they allow asks, what asks still asks, what they deny stays denied, for blanket and pattern rules alike.
/// `None` also when the value would hold a config token ([`CONFIG_TOKENS`]).
fn ask_rules(listing: &str, primary: &str, asked: &[(&str, &str)], fold: bool) -> Option<String> {
    let q = |v: &str| Value::String(v.into()).to_string();
    let agents = resolved(listing, primary, asked, fold)?
        .iter()
        .map(|agent| {
            let tools = asked
                .iter()
                .zip(&agent.tools)
                .map(|((_, key), rules)| {
                    let pairs: Vec<String> = rules.iter().map(|(p, a)| format!("{}:{}", q(p), q(if a == "deny" { "deny" } else { "ask" }))).collect();
                    let mut entries = vec![format!("{}:{{{}}}", q(key), pairs.join(","))];
                    entries.extend(guard_keys(key).iter().map(|g| format!("{}:{{\"*\":\"deny\"}}", q(g))));
                    entries.join(",")
                })
                .collect::<Vec<_>>();
            format!("{}:{{\"permission\":{{{}}}}}", q(&agent.name), tools.join(","))
        })
        .collect::<Vec<_>>();
    let value = format!("{{\"agent\":{{{}}}}}", agents.join(","));
    // The agent replaces `{file:…}` and `{env:…}` (Kilo also writes them `${…}`) inside this value with a file's
    // content or a variable, though it left the same text literal in the project file it came from: no value at all
    // when an agent's name or a pattern holds the start of one, so the agent is not listed again with it.
    (!CONFIG_TOKENS.iter().any(|token| value.contains(token))).then_some(value)
}

/// How a reference to a file or to an environment variable starts in OpenCode's and Kilo Code's config text.
const CONFIG_TOKENS: [&str; 2] = ["{file:", "{env:"];

/// The two listings (`first` without `rules`, `listing` with them set) as far as omher's own rules cannot explain a
/// difference: `rules` is what `first` gives, both name the same agents in the same order, each with the same mode,
/// and every permission omher wrote no rule for is decided by the same rules ([`Listed::rest`]). `None` when any of
/// that differs: an agent appeared, went or changed mode, or a rule of the person's (their `webfetch` or
/// `external_directory` deny, say) is gone because the agent replaced their entry with omher's.
fn same_but_asked(first: &str, rules: &str, listing: &str, primary: &str, asked: &[(&str, &str)], fold: bool) -> Option<(Vec<Listed>, Vec<Listed>)> {
    let (before, after) = (resolved(first, primary, asked, fold)?, resolved(listing, primary, asked, fold)?);
    let same = ask_rules(first, primary, asked, fold).as_deref() == Some(rules)
        && before.len() == after.len()
        && before.iter().zip(&after).all(|(b, a)| b.name == a.name && b.mode == a.mode && b.rest == a.rest && guards_kept(a, asked, fold));
    same.then_some((before, after))
}

/// Whether the agent, listed again with `rules` set (`listing`), took them as meant: no agent lets any of `asked`
/// run unasked anywhere, and its rules are exactly the ones `rules` was built from. A later config layer that put
/// an allow back after them fails this, and the chat does not start.
fn rules_kept(rules: &str, listing: &str, primary: &str, asked: &[(&str, &str)], fold: bool) -> bool {
    no_allow(listing, primary, asked, fold) && ask_rules(listing, primary, asked, fold).as_deref() == Some(rules)
}

/// No agent of `listing` lets any of `asked` run unasked for any pattern.
fn no_allow(listing: &str, primary: &str, asked: &[(&str, &str)], fold: bool) -> bool {
    resolved(listing, primary, asked, fold).is_some_and(|agents| agents.iter().all(|a| a.tools.iter().flatten().all(|(_, a)| a != "allow")))
}

/// OpenCode's ask rules (`OPENCODE_CONFIG_CONTENT`) for `bash` and `edit`, from `opencode agent list`.
pub fn opencode_ask(listing: &str) -> Option<String> {
    opencode_ask_on(listing, cfg!(windows))
}

/// [`opencode_ask`] as OpenCode matches on Windows (`fold`) or elsewhere.
fn opencode_ask_on(listing: &str, fold: bool) -> Option<String> {
    ask_rules(listing, "build", &ASKED, fold)
}

/// Whether OpenCode kept [`opencode_ask`]'s rules: listed again it resolves exactly them for `bash` and `edit`, and
/// nothing else about any agent differs from the `first` listing ([`same_but_asked`]).
pub fn opencode_kept(first: &str, rules: &str, listing: &str) -> bool {
    opencode_kept_on(first, rules, listing, cfg!(windows))
}

/// [`opencode_kept`] as OpenCode matches on Windows (`fold`) or elsewhere.
fn opencode_kept_on(first: &str, rules: &str, listing: &str, fold: bool) -> bool {
    same_but_asked(first, rules, listing, "build", &ASKED, fold).is_some() && rules_kept(rules, listing, "build", &ASKED, fold)
}

/// Kilo Code's ask rules (`KILO_CONFIG_CONTENT`) for `bash`, `edit` and `write`, from `kilo agent list`.
pub fn kilo_ask(listing: &str) -> Option<String> {
    kilo_ask_on(listing, cfg!(windows))
}

/// [`kilo_ask`] as Kilo matches on Windows (`fold`) or elsewhere.
fn kilo_ask_on(listing: &str, fold: bool) -> Option<String> {
    ask_rules(listing, "code", &KILO_ASKED, fold)
}

/// A cheap, conservative disjointness proof for two glob languages. Different literal prefixes cannot
/// overlap. Anything less obvious is treated as overlapping (including `?` and the optional trailing `" *"`).
fn may_overlap(a: &str, b: &str, fold: bool) -> bool {
    let prefix = |p: &str| {
        let p = units(p, fold);
        let p = p.strip_suffix(&[32, 42]).unwrap_or(&p);
        p.split(|u| matches!(u, 42 | 63)).next().unwrap_or(&[]).to_vec()
    };
    let (a, b) = (prefix(a), prefix(b));
    a.starts_with(&b) || b.starts_with(&a)
}

/// Whether `p` is one of Kilo's own plan-file patterns: Markdown files right under a `plans` or `.plans` folder
/// named without a wildcard (Kilo on Windows writes the path with `\\`, which the matcher reads as `/`).
fn plan_file(p: &str, fold: bool) -> bool {
    let (p, at) = (units(p, fold), |s: &str| units(s, fold));
    (p == at("plans/*.md") || p == at(".plans/*.md") || p.ends_with(&at("/plans/*.md"))) && !p[..p.len() - 4].iter().any(|u| matches!(u, 42 | 63))
}

/// Prove a last-match ruleset cannot get weaker, without sampling inputs. Keep every original deny. Each new
/// non-deny must come from the same original pattern with an equal or stronger action, and every later original
/// restriction that may overlap it must still occur later. Reordering disjoint rules or moving denies later is
/// fine; an ordering we cannot prove safe refuses the chat. Missing rules default to ask, not allow. Patterns are
/// compared as the agent's matcher reads them ([`units`]: on Windows, `fold`, without case).
fn not_weaker(before: &[(String, String)], after: &[(String, String)], plan_edit: bool, fold: bool) -> bool {
    let rank = |a: &str| match a { "deny" => 0, "ask" => 1, _ => 2 };
    let same = |a: &str, b: &str| units(a, fold) == units(b, fold);
    // A later blanket rule shadows every earlier rule for every input, including Kilo's built-in allows.
    // Compare only the effective suffix; a new ask may also narrow the original blanket allow/ask.
    let before = &before[before.iter().rposition(|(p, _)| p == "*").unwrap_or(0)..];
    let after = &after[after.iter().rposition(|(p, _)| p == "*").unwrap_or(0)..];
    before.iter().filter(|(_, a)| a == "deny").all(|(p, _)| after.iter().any(|(q, a)| same(q, p) && a == "deny"))
        && after.iter().enumerate().all(|(j, (p, action))| {
            if action == "deny" { return true; }
            // Kilo's only unasked exception is the plan agent's own Markdown plan files, never arbitrary edits.
            if action == "allow" && !(plan_edit && plan_file(p, fold)) { return false; }
            let Some(i) = before.iter().position(|(q, _)| same(q, p)).or_else(|| before.iter().position(|(q, _)| q == "*")) else { return false };
            if rank(&before[i].1) < rank(action) { return false; }
            before[i + 1..].iter().all(|(q, restriction)| {
                rank(restriction) >= rank(action) || !may_overlap(p, q, fold)
                    || after[j + 1..].iter().any(|(r, a)| same(r, q) && rank(a) <= rank(restriction))
            })
        })
}

/// Kilo moves some denies and appends built-in plan-file rules. Prove the effective rules for every tool of
/// every agent are no weaker than the first listing; never turn a person's deny into an approval card. Unlike a
/// representative-input check this covers all strings, and fails closed when rule ordering is ambiguous. Every
/// other permission, and each agent's mode, must be what the first listing had ([`same_but_asked`]): Kilo reads a
/// person's `agent.build` entry as `code` and lets omher's `agent.code` replace it whole.
pub fn kilo_kept(first: &str, rules: &str, listing: &str) -> bool {
    kilo_kept_on(first, rules, listing, cfg!(windows))
}

/// [`kilo_kept`] as Kilo matches on Windows (`fold`) or elsewhere.
fn kilo_kept_on(first: &str, rules: &str, listing: &str, fold: bool) -> bool {
    same_but_asked(first, rules, listing, "code", &KILO_ASKED, fold).is_some_and(|(before, after)| {
        before.iter().zip(&after).all(|(b, a)| {
            KILO_ASKED.iter().enumerate().all(|(i, (tool, _))| not_weaker(&b.tools[i], &a.tools[i], b.name == "plan" && *tool == "edit", fold))
        })
    })
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
    /// the agent refused to open a conversation because it is not signed in: nothing more can be sent
    signed_out: bool,
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
            signed_out: false,
        }
    }

    fn call(&mut self, st: &mut Step, what: Call, method: &str, params: Value) -> u64 {
        self.seq += 1;
        self.calls.insert(self.seq, what);
        out(st, json!({"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params}));
        self.seq
    }

    fn signed_out(&self) -> String {
        format!("{} is not signed in. Run `{}` in a terminal and sign in.", self.agent.label, self.agent.login)
    }

    /// The turn's end for an agent that is not signed in: the one line, and what the UI needs to say it in the
    /// person's language (the agent's sign-in command from its row).
    fn end_signed_out(&mut self, st: &mut Step) {
        let e = self.signed_out();
        self.queued.clear();
        self.end(st, "error", Some(e));
        if let Some(last) = st.events.last_mut().filter(|e| s(e, "event") == "turn.end") {
            last["signed_out"] = Value::Bool(true);
            last["login"] = Value::String(self.agent.login.into());
        }
    }

    /// Whether an error the agent answered says it needs a sign-in: `-32000`, or a message that says so (Kilo Code
    /// answers a prompt to a model that needs its account with `-32603 "… You need to sign in to use this model."`).
    fn needs_sign_in(code: i64, msg: &str) -> bool {
        let low = msg.to_ascii_lowercase();
        code == -32000 || low.contains("sign in to use") || low.contains("authentication required")
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
            // Kilo Code's permission request names it `filepath`
            "patch" | "read_file" => pick("filePath").or_else(|| pick("path")).or_else(|| pick("file_path")).or_else(|| pick("filepath")).map(|p| rel(&p, &self.cwd)),
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
                    // one plain line built from the row, never the agent's own text or its `authenticate`: the shell
                    // ends the session, and the person signs in in a terminal
                    self.signed_out = true;
                    emit(st, ev("session.error", json!({"kind": "signed_out", "message": self.signed_out(), "login": self.agent.login})));
                    if self.turn {
                        self.end_signed_out(st);
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
                Call::Prompt if Acp::needs_sign_in(code, &msg) => self.end_signed_out(st),
                Call::Prompt => self.end(st, "error", Some(msg)),
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
        last_line(err).to_string()
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
                if self.signed_out {
                    return Err(self.signed_out());
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

/// Each agent's rules for the tools in `asked` (permission, pattern, action), in order, from an `agent list`.
fn rulesets(listing: &str, asked: &[(&str, &str)]) -> Option<Vec<(String, Vec<(String, String, String)>)>> {
    let mut agents: Vec<(String, String)> = Vec::new();
    for line in listing.lines() {
        if !line.starts_with([' ', '\t', '[', ']', '{', '}']) && line.ends_with(')') && line.contains(" (") {
            agents.push((line[..line.rfind(" (")?].to_string(), String::new()));
        } else {
            let last = agents.last_mut()?;
            last.1.push_str(line);
            last.1.push('\n');
        }
    }
    agents
        .into_iter()
        .map(|(name, body)| {
            let rules: Vec<Value> = serde_json::from_str(&body).ok()?;
            let mut out = Vec::new();
            for r in &rules {
                let (perm, pattern, action) = (r.get("permission")?.as_str()?, r.get("pattern")?.as_str()?, r.get("action")?.as_str()?);
                if asked.iter().any(|(t, _)| wildcard(t, perm, false)) {
                    out.push((perm.to_string(), pattern.to_string(), action.to_string()));
                }
            }
            Some((name, out))
        })
        .collect()
}

/// What an agent decides for `tool` on `input` under `rules` (the last rule whose permission and pattern match, else
/// ask), as OpenCode and Kilo evaluate.
fn decide(rules: &[(String, String, String)], tool: &str, input: &str) -> &'static str {
    decide_on(rules, tool, input, false)
}

/// [`decide`] as the agents match on Windows (`fold`) or elsewhere.
fn decide_on(rules: &[(String, String, String)], tool: &str, input: &str, fold: bool) -> &'static str {
    match rules.iter().rev().find(|(p, pat, _)| wildcard(tool, p, fold) && wildcard(input, pat, fold)).map(|r| r.2.as_str()) {
        Some("allow") => "allow",
        Some("deny") => "deny",
        _ => "ask",
    }
}



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
        rules.iter().rev().find(|r| wildcard(tool, &s(r, "permission"), false) && wildcard(input, &s(r, "pattern"), false)).map(|r| s(r, "action")).unwrap_or_else(|| "ask".into())
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
        assert!(opencode_kept(&base, &rules, &in_omher), "{case}");
        assert!(!opencode_kept(&base, &rules, &base), "{case}: without the rules OpenCode runs tools unasked");
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
        assert!(!opencode_kept(&base, &rules, &base));
        assert!(!opencode_kept(&base, &rules, ""));
    }

    #[test]
    fn wildcard_matches_as_opencode_does() {
        let wildcard = |t: &str, p: &str| wildcard(t, p, false);
        assert!(wildcard("bash", "*") && wildcard("bash", "bash") && wildcard("bash", "bash *") && wildcard("bash", "ba?h"));
        assert!(wildcard("rm -rf x", "rm *") && wildcard("rm", "rm *") && !wildcard("rmdir x", "rm *"));
        assert!(!wildcard("bash", "edit *") && !wildcard("bashful", "bash *"));
        assert!(wildcard("a\\b.md", "a/*.md"));
    }

    /// omher's matcher against the agents' own (`wildcard-match.json`: Kilo Code 7.8.27's `Wildcard.match`, the same
    /// file as OpenCode 1.19.5's, run with the platform set to macOS and to Windows): the same answer for every
    /// recorded text and pattern, with and without Windows' case folding.
    #[test]
    fn wildcard_matches_as_the_agents_do_on_windows_and_elsewhere() {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("acp").join("wildcard-match.json");
        let all: Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
        let cases = all["cases"].as_array().unwrap();
        assert!(cases.len() >= 300 && cases.iter().filter(|c| c[2] != c[3]).count() >= 40, "{}", cases.len());
        for c in cases {
            let (text, pattern) = (c[0].as_str().unwrap(), c[1].as_str().unwrap());
            assert_eq!(wildcard(text, pattern, false), c[2], "{text:?} against {pattern:?} off Windows");
            assert_eq!(wildcard(text, pattern, true), c[3], "{text:?} against {pattern:?} on Windows");
        }
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

    /// Each of the five agents without a free model, as recorded on a Mac where nobody signed it in (scratch HOME):
    /// its real `initialize`, then its real `-32000` to `session/new`. The person sees one line with the row's sign-in
    /// command, the session is marked signed out (the UI ends it), nothing raw reaches the chat, `authenticate` is
    /// never sent, and a second message is refused with the same line.
    #[test]
    fn real_signed_out_agents_end_in_one_line_with_their_own_sign_in() {
        for (id, file, line, raw) in [
            ("gemini", "gemini-signed-out.jsonl", "Gemini CLI is not signed in. Run `gemini` in a terminal and sign in.", "Gemini API key is missing"),
            ("qwen", "qwen-signed-out.jsonl", "Qwen Code is not signed in. Run `qwen` in a terminal and sign in.", "Use /auth"),
            ("kimi", "kimi-signed-out.jsonl", "Kimi Code is not signed in. Run `kimi login` in a terminal and sign in.", "--login"),
            ("copilot", "copilot-signed-out.jsonl", "Copilot CLI is not signed in. Run `copilot login` in a terminal and sign in.", "copilot-darwin-arm64"),
            ("cline", "cline-signed-out.jsonl", "Cline is not signed in. Run `cline auth` in a terminal and sign in.", "Call authenticate"),
        ] {
            let mut a = Acp::new(acp_agent(id).unwrap(), "/w/proj", None);
            // the person's first message goes in at once, as a draft's first send does; the conversation never opens
            let mut st = a.start();
            st.events.extend(a.on_input(Input::send("Add a dark mode toggle")).unwrap().events);
            for l in real(file) {
                let s2 = a.on_line(&l);
                st.write.extend(s2.write);
                st.events.extend(s2.events);
            }
            let w = written(&st);
            assert_eq!(w.iter().map(|x| s(x, "method")).collect::<Vec<_>>(), ["initialize", "session/new"], "{id}");
            assert!(!w.iter().any(|x| s(x, "method") == "authenticate"), "{id}");
            let err = of(&st.events, "session.error");
            assert_eq!(err.len(), 1, "{id}");
            assert_eq!((s(err[0], "kind"), s(err[0], "message"), s(err[0], "login")), ("signed_out".to_string(), line.to_string(), acp_agent(id).unwrap().login.to_string()), "{id}");
            let end = of(&st.events, "turn.end");
            assert_eq!((s(end[0], "outcome"), s(end[0], "error")), ("error".to_string(), line.to_string()), "{id}");
            assert_eq!(end[0]["signed_out"], true, "{id}");
            one_clean_turn(&st.events);
            // never the agent's own words, its JSON or its terminal-auth command
            let all = format!("{:?}", st.events);
            assert!(!all.contains("-32000") && !all.contains(raw), "{id}: {all}");
            assert_eq!(a.on_input(Input::send("again")).unwrap_err(), line, "{id}");
        }
    }

    /// Kilo Code 7.8.27 opens a conversation without a sign-in (scratch HOME): its real `session/new` with 407 models,
    /// flat; omher lists every one with its own name, and the current one is the model shown.
    #[test]
    fn real_kilo_new_lists_its_407_models() {
        let mut a = Acp::new(acp_agent("kilo").unwrap(), "/w/proj", None);
        let mut st = Step::default();
        a.start();
        for l in real("kilo-1-new.jsonl") {
            let s2 = a.on_line(&l);
            st.events.extend(s2.events);
            st.write.extend(s2.write);
        }
        assert_eq!(s(of(&st.events, "session.info")[0], "agent_session"), "ses_e2d9961a8ffe6pwTlM4aAUbsu1");
        let models = of(&st.events, "session.models")[0]["options"].as_array().unwrap().clone();
        assert_eq!(models.len(), 407);
        assert!(models.iter().any(|m| m == &json!({"id": "kilo/kilo-auto/free", "label": "Kilo Gateway/Auto Free", "detail": ""})));
        assert_eq!(of(&st.events, "session.info").iter().map(|e| s(e, "model")).find(|m| !m.is_empty()).unwrap(), "Kilo Gateway/Google: Nano Banana Pro (Gemini 3 Pro Image)");
        assert!(!of(&st.events, "session.commands")[0]["commands"].as_array().unwrap().is_empty());
        // continued by session/resume (it offers resume and load)
        let mut b = Acp::new(acp_agent("kilo").unwrap(), "/w/proj", Some("ses_e2d9961a8ffe6pwTlM4aAUbsu1"));
        b.start();
        assert_eq!(written(&b.on_line(&real("kilo-1-new.jsonl")[0]))[0]["method"], "session/resume");
    }

    /// A real Kilo Code write on its free model (`kilo/kilo-auto/free`, no sign-in, scratch HOME): one step, the card
    /// with Deny and Allow once (Kilo offers once / always / reject), answered once; Kilo also asks omher to write the
    /// file (`fs/write_text_file`, though omher said at `initialize` it offers no file writing), omher refuses, and
    /// Kilo writes it with its own tool.
    #[test]
    fn real_kilo_2_a_write_asks_and_allow_once_writes() {
        let lines = real("kilo-2-write-once.jsonl");
        let mut a = Acp::new(acp_agent("kilo").unwrap(), "/w/proj", None);
        let mut all = a.start();
        let feed = |a: &mut Acp, l: &str, all: &mut Step| {
            let st = a.on_line(l);
            all.write.extend(st.write);
            for e in st.events {
                if s(&e, "event") == "approval.request" {
                    let w = a.on_input(Input::Approve { request_id: s(&e, "request_id"), choice: "once".into() }).unwrap();
                    all.write.extend(w.write);
                }
                all.events.push(e);
            }
        };
        feed(&mut a, &lines[0], &mut all);
        feed(&mut a, &lines[1], &mut all);
        all.write.extend(a.on_input(Input::Model { model: "kilo/kilo-auto/free".into() }).unwrap().write);
        feed(&mut a, &lines[2], &mut all);
        let w = a.on_input(Input::send("Use your write tool to create the file hello3.txt containing hi, then reply done.")).unwrap();
        all.write.extend(w.write);
        all.events.extend(w.events);
        for l in &lines[3..] {
            feed(&mut a, l, &mut all);
        }
        one_clean_turn(&all.events);
        let card = of(&all.events, "approval.request")[0];
        assert_eq!(card["choices"], json!(["deny", "once"]));
        assert_eq!(s(card, "title"), "Allow Kilo Code to change hello3.txt?");
        let w = written(&all);
        assert!(w.iter().any(|x| x["id"] == 0 && x["result"] == json!({"outcome": {"outcome": "selected", "optionId": "once"}})));
        // omher writes nothing for it
        assert!(w.iter().any(|x| x["id"] == 1 && x["error"]["code"] == -32601));
        let tools: Vec<(String, String)> = of(&all.events, "tool.start").iter().map(|e| (s(e, "name"), s(e, "detail"))).collect();
        assert_eq!(tools, [("patch".to_string(), "hello3.txt".to_string())]);
        assert_eq!(of(&all.events, "tool.end")[0]["ok"], true);
        assert_eq!(of(&all.events, "message").iter().map(|e| s(e, "text").trim().to_string()).collect::<Vec<_>>(), ["done"]);
        assert_eq!(s(of(&all.events, "turn.end")[0], "outcome"), "done");
    }

    /// A Kilo Code prompt to a model that needs Kilo's account answers `-32603 "Internal error: You need to sign in to
    /// use this model."` (recorded): the turn ends with the sign-in line, not that text.
    #[test]
    fn kilo_a_model_that_needs_its_account_says_sign_in() {
        let mut a = Acp::new(acp_agent("kilo").unwrap(), "/w/proj", None);
        a.start();
        for l in &real("kilo-1-new.jsonl")[..2] {
            a.on_line(l);
        }
        a.on_input(Input::send("hi")).unwrap();
        let st = a.on_line(r#"{"jsonrpc":"2.0","id":3,"error":{"code":-32603,"message":"Internal error: You need to sign in to use this model.","data":{"service":"session","errorName":"APIError"}}}"#);
        let end = of(&st.events, "turn.end");
        assert_eq!(s(end[0], "error"), "Kilo Code is not signed in. Run `kilo auth login` in a terminal and sign in.");
        assert_eq!(end[0]["signed_out"], true);
        // the conversation itself is open: the next message goes out (another model may need no account)
        assert!(a.on_input(Input::send("again")).is_ok());
    }

    /// `kilo agent list` from Kilo Code 7.8.27 (scratch HOME, `kilo-rules.json`, trimmed to the agents `code`, `explore`
    /// and `plan` and the rules for `bash`, `edit`, `write` and `*`) for one person's config.
    fn kilo_case(case: &str) -> (String, String, String) {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("acp").join("kilo-rules.json");
        let all: Value = serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap();
        let c = &all[case];
        (s(c, "agent_list"), s(c, "agent_list_in_omher"), s(c, "env_sent"))
    }

    #[test]
    fn kilo_rule_proof_keeps_every_restriction_in_small_glob_rulesets() {
        let patterns = ["*", "a*", "ab", "?b", "a *"];
        let actions = ["deny", "ask", "allow"];
        let mut sets = Vec::new();
        for p in patterns { for q in patterns { if p != q {
            for a in actions { for b in actions {
                sets.push(vec![(p.to_string(), a.to_string()), (q.to_string(), b.to_string())]);
            } }
        } } }
        let rank = |a: &str| match a { "deny" => 0, "ask" => 1, _ => 2 };
        for b in &sets { for a in &sets { if not_weaker(b, a, false, false) {
            let rules = |r: &Vec<(String, String)>| r.iter().map(|(p, a)| ("bash".into(), p.clone(), a.clone())).collect::<Vec<_>>();
            for input in ["", "a", "b", "aa", "ab", "ba", "bb", "aaa", "a b", "abc"] {
                let (was, now) = (decide(&rules(b), "bash", input), decide(&rules(a), "bash", input));
                assert!(rank(now) <= rank(was) && now != "allow", "{b:?} -> {a:?} on {input:?}");
            }
        } } }
        // Losing a deny falls back to ask, which is still a weakening; plan is not a blanket edit exception.
        assert!(!not_weaker(&vec![("*".into(), "deny".into())], &[], false, false));
        assert!(!not_weaker(&vec![("*.rs".into(), "allow".into())], &vec![("*.rs".into(), "allow".into())], true, false));
    }

    #[test]
    fn kilo_rule_verifier_rejects_an_unsampled_hole_in_a_deny() {
        let first = "code (primary)\n[{\"permission\":\"*\",\"pattern\":\"*\",\"action\":\"deny\"}]\n";
        let after = "code (primary)\n[{\"permission\":\"*\",\"pattern\":\"*\",\"action\":\"deny\"},{\"permission\":\"bash\",\"pattern\":\"rm *\",\"action\":\"ask\"},{\"permission\":\"bash\",\"pattern\":\"rm x\",\"action\":\"deny\"}]\n";
        let rules = kilo_ask(first).unwrap();
        assert_eq!(decide(&rulesets(first, &KILO_ASKED).unwrap()[0].1, "bash", "rm private"), "deny");
        assert_eq!(decide(&rulesets(after, &KILO_ASKED).unwrap()[0].1, "bash", "rm private"), "ask");
        assert!(!kilo_kept(first, &rules, after), "checking only rm x misses rm private");
    }

    /// One rule of a listing, as the agents print it.
    fn rule(permission: &str, pattern: &str, action: &str) -> String {
        json!({"permission": permission, "pattern": pattern, "action": action}).to_string()
    }

    /// A listing: each agent's `name (mode)` line, then its rules.
    fn listing(agents: &[(&str, &[String])]) -> String {
        agents.iter().map(|(head, rules)| {
            let mut rules = rules.to_vec();
            for key in ["bash *", "edit *"] {
                if rules.iter().any(|r| serde_json::from_str::<Value>(r).unwrap()["permission"] == key) {
                    rules.extend(guard_keys(key).iter().map(|g| rule(g, "*", "deny")));
                }
            }
            format!("{head}\n[{}]\n", rules.join(","))
        }).collect()
    }

    /// Kilo reads a person's `agent.build` entry as `code`, and omher's `agent.code` then replaces it whole: their
    /// denies for permissions omher writes no rule for are gone from the second listing (seen with Kilo 7.8.27).
    #[test]
    fn kilo_kept_refuses_when_a_deny_outside_bash_edit_write_is_lost() {
        let first = listing(&[("code (primary)", &[rule("*", "*", "allow"), rule("external_directory", "*", "deny"), rule("webfetch", "*", "deny")])]);
        let rules = kilo_ask(&first).unwrap();
        // what Kilo lists again once omher's agent.code has replaced the person's agent.build entry
        let after = listing(&[("code (primary)", &[rule("*", "*", "allow"), rule("bash", "*", "ask"), rule("edit", "*", "ask"), rule("write", "*", "ask")])]);
        assert!(!kilo_kept(&first, &rules, &after), "the person's external_directory and webfetch denies are gone");
        // with those two denies still there, the same rules start
        let held = listing(&[("code (primary)", &[rule("*", "*", "allow"), rule("external_directory", "*", "deny"), rule("webfetch", "*", "deny"), rule("bash", "*", "ask"), rule("edit", "*", "ask"), rule("write", "*", "ask")])]);
        assert!(kilo_kept(&first, &rules, &held));
    }

    /// Any permission of any agent: a pattern deny under `read`, a `task` and a `skill` deny, in a subagent too; a
    /// deny that only moved in front of the allow it used to follow; an allow put back for another permission.
    #[test]
    fn a_weaker_rule_for_any_other_permission_refuses_for_both_agents() {
        type Ask = fn(&str) -> Option<String>;
        type Kept = fn(&str, &str, &str) -> bool;
        let keys: [(&str, Ask, Kept, &[&str]); 2] = [("code", kilo_ask, kilo_kept, &["bash", "edit", "write"]), ("build", opencode_ask, opencode_kept, &["bash *", "edit *"])];
        for (primary, ask, kept, keys) in keys {
            let head = format!("{primary} (primary)");
            let person = [rule("*", "*", "allow"), rule("read", "*", "allow"), rule("read", "*.pem", "deny"), rule("task", "*", "deny"), rule("skill", "*", "deny")];
            let helper = [rule("*", "*", "deny"), rule("grep", "*", "allow")];
            let first = listing(&[(&head, &person), ("helper (subagent)", &helper)]);
            let rules = ask(&first).unwrap();
            // the second listing: what each agent had, then omher's own rules (ask for the person's allow, deny for
            // the subagent's deny)
            let own = |action: &str| keys.iter().map(|k| rule(k, "*", action)).collect::<Vec<_>>();
            let with = |main: &[String], sub: &[String]| listing(&[(&head, &[main, &own("ask")].concat()), ("helper (subagent)", &[sub, &own("deny")].concat())]);
            assert!(kept(&first, &rules, &with(&person, &helper)), "{primary}: nothing else changed");
            let without = |i: usize| person.iter().enumerate().filter(|(j, _)| *j != i).map(|(_, r)| r.clone()).collect::<Vec<_>>();
            for (what, main, sub) in [
                ("the read *.pem deny is gone", without(2), helper.to_vec()),
                ("the task deny is gone", without(3), helper.to_vec()),
                ("the skill deny became ask", [&person[..], &[rule("skill", "*", "ask")]].concat(), helper.to_vec()),
                ("the read deny moved in front of its allow", vec![person[0].clone(), person[2].clone(), person[1].clone(), person[3].clone(), person[4].clone()], helper.to_vec()),
                ("webfetch is allowed for the subagent", person.to_vec(), [&helper[..], &[rule("webfetch", "*", "allow")]].concat()),
                ("the subagent's blanket deny is gone", person.to_vec(), vec![helper[1].clone()]),
            ] {
                assert!(!kept(&first, &rules, &with(&main, &sub)), "{primary}: {what}");
            }
            // a rule a later one replaces for every input is no difference: Kilo lists such rules twice
            let twice = [&person[..], &[rule("task", "*", "ask"), rule("*", "*", "allow")], &person[..]].concat();
            assert!(kept(&first, &rules, &with(&twice, &helper)), "{primary}: a replaced rule changes nothing");
        }
    }

    /// OpenCode's injected `bash *` and `edit *` keys also match other permission names starting with `bash ` or
    /// `edit `. A deny for such a name need not match the tool omher resolves: fixed suffix denies keep those
    /// permissions denied too, and a listing without those guards refuses. Check every permission, not only tools.
    #[test]
    fn opencode_does_not_shadow_a_deny_for_another_permission_matching_its_key() {
        for fold in [false, true] {
            for permission in ["bash x", "bash?x", "edit other", "edit?other"] {
                let person = [rule("*", "*", "allow"), rule(permission, "*", "deny")];
                let first = listing(&[("build (primary)", &person)]);
                let rules = opencode_ask_on(&first, fold).unwrap();
                let after = listing(&[("build (primary)", &[&person[..], &[rule("bash *", "*", "ask"), rule("edit *", "*", "ask")]].concat())]);
                assert!(opencode_kept_on(&first, &rules, &after, fold), "{permission}, folding {fold}");
                let unguarded = after.lines().map(|line| if line.starts_with('[') {
                    let rs: Vec<Value> = serde_json::from_str(line).unwrap();
                    serde_json::to_string(&rs.into_iter().filter(|r| !["bash ", "bash ?*", "edit ", "edit ?*"].contains(&r["permission"].as_str().unwrap())).collect::<Vec<_>>()).unwrap()
                } else { line.to_string() }).collect::<Vec<_>>().join("\n");
                assert!(!opencode_kept_on(&first, &rules, &unguarded, fold));
            }
        }
    }

    /// With Kilo's `references` an agent the person named became `all` (one they can be put in) where it was a
    /// `subagent`, and lost its denies: any agent whose mode differs between the listings refuses.
    #[test]
    fn kilo_kept_refuses_an_agent_changing_mode() {
        let body = [rule("*", "*", "deny")];
        let first = listing(&[("code (primary)", &body), ("mylib (subagent)", &body)]);
        let rules = kilo_ask(&first).unwrap();
        let own = [rule("*", "*", "deny"), rule("bash", "*", "deny"), rule("edit", "*", "deny"), rule("write", "*", "deny")];
        assert!(kilo_kept(&first, &rules, &listing(&[("code (primary)", &own), ("mylib (subagent)", &own)])));
        assert!(!kilo_kept(&first, &rules, &listing(&[("code (primary)", &own), ("mylib (all)", &own)])));
        assert!(!kilo_kept(&first, &rules, &listing(&[("code (primary)", &body), ("mylib (all)", &body)])));
        // OpenCode's check reads the mode too
        let first = listing(&[("build (primary)", &body), ("mylib (subagent)", &body)]);
        let rules = opencode_ask(&first).unwrap();
        let own = [rule("*", "*", "deny"), rule("bash *", "*", "deny"), rule("edit *", "*", "deny")];
        assert!(opencode_kept(&first, &rules, &listing(&[("build (primary)", &own), ("mylib (subagent)", &own)])));
        assert!(!opencode_kept(&first, &rules, &listing(&[("build (primary)", &own), ("mylib (all)", &own)])));
        assert!(!opencode_kept(&first, &rules, &listing(&[("build (primary)", &own), ("mylib (primary)", &own)])));
    }

    /// An agent that is in one listing only refuses, and so does an agent in another place.
    #[test]
    fn an_agent_that_appears_or_disappears_refuses() {
        for (primary, ask, kept, own) in [
            ("code", kilo_ask as fn(&str) -> Option<String>, kilo_kept as fn(&str, &str, &str) -> bool, vec![rule("*", "*", "deny"), rule("bash", "*", "deny"), rule("edit", "*", "deny"), rule("write", "*", "deny")]),
            ("build", opencode_ask, opencode_kept, vec![rule("*", "*", "deny"), rule("bash *", "*", "deny"), rule("edit *", "*", "deny")]),
        ] {
            let head = format!("{primary} (primary)");
            let body = [rule("*", "*", "deny")];
            let first = listing(&[(&head, &body), ("mine (subagent)", &body)]);
            let rules = ask(&first).unwrap();
            assert!(kept(&first, &rules, &listing(&[(&head, &own), ("mine (subagent)", &own)])), "{primary}");
            assert!(!kept(&first, &rules, &listing(&[(&head, &own)])), "{primary}: mine is gone");
            assert!(!kept(&first, &rules, &listing(&[(&head, &own), ("mine (subagent)", &own), ("other (subagent)", &own)])), "{primary}: other appeared");
            assert!(!kept(&first, &rules, &listing(&[(&head, &own), ("other (subagent)", &own)])), "{primary}: another name");
            assert!(!kept(&first, &rules, &listing(&[("mine (subagent)", &own), (&head, &own)])), "{primary}: another order");
        }
    }

    /// A mode this does not know refuses at the first listing; an agent the person made themselves, with a mode the
    /// agents have, starts when nothing about it changes.
    #[test]
    fn an_unknown_agent_or_mode_refuses() {
        let body = [rule("*", "*", "allow")];
        let unknown = listing(&[("code (primary)", &body), ("never-heard-of (some-new-mode)", &body)]);
        assert_eq!(kilo_ask(&unknown), None);
        assert_eq!(opencode_ask(&unknown.replace("code (primary)", "build (primary)")), None);
        for mode in ["primary", "subagent", "all"] {
            let head = format!("reviewer (v2) ({mode})");
            let first = listing(&[("code (primary)", &body), (&head, &[rule("*", "*", "deny"), rule("read", "*", "allow")])]);
            let rules = kilo_ask(&first).unwrap();
            assert!(rules.contains(r#""reviewer (v2)":{"permission":{"bash":{"*":"deny"},"edit":{"*":"deny"},"write":{"*":"deny"}}}"#), "{rules}");
            let own = [rule("bash", "*", "ask"), rule("edit", "*", "ask"), rule("write", "*", "ask")];
            let denied = [rule("bash", "*", "deny"), rule("edit", "*", "deny"), rule("write", "*", "deny")];
            let after = listing(&[("code (primary)", &[&body[..], &own].concat()), (&head, &[&[rule("*", "*", "deny"), rule("read", "*", "allow")][..], &denied].concat())]);
            assert!(kilo_kept(&first, &rules, &after), "{mode}: a person's own agent starts");
        }
    }

    /// On Windows OpenCode and Kilo match a permission key without case, so `"Bash": "deny"` there denies the tool
    /// `bash`: omher repeats it as a deny, not as the ask of the `*` allow under it. Elsewhere that key names no tool.
    #[test]
    fn a_capitalised_permission_key_is_a_bash_rule_on_windows() {
        let person = [rule("*", "*", "allow"), rule("Bash", "*", "deny"), rule("Edit", "*", "allow"), rule("Edit", "*.key", "deny")];
        let first = listing(&[("build (primary)", &person)]);
        let rules = opencode_ask_on(&first, true).unwrap();
        assert_eq!(rules, r#"{"agent":{"build":{"permission":{"bash *":{"*":"deny"},"bash ":{"*":"deny"},"bash ?*":{"*":"deny"},"edit *":{"*":"ask","*.key":"deny"},"edit ":{"*":"deny"},"edit ?*":{"*":"deny"}}}}}"#);
        assert_eq!(opencode_ask_on(&first, false).unwrap(), r#"{"agent":{"build":{"permission":{"bash *":{"*":"ask"},"bash ":{"*":"deny"},"bash ?*":{"*":"deny"},"edit *":{"*":"ask"},"edit ":{"*":"deny"},"edit ?*":{"*":"deny"}}}}}"#);
        let own = |fold: bool| if fold { vec![rule("bash *", "*", "deny"), rule("edit *", "*", "ask"), rule("edit *", "*.key", "deny")] } else { vec![rule("bash *", "*", "ask"), rule("edit *", "*", "ask")] };
        for fold in [true, false] {
            let rules = opencode_ask_on(&first, fold).unwrap();
            assert!(opencode_kept_on(&first, &rules, &listing(&[("build (primary)", &[&person[..], &own(fold)].concat())]), fold), "{fold}");
        }
        // the rules built without the folding do not hold on Windows: OpenCode there denies bash and *.key edits
        let unfolded = opencode_ask_on(&first, false).unwrap();
        assert!(!opencode_kept_on(&first, &unfolded, &listing(&[("build (primary)", &[&person[..], &own(false)].concat())]), true));
        // Kilo Code: the same person, its own keys
        let first = listing(&[("code (primary)", &person)]);
        assert_eq!(kilo_ask_on(&first, true).unwrap(), r#"{"agent":{"code":{"permission":{"bash":{"*":"deny"},"edit":{"*":"ask","*.key":"deny"},"write":{"*":"ask"}}}}}"#);
        let kilo_own = [rule("bash", "*", "ask"), rule("edit", "*", "ask"), rule("write", "*", "ask")];
        let unfolded = kilo_ask_on(&first, false).unwrap();
        assert!(!kilo_kept_on(&first, &unfolded, &listing(&[("code (primary)", &[&person[..], &kilo_own].concat())]), true));
    }

    /// Two patterns that differ only in case are one pattern on Windows: a deny under `RM *` covers `rm -i x`, and
    /// an ask that Kilo moved behind it is a weaker rule there. Elsewhere `RM *` never matches `rm`.
    #[test]
    fn patterns_that_differ_only_in_case_are_one_pattern_on_windows() {
        let l = |v: &[(&str, &str)]| v.iter().map(|(p, a)| (p.to_string(), a.to_string())).collect::<Vec<_>>();
        let (before, after) = (l(&[("rm *", "ask"), ("RM *", "deny")]), l(&[("RM *", "deny"), ("rm *", "ask")]));
        assert!(!not_weaker(&before, &after, false, true));
        assert!(may_overlap("rm -i *", "RM *", true) && !may_overlap("rm -i *", "RM *", false));
        // `{"permission":{"bash":{"rm -i *":"allow"}},"agent":{"code":{"permission":{"bash":{"*":"allow","RM *":"deny"}}}}}`:
        // Kilo keeps the person's key order and puts omher's `rm -i *` ask after their `RM *` deny
        let person = [rule("bash", "rm -i *", "allow"), rule("bash", "*", "allow"), rule("bash", "RM *", "deny")];
        let first = listing(&[("code (primary)", &person)]);
        let second = listing(&[("code (primary)", &[&person[..1], &[rule("bash", "*", "ask"), rule("bash", "RM *", "deny"), rule("bash", "rm -i *", "ask")]].concat())]);
        for fold in [true, false] {
            let rules = kilo_ask_on(&first, fold).unwrap();
            let (code1, code2) = (&rulesets(&first, &KILO_ASKED).unwrap()[0].1, &rulesets(&second, &KILO_ASKED).unwrap()[0].1);
            let weaker = decide_on(code1, "bash", "rm -i x", fold) == "deny" && decide_on(code2, "bash", "rm -i x", fold) == "ask";
            assert_eq!(weaker, fold);
            assert_eq!(kilo_kept_on(&first, &rules, &second, fold), !fold, "on Windows rm -i x went from deny to ask");
        }
        // one pattern is sent once, at its last place
        let twice = listing(&[("code (primary)", &[rule("bash", "*", "ask"), rule("bash", "rm *", "allow"), rule("bash", "RM *", "deny")])]);
        assert!(kilo_ask_on(&twice, true).unwrap().contains(r#""bash":{"*":"ask","RM *":"deny"}"#));
        assert!(kilo_ask_on(&twice, false).unwrap().contains(r#""bash":{"*":"ask","rm *":"ask","RM *":"deny"}"#));
    }

    /// Kilo on Windows writes its plan-file patterns with `\` (Node's `path.join`): the recorded default listing
    /// with those separators still starts, with and without Windows' case folding, and an allow for anything else
    /// under a plans folder still refuses.
    #[test]
    fn kilo_plan_files_are_recognised_with_windows_separators() {
        let (base, in_omher, _) = kilo_case("none");
        let win = |l: &str| {
            [".kilo/plans/*.md", ".plans/*.md", ".opencode/plans/*.md", "home/you/.local/share/kilo/plans/*.md", "\"plans/*.md"]
                .iter()
                .fold(l.to_string(), |l, p| l.replace(p, &p.replace('/', "\\\\")))
        };
        let (base, in_omher) = (win(&base), win(&in_omher));
        assert!(base.contains(r#""pattern":".kilo\\plans\\*.md""#) && base.contains(r#""pattern":"plans\\*.md""#) && !base.contains("plans/*.md"));
        for fold in [true, false] {
            let rules = kilo_ask_on(&base, fold).unwrap();
            assert!(rules.contains(r#"".kilo\\plans\\*.md":"ask""#), "{rules}");
            assert!(kilo_kept_on(&base, &rules, &in_omher, fold), "{fold}");
            assert!(plan_file(".KILO\\Plans\\*.md", fold) == fold && plan_file("C:\\Users\\me\\AppData\\kilo\\plans\\*.md", fold));
            for not_a_plan in ["plans\\*.rs", "*\\plans\\*.md", "plans\\..\\*.md", "plans\\*", "myplans\\*.md", "pl?ns\\*.md"] {
                assert!(!plan_file(not_a_plan, fold), "{not_a_plan}");
            }
        }
    }

    /// A project's agent file can name a file or a variable in a pattern (`${file:…}` / `${env:…}` in Kilo,
    /// `{file:…}` / `{env:…}` in OpenCode). The agent leaves that literal for a project file, but replaces it inside
    /// the value omher sends, which would make it read the named file during omher's second listing. Any such token
    /// in what omher would send (an agent's name or a pattern) builds no rules, so nothing is listed a second time.
    #[test]
    fn rules_never_carry_a_config_token() {
        let first = "code (primary)\n[{\"permission\":\"bash\",\"pattern\":\"${file:/etc/passwd}\",\"action\":\"deny\"}]\n";
        assert_eq!(kilo_ask(first), None);
        type Ask = fn(&str, bool) -> Option<String>;
        let both: [(&str, Ask); 2] = [("code", kilo_ask_on), ("build", opencode_ask_on)];
        for (primary, ask) in both {
            let head = format!("{primary} (primary)");
            for fold in [true, false] {
                for token in ["${file:~/.local/share/kilo/auth.json}", "{file:~/.local/share/opencode/auth.json}", "${env:HOME}", "{env:ANTHROPIC_API_KEY}", "{file:x", "{env:"] {
                    let texts = [token.to_string(), format!("cat {token} *"), format!("*{token}")];
                    for text in &texts {
                        // in a pattern of a tool omher asks about, for the default agent and for another
                        for tool in ["bash", "edit", "*"] {
                            let l = listing(&[(&head, &[rule("*", "*", "ask"), rule(tool, text, "deny")])]);
                            assert_eq!(ask(&l, fold), None, "{primary} {tool} {text}");
                            let l = listing(&[(&head, &[rule("*", "*", "ask")]), ("helper (subagent)", &[rule(tool, text, "allow")])]);
                            assert_eq!(ask(&l, fold), None, "{primary} helper {tool} {text}");
                        }
                        // in an agent's name
                        let named = format!("{text} (subagent)");
                        assert_eq!(ask(&listing(&[(&head, &[rule("*", "*", "ask")]), (&named, &[rule("*", "*", "deny")])]), fold), None, "{primary} named {text}");
                    }
                }
                // a pattern of a permission omher writes no rule for is never sent, and braces alone are no token
                let l = listing(&[(&head, &[rule("*", "*", "ask"), rule("read", "{file:notes.txt}", "deny"), rule("bash", "echo ${HOME} {a,b} file: env:", "deny")])]);
                assert!(ask(&l, fold).unwrap().contains(r#""echo ${HOME} {a,b} file: env:":"deny""#), "{primary}");
            }
        }
    }

    /// The rules of one agent (permission, pattern, action), generated.
    type Rules = Vec<(String, String, String)>;

    /// A seeded generator (xorshift): the same listings on every run.
    struct Gen(u64);

    impl Gen {
        fn below(&mut self, n: usize) -> usize {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            (self.0 % n as u64) as usize
        }

        fn pick<'a>(&mut self, of: &[&'a str]) -> &'a str {
            of[self.below(of.len())]
        }

        fn rules(&mut self, most: usize) -> Rules {
            let n = self.below(most + 1);
            (0..n)
                .map(|_| {
                    let permission = self.pick(&["*", "*", "bash", "bash", "edit", "write", "read", "webfetch", "external_directory", "Bash", "EDIT", "ba*", "?dit", "task", "bash x", "bash?x", "edit other", "edit?other"]);
                    let pattern = self.pick(&["*", "*", "*", "a*", "A*", "ab", "AB", "?b", "a *", "rm *", "RM *", "b\\*", "b/*"]);
                    (permission.to_string(), pattern.to_string(), self.pick(&["allow", "ask", "deny"]).to_string())
                })
                .collect()
        }
    }

    fn listed(agents: &[(String, Rules)]) -> String {
        agents.iter().map(|(head, rules)| format!("{head}\n[{}]\n", rules.iter().map(|(p, q, a)| rule(p, q, a)).collect::<Vec<_>>().join(","))).collect()
    }

    /// Whatever second listing the checks accept, no agent decides any permission more loosely than in the first,
    /// and none of the tools omher asks about runs unasked: generated first listings, the rules omher builds from
    /// them, and second listings that are the first plus those rules, then changed at random (a rule dropped, added,
    /// moved or turned into another action, in or outside omher's own rules; a mode changed; an agent dropped). For
    /// both agents, as they match on Windows and elsewhere, over every permission and input below.
    #[test]
    fn whatever_the_checks_accept_is_never_weaker_for_any_permission() {
        type Ask = fn(&str, bool) -> Option<String>;
        type Kept = fn(&str, &str, &str, bool) -> bool;
        let agents: [(&str, Ask, Kept, &[(&str, &str)]); 2] = [("code", kilo_ask_on, kilo_kept_on, &KILO_ASKED), ("build", opencode_ask_on, opencode_kept_on, &ASKED)];
        let permissions = ["bash", "edit", "write", "read", "webfetch", "external_directory", "task", "skill", "Bash", "EDIT", "bat", "xdit", "bash x", "bashXx", "edit other", "editXother"];
        let inputs = ["", "a", "A", "b", "ab", "AB", "aB", "abc", "a b", "a  b", "bb", "Ab", "rm", "rm x", "RM x", "Rm -rf /", "b/c", "b\\c", "B/c", "zz"];
        let rank = |a: &str| match a { "deny" => 0, "ask" => 1, _ => 2 };
        let started = Instant::now();
        let (mut accepted, mut changed_and_accepted, mut refused) = (0, 0, 0);
        for (which, (primary, ask, kept, asked)) in agents.into_iter().enumerate() {
            for fold in [false, true] {
                let mut g = Gen(0x9E37_79B9_7F4A_7C15 ^ ((which as u64) << 1 | fold as u64));
                for _ in 0..150 {
                    let mut first = vec![(format!("{primary} (primary)"), g.rules(5))];
                    for name in ["helper", "review"].iter().take(g.below(3)) {
                        first.push((format!("{name} ({})", g.pick(&["subagent", "all", "primary"])), g.rules(4)));
                    }
                    let first_text = listed(&first);
                    let Some(rules) = ask(&first_text, fold) else { panic!("{first_text}") };
                    // the first listing with omher's own rules after each agent's: what the agent lists when it
                    // took them as meant
                    let mine = resolved(&first_text, primary, asked, fold).unwrap();
                    let mut second: Vec<(String, Rules)> = first
                        .iter()
                        .zip(&mine)
                        .map(|((head, rules), agent)| {
                            let own = asked.iter().zip(&agent.tools).flat_map(|((_, key), tool)| tool.iter().map(|(p, a)| (key.to_string(), p.clone(), (if a == "deny" { "deny" } else { "ask" }).to_string())));
                            let guards = asked.iter().flat_map(|(_, key)| guard_keys(key)).map(|p| (p, "*".to_string(), "deny".to_string()));
                            (head.clone(), rules.iter().cloned().chain(own).chain(guards).collect())
                        })
                        .collect();
                    let faithful = listed(&second);
                    let changes = g.below(3);
                    for _ in 0..changes {
                        let at = g.below(second.len());
                        let n = second[at].1.len();
                        match g.below(7) {
                            0 if n > 0 => drop(second[at].1.remove(g.below(n))),
                            1 => {
                                let extra = g.rules(1);
                                let to = g.below(n + 1);
                                second[at].1.splice(to..to, extra);
                            }
                            2 if n > 1 => {
                                let moved = second[at].1.remove(g.below(n));
                                second[at].1.insert(g.below(n), moved);
                            }
                            3 if n > 0 => second[at].1[g.below(n)].2 = g.pick(&["allow", "ask", "deny"]).to_string(),
                            4 if n > 0 => second[at].1[g.below(n)].1 = g.pick(&["*", "a*", "A*", "ab", "rm *", "RM *"]).to_string(),
                            5 => second[at].0 = second[at].0.replace("(subagent)", "(all)").replace("(primary)", "(subagent)"),
                            6 if second.len() > 1 => drop(second.remove(at)),
                            _ => {}
                        }
                    }
                    let second_text = listed(&second);
                    if !kept(&first_text, &rules, &second_text, fold) {
                        refused += 1;
                        continue;
                    }
                    accepted += 1;
                    changed_and_accepted += usize::from(second_text != faithful);
                    assert_eq!(first.iter().map(|a| &a.0).collect::<Vec<_>>(), second.iter().map(|a| &a.0).collect::<Vec<_>>(), "the same agents and modes");
                    for ((head, was), (_, now)) in first.iter().zip(&second) {
                        for permission in permissions {
                            for input in inputs {
                                let (before, after) = (decide_on(was, permission, input, fold), decide_on(now, permission, input, fold));
                                assert!(rank(after) <= rank(before), "{head} {permission} {input:?}: {before} -> {after} (fold {fold})\n{first_text}\n{second_text}");
                                let asked_tool = asked.iter().any(|(tool, _)| wildcard(permission, tool, fold));
                                assert!(!(asked_tool && after == "allow"), "{head} {permission} {input:?} runs unasked (fold {fold})\n{second_text}");
                            }
                        }
                    }
                }
            }
        }
        println!("{accepted} accepted, {changed_and_accepted} of them changed, {refused} refused in {:?}", started.elapsed());
        assert!(accepted >= 150 && changed_and_accepted >= 10 && refused >= 200, "{accepted} accepted, {changed_and_accepted} of them changed, {refused} refused");
    }

    fn check_kilo(case: &str, want: &[(&str, &str, &str, &str)]) {
        let (base, in_omher, sent) = kilo_case(case);
        let rules = kilo_ask(&base).unwrap();
        assert_eq!(rules, sent, "{case}");
        // Kilo, started with these rules, decides nothing more loosely than the person's own rules and lets nothing in
        // bash, edit or write run unasked but its own plan files
        assert!(kilo_kept(&base, &rules, &in_omher), "{case}");
        // without them, Kilo runs something the person allows unasked (unless they deny everything already)
        if want.iter().any(|w| w.2 == "allow") {
            assert!(!kilo_kept(&base, &rules, &base), "{case}: without the rules Kilo runs tools unasked");
        }
        for agent in ["code", "explore", "plan"] {
            for (tool, input, own, inside) in want {
                let got = decides(&in_omher, agent, tool, input);
                let never_looser = match decides(&base, agent, tool, input).as_str() {
                    "deny" => got == "deny",
                    _ => got == "ask" || got == "deny",
                };
                assert!(never_looser, "{case} {agent} {tool} {input}: {got}");
                if agent == "code" {
                    assert_eq!(decides(&base, agent, tool, input), *own, "{case} code {tool} {input}: the person's own rule");
                    assert_eq!(got, *inside, "{case} code {tool} {input}");
                }
            }
        }
    }

    #[test]
    fn real_kilo_rules_a_blanket_deny_stays_deny_and_its_own_allows_ask() {
        // `"permission": {"bash": "deny"}`: Kilo's own `cat *` allow is under it, so cat is denied too
        check_kilo("string-deny", &[("bash", "echo hi", "deny", "deny"), ("bash", "cat a.txt", "deny", "deny"), ("edit", "a.md", "allow", "ask"), ("write", "a.png", "allow", "ask")]);
    }

    #[test]
    fn real_kilo_rules_a_star_deny_stays_deny() {
        check_kilo("star-deny", &[("bash", "echo hi", "deny", "deny"), ("edit", "a.md", "deny", "deny"), ("write", "a.png", "deny", "deny")]);
    }

    #[test]
    fn real_kilo_rules_a_pattern_deny_stays_deny_and_the_rest_asks() {
        check_kilo("pattern-deny", &[("bash", "rm -rf x", "deny", "deny"), ("bash", "cat a.txt", "allow", "ask"), ("bash", "make", "ask", "ask"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_kilo_rules_an_agent_level_allow_asks_and_its_deny_stays() {
        // `"agent": {"code": {"permission": {"bash": {"*": "allow", "rm *": "deny"}}}}`
        check_kilo("agent-level", &[("bash", "make", "allow", "ask"), ("bash", "rm -rf x", "deny", "deny"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_kilo_rules_an_allow_becomes_ask() {
        check_kilo("allow", &[("bash", "make", "allow", "ask"), ("edit", "a.md", "allow", "ask")]);
    }

    #[test]
    fn real_kilo_rules_with_nothing_set_its_own_allows_ask() {
        // Kilo's own default lets `cat`, `ls`, `mkdir`, `cp`, `mv`… run unasked in `code`: inside omher each asks
        check_kilo("none", &[("bash", "cat a.txt", "allow", "ask"), ("bash", "mv a b", "allow", "ask"), ("bash", "make", "ask", "ask"), ("edit", "a.md", "allow", "ask"), ("write", "a.png", "allow", "ask")]);
    }

    #[test]
    fn kilo_rules_refuse_what_they_cannot_read_or_did_not_hold() {
        let (base, in_omher, _) = kilo_case("none");
        assert_eq!(kilo_ask(""), None);
        assert_eq!(kilo_ask(&base.replace("code (primary)", "coder (primary)")), None);
        let rules = kilo_ask(&base).unwrap();
        // a later layer put an allow back after omher's rules: refused
        let code = in_omher.find("code (primary)\n[").unwrap() + "code (primary)\n[".len();
        let mut loose = in_omher.clone();
        let tail = in_omher[code..].find('\n').unwrap() + code - 1;
        loose.insert_str(tail, r#",{"permission":"bash","pattern":"curl *","action":"allow"}"#);
        assert!(!kilo_kept(&base, &rules, &loose));
        // without the rules Kilo runs `cat` unasked in `code`: refused
        assert!(!kilo_kept(&base, &rules, &base));
        assert!(!kilo_kept(&base, "{}", &in_omher));
        assert!(!kilo_kept("", &rules, &in_omher));
        let probe = acp_agent("kilo").unwrap().rules.as_ref().unwrap();
        assert_eq!((probe.args, probe.var), (&["agent", "list"][..], "KILO_CONFIG_CONTENT"));
        // the rules go under each tool's own key, so they merge after the person's own and outrank Kilo's plan allows
        assert!(rules.contains(r#""code":{"permission":{"bash":{"#) && !rules.contains(r#""bash *""#));
        assert_eq!(no_rules("Kilo Code"), "Kilo Code did not start because omher could not confirm it would keep your own Kilo Code permission rules.");
    }

    /// The six rows: ids, sign-in lines from each agent's own help, and only OpenCode and Kilo (whose defaults run
    /// tools unasked) carry a rule probe.
    #[test]
    fn the_seven_rows() {
        let rows: Vec<(&str, &str, &str, bool)> = ACP_AGENTS.iter().map(|a| (a.id, a.label, a.login, a.rules.is_some())).collect();
        assert_eq!(
            rows,
            [
                ("opencode", "OpenCode", "opencode auth login", true),
                ("kilo", "Kilo Code", "kilo auth login", true),
                ("gemini", "Gemini CLI", "gemini", false),
                ("qwen", "Qwen Code", "qwen", false),
                ("kimi", "Kimi Code", "kimi login", false),
                ("copilot", "Copilot CLI", "copilot login", false),
                ("cline", "Cline", "cline auth", false),
            ]
        );
        for a in &ACP_AGENTS {
            assert_eq!(crate::sessions::agent(a.id).map(|x| x.label), Some(a.label), "{}", a.id);
            assert!(crate::sessions::chat_args(a.id).is_some(), "{}", a.id);
        }
    }

    #[test]
    fn signed_out_names_the_tables_login_line_not_the_agents() {
        // the survey's real Kimi answer to session/new (`-32000`), with a terminal-auth hint omher must not use
        let mut a = Acp::new(opencode(), "/w", None);
        a.start();
        a.on_line(r#"{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{},"authMethods":[{"id":"x","_meta":{"terminal-auth":{"command":"rm","args":["-rf","/"]}}}]}}"#);
        a.on_input(Input::send("hi")).unwrap();
        let st = a.on_line(r#"{"jsonrpc":"2.0","id":2,"error":{"code":-32000,"message":"Authentication required"}}"#);
        let want = "OpenCode is not signed in. Run `opencode auth login` in a terminal and sign in.";
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

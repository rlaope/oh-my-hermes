//! The Agent Client Protocol agents a person added on Settings › Agents, after a confirm card showing the exact
//! command (rule 11). They live in ONE file in omher's own folder, [`store_path`] (`~/.omher/custom-agents.json`),
//! never in a CLI's config. The shell owns reading and writing it; the UI only asks.
//!
//! - Every read validates every entry ([`check`]): an entry that fails is skipped, reported as broken
//!   ([`Broken`]) and never run; a file that cannot be read at all is never overwritten.
//! - The file is written in one place, [`save`], called only by the two confirm commands ([`confirm_add`] after the
//!   card's Add, [`confirm_remove`] after the remove confirm). The preview ([`draft`]) writes nothing.
//! - A custom agent starts as its program, resolved now through the same folders as the built-ins (or the absolute
//!   path it names), with exactly its stored arguments, on pipes and through no shell: a Windows `.cmd` / `.bat` shim
//!   (which only `cmd.exe` runs) is refused ([`launch`]). It gets the environment the generic ACP agents get and
//!   nothing more, and continues a conversation only inside the protocol (`session/load`), never by a flag.
//! - No rule rewriting: OpenCode's ask-rule check is OpenCode's; `opencode` and `kilo` are refused here.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::acp_chat::AcpAgent;
use crate::bridge::Os;
use crate::sessions::Mode;

/// The file's format version.
pub const VERSION: u64 = 1;
/// At most this many agents of a person's own.
pub const MAX_AGENTS: usize = 32;
/// At most this many arguments per agent.
pub const MAX_ARGS: usize = 8;
/// A name's length cap, in characters.
pub const LABEL_MAX: usize = 40;
/// An install line's length cap (shown only, never run).
pub const INSTALL_MAX: usize = 200;
/// An absolute program path's length cap.
pub const PATH_MAX: usize = 512;
/// The file is read only up to this size.
const FILE_MAX: u64 = 64 * 1024;

/// Characters a shell gives a meaning to. None of them may appear in any field of an entry.
pub const SHELL_META: &[char] = &['`', '$', ';', '|', '&', '<', '>', '(', ')', '"', '\'', '*', '?', '[', ']', '{', '}', '!', '#', '~', '%', '^', '\n', '\r', '\t'];

/// One agent a person added: the name it shows, the program (a bare name looked up like a built-in's, or an absolute
/// path to an executable file), its ACP arguments, and an optional install line shown when it is missing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CustomAgent {
    pub id: String,
    pub label: String,
    pub program: String,
    pub args: Vec<String>,
    #[serde(default)]
    pub install: String,
}

/// Why an entry was refused (the UI translates the code, `ag.why.<code>`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Why {
    /// the id is not `^[a-z0-9][a-z0-9-]{0,31}$`
    Id,
    /// the id is a built-in's (or Kilo Code's)
    Builtin,
    /// the name is empty, too long or holds a character other than letters, digits, space and `.-_+`
    Label,
    /// the program is neither a bare `^[A-Za-z0-9._-]{1,64}$` name nor an absolute path
    Program,
    /// the absolute path is not an executable file
    Path,
    /// a Windows `.cmd` / `.bat` shim: only a shell (`cmd.exe`) starts it
    Shim,
    /// an argument is not `^[A-Za-z0-9._=/:-]{1,64}$`, or there are more than eight
    Args,
    /// the install line is too long or holds a shell character
    Install,
    /// the program is OpenCode: use the built-in one
    Opencode,
    /// the program is Kilo Code, which omher does not offer
    Kilo,
    /// an agent with this id is already there
    Dup,
    /// more than [`MAX_AGENTS`] agents
    Many,
    /// not an agent entry (a field missing or of the wrong kind)
    Shape,
    /// the file could not be read (it is left as it is)
    File,
}

impl Why {
    pub fn code(self) -> String {
        serde_json::to_value(self).ok().and_then(|v| v.as_str().map(str::to_string)).unwrap_or_default()
    }
}

/// An entry of the file that failed validation: skipped, shown as broken on the Agents page, never run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Broken {
    /// its id when it has a readable one ("" otherwise), so the person can remove it
    pub id: String,
    pub why: Why,
}

/// `<home>/.omher/custom-agents.json`, beside omher's other state. The only file this module reads or writes.
pub fn store_path(home: &Path) -> PathBuf {
    home.join(".omher").join("custom-agents.json")
}

/// The ids of every agent omher offers itself (and Kilo Code's): a custom agent may take none of them.
fn reserved(id: &str) -> bool {
    id == "kilo" || crate::sessions::AGENTS.iter().any(|a| a.id == id) || crate::acp_agents::entry(id).is_some()
}

/// `^[a-z0-9][a-z0-9-]{0,31}$`
pub fn id_ok(id: &str) -> bool {
    let b = id.as_bytes();
    (1..=32).contains(&b.len()) && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit()) && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
}

/// `^[A-Za-z0-9._-]{1,64}$` with at least one letter or digit (so never `.` or `..`).
pub fn bare_ok(p: &str) -> bool {
    (1..=64).contains(&p.len()) && p.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-')) && p.bytes().any(|c| c.is_ascii_alphanumeric())
}

/// `^[A-Za-z0-9._=/:-]{1,64}$`
pub fn arg_ok(a: &str) -> bool {
    (1..=64).contains(&a.len()) && a.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'=' | b'/' | b':' | b'-'))
}

/// A name: 1 to [`LABEL_MAX`] characters, letters (any script), digits, space and `.-_+`, no leading or trailing space.
pub fn label_ok(l: &str) -> bool {
    let n = l.chars().count();
    (1..=LABEL_MAX).contains(&n) && l.trim() == l && l.chars().all(|c| c.is_alphanumeric() || matches!(c, ' ' | '.' | '-' | '_' | '+'))
}

/// An install line: shown only. Up to [`INSTALL_MAX`] characters of `[A-Za-z0-9._=/:@+ -]`, or none.
pub fn install_ok(i: &str) -> bool {
    i.len() <= INSTALL_MAX && i.trim() == i && i.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'=' | b'/' | b':' | b'@' | b'+' | b' ' | b'-'))
}

/// An absolute path for `os`, in the characters a path may hold there: `/…` of `[A-Za-z0-9._/@+-]` on macOS and Linux;
/// `X:\…` of the same plus `\`, `:` and space on Windows.
pub fn abs_shape_ok(p: &str, os: Os) -> bool {
    if p.len() > PATH_MAX || p.contains(SHELL_META) {
        return false;
    }
    let plain = |c: u8| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'/' | b'@' | b'+' | b'-');
    match os {
        Os::Unix => p.starts_with('/') && p.len() > 1 && p.bytes().all(plain) && !p.split('/').any(|s| s == ".."),
        Os::Windows => {
            let b = p.as_bytes();
            b.len() > 3 && b[0].is_ascii_alphabetic() && b[1] == b':' && matches!(b[2], b'\\' | b'/') && p.bytes().all(|c| plain(c) || matches!(c, b'\\' | b':' | b' ')) && !p.split(['/', '\\']).any(|s| s == "..")
        }
    }
}

/// The program's file name without folder or `.exe`, lower-cased.
fn base_name(p: &str) -> String {
    let name = p.rsplit(['/', '\\']).next().unwrap_or(p).to_ascii_lowercase();
    name.strip_suffix(".exe").map(str::to_string).unwrap_or(name)
}

/// The extension of a path, lower-cased.
fn ext_of(p: &str) -> String {
    let name = p.rsplit(['/', '\\']).next().unwrap_or(p);
    name.rsplit_once('.').map(|(_, e)| e.to_ascii_lowercase()).unwrap_or_default()
}

/// Validate one entry for `os`; `is_program` checks an absolute path is an executable file. This runs on every read
/// and before every write.
pub fn check<X: Fn(&Path) -> bool>(c: &CustomAgent, os: Os, is_program: X) -> Result<(), Why> {
    if !id_ok(&c.id) {
        return Err(Why::Id);
    }
    if reserved(&c.id) {
        return Err(Why::Builtin);
    }
    if !label_ok(&c.label) || c.label.contains(SHELL_META) {
        return Err(Why::Label);
    }
    match base_name(&c.program).as_str() {
        "opencode" => return Err(Why::Opencode),
        "kilo" | "kilocode" => return Err(Why::Kilo),
        _ => {}
    }
    if bare_ok(&c.program) {
        if os == Os::Windows && matches!(ext_of(&c.program).as_str(), "cmd" | "bat") {
            return Err(Why::Shim);
        }
    } else if abs_shape_ok(&c.program, os) {
        if os == Os::Windows && ext_of(&c.program) != "exe" {
            return Err(if matches!(ext_of(&c.program).as_str(), "cmd" | "bat") { Why::Shim } else { Why::Path });
        }
        if !is_program(Path::new(&c.program)) {
            return Err(Why::Path);
        }
    } else {
        return Err(Why::Program);
    }
    if c.args.len() > MAX_ARGS || !c.args.iter().all(|a| arg_ok(a)) {
        return Err(Why::Args);
    }
    if !install_ok(&c.install) {
        return Err(Why::Install);
    }
    Ok(())
}

/// What the file holds, read and checked: the agents that may run, the entries that are broken, and whether the
/// file itself could not be read (then nothing may write it).
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Loaded {
    pub agents: Vec<CustomAgent>,
    pub broken: Vec<Broken>,
    pub unreadable: bool,
}

/// The file's entries as they are, or `Err` when the file cannot be read (a link, too big, not the format).
/// No file is no entries.
fn read_raw(home: &Path) -> Result<Vec<Value>, ()> {
    let path = store_path(home);
    let meta = match std::fs::symlink_metadata(&path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(_) => return Err(()),
    };
    if !meta.is_file() || meta.len() > FILE_MAX {
        return Err(());
    }
    let text = std::fs::read_to_string(&path).map_err(|_| ())?;
    let v: Value = serde_json::from_str(&text).map_err(|_| ())?;
    if v.get("version").and_then(Value::as_u64) != Some(VERSION) {
        return Err(());
    }
    v.get("agents").and_then(Value::as_array).cloned().ok_or(())
}

/// A broken entry's id, only when it is plainly an id (so it can be named and removed).
fn readable_id(v: &Value) -> String {
    v.get("id").and_then(Value::as_str).filter(|s| s.len() <= 64 && s.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')).unwrap_or("").to_string()
}

/// Read and check every entry. Broken entries are skipped; a file that cannot be read is skipped whole.
pub fn load<X: Fn(&Path) -> bool>(home: &Path, os: Os, is_program: X) -> Loaded {
    let Ok(raw) = read_raw(home) else {
        return Loaded { agents: Vec::new(), broken: vec![Broken { id: String::new(), why: Why::File }], unreadable: true };
    };
    let mut out = Loaded::default();
    for v in raw {
        let id = readable_id(&v);
        let entry: Result<CustomAgent, Why> = serde_json::from_value::<CustomAgent>(v).map_err(|_| Why::Shape).and_then(|c| check(&c, os, &is_program).map(|_| c));
        match entry {
            Ok(_) if out.agents.len() >= MAX_AGENTS => out.broken.push(Broken { id, why: Why::Many }),
            Ok(c) if out.agents.iter().any(|a| a.id == c.id) => out.broken.push(Broken { id, why: Why::Dup }),
            Ok(c) => out.agents.push(c),
            Err(why) => out.broken.push(Broken { id, why }),
        }
    }
    out
}

/// The ONE place the file is written: `entries` as the file's agents, through a temporary file and a rename, never
/// through a link. Called only by [`confirm_add`] and [`confirm_remove`].
fn save(home: &Path, entries: Vec<Value>) -> Result<(), Why> {
    let dir = home.join(".omher");
    if dir.is_symlink() {
        return Err(Why::File);
    }
    std::fs::create_dir_all(&dir).map_err(|_| Why::File)?;
    let path = store_path(home);
    if path.is_symlink() {
        return Err(Why::File);
    }
    let tmp = dir.join("custom-agents.json.tmp");
    let body = serde_json::to_string_pretty(&json!({"version": VERSION, "agents": entries})).map_err(|_| Why::File)?;
    std::fs::write(&tmp, body + "\n").map_err(|_| Why::File)?;
    std::fs::rename(&tmp, &path).map_err(|_| Why::File)
}

/// An id made from the name (else the program's name), free of every built-in's and every agent already there.
fn new_id(label: &str, program: &str, taken: &[String]) -> String {
    let slug = |s: &str| {
        let mut out = String::new();
        for c in s.chars() {
            if c.is_ascii_alphanumeric() {
                out.push(c.to_ascii_lowercase());
            } else if !out.ends_with('-') && !out.is_empty() {
                out.push('-');
            }
        }
        let mut out: String = out.trim_matches('-').chars().take(28).collect();
        while out.ends_with('-') {
            out.pop();
        }
        out
    };
    let mut base = slug(label);
    if base.is_empty() {
        base = slug(&base_name(program));
    }
    if base.is_empty() {
        base = "agent".into();
    }
    let free = |id: &str| id_ok(id) && !reserved(id) && !taken.iter().any(|t| t == id);
    if free(&base) {
        return base;
    }
    (2..100).map(|n| format!("{base}-{n}")).find(|id| free(id)).unwrap_or_else(|| format!("{base}-x"))
}

/// What the form's fields make, checked, with its id chosen; writes nothing. The arguments are one line split on
/// spaces (no shell).
pub fn draft<X: Fn(&Path) -> bool>(home: &Path, label: &str, program: &str, args: &str, install: &str, os: Os, is_program: X) -> Result<CustomAgent, Why> {
    let label = label.trim();
    let program = program.trim();
    let args: Vec<String> = args.split_whitespace().map(str::to_string).collect();
    let taken: Vec<String> = match read_raw(home) {
        Ok(raw) => raw.iter().map(readable_id).filter(|s| !s.is_empty()).collect(),
        Err(()) => return Err(Why::File),
    };
    let c = CustomAgent { id: new_id(label, program, &taken), label: label.to_string(), program: program.to_string(), args, install: install.trim().to_string() };
    check(&c, os, is_program)?;
    if taken.len() >= MAX_AGENTS {
        return Err(Why::Many);
    }
    Ok(c)
}

/// The card's Add: check `c` again and add it to the file. Refused when the file cannot be read (it is left as it
/// is), when its id is taken or when there are [`MAX_AGENTS`] already. One of the two writers of the file.
pub fn confirm_add<X: Fn(&Path) -> bool>(home: &Path, c: &CustomAgent, os: Os, is_program: X) -> Result<(), Why> {
    check(c, os, is_program)?;
    let mut raw = read_raw(home).map_err(|()| Why::File)?;
    if raw.iter().any(|v| readable_id(v) == c.id) {
        return Err(Why::Dup);
    }
    if raw.len() >= MAX_AGENTS {
        return Err(Why::Many);
    }
    raw.push(serde_json::to_value(c).map_err(|_| Why::File)?);
    save(home, raw)
}

/// The remove confirm: every entry with id `id` leaves the file (a broken one too); the others stay as they are.
/// The other writer of the file.
pub fn confirm_remove(home: &Path, id: &str) -> Result<(), Why> {
    if id.is_empty() {
        return Err(Why::Id);
    }
    let raw = read_raw(home).map_err(|()| Why::File)?;
    let kept: Vec<Value> = raw.iter().filter(|v| readable_id(v) != id).cloned().collect();
    if kept.len() == raw.len() {
        return Ok(());
    }
    save(home, kept)
}

/// The file names a bare program is looked up as: the name on macOS and Linux; on Windows only `<name>.exe` (a
/// `.cmd` / `.bat` shim needs `cmd.exe`, a shell).
fn names(program: &str, os: Os) -> Vec<String> {
    match os {
        Os::Unix => vec![program.to_string()],
        Os::Windows if ext_of(program) == "exe" => vec![program.to_string()],
        Os::Windows => vec![format!("{program}.exe")],
    }
}

/// Where `c`'s program is: its absolute path when that is an executable file, else the first `dir/name` in `dirs`
/// (the same folders as the built-ins) that is one. `None` = not found.
pub fn find<X: Fn(&Path) -> bool>(c: &CustomAgent, dirs: &[PathBuf], is_program: X, os: Os) -> Option<PathBuf> {
    if !bare_ok(&c.program) {
        return is_program(Path::new(&c.program)).then(|| PathBuf::from(&c.program));
    }
    let names = names(&c.program, os);
    dirs.iter().flat_map(|d| names.iter().map(move |n| d.join(n))).find(|p| is_program(p))
}

/// The argv omher runs for `c`: the program found, then exactly its stored arguments; nothing else, no shell.
pub fn launch<X: Fn(&Path) -> bool>(c: &CustomAgent, dirs: &[PathBuf], is_program: X, os: Os) -> Result<Vec<OsString>, String> {
    check(c, os, &is_program).map_err(|w| format!("{} cannot start ({})", c.label, w.code()))?;
    let path = find(c, dirs, &is_program, os).ok_or_else(|| format!("{} is not installed (no `{}` found)", c.label, c.program))?;
    if os == Os::Windows && ext_of(&path.to_string_lossy()) != "exe" {
        return Err(format!("{} cannot start without a shell", c.label));
    }
    let mut argv = vec![path.into_os_string()];
    argv.extend(c.args.iter().map(OsString::from));
    Ok(argv)
}

/// The command the card shows: the program as found now, then the arguments; `None` when it is not found.
pub fn command<X: Fn(&Path) -> bool>(c: &CustomAgent, dirs: &[PathBuf], is_program: X, os: Os) -> Option<String> {
    let path = find(c, dirs, is_program, os)?;
    Some(std::iter::once(path.to_string_lossy().into_owned()).chain(c.args.iter().cloned()).collect::<Vec<_>>().join(" "))
}

/// The person's home folder on this computer.
pub fn home() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).filter(|v| !v.is_empty()).map(PathBuf::from)
}

/// The file on this computer, read and checked.
pub fn load_here() -> Loaded {
    match home() {
        Some(h) => load(&h, Os::current(), crate::sessions::is_program_file),
        None => Loaded::default(),
    }
}

/// Custom agent `id` on this computer, checked as it is read now; `None` for anything else.
pub fn lookup(id: &str) -> Option<CustomAgent> {
    if !id_ok(id) || reserved(id) {
        return None;
    }
    load_here().agents.into_iter().find(|c| c.id == id)
}

/// argv and the child's `PATH` for custom agent `c`, looked up in `dirs` (the app passes `sessions::host_dirs`), as `sessions::launch_for` makes them for a
/// built-in: the program's own folder, then the install folders.
pub fn launch_here(c: &CustomAgent, dirs: &[PathBuf]) -> Result<(Vec<OsString>, OsString), String> {
    let argv = launch(c, dirs, crate::sessions::is_program_file, Os::current())?;
    let mut child_dirs: Vec<PathBuf> = Path::new(&argv[0]).parent().map(|p| vec![p.to_path_buf()]).unwrap_or_default();
    child_dirs.extend(dirs.iter().cloned());
    let joined = std::env::join_paths(child_dirs.iter().filter(|d| d.is_dir())).map_err(|e| e.to_string())?;
    Ok((argv, joined))
}

/// The adapter row for `c`: its name, and its program as the sign-in line (running it in a terminal is how such an
/// agent signs in); no skill tool, no rule probe. Rows are kept for the app's life, one per distinct agent.
pub fn adapter_row(c: &CustomAgent) -> &'static AcpAgent {
    static ROWS: Mutex<Vec<&'static AcpAgent>> = Mutex::new(Vec::new());
    let mut rows = ROWS.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(r) = rows.iter().find(|r| r.id == c.id && r.label == c.label && r.login == c.program) {
        return r;
    }
    let leak = |s: &str| -> &'static str { Box::leak(s.to_string().into_boxed_str()) };
    let row: &'static AcpAgent = Box::leak(Box::new(AcpAgent { id: leak(&c.id), label: leak(&c.label), login: leak(&c.program), skill_tool: None, rules: None }));
    rows.push(row);
    row
}

/// What the UI gets for a custom agent: the same shape as a generic ACP agent's row (`AcpRow`), marked `custom`.
#[derive(Debug, Clone, Serialize)]
pub struct CustomRow {
    pub id: String,
    pub label: String,
    pub program: String,
    pub args: Vec<String>,
    pub login: String,
    pub install: String,
    pub mark: &'static str,
    pub continues: bool,
    pub custom: bool,
}

/// One custom agent as the agent look-up reports it (the shape of `sessions::AgentInfo`).
#[derive(Debug, Clone, Serialize)]
pub struct CustomInfo {
    pub id: String,
    pub label: String,
    pub mode: Mode,
    pub path: Option<String>,
    pub acp: CustomRow,
}

pub fn info(c: &CustomAgent, path: Option<PathBuf>) -> CustomInfo {
    CustomInfo {
        id: c.id.clone(),
        label: c.label.clone(),
        mode: Mode::Chat,
        path: path.map(|p| p.to_string_lossy().into_owned()),
        acp: CustomRow { id: c.id.clone(), label: c.label.clone(), program: c.program.clone(), args: c.args.clone(), login: c.program.clone(), install: c.install.clone(), mark: "", continues: true, custom: true },
    }
}

/// The Agents page's list: each custom agent with where its program is now, and the broken entries.
#[derive(Debug, Clone, Serialize)]
pub struct CustomList {
    pub agents: Vec<CustomInfo>,
    pub broken: Vec<Broken>,
}

pub fn list_here() -> CustomList {
    let l = load_here();
    let dirs = crate::sessions::host_dirs();
    let agents = l.agents.iter().map(|c| info(c, find(c, &dirs, crate::sessions::is_program_file, Os::current()))).collect();
    CustomList { agents, broken: l.broken }
}

/// The card: the entry the form makes, and the command omher will run (`None`: not found on the search path now).
#[derive(Debug, Clone, Serialize)]
pub struct Preview {
    pub entry: CustomAgent,
    pub command: Option<String>,
}

pub fn preview_here(label: &str, program: &str, args: &str, install: &str) -> Result<Preview, Why> {
    let h = home().ok_or(Why::File)?;
    let entry = draft(&h, label, program, args, install, Os::current(), crate::sessions::is_program_file)?;
    let command = command(&entry, &crate::sessions::host_dirs(), crate::sessions::is_program_file, Os::current());
    Ok(Preview { entry, command })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent(id: &str, program: &str, args: &[&str]) -> CustomAgent {
        CustomAgent { id: id.into(), label: "Cursor Agent".into(), program: program.into(), args: args.iter().map(|s| s.to_string()).collect(), install: String::new() }
    }

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("omher-custom-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d.canonicalize().unwrap()
    }

    const ANY: fn(&Path) -> bool = |_| true;
    const NONE: fn(&Path) -> bool = |_| false;

    /// The validation table: good entries pass; shell characters, relative paths, a built-in's id, too many or bad
    /// arguments, OpenCode and Kilo Code, and Windows shims are refused, each with its reason.
    #[test]
    fn the_validation_table() {
        let ok = [
            agent("cursor", "cursor-agent", &["acp"]),
            agent("my-agent-2", "my_agent.v2", &[]),
            agent("x", "/opt/homebrew/bin/cursor-agent", &["acp", "--model=sonnet-4", "--dir=/tmp/x", "a:b"]),
            agent("eight", "agent", &["a", "b", "c", "d", "e", "f", "g", "h"]),
            CustomAgent { install: "npm install -g @cursor/agent".into(), ..agent("c2", "cursor-agent", &["acp"]) },
            CustomAgent { label: "커서 에이전트".into(), ..agent("c3", "cursor-agent", &["acp"]) },
        ];
        for c in &ok {
            assert_eq!(check(c, Os::Unix, ANY), Ok(()), "{c:?}");
        }
        let bad: Vec<(CustomAgent, Why)> = vec![
            (agent("Cursor", "cursor-agent", &["acp"]), Why::Id),
            (agent("-x", "cursor-agent", &["acp"]), Why::Id),
            (agent("", "cursor-agent", &["acp"]), Why::Id),
            (agent(&"a".repeat(33), "cursor-agent", &["acp"]), Why::Id),
            (agent("a/b", "cursor-agent", &["acp"]), Why::Id),
            (agent("claude", "cursor-agent", &["acp"]), Why::Builtin),
            (agent("gemini", "cursor-agent", &["acp"]), Why::Builtin),
            (agent("opencode", "cursor-agent", &["acp"]), Why::Builtin),
            (agent("kilo", "cursor-agent", &["acp"]), Why::Builtin),
            (CustomAgent { label: "".into(), ..agent("c", "cursor-agent", &["acp"]) }, Why::Label),
            (CustomAgent { label: "a".repeat(41), ..agent("c", "cursor-agent", &["acp"]) }, Why::Label),
            (CustomAgent { label: "x; rm -rf ~".into(), ..agent("c", "cursor-agent", &["acp"]) }, Why::Label),
            (CustomAgent { label: "$(id)".into(), ..agent("c", "cursor-agent", &["acp"]) }, Why::Label),
            (agent("c", "cursor-agent; rm -rf ~", &["acp"]), Why::Program),
            (agent("c", "cursor agent", &["acp"]), Why::Program),
            (agent("c", "$(id)", &["acp"]), Why::Program),
            (agent("c", "`id`", &["acp"]), Why::Program),
            (agent("c", "bin/cursor-agent", &["acp"]), Why::Program),
            (agent("c", "./cursor-agent", &["acp"]), Why::Program),
            (agent("c", "../cursor-agent", &["acp"]), Why::Program),
            (agent("c", "~/bin/cursor-agent", &["acp"]), Why::Program),
            (agent("c", "..", &["acp"]), Why::Program),
            (agent("c", "/opt/../etc/x", &["acp"]), Why::Program),
            (agent("c", "/opt/bin/a b", &["acp"]), Why::Program),
            (agent("c", "/opt/bin/x|y", &["acp"]), Why::Program),
            (agent("c", &"a".repeat(65), &["acp"]), Why::Program),
            (agent("c", "cursor-agent", &["acp; rm -rf ~"]), Why::Args),
            (agent("c", "cursor-agent", &["$(id)"]), Why::Args),
            (agent("c", "cursor-agent", &["a b"]), Why::Args),
            (agent("c", "cursor-agent", &["`id`"]), Why::Args),
            (agent("c", "cursor-agent", &["a|b"]), Why::Args),
            (agent("c", "cursor-agent", &["a>b"]), Why::Args),
            (agent("c", "cursor-agent", &["~"]), Why::Args),
            (agent("c", "cursor-agent", &[""]), Why::Args),
            (agent("c", "cursor-agent", &[&"a".repeat(65)]), Why::Args),
            (agent("c", "cursor-agent", &["a", "b", "c", "d", "e", "f", "g", "h", "i"]), Why::Args),
            (CustomAgent { install: "curl -fsSL x | sh".into(), ..agent("c", "cursor-agent", &["acp"]) }, Why::Install),
            (CustomAgent { install: "a".repeat(201), ..agent("c", "cursor-agent", &["acp"]) }, Why::Install),
            (agent("c", "opencode", &["acp"]), Why::Opencode),
            (agent("c", "/usr/local/bin/opencode", &["acp"]), Why::Opencode),
            (agent("c", "kilo", &["acp"]), Why::Kilo),
            (agent("c", "/opt/homebrew/bin/kilocode", &["acp"]), Why::Kilo),
        ];
        for (c, why) in &bad {
            assert_eq!(check(c, Os::Unix, ANY), Err(*why), "{c:?}");
        }
        // an absolute path must be an executable file now
        assert_eq!(check(&agent("c", "/opt/homebrew/bin/cursor-agent", &["acp"]), Os::Unix, NONE), Err(Why::Path));
        // a bare name is checked by shape only (whether it is installed is the look-up's)
        assert_eq!(check(&agent("c", "cursor-agent", &["acp"]), Os::Unix, NONE), Ok(()));
        // Windows: an .exe path or name; never a .cmd / .bat shim, which only cmd.exe starts
        assert_eq!(check(&agent("c", r"C:\Program Files\Cursor\cursor-agent.exe", &["acp"]), Os::Windows, ANY), Ok(()));
        assert_eq!(check(&agent("c", r"C:\Users\me\AppData\Roaming\npm\cursor-agent.cmd", &["acp"]), Os::Windows, ANY), Err(Why::Shim));
        assert_eq!(check(&agent("c", "cursor-agent.bat", &["acp"]), Os::Windows, ANY), Err(Why::Shim));
        assert_eq!(check(&agent("c", r"C:\x\cursor-agent.ps1", &["acp"]), Os::Windows, ANY), Err(Why::Path));
        assert_eq!(check(&agent("c", r"C:\x\a&b.exe", &["acp"]), Os::Windows, ANY), Err(Why::Program));
        assert_eq!(check(&agent("c", r"C:\x\%PATH%.exe", &["acp"]), Os::Windows, ANY), Err(Why::Program));
        // every shell character is refused in every field that holds text
        for m in SHELL_META {
            let s = format!("a{m}b");
            assert!(check(&agent("c", &s, &["acp"]), Os::Unix, ANY).is_err(), "program {m:?}");
            assert!(check(&agent("c", "x", &[&s]), Os::Unix, ANY).is_err(), "arg {m:?}");
            assert!(check(&CustomAgent { label: s.clone(), ..agent("c", "x", &[]) }, Os::Unix, ANY).is_err(), "label {m:?}");
            assert!(check(&CustomAgent { install: s.clone(), ..agent("c", "x", &[]) }, Os::Unix, ANY).is_err(), "install {m:?}");
            assert!(check(&agent("c", &format!("/opt/{s}"), &[]), Os::Unix, ANY).is_err(), "path {m:?}");
        }
    }

    /// A broken entry is skipped and reported, never fatal: the good ones still load; a file that cannot be read
    /// loads nothing and is never overwritten by an add or a remove.
    #[test]
    fn a_broken_file_is_skipped_not_fatal() {
        let home = tmp("broken");
        std::fs::create_dir_all(home.join(".omher")).unwrap();
        let body = json!({"version": 1, "agents": [
            {"id": "cursor", "label": "Cursor", "program": "cursor-agent", "args": ["acp"]},
            {"id": "evil", "label": "Evil", "program": "sh", "args": ["-c", "rm -rf ~"]},
            {"id": "claude", "label": "Mine", "program": "x", "args": []},
            {"id": "noargs", "label": "No args"},
            {"label": "No id", "program": "x", "args": []},
            {"id": "cursor", "label": "Again", "program": "y", "args": []},
            {"id": "rel", "label": "Rel", "program": "./x", "args": []},
            "not an object"
        ]});
        std::fs::write(store_path(&home), body.to_string()).unwrap();
        let l = load(&home, Os::Unix, ANY);
        assert!(!l.unreadable);
        assert_eq!(l.agents.iter().map(|c| c.id.as_str()).collect::<Vec<_>>(), ["cursor"]);
        assert_eq!(
            l.broken,
            vec![
                Broken { id: "evil".into(), why: Why::Args },
                Broken { id: "claude".into(), why: Why::Builtin },
                Broken { id: "noargs".into(), why: Why::Shape },
                Broken { id: "".into(), why: Why::Shape },
                Broken { id: "cursor".into(), why: Why::Dup },
                Broken { id: "rel".into(), why: Why::Program },
                Broken { id: "".into(), why: Why::Shape },
            ]
        );
        // the broken one can be removed by its id; the rest stays as written
        confirm_remove(&home, "evil").unwrap();
        let after: Value = serde_json::from_str(&std::fs::read_to_string(store_path(&home)).unwrap()).unwrap();
        assert_eq!(after["agents"].as_array().unwrap().len(), 7);
        // not the format, not JSON, a link: nothing loads, and nothing writes over it
        for text in ["{\"version\": 2, \"agents\": []}", "not json", "[]"] {
            std::fs::write(store_path(&home), text).unwrap();
            let l = load(&home, Os::Unix, ANY);
            assert!(l.unreadable && l.agents.is_empty(), "{text}");
            assert_eq!(l.broken, vec![Broken { id: "".into(), why: Why::File }]);
            assert_eq!(confirm_add(&home, &agent("cursor", "cursor-agent", &["acp"]), Os::Unix, ANY), Err(Why::File));
            assert_eq!(confirm_remove(&home, "cursor"), Err(Why::File));
            assert_eq!(draft(&home, "Cursor", "cursor-agent", "acp", "", Os::Unix, ANY), Err(Why::File));
            assert_eq!(std::fs::read_to_string(store_path(&home)).unwrap(), text);
        }
        #[cfg(unix)]
        {
            std::fs::remove_file(store_path(&home)).unwrap();
            let elsewhere = home.join("elsewhere.json");
            std::fs::write(&elsewhere, json!({"version": 1, "agents": []}).to_string()).unwrap();
            std::os::unix::fs::symlink(&elsewhere, store_path(&home)).unwrap();
            assert!(load(&home, Os::Unix, ANY).unreadable);
            assert_eq!(confirm_add(&home, &agent("cursor", "cursor-agent", &["acp"]), Os::Unix, ANY), Err(Why::File));
        }
        // no file: no agents, nothing broken
        let empty = tmp("empty");
        assert_eq!(load(&empty, Os::Unix, ANY), Loaded::default());
        std::fs::remove_dir_all(home).unwrap();
        std::fs::remove_dir_all(empty).unwrap();
    }

    /// The preview writes nothing; Add writes exactly the checked entry into omher's own file; Remove takes it out.
    #[test]
    fn add_then_remove() {
        let home = tmp("add");
        let c = draft(&home, " Cursor Agent ", "cursor-agent", "acp  --model=x", "", Os::Unix, ANY).unwrap();
        assert_eq!(c, CustomAgent { id: "cursor-agent".into(), label: "Cursor Agent".into(), program: "cursor-agent".into(), args: vec!["acp".into(), "--model=x".into()], install: "".into() });
        assert!(!store_path(&home).exists(), "the preview wrote the file");
        assert!(!home.join(".omher").exists());
        // a name in another script makes its id from the program; a taken id gets a number
        assert_eq!(draft(&home, "커서", "cursor-agent", "acp", "", Os::Unix, ANY).unwrap().id, "cursor-agent");
        assert_eq!(draft(&home, "Claude", "x", "acp", "", Os::Unix, ANY).unwrap().id, "claude-2");
        confirm_add(&home, &c, Os::Unix, ANY).unwrap();
        assert_eq!(confirm_add(&home, &c, Os::Unix, ANY), Err(Why::Dup));
        assert_eq!(draft(&home, "Cursor Agent", "cursor-agent", "acp", "", Os::Unix, ANY).unwrap().id, "cursor-agent-2");
        let l = load(&home, Os::Unix, ANY);
        assert_eq!(l.agents, vec![c.clone()]);
        let on_disk: Value = serde_json::from_str(&std::fs::read_to_string(store_path(&home)).unwrap()).unwrap();
        assert_eq!(on_disk, json!({"version": 1, "agents": [{"id": "cursor-agent", "label": "Cursor Agent", "program": "cursor-agent", "args": ["acp", "--model=x"], "install": ""}]}));
        // an entry the card never checked is refused at Add too
        assert_eq!(confirm_add(&home, &agent("evil", "sh", &["-c"]), Os::Unix, ANY), Ok(()), "a plain name and argument are fine");
        assert_eq!(confirm_add(&home, &agent("evil2", "sh", &["-c", "rm -rf ~"]), Os::Unix, ANY), Err(Why::Args));
        assert_eq!(confirm_add(&home, &agent("claude", "x", &[]), Os::Unix, ANY), Err(Why::Builtin));
        confirm_remove(&home, "evil").unwrap();
        confirm_remove(&home, "cursor-agent").unwrap();
        assert!(load(&home, Os::Unix, ANY).agents.is_empty());
        assert!(!home.join(".omher").join("custom-agents.json.tmp").exists());
        // a removed id is gone for good; removing again changes nothing
        confirm_remove(&home, "cursor-agent").unwrap();
        // the cap
        for i in 0..MAX_AGENTS {
            confirm_add(&home, &agent(&format!("a{i}"), "x", &[]), Os::Unix, ANY).unwrap();
        }
        assert_eq!(confirm_add(&home, &agent("one-more", "x", &[]), Os::Unix, ANY), Err(Why::Many));
        assert_eq!(draft(&home, "One more", "x", "", "", Os::Unix, ANY), Err(Why::Many));
        std::fs::remove_dir_all(home).unwrap();
    }

    /// The look-up: a bare name through the given folders (on Windows only `<name>.exe`), an absolute path as it is;
    /// argv is the program found and exactly the stored arguments, and the card's command is the same text.
    #[test]
    fn launch_is_the_program_and_the_stored_arguments_only() {
        let dirs = vec![PathBuf::from("/a"), PathBuf::from("/opt/homebrew/bin")];
        let at = |want: &'static str| move |p: &Path| p == Path::new(want);
        let c = agent("cursor", "cursor-agent", &["acp", "--model=x"]);
        let argv = launch(&c, &dirs, at("/opt/homebrew/bin/cursor-agent"), Os::Unix).unwrap();
        assert_eq!(argv, ["/opt/homebrew/bin/cursor-agent", "acp", "--model=x"].map(OsString::from));
        assert_eq!(command(&c, &dirs, at("/opt/homebrew/bin/cursor-agent"), Os::Unix).as_deref(), Some("/opt/homebrew/bin/cursor-agent acp --model=x"));
        assert_eq!(command(&c, &dirs, NONE, Os::Unix), None);
        assert!(launch(&c, &dirs, NONE, Os::Unix).unwrap_err().contains("not installed"));
        let abs = agent("cursor", "/x/cursor-agent", &["acp"]);
        assert_eq!(launch(&abs, &dirs, at("/x/cursor-agent"), Os::Unix).unwrap(), ["/x/cursor-agent", "acp"].map(OsString::from));
        // Windows: the .exe only; the npm .cmd shim next to it is never picked
        let wdirs = vec![PathBuf::from(r"C:\npm")];
        let both = |p: &Path| p == Path::new(r"C:\npm").join("cursor-agent.cmd") || p == Path::new(r"C:\npm").join("cursor-agent.exe");
        let shim = |p: &Path| p == Path::new(r"C:\npm").join("cursor-agent.cmd");
        assert_eq!(launch(&c, &wdirs, both, Os::Windows).unwrap()[0], Path::new(r"C:\npm").join("cursor-agent.exe").into_os_string());
        assert!(launch(&c, &wdirs, shim, Os::Windows).is_err());
        // what fails a check never resolves to anything
        assert!(launch(&agent("cursor", "opencode", &["acp"]), &dirs, ANY, Os::Unix).is_err());
        assert!(launch(&agent("claude", "cursor-agent", &["acp"]), &dirs, ANY, Os::Unix).is_err());
    }

    /// A custom agent's adapter row: its name and its program as the sign-in line, no rule probe, kept once.
    #[test]
    fn the_adapter_row_rewrites_no_rules() {
        let c = agent("cursor", "cursor-agent", &["acp"]);
        let r = adapter_row(&c);
        assert_eq!((r.id, r.label, r.login), ("cursor", "Cursor Agent", "cursor-agent"));
        assert!(r.rules.is_none() && r.skill_tool.is_none());
        assert!(std::ptr::eq(r, adapter_row(&c)));
        let row = serde_json::to_value(info(&c, None)).unwrap();
        assert_eq!(row["acp"], json!({"id": "cursor", "label": "Cursor Agent", "program": "cursor-agent", "args": ["acp"], "login": "cursor-agent", "install": "", "mark": "", "continues": true, "custom": true}));
        assert_eq!(row["mode"], "chat");
    }
}

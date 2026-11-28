//! Program Resume Protocol, OSC 7577 revision 0.5: a program in an omher terminal can tell omher how to start it
//! again after omher restarts.
//!
//! - Every terminal start (Settings › Terminal "Let programs ask to be restarted", on by default) gets its own
//!   `OSC7577_TOKEN`: 32 characters of `[A-Za-z0-9_-]` from 192 random bits ([`new_token`]). A token omher itself
//!   inherited is never passed on (`sessions::command_for` removes it). The token lives in Rust only: it is in the
//!   program's environment and in this module's memory, never in a message to the page and never in a log.
//! - The session's reader hands every PTY read to [`Tap::feed`], which picks out `ESC ] 7577 ; body (ST | BEL)` and
//!   nothing else ([`Scanner`]). A report is checked in the spec's order: the mac (SHA-256 of the body before `:mac=`,
//!   then `:`, then the token) and the time (within [`TIME_WINDOW`] of the clock and never earlier than the last
//!   accepted report of the same pid) first, and a report cut short or longer than [`MAX_BODY`] bytes is **ignored**
//!   ([`verify`]). Then the strict parse ([`parse`]) and the pid check (alive, this user, the terminal's first process
//!   or one of its descendants); a failure **rejects** the report and removes its owner's record.
//! - An accepted report is the terminal's one record ([`Record`]: argv, cwd, pid, its start time, the user), keyed by
//!   the TERMINALS row's link id, written at once to `~/.omher/resume/resume.json` (dir 0700, file 0600). It goes on
//!   `clear=1`, on a rejection, when its owner exits while the terminal lives on ([`OWNER_GRACE`]), and when the
//!   terminal ends for good or its row is closed. It stays when omher quits or crashes.
//! - Restoring ([`Store::take`], [`Launch`]): the record leaves the store before anything starts (one-shot; a failed
//!   resume is not retried). omher starts the person's shell in the record's cwd and, once it is at its first prompt,
//!   types one fixed line: `'<omher>' --resume-exec '<launch file>'`. The argv is in that one-use 0600 launch file;
//!   [`resume_exec`] checks it is this user's private file, deletes it, and starts the program with each element as
//!   one argument (`exec`, never shell source: `$(…)` and `a; b` stay text). No resume as root; not on Windows.
#![cfg_attr(not(unix), allow(dead_code))]

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// The environment variable a program finds its token in.
pub const TOKEN_ENV: &str = "OSC7577_TOKEN";
/// Longest report body read; a longer one is ignored.
pub const MAX_BODY: usize = 4096;
/// A report's `time` may differ from the clock by at most this many seconds.
pub const TIME_WINDOW: u64 = 60;
/// At most this many argv elements.
pub const MAX_ARGV: usize = 128;
/// At most this many records are kept.
pub const MAX_RECORDS: usize = 256;
/// A record's owner that exits while its terminal lives on loses its record after this long.
pub const OWNER_GRACE: Duration = Duration::from_secs(2);
/// The flag `main.rs` hands to [`resume_exec`].
pub const EXEC_FLAG: &str = "--resume-exec";

// ---------------------------------------------------------------------------------------------
// Token and encodings
// ---------------------------------------------------------------------------------------------

const B64URL: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const B64STD: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// A new token: 24 random bytes (192 bits) as 32 characters of `[A-Za-z0-9_-]`. `None` when the system has no
/// randomness to give (the terminal then gets no token).
pub fn new_token() -> Option<String> {
    let mut b = [0u8; 24];
    getrandom::fill(&mut b).ok()?;
    let mut s = String::with_capacity(32);
    for c in b.chunks(3) {
        let n = (c[0] as u32) << 16 | (c[1] as u32) << 8 | c[2] as u32;
        for k in (0..4).rev() {
            s.push(B64URL[((n >> (6 * k)) & 63) as usize] as char);
        }
    }
    Some(s)
}

/// Standard base64 with optional padding; padding that is present must be the right amount, and the unused bits of
/// the last character must be zero.
pub fn b64_decode(s: &str) -> Option<Vec<u8>> {
    let b = s.as_bytes();
    let body = b.iter().position(|c| *c == b'=').map_or(b, |i| &b[..i]);
    let pad = b.len() - body.len();
    if b[body.len()..].iter().any(|c| *c != b'=') || body.len() % 4 == 1 {
        return None;
    }
    if pad > 0 && (body.len() + pad) % 4 != 0 {
        return None;
    }
    let val = |c: u8| B64STD.iter().position(|x| *x == c).map(|v| v as u32);
    let mut out = Vec::with_capacity(body.len() * 3 / 4);
    for chunk in body.chunks(4) {
        let mut n = 0u32;
        for (i, c) in chunk.iter().enumerate() {
            n |= val(*c)? << (18 - 6 * i);
        }
        let bytes = [(n >> 16) as u8, (n >> 8) as u8, n as u8];
        let keep = chunk.len() * 6 / 8;
        // the bits past the last whole byte must be zero (one encoding per value)
        let used = chunk.len() * 6;
        if used % 8 != 0 && (n >> (24 - used)) & ((1 << (used % 8)) - 1) != 0 {
            return None;
        }
        out.extend_from_slice(&bytes[..keep]);
    }
    Some(out)
}

fn b64_encode(b: &[u8]) -> String {
    let mut s = String::new();
    for c in b.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        for k in 0..=c.len() {
            s.push(B64STD[((n >> (18 - 6 * k)) & 63) as usize] as char);
        }
        for _ in c.len()..3 {
            s.push('=');
        }
    }
    s
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// The mac of `prefix` (the body before `:mac=`) under `token`.
pub fn mac(prefix: &[u8], token: &str) -> String {
    let mut h = Sha256::new();
    h.update(prefix);
    h.update(b":");
    h.update(token.as_bytes());
    hex(&h.finalize())
}

/// Text with a control character (C0, DEL, C1) is refused.
fn has_control(s: &str) -> bool {
    s.chars().any(|c| (c as u32) < 0x20 || (0x7f..=0x9f).contains(&(c as u32)))
}

/// `s` with control characters and direction overrides shown as `\uXXXX`, for display.
pub fn escaped(s: &str) -> String {
    s.chars()
        .map(|c| {
            let u = c as u32;
            if u < 0x20 || (0x7f..=0x9f).contains(&u) || (0x200e..=0x200f).contains(&u) || (0x202a..=0x202e).contains(&u) || (0x2066..=0x2069).contains(&u) {
                format!("\\u{u:04X}")
            } else {
                c.to_string()
            }
        })
        .collect()
}

// ---------------------------------------------------------------------------------------------
// Scanner: OSC 7577 only
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum St {
    Ground,
    Esc,
    /// matched this many bytes of `7577;` after `ESC ]`
    Prefix(usize),
    Body,
    BodyEsc,
    /// longer than [`MAX_BODY`]: skipped to its end, ignored
    Over,
    OverEsc,
}

/// Picks whole `ESC ] 7577 ; body ST|BEL` bodies out of a byte stream that arrives in pieces.
pub struct Scanner {
    st: St,
    body: Vec<u8>,
}

impl Default for Scanner {
    fn default() -> Self {
        Scanner { st: St::Ground, body: Vec::new() }
    }
}

const PREFIX: &[u8] = b"7577;";

impl Scanner {
    /// Feed `bytes`; every whole body found is handed to `found`. A body cut short (another control byte, an ESC not
    /// followed by `\`) or too long never is.
    pub fn feed(&mut self, mut bytes: &[u8], found: &mut dyn FnMut(&[u8])) {
        while !bytes.is_empty() {
            if self.st == St::Ground {
                match bytes.iter().position(|b| *b == 0x1b) {
                    Some(i) => {
                        self.st = St::Esc;
                        bytes = &bytes[i + 1..];
                    }
                    None => return,
                }
                continue;
            }
            let b = bytes[0];
            bytes = &bytes[1..];
            self.st = match self.st {
                St::Ground => unreachable!(),
                St::Esc if b == b']' => St::Prefix(0),
                St::Esc if b == 0x1b => St::Esc,
                St::Esc => St::Ground,
                St::Prefix(n) if b == PREFIX[n] => {
                    if n + 1 == PREFIX.len() {
                        self.body.clear();
                        St::Body
                    } else {
                        St::Prefix(n + 1)
                    }
                }
                St::Prefix(_) if b == 0x1b => St::Esc,
                St::Prefix(_) => St::Ground,
                St::Body if b == 0x07 => {
                    found(&self.body);
                    St::Ground
                }
                St::Body if b == 0x1b => St::BodyEsc,
                // any other control byte cuts it short
                St::Body if b < 0x20 || b == 0x7f => St::Ground,
                St::Body if self.body.len() >= MAX_BODY => St::Over,
                St::Body => {
                    self.body.push(b);
                    St::Body
                }
                St::BodyEsc if b == b'\\' => {
                    found(&self.body);
                    St::Ground
                }
                St::BodyEsc if b == b']' => St::Prefix(0),
                St::BodyEsc if b == 0x1b => St::Esc,
                St::BodyEsc => St::Ground,
                St::Over if b == 0x07 => St::Ground,
                St::Over if b == 0x1b => St::OverEsc,
                St::Over if b < 0x20 => St::Ground,
                St::Over => St::Over,
                St::OverEsc if b == b']' => St::Prefix(0),
                St::OverEsc => St::Ground,
            };
            if self.st != St::Body && self.st != St::Over {
                // nothing to keep between sequences
                if matches!(self.st, St::Ground) {
                    self.body.clear();
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Checks
// ---------------------------------------------------------------------------------------------

/// What passed the mac and time checks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Verified {
    pub time: u64,
    /// the owner, when the body names a usable one (a rejection removes its record)
    pub pid: Option<u32>,
}

fn digits(v: &str) -> Option<u64> {
    if v.is_empty() || v.starts_with('0') || !v.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    v.parse().ok()
}

/// The mac and time checks, before anything else is read: `None` means the report is ignored. `last` is the time of
/// the last report accepted for a pid.
pub fn verify(body: &[u8], token: &str, now: u64, last: &dyn Fn(u32) -> Option<u64>) -> Option<Verified> {
    if body.len() > MAX_BODY || body == b"?" {
        return None;
    }
    let at = body.windows(5).rposition(|w| w == b":mac=")?;
    let (prefix, sent) = (&body[..at], &body[at + 5..]);
    if sent.len() != 64 || !sent.iter().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(c)) {
        return None;
    }
    let want = mac(prefix, token);
    // compared in full whatever differs first
    if want.bytes().zip(sent.iter()).fold(0u8, |acc, (a, b)| acc | (a ^ b)) != 0 {
        return None;
    }
    let text = std::str::from_utf8(prefix).ok()?;
    let pair = |k: &str| text.split(':').find_map(|p| p.strip_prefix(k).and_then(|r| r.strip_prefix('=')));
    let time = digits(pair("time")?)?;
    if time.abs_diff(now) > TIME_WINDOW {
        return None;
    }
    let pid = pair("pid").and_then(digits).and_then(|p| u32::try_from(p).ok());
    if let Some(p) = pid {
        if last(p).is_some_and(|t| time < t) {
            return None;
        }
    }
    Some(Verified { time, pid })
}

/// What a verified report asks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Report {
    Set { pid: u32, argv: Vec<String>, cwd: Option<String> },
    Clear { pid: u32 },
}

/// Why a verified report is rejected (its owner's record goes).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reject {
    Malformed,
    Repeated,
    BadValue,
    Missing,
    TooMany,
    Need,
    Pid,
}

fn decode_text(v: &str) -> Result<String, Reject> {
    let b = b64_decode(v).ok_or(Reject::BadValue)?;
    let s = String::from_utf8(b).map_err(|_| Reject::BadValue)?;
    if has_control(&s) {
        return Err(Reject::BadValue);
    }
    Ok(s)
}

/// The strict parse of a verified body (everything before `:mac=`).
pub fn parse(prefix: &str) -> Result<Report, Reject> {
    let mut pairs: BTreeMap<&str, &str> = BTreeMap::new();
    for p in prefix.split(':') {
        let (k, v) = p.split_once('=').ok_or(Reject::Malformed)?;
        if k.is_empty() || !k.bytes().all(|b| b.is_ascii_lowercase()) {
            return Err(Reject::Malformed);
        }
        if !v.bytes().all(|b| b.is_ascii_alphanumeric() || b"_.,+/=-".contains(&b)) {
            return Err(Reject::Malformed);
        }
        if k == "mac" || pairs.insert(k, v).is_some() {
            return Err(Reject::Repeated);
        }
    }
    const KNOWN: [&str; 6] = ["pid", "time", "argv", "cwd", "clear", "need"];
    if let Some(need) = pairs.get("need") {
        for n in need.split(',') {
            if !KNOWN.contains(&n) && n != "mac" {
                return Err(Reject::Need);
            }
        }
    }
    let pid = pairs.get("pid").ok_or(Reject::Missing).and_then(|v| digits(v).and_then(|p| u32::try_from(p).ok()).ok_or(Reject::BadValue))?;
    pairs.get("time").ok_or(Reject::Missing).and_then(|v| digits(v).ok_or(Reject::BadValue))?;
    match (pairs.get("argv"), pairs.get("clear")) {
        (Some(_), Some(_)) | (None, None) => Err(Reject::Missing),
        (None, Some(c)) => {
            if *c != "1" {
                return Err(Reject::BadValue);
            }
            Ok(Report::Clear { pid })
        }
        (Some(a), None) => {
            let parts: Vec<&str> = a.split(',').collect();
            if parts.len() > MAX_ARGV {
                return Err(Reject::TooMany);
            }
            let argv = parts.into_iter().map(decode_text).collect::<Result<Vec<_>, _>>()?;
            let first = &argv[0];
            let bare = !first.contains('/') && !first.starts_with('-');
            if first.is_empty() || !(first.starts_with('/') || bare) {
                return Err(Reject::BadValue);
            }
            let cwd = match pairs.get("cwd") {
                Some(c) => {
                    let c = decode_text(c)?;
                    if !c.starts_with('/') {
                        return Err(Reject::BadValue);
                    }
                    Some(c)
                }
                None => None,
            };
            Ok(Report::Set { pid, argv, cwd })
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Processes
// ---------------------------------------------------------------------------------------------

/// What omher reads of a process: its parent, its user and when it started.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Proc {
    pub ppid: u32,
    pub uid: u32,
    pub start: i64,
}

#[cfg(target_os = "macos")]
pub fn proc_info(pid: u32) -> Option<Proc> {
    let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
    let size = std::mem::size_of::<libc::proc_bsdinfo>() as libc::c_int;
    let n = unsafe { libc::proc_pidinfo(pid as libc::c_int, libc::PROC_PIDTBSDINFO, 0, (&mut info as *mut libc::proc_bsdinfo).cast(), size) };
    (n == size).then_some(Proc { ppid: info.pbi_ppid, uid: info.pbi_uid, start: info.pbi_start_tvsec as i64 * 1_000_000 + info.pbi_start_tvusec as i64 })
}

#[cfg(all(unix, not(target_os = "macos")))]
pub fn proc_info(pid: u32) -> Option<Proc> {
    use std::os::unix::fs::MetadataExt;
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let rest: Vec<&str> = stat.rsplit_once(')')?.1.split_whitespace().collect();
    // a zombie is gone
    if rest.first() == Some(&"Z") {
        return None;
    }
    let ppid = rest.get(1)?.parse().ok()?;
    let start = rest.get(19)?.parse().ok()?;
    let uid = std::fs::metadata(format!("/proc/{pid}")).ok()?.uid();
    Some(Proc { ppid, uid, start })
}

#[cfg(not(unix))]
pub fn proc_info(_pid: u32) -> Option<Proc> {
    None
}

/// The directory process `pid` is in, read from the system (never OSC 7).
#[cfg(target_os = "macos")]
fn proc_cwd(pid: u32) -> Option<String> {
    let mut info: libc::proc_vnodepathinfo = unsafe { std::mem::zeroed() };
    let size = std::mem::size_of::<libc::proc_vnodepathinfo>() as libc::c_int;
    let n = unsafe { libc::proc_pidinfo(pid as libc::c_int, libc::PROC_PIDVNODEPATHINFO, 0, (&mut info as *mut libc::proc_vnodepathinfo).cast(), size) };
    if n != size {
        return None;
    }
    let raw: &[u8] = unsafe { std::slice::from_raw_parts(info.pvi_cdir.vip_path.as_ptr().cast(), 1024) };
    let end = raw.iter().position(|b| *b == 0)?;
    String::from_utf8(raw[..end].to_vec()).ok().filter(|s| s.starts_with('/') && !has_control(s))
}

#[cfg(all(unix, not(target_os = "macos")))]
fn proc_cwd(pid: u32) -> Option<String> {
    std::fs::read_link(format!("/proc/{pid}/cwd")).ok()?.to_str().map(str::to_string).filter(|s| s.starts_with('/') && !has_control(s))
}

#[cfg(not(unix))]
fn proc_cwd(_pid: u32) -> Option<String> {
    None
}

#[cfg(unix)]
fn my_uid() -> u32 {
    unsafe { libc::getuid() }
}

#[cfg(unix)]
pub fn is_root() -> bool {
    unsafe { libc::geteuid() == 0 }
}

#[cfg(not(unix))]
fn my_uid() -> u32 {
    0
}

#[cfg(not(unix))]
pub fn is_root() -> bool {
    false
}

/// Whether this machine takes part: unix, not as root.
pub fn supported() -> bool {
    cfg!(unix) && !is_root()
}

/// Process `pid` runs as this user and is `root` or one of its descendants. `info` reads a process.
pub fn owned_by_terminal(pid: u32, root: u32, uid: u32, info: &dyn Fn(u32) -> Option<Proc>) -> Option<Proc> {
    let me = info(pid)?;
    if me.uid != uid {
        return None;
    }
    let mut at = pid;
    let mut p = me;
    for _ in 0..256 {
        if at == root {
            return Some(me);
        }
        if p.ppid <= 1 || p.ppid == at {
            return None;
        }
        at = p.ppid;
        p = info(at)?;
    }
    None
}

// ---------------------------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------------------------

/// One terminal's record: what brings its program back.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Record {
    pub argv: Vec<String>,
    /// the report's `cwd`, else the owner's directory read from the system
    pub cwd: Option<String>,
    /// `cwd` came from the report: a gone folder then drops the record
    #[serde(default)]
    pub cwd_reported: bool,
    pub pid: u32,
    pub start: i64,
    pub uid: u32,
    pub time: u64,
    /// which start of the terminal it belongs to (a later start of the same row is another)
    #[serde(default)]
    pub run: u64,
}

#[derive(Default, Serialize, Deserialize)]
struct File {
    #[serde(default)]
    records: BTreeMap<String, Record>,
}

/// The records, kept in `<dir>/resume.json`.
pub struct Store {
    dir: PathBuf,
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    records: BTreeMap<String, Record>,
    /// the time of the last accepted report per pid
    last: HashMap<u32, u64>,
}

#[cfg(unix)]
fn private_dir(dir: &Path) -> std::io::Result<()> {
    use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
    std::fs::DirBuilder::new().recursive(true).mode(0o700).create(dir)?;
    std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700))
}

#[cfg(not(unix))]
fn private_dir(dir: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dir)
}

/// Write `bytes` to `path` as a new 0600 file (through a temporary file and a rename).
fn write_private(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    use std::io::Write;
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    let _ = std::fs::remove_file(&tmp);
    let mut o = std::fs::OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut o, 0o600);
    let mut f = o.open(&tmp)?;
    f.write_all(bytes)?;
    f.sync_all()?;
    drop(f);
    std::fs::rename(&tmp, path)
}

/// `~/.omher/resume`.
pub fn default_dir(home: &Path) -> PathBuf {
    home.join(".omher").join("resume")
}

impl Store {
    /// The store in `dir`: its records read back, and launch files a former run left removed.
    pub fn open(dir: PathBuf) -> Arc<Store> {
        let records = std::fs::read(dir.join("resume.json")).ok().and_then(|b| serde_json::from_slice::<File>(&b).ok()).map(|f| f.records).unwrap_or_default();
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for e in rd.flatten() {
                if e.file_name().to_str().is_some_and(|n| n.starts_with("launch-")) {
                    let _ = std::fs::remove_file(e.path());
                }
            }
        }
        Arc::new(Store { dir, inner: Mutex::new(Inner { records, last: HashMap::new() }) })
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    fn save(&self, records: &BTreeMap<String, Record>) {
        if private_dir(&self.dir).is_err() {
            return;
        }
        if let Ok(b) = serde_json::to_vec(&File { records: records.clone() }) {
            let _ = write_private(&self.dir.join("resume.json"), &b);
        }
    }

    fn last(&self, pid: u32) -> Option<u64> {
        self.inner.lock().unwrap().last.get(&pid).copied()
    }

    pub fn get(&self, key: &str) -> Option<Record> {
        self.inner.lock().unwrap().records.get(key).cloned()
    }

    fn put(&self, key: &str, r: Record) -> bool {
        let mut g = self.inner.lock().unwrap();
        if !g.records.contains_key(key) && g.records.len() >= MAX_RECORDS {
            return false;
        }
        g.last.insert(r.pid, r.time);
        g.records.insert(key.to_string(), r);
        self.save(&g.records);
        true
    }

    /// Remove `key`'s record when `keep` says it is the one meant.
    fn remove_if(&self, key: &str, keep: impl Fn(&Record) -> bool) {
        let mut g = self.inner.lock().unwrap();
        if g.records.get(key).is_some_and(keep) {
            g.records.remove(key);
            self.save(&g.records);
        }
    }

    /// Take `key`'s record out of the store (it is gone from the file before this returns): a resume runs it once.
    pub fn take(&self, key: &str) -> Option<Record> {
        let mut g = self.inner.lock().unwrap();
        let r = g.records.remove(key)?;
        self.save(&g.records);
        Some(r)
    }

    /// After omher started: the records of `keep` stay and each one's program name comes back; every other record goes
    /// (a row that is gone, or one that comes back by its own CLI's id).
    pub fn restore(&self, keep: &[String]) -> Vec<(String, String)> {
        let mut g = self.inner.lock().unwrap();
        let before = g.records.len();
        g.records.retain(|k, _| keep.contains(k));
        if g.records.len() != before {
            self.save(&g.records);
        }
        g.records.iter().map(|(k, r)| (k.clone(), label(&r.argv))).collect()
    }

    pub fn keys(&self) -> Vec<String> {
        self.inner.lock().unwrap().records.keys().cloned().collect()
    }
}

/// The name a row shows for a record: its program's file name, escaped.
pub fn label(argv: &[String]) -> String {
    let first = argv.first().map(String::as_str).unwrap_or("");
    escaped(first.rsplit('/').next().unwrap_or(first))
}

// ---------------------------------------------------------------------------------------------
// One terminal's tap
// ---------------------------------------------------------------------------------------------

/// How a terminal ended, for its record.
pub const LIVE: u8 = 0;
/// The person closed its row: the record goes.
pub const CLOSED: u8 = 1;
/// omher is quitting (or the page reloaded): the record stays.
pub const QUITTING: u8 = 2;

/// What the session and the tap share.
pub struct TapState {
    pub end: AtomicU8,
    pub exited: Arc<AtomicBool>,
    pub key: Option<String>,
    pub run: u64,
    pub store: Arc<Store>,
}

impl TapState {
    /// The terminal's program ended: unless omher is quitting, its record goes (it ended for good).
    pub fn program_ended(&self) {
        if self.end.load(Ordering::SeqCst) != QUITTING {
            self.drop_record();
        }
    }

    /// The row was closed.
    pub fn closed(&self) {
        if self.end.compare_exchange(LIVE, CLOSED, Ordering::SeqCst, Ordering::SeqCst).is_ok() {
            self.drop_record();
        }
    }

    pub fn quitting(&self) {
        let _ = self.end.compare_exchange(LIVE, QUITTING, Ordering::SeqCst, Ordering::SeqCst);
    }

    fn drop_record(&self) {
        if let Some(k) = &self.key {
            let run = self.run;
            self.store.remove_if(k, |r| r.run == run);
        }
    }
}

/// A terminal's watch over its own output.
pub struct Tap {
    token: String,
    root: Option<u32>,
    scanner: Scanner,
    pub state: Arc<TapState>,
}

fn now_secs() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// What one report did, for the tests.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    Ignored,
    Rejected(Reject),
    Accepted,
    Cleared,
}

impl Tap {
    pub fn new(token: String, root: Option<u32>, state: Arc<TapState>) -> Tap {
        Tap { token, root, scanner: Scanner::default(), state }
    }

    /// The bytes the terminal's program printed.
    pub fn feed(&mut self, bytes: &[u8]) {
        let mut bodies: Vec<Vec<u8>> = Vec::new();
        self.scanner.feed(bytes, &mut |b| bodies.push(b.to_vec()));
        for b in bodies {
            self.report(&b, now_secs(), &proc_info);
        }
    }

    /// One whole report body.
    pub fn report(&self, body: &[u8], now: u64, info: &dyn Fn(u32) -> Option<Proc>) -> Outcome {
        let st = &self.state;
        if !supported() {
            return Outcome::Ignored;
        }
        let Some(v) = verify(body, &self.token, now, &|p| st.store.last(p)) else { return Outcome::Ignored };
        let at = body.windows(5).rposition(|w| w == b":mac=").unwrap_or(0);
        let reject = |why: Reject| {
            if let (Some(k), Some(owner)) = (&st.key, v.pid) {
                st.store.remove_if(k, |r| r.pid == owner);
            }
            Outcome::Rejected(why)
        };
        let report = match std::str::from_utf8(&body[..at]).map_err(|_| Reject::Malformed).and_then(parse) {
            Ok(r) => r,
            Err(why) => return reject(why),
        };
        let pid = match &report {
            Report::Set { pid, .. } | Report::Clear { pid } => *pid,
        };
        let uid = my_uid();
        let Some(owner) = self.root.and_then(|root| owned_by_terminal(pid, root, uid, info)) else { return reject(Reject::Pid) };
        let Some(key) = &st.key else { return Outcome::Accepted };
        match report {
            Report::Clear { pid } => {
                st.store.remove_if(key, |r| r.pid == pid);
                st.store.inner.lock().unwrap().last.insert(pid, v.time);
                Outcome::Cleared
            }
            Report::Set { pid, argv, cwd } => {
                let cwd_reported = cwd.is_some();
                let cwd = cwd.or_else(|| proc_cwd(pid));
                let rec = Record { argv, cwd, cwd_reported, pid, start: owner.start, uid, time: v.time, run: st.run };
                if !st.store.put(key, rec) {
                    return reject(Reject::TooMany);
                }
                watch_owner(st.clone(), pid, owner.start);
                Outcome::Accepted
            }
        }
    }
}

/// A run number for a terminal start.
pub fn new_run() -> u64 {
    let mut b = [0u8; 8];
    let _ = getrandom::fill(&mut b);
    u64::from_le_bytes(b)
}

/// While `pid` (started at `start`) owns the terminal's record: once it is gone and the terminal still lives
/// [`OWNER_GRACE`] later, the record goes.
fn watch_owner(st: Arc<TapState>, pid: u32, start: i64) {
    let Some(key) = st.key.clone() else { return };
    let ours = move |st: &TapState| st.store.get(&key).is_some_and(|r| r.pid == pid && r.start == start && r.run == st.run);
    let _ = std::thread::Builder::new().name("omher-resume-owner".into()).spawn(move || loop {
        std::thread::sleep(Duration::from_millis(500));
        if !ours(&st) || st.exited.load(Ordering::SeqCst) {
            return;
        }
        if proc_info(pid).is_some_and(|p| p.start == start) {
            continue;
        }
        std::thread::sleep(OWNER_GRACE);
        if ours(&st) && !st.exited.load(Ordering::SeqCst) && st.end.load(Ordering::SeqCst) == LIVE {
            let k = st.key.clone().unwrap_or_default();
            st.store.remove_if(&k, |r| r.pid == pid && r.start == start);
        }
        return;
    });
}

// ---------------------------------------------------------------------------------------------
// Resuming
// ---------------------------------------------------------------------------------------------

/// What a launch file holds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LaunchFile {
    pub argv: Vec<String>,
    pub cwd: Option<String>,
}

/// A record on its way back: where its shell starts and the launch file the typed line names.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Launch {
    pub cwd: Option<PathBuf>,
    pub file: PathBuf,
    pub label: String,
}

/// Shells that take the typed line as written.
pub const TYPED_SHELLS: [&str; 10] = ["sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "yash", "loksh", "fish"];

/// Make the launch for record `r` (already taken out of the store): `None` (the record is dropped) when it is another
/// user's, omher runs as root, or the folder it reported is gone.
pub fn prepare(r: &Record, dir: &Path) -> Option<Launch> {
    if !supported() || r.uid != my_uid() || r.argv.is_empty() {
        return None;
    }
    let cwd = match &r.cwd {
        Some(c) if Path::new(c).is_dir() => Some(PathBuf::from(c)),
        Some(_) if r.cwd_reported => return None,
        _ => None,
    };
    private_dir(dir).ok()?;
    let mut rnd = [0u8; 12];
    getrandom::fill(&mut rnd).ok()?;
    let file = dir.join(format!("launch-{}.json", hex(&rnd)));
    let lf = LaunchFile { argv: r.argv.clone(), cwd: cwd.as_ref().map(|c| c.to_string_lossy().into_owned()) };
    write_private(&file, &serde_json::to_vec(&lf).ok()?).ok()?;
    Some(Launch { cwd, file, label: label(&r.argv) })
}

/// A path that is typed inside single quotes the same way by every shell in [`TYPED_SHELLS`].
fn plain_quoted(p: &Path) -> Option<String> {
    let s = p.to_str()?;
    if s.is_empty() || s.contains('\'') || s.contains('\\') || has_control(s) {
        return None;
    }
    Some(format!("'{s}'"))
}

/// The one line typed at the shell's first prompt (without its Enter): omher's own program and the launch file, both
/// paths omher chose; no byte of the record's argv or cwd is in it. A leading space keeps it out of shells' history
/// where they allow.
pub fn typed_line(helper: &Path, launch: &Path) -> Option<String> {
    Some(format!(" {} {EXEC_FLAG} {}", plain_quoted(helper)?, plain_quoted(launch)?))
}

/// Whether `shell` (a path) takes the typed line.
pub fn types_into(shell: &Path) -> bool {
    shell.file_name().and_then(|n| n.to_str()).is_some_and(|n| TYPED_SHELLS.contains(&n.trim_start_matches('-')))
}

/// Why `omher --resume-exec` refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExecError {
    Root,
    NotPrivate,
    Read,
    Bad,
    NotFound,
}

/// Read and delete launch file `file` (it must be in `dir`, this user's, a plain 0600 file), and say which program
/// runs, with which arguments, in which folder. `path` is the `PATH` a bare name is looked up on.
pub fn exec_plan(file: &Path, dir: &Path, path: Option<&std::ffi::OsStr>) -> Result<(PathBuf, Vec<String>, Option<PathBuf>), ExecError> {
    if !supported() {
        return Err(ExecError::Root);
    }
    let name_ok = file.file_name().and_then(|n| n.to_str()).is_some_and(|n| n.starts_with("launch-") && n.ends_with(".json"));
    let in_dir = file.parent().and_then(|p| p.canonicalize().ok()) == dir.canonicalize().ok();
    if !name_ok || !in_dir {
        return Err(ExecError::NotPrivate);
    }
    let meta = std::fs::symlink_metadata(file).map_err(|_| ExecError::Read)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if !meta.file_type().is_file() || meta.uid() != my_uid() || meta.mode() & 0o077 != 0 {
            return Err(ExecError::NotPrivate);
        }
    }
    #[cfg(not(unix))]
    let _ = meta;
    let bytes = std::fs::read(file).map_err(|_| ExecError::Read)?;
    std::fs::remove_file(file).map_err(|_| ExecError::Read)?;
    let lf: LaunchFile = serde_json::from_slice(&bytes).map_err(|_| ExecError::Bad)?;
    let first = lf.argv.first().ok_or(ExecError::Bad)?;
    if lf.argv.iter().any(|a| has_control(a)) || first.is_empty() {
        return Err(ExecError::Bad);
    }
    let program = if first.starts_with('/') {
        PathBuf::from(first)
    } else if first.contains('/') || first.starts_with('-') {
        return Err(ExecError::Bad);
    } else {
        find_on_path(first, path).ok_or(ExecError::NotFound)?
    };
    let cwd = lf.cwd.map(PathBuf::from);
    if cwd.as_ref().is_some_and(|c| !c.is_absolute()) {
        return Err(ExecError::Bad);
    }
    Ok((program, lf.argv, cwd))
}

fn find_on_path(name: &str, path: Option<&std::ffi::OsStr>) -> Option<PathBuf> {
    std::env::split_paths(path?).filter(|d| d.is_absolute()).map(|d| d.join(name)).find(|p| is_executable(p))
}

#[cfg(unix)]
fn is_executable(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(p).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

#[cfg(not(unix))]
fn is_executable(p: &Path) -> bool {
    p.is_file()
}

/// The command a plan runs: the program, the record's first element as its own name, every other element as one
/// argument each. Nothing passes through a shell.
pub fn exec_command(program: &Path, argv: &[String], cwd: Option<&Path>) -> std::process::Command {
    let mut c = std::process::Command::new(program);
    #[cfg(unix)]
    std::os::unix::process::CommandExt::arg0(&mut c, &argv[0]);
    c.args(&argv[1..]);
    if let Some(d) = cwd {
        c.current_dir(d);
    }
    c.env_remove(TOKEN_ENV);
    // inside a Linux AppImage the program gets the host's library paths, as every program omher starts
    crate::appimage::host_env(&mut c);
    c
}

/// `omher --resume-exec <launch file>`: run the launch file's program in place of this process (the shell's
/// foreground job). `None` when the arguments are not this.
pub fn resume_exec(args: &[std::ffi::OsString], home: Option<PathBuf>) -> Option<i32> {
    if args.get(1)?.to_str()? != EXEC_FLAG {
        return None;
    }
    let fail = |why: &str| {
        eprintln!("omher: the program could not be brought back ({why})");
        Some(126)
    };
    let (Some(file), Some(home)) = (args.get(2), home) else { return fail("no launch file") };
    let plan = exec_plan(Path::new(file), &default_dir(&home), std::env::var_os("PATH").as_deref());
    let (program, argv, cwd) = match plan {
        Ok(p) => p,
        Err(ExecError::NotFound) => return fail("not found on PATH"),
        Err(e) => return fail(&format!("{e:?}")),
    };
    let mut cmd = exec_command(&program, &argv, cwd.as_deref());
    #[cfg(unix)]
    {
        let err = std::os::unix::process::CommandExt::exec(&mut cmd);
        eprintln!("omher: {}: {err}", escaped(&program.to_string_lossy()));
        Some(127)
    }
    #[cfg(not(unix))]
    {
        let _ = &mut cmd;
        fail("not supported here")
    }
}

/// For tests and callers: a valid report body for `token`.
pub fn report_body(pairs: &str, token: &str) -> String {
    format!("{pairs}:mac={}", mac(pairs.as_bytes(), token))
}

/// `argv` as the report's `argv=` value.
pub fn argv_value(argv: &[&str]) -> String {
    argv.iter().map(|a| b64_encode(a.as_bytes())).collect::<Vec<_>>().join(",")
}

pub fn b64(s: &str) -> String {
    b64_encode(s.as_bytes())
}

#[cfg(test)]
#[cfg(unix)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    const TOKEN: &str = "abcdefghijklmnopqrstuvwxyz012345";
    const NOW: u64 = 1_795_543_200;

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("omher-pr-{name}-{}-{}", std::process::id(), new_run()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn tap(dir: &Path, root: u32) -> Tap {
        let st = Arc::new(TapState { end: AtomicU8::new(LIVE), exited: Arc::new(AtomicBool::new(false)), key: Some("abcdefgh23".into()), run: 7, store: Store::open(dir.to_path_buf()) });
        Tap::new(TOKEN.into(), Some(root), st)
    }

    /// A process table: 100 (the terminal's first process) → 200 → 300; 400 another user's child of 100.
    fn table(pid: u32) -> Option<Proc> {
        let uid = my_uid();
        match pid {
            100 => Some(Proc { ppid: 1, uid, start: 1 }),
            200 => Some(Proc { ppid: 100, uid, start: 2 }),
            300 => Some(Proc { ppid: 200, uid, start: 3 }),
            400 => Some(Proc { ppid: 100, uid: uid + 1, start: 4 }),
            500 => Some(Proc { ppid: 1, uid, start: 5 }),
            _ => None,
        }
    }

    fn set(pid: u32, time: u64, argv: &[&str], extra: &str) -> String {
        report_body(&format!("pid={pid}:time={time}:argv={}{extra}", argv_value(argv)), TOKEN)
    }

    #[test]
    fn program_resume_token_is_32_url_safe_chars_and_new_each_time() {
        let a = new_token().unwrap();
        let b = new_token().unwrap();
        assert_eq!(a.len(), 32);
        assert!(a.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_'), "{a}");
        assert_ne!(a, b);
    }

    #[test]
    fn program_resume_base64_round_trip_and_strict_padding() {
        for s in ["", "a", "ab", "abc", "nvim", "/home/user/x.vim", "$(touch pwned)"] {
            assert_eq!(b64_decode(&b64(s)).unwrap(), s.as_bytes());
            assert_eq!(b64_decode(b64(s).trim_end_matches('=')).unwrap(), s.as_bytes());
        }
        assert_eq!(b64_decode("LVM=").unwrap(), b"-S");
        assert!(b64_decode("LVM==").is_none());
        assert!(b64_decode("LV=").is_none());
        assert!(b64_decode("L").is_none());
        assert!(b64_decode("LVN").is_none(), "non-zero trailing bits");
    }

    #[test]
    fn program_resume_spec_example_mac() {
        // the spec's example: the mac of `pid=74877:time=1795543200:clear=1` with token dummy-token-replace-me
        let want = {
            let mut h = Sha256::new();
            h.update(b"pid=74877:time=1795543200:clear=1:dummy-token-replace-me");
            hex(&h.finalize())
        };
        assert_eq!(mac(b"pid=74877:time=1795543200:clear=1", "dummy-token-replace-me"), want);
    }

    #[test]
    fn program_resume_scanner_takes_only_7577_across_pieces() {
        let body = set(200, NOW, &["nvim"], "");
        let stream = format!("hello\x1b]0;title\x07\x1b]7577;{body}\x1b\\tail\x1b]7577;{body}\x07\x1b]7577;cut\x1b[0m");
        for step in [1, 3, 7, 4096] {
            let mut sc = Scanner::default();
            let mut got = Vec::new();
            for piece in stream.as_bytes().chunks(step) {
                sc.feed(piece, &mut |b| got.push(b.to_vec()));
            }
            assert_eq!(got, vec![body.as_bytes().to_vec(), body.as_bytes().to_vec()], "step {step}");
        }
        // one byte over the limit is never handed on, and what follows still is
        let mut sc = Scanner::default();
        let mut got = Vec::new();
        let long = "a".repeat(MAX_BODY + 1);
        sc.feed(format!("\x1b]7577;{long}\x07\x1b]7577;{body}\x07").as_bytes(), &mut |b| got.push(b.to_vec()));
        assert_eq!(got, vec![body.as_bytes().to_vec()]);
        let mut got = Vec::new();
        let exact = "a".repeat(MAX_BODY);
        Scanner::default().feed(format!("\x1b]7577;{exact}\x07").as_bytes(), &mut |b| got.push(b.len()));
        assert_eq!(got, vec![MAX_BODY]);
    }

    #[test]
    fn program_resume_report_table() {
        let dir = tmp("table");
        let t = tap(&dir, 100);
        let key = "abcdefgh23";
        let ok = set(200, NOW, &["nvim", "-S", "/s.vim"], &format!(":cwd={}", b64("/tmp")));
        let wrong_mac = {
            let mut b = ok.clone();
            let last = b.pop().unwrap();
            b.push(if last == '0' { '1' } else { '0' });
            b
        };
        // valid
        assert_eq!(t.report(ok.as_bytes(), NOW, &table), Outcome::Accepted);
        let r = t.state.store.get(key).unwrap();
        assert_eq!((r.argv.clone(), r.cwd.clone(), r.pid, r.start, r.run), (vec!["nvim".to_string(), "-S".into(), "/s.vim".into()], Some("/tmp".into()), 200, 2, 7));
        // replay of an earlier time for the same pid; a wrong mac; an old time; a forged token: ignored, the record stays
        let earlier = set(200, NOW - 5, &["evil"], "");
        let forged = report_body(&format!("pid=200:time={NOW}:argv={}", argv_value(&["evil"])), "not-the-token-not-the-token-xxxx");
        let old = set(200, NOW - TIME_WINDOW - 1, &["evil"], "");
        let future = set(200, NOW + TIME_WINDOW + 1, &["evil"], "");
        let long = set(200, NOW, &["x".repeat(MAX_BODY).as_str()], "");
        let no_mac = format!("pid=200:time={NOW}:argv={}", argv_value(&["evil"]));
        for bad in [&earlier, &wrong_mac, &forged, &old, &future, &long, &no_mac, &"?".to_string()] {
            assert_eq!(t.report(bad.as_bytes(), NOW, &table), Outcome::Ignored, "{bad:.60}");
            assert_eq!(t.state.store.get(key).unwrap().argv[0], "nvim");
        }
        // the same report again (inside the window, same time) is accepted: not earlier than the last
        assert_eq!(t.report(ok.as_bytes(), NOW, &table), Outcome::Accepted);
        // rejections: each removes the owner's record
        let ctl = set(200, NOW, &["nvim", "a\nb"], "");
        let rel_cwd = set(200, NOW, &["nvim"], &format!(":cwd={}", b64("rel/dir")));
        let rel_first = set(200, NOW, &["bin/nvim"], "");
        let dash_first = set(200, NOW, &["-x"], "");
        let empty_first = report_body(&format!("pid=200:time={NOW}:argv="), TOKEN);
        let many: Vec<&str> = std::iter::repeat("a").take(MAX_ARGV + 1).collect();
        let too_many = set(200, NOW, &many, "");
        let need = set(200, NOW, &["nvim"], ":need=argv,future");
        let both = report_body(&format!("pid=200:time={NOW}:argv={}:clear=1", argv_value(&["x"])), TOKEN);
        let repeated = report_body(&format!("pid=200:time={NOW}:time={NOW}:argv={}", argv_value(&["x"])), TOKEN);
        let bad_b64 = report_body(&format!("pid=200:time={NOW}:argv=****"), TOKEN);
        let not_utf8 = report_body(&format!("pid=200:time={NOW}:argv={}", b64_encode(&[0xff, 0xfe])), TOKEN);
        let c1 = set(200, NOW, &["nvim\u{85}"], "");
        let cases: Vec<(&String, Reject)> = vec![
            (&ctl, Reject::BadValue),
            (&rel_cwd, Reject::BadValue),
            (&rel_first, Reject::BadValue),
            (&dash_first, Reject::BadValue),
            (&empty_first, Reject::BadValue),
            (&too_many, Reject::TooMany),
            (&need, Reject::Need),
            (&both, Reject::Missing),
            (&repeated, Reject::Repeated),
            (&bad_b64, Reject::Malformed),
            (&not_utf8, Reject::BadValue),
            (&c1, Reject::BadValue),
        ];
        for (body, why) in cases {
            assert_eq!(t.report(ok.as_bytes(), NOW, &table), Outcome::Accepted);
            assert_eq!(t.report(body.as_bytes(), NOW, &table), Outcome::Rejected(why), "{body:.80}");
            assert!(t.state.store.get(key).is_none(), "a rejection removes the record: {body:.60}");
        }
        // 128 elements is fine; an unknown key is ignored; a known need is fine
        let mut max2 = vec!["nvim"];
        max2.extend(std::iter::repeat("a").take(MAX_ARGV - 1));
        assert_eq!(t.report(set(200, NOW, &max2, ":zzz=1:need=cwd").as_bytes(), NOW, &table), Outcome::Accepted);
        // clear=1 removes it
        let clear = report_body(&format!("pid=200:time={NOW}:clear=1"), TOKEN);
        assert_eq!(t.report(clear.as_bytes(), NOW, &table), Outcome::Cleared);
        assert!(t.state.store.get(key).is_none());
        // pid checks: a descendant is fine, another user's process, an unrelated process and a gone one are not
        assert_eq!(t.report(set(300, NOW, &["nvim"], "").as_bytes(), NOW, &table), Outcome::Accepted);
        for pid in [400, 500, 999] {
            assert_eq!(t.report(set(pid, NOW, &["nvim"], "").as_bytes(), NOW, &table), Outcome::Rejected(Reject::Pid), "{pid}");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn program_resume_store_file_modes_and_survives_reopen() {
        let dir = tmp("modes").join("resume");
        let t = tap(&dir, 100);
        assert_eq!(t.report(set(200, NOW, &["nvim"], "").as_bytes(), NOW, &table), Outcome::Accepted);
        assert_eq!(std::fs::metadata(&dir).unwrap().permissions().mode() & 0o777, 0o700);
        assert_eq!(std::fs::metadata(dir.join("resume.json")).unwrap().permissions().mode() & 0o777, 0o600);
        // omher quits: the record stays; the row closing removes it
        t.state.quitting();
        t.state.program_ended();
        let again = Store::open(dir.clone());
        assert_eq!(again.get("abcdefgh23").unwrap().argv, vec!["nvim".to_string()]);
        // one-shot: taken once, gone from the file at once
        assert!(again.take("abcdefgh23").is_some());
        assert!(again.take("abcdefgh23").is_none(), "taken once");
        assert!(Store::open(dir.clone()).get("abcdefgh23").is_none());
        let _ = std::fs::remove_dir_all(dir.parent().unwrap());
    }

    #[test]
    fn program_resume_record_goes_when_the_terminal_ends_or_closes() {
        let dir = tmp("ends");
        let t = tap(&dir, 100);
        t.report(set(200, NOW, &["nvim"], "").as_bytes(), NOW, &table);
        t.state.program_ended();
        assert!(t.state.store.get("abcdefgh23").is_none());
        let t = tap(&dir, 100);
        t.report(set(200, NOW + 1, &["nvim"], "").as_bytes(), NOW + 1, &table);
        t.state.closed();
        assert!(t.state.store.get("abcdefgh23").is_none());
        // restore keeps only the rows still listed
        let s = Store::open(dir.clone());
        let r = Record { argv: vec!["/usr/bin/vim".into()], cwd: None, cwd_reported: false, pid: 1, start: 0, uid: my_uid(), time: NOW, run: 1 };
        s.put("aaaaaaaaaa", r.clone());
        s.put("bbbbbbbbbb", r);
        assert_eq!(s.restore(&["aaaaaaaaaa".into()]), vec![("aaaaaaaaaa".to_string(), "vim".to_string())]);
        assert_eq!(s.keys(), vec!["aaaaaaaaaa".to_string()]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn program_resume_pid_must_descend_from_the_terminal() {
        let root = std::process::id();
        let mut child = std::process::Command::new("/bin/sleep").arg("5").spawn().unwrap();
        let uid = my_uid();
        assert!(owned_by_terminal(child.id(), root, uid, &proc_info).is_some());
        assert!(owned_by_terminal(root, root, uid, &proc_info).is_some());
        // our parent is not our descendant; another uid is refused
        let parent = proc_info(root).unwrap().ppid;
        assert!(owned_by_terminal(parent, root, uid, &proc_info).is_none());
        assert!(owned_by_terminal(child.id(), root, uid + 1, &proc_info).is_none());
        let start = proc_info(child.id()).unwrap().start;
        child.kill().unwrap();
        child.wait().unwrap();
        assert!(proc_info(child.id()).is_none_or(|p| p.start != start));
    }

    #[test]
    fn program_resume_argv_stays_text() {
        let dir = tmp("argv");
        let work = dir.join("work");
        std::fs::create_dir_all(&work).unwrap();
        let rdir = dir.join("resume");
        let out = dir.join("out.txt");
        let r = Record {
            argv: vec!["sh".into(), "-c".into(), "printf '%s|' \"$0\" \"$@\" > \"$OUT\"; echo >> \"$OUT\"; pwd >> \"$OUT\"".into(), "$(touch pwned)".into(), "a; touch pwned2".into(), "`touch pwned3`".into()],
            cwd: Some(work.to_string_lossy().into_owned()),
            cwd_reported: true,
            pid: 1,
            start: 0,
            uid: my_uid(),
            time: NOW,
            run: 1,
        };
        let l = prepare(&r, &rdir).unwrap();
        assert_eq!(std::fs::metadata(&l.file).unwrap().permissions().mode() & 0o777, 0o600);
        // the typed line names omher and the launch file only: no byte of the argv
        let line = typed_line(Path::new("/Applications/omher.app/Contents/MacOS/omher"), &l.file).unwrap();
        assert!(!line.contains("pwned") && !line.contains("printf"), "{line}");
        assert!(line.starts_with(" '/Applications/omher.app/Contents/MacOS/omher' --resume-exec '"), "{line}");
        let (program, argv, cwd) = exec_plan(&l.file, &rdir, Some(std::ffi::OsStr::new("/usr/bin:/bin"))).unwrap();
        assert!(!l.file.exists(), "the launch file is used once");
        assert!(exec_plan(&l.file, &rdir, None).is_err());
        let st = exec_command(&program, &argv, cwd.as_deref()).env("OUT", &out).status().unwrap();
        assert!(st.success());
        let got = std::fs::read_to_string(&out).unwrap();
        // `sh -c script $0 $@`: the elements arrive one each, unchanged, and nothing ran them
        assert_eq!(got.lines().next().unwrap(), "$(touch pwned)|a; touch pwned2|`touch pwned3`|");
        assert_eq!(Path::new(got.lines().nth(1).unwrap()).canonicalize().unwrap(), work.canonicalize().unwrap());
        for f in ["pwned", "pwned2", "pwned3"] {
            assert!(!work.join(f).exists() && !dir.join(f).exists(), "{f}");
        }
        // a reported folder that is gone drops the record; another user's record is dropped
        let gone = Record { cwd: Some("/nonexistent/omher-x".into()), ..r.clone() };
        assert!(prepare(&gone, &rdir).is_none());
        assert!(prepare(&Record { uid: my_uid() + 1, ..r.clone() }, &rdir).is_none());
        // a launch file another process could read, or outside the store, is refused
        let l = prepare(&r, &rdir).unwrap();
        std::fs::set_permissions(&l.file, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert_eq!(exec_plan(&l.file, &rdir, None).unwrap_err(), ExecError::NotPrivate);
        let outside = dir.join("launch-x.json");
        std::fs::write(&outside, b"{}").unwrap();
        assert_eq!(exec_plan(&outside, &rdir, None).unwrap_err(), ExecError::NotPrivate);
        // paths with a quote are never typed
        assert!(typed_line(Path::new("/a'b/omher"), &l.file).is_none());
        assert!(types_into(Path::new("/bin/zsh")) && types_into(Path::new("/opt/homebrew/bin/fish")) && !types_into(Path::new("/usr/bin/nu")));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn program_resume_display_is_escaped() {
        assert_eq!(label(&["/usr/bin/vi\u{202e}m".into()]), "vi\\u202Em");
        assert_eq!(escaped("a\u{1b}b"), "a\\u001Bb");
    }
}

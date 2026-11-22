//! Starts, owns and stops the omher bridge (`bridge/omher_bridge.py`).
//!
//! The app spawns the bridge with Hermes' own Python, reads its `OMHER_BRIDGE_READY {"port": N}` line
//! and hands the UI a loopback `ws://` URL carrying a per-launch random token. The child's stdin stays
//! open for the life of the app: the bridge runs with `--exit-on-stdin-eof`, so it also stops if this
//! process dies without cleaning up. The app makes no model or network call of its own.
//!
//! A bridge that stops on its own after it was ready is started again, on a new port with a new token, after a
//! short wait that doubles with each quick death in a row ([`revive_plan`]); after too many in a row the failure
//! shows instead. A bridge the app stopped (quit, Retry, an install in progress) is never started again here.

use std::collections::HashSet;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

pub const READY_PREFIX: &str = "OMHER_BRIDGE_READY ";
/// The bridge prints `OMHER_MEDIA_SERVED {"path": "/abs/file"}` each time `media.read` serves a file the
/// bot named. Those paths, and only those, may be opened by `open_media`.
pub const MEDIA_PREFIX: &str = "OMHER_MEDIA_SERVED ";
const MEDIA_REMEMBERED: usize = 2000;
pub const READY_TIMEOUT: Duration = Duration::from_secs(20);
pub const HERMES_NOT_FOUND: &str = "Hermes not found: install Hermes Agent first";
const STDERR_TAIL_LINES: usize = 6;
/// A bridge that ran this long after it was ready did not die quickly: its death starts a new count.
pub const STEADY_LIFE: Duration = Duration::from_secs(30);
/// Quick deaths in a row omher revives; the next one is shown as a failure.
pub const MAX_QUICK_DEATHS: u32 = 5;
const REVIVE_FIRST: Duration = Duration::from_millis(500);
const REVIVE_CAP: Duration = Duration::from_secs(8);

// ---------------------------------------------------------------------------------------------
// Pure helpers (unit tested)
// ---------------------------------------------------------------------------------------------

/// `OMHER_BRIDGE_READY {"port": 51234}` -> `Some(51234)`. Anything else (or port 0) -> `None`.
pub fn parse_ready_line(line: &str) -> Option<u16> {
    let rest = line.trim_end().strip_prefix(READY_PREFIX)?;
    let v: serde_json::Value = serde_json::from_str(rest.trim()).ok()?;
    let port = v.get("port")?.as_u64()?;
    if (1..=u64::from(u16::MAX)).contains(&port) {
        Some(port as u16)
    } else {
        None
    }
}

/// `OMHER_MEDIA_SERVED {"path": "/a/b.png"}` -> `Some("/a/b.png")`. Anything else -> `None`.
pub fn parse_media_line(line: &str) -> Option<String> {
    let rest = line.trim_end().strip_prefix(MEDIA_PREFIX)?;
    let v: serde_json::Value = serde_json::from_str(rest.trim()).ok()?;
    let path = v.get("path")?.as_str()?;
    if path.is_empty() || path.contains('\0') || !Path::new(path).is_absolute() {
        return None;
    }
    Some(path.to_string())
}

/// What to do after the bridge stopped on its own. `streak` is the quick deaths in a row before this one, `lived`
/// how long this bridge ran after it was ready (zero when it never got ready). Returns the new streak and the wait
/// before starting the bridge again (0.5 s, 1 s, 2 s, ... capped at 8 s), or `None` once more than
/// [`MAX_QUICK_DEATHS`] came in a row: then the person sees the failure and Retry starts it.
pub fn revive_plan(streak: u32, lived: Duration) -> (u32, Option<Duration>) {
    let streak = if lived >= STEADY_LIFE { 1 } else { streak.saturating_add(1) };
    if streak > MAX_QUICK_DEATHS {
        return (streak, None);
    }
    let delay = REVIVE_FIRST.saturating_mul(1 << (streak - 1).min(16)).min(REVIVE_CAP);
    (streak, Some(delay))
}

/// Lower-case hex of `bytes`.
pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// A 32-hex-character token from 16 bytes supplied by `fill` (the OS random source in production).
pub fn make_token<F: FnOnce(&mut [u8]) -> std::io::Result<()>>(fill: F) -> std::io::Result<String> {
    let mut buf = [0u8; 16];
    fill(&mut buf)?;
    Ok(hex(&buf))
}

fn os_random(buf: &mut [u8]) -> std::io::Result<()> {
    // The OS random source on every platform (`/dev/urandom` does not exist on Windows).
    getrandom::fill(buf).map_err(|e| std::io::Error::other(e.to_string()))
}

pub fn new_token() -> std::io::Result<String> {
    make_token(os_random)
}

/// Which layout Hermes uses on this machine. Passed in so the Windows rules are tested on any host.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Os {
    Unix,
    Windows,
}

impl Os {
    pub fn current() -> Os {
        if cfg!(windows) {
            Os::Windows
        } else {
            Os::Unix
        }
    }
}

/// The Hermes home(s) to look in, the way Hermes' own installers place it: `HERMES_HOME` first, then
/// `~/.hermes` (macOS, Linux) or `%LOCALAPPDATA%\hermes` (Windows; `install.ps1`, falling back to
/// `%USERPROFILE%\AppData\Local`).
fn hermes_homes<E: Fn(&str) -> Option<String>>(env: &E, os: Os) -> Vec<PathBuf> {
    let set = |k: &str| env(k).map(|v| v.trim().to_string()).filter(|v| !v.is_empty());
    let mut homes = Vec::new();
    if let Some(h) = set("HERMES_HOME") {
        let h = PathBuf::from(h);
        // `HERMES_HOME=<root>/profiles/<name>` (Hermes running a profile): the venv lives under the root.
        if let Some(root) = h.parent().filter(|p| p.file_name().is_some_and(|n| n == "profiles")).and_then(|p| p.parent()) {
            homes.push(root.to_path_buf());
        }
        homes.push(h);
    }
    match os {
        Os::Unix => {
            if let Some(h) = set("HOME") {
                homes.push(PathBuf::from(h).join(".hermes"));
            }
        }
        Os::Windows => {
            if let Some(l) = set("LOCALAPPDATA") {
                homes.push(PathBuf::from(l).join("hermes"));
            } else if let Some(u) = set("USERPROFILE") {
                homes.push(PathBuf::from(u).join("AppData").join("Local").join("hermes"));
            }
        }
    }
    homes
}

/// Where Hermes' Python lives, in the order the person would expect: `OMHER_HERMES_PYTHON`, then the
/// interpreter each Hermes home's PM launcher names, then each home's `hermes-agent/venv`, then
/// `hermes-agent/.venv` (`bin/python`, or `Scripts\python.exe` on Windows). The launcher is
/// `hermes-agent/.hermes/bin/hermes` (a sh script that `exec`s it) on Unix; on Windows it is
/// `hermes-agent\.hermes\bin\hermes.exe` or `hermes.cmd`, then the user bin `<home>\bin\hermes.exe` or
/// `hermes.cmd` older PM installers published to (`.exe` first, as PATHEXT runs it). A Windows PM install
/// has no venv at all. The launcher goes first because it is the Python `hermes` itself runs on: an
/// install upgraded to the unified package manager keeps its old venv, whose older Python cannot load the
/// committed dependency generation the bridge activates. omher only reads the launcher file; it never runs
/// it. `env` and `exists` are injected so tests never touch the real machine.
pub fn discover_python<E, X>(env: E, exists: X) -> Result<PathBuf, String>
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
{
    discover_python_for(env, exists, Os::current())
}

pub fn discover_python_for<E, X>(env: E, exists: X, os: Os) -> Result<PathBuf, String>
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
{
    discover_python_in(env, exists, |p| std::fs::read(p).ok(), os)
}

/// The interpreter a PM launcher script `exec`s: `exec /abs/python3 -I -c '...'`. Hermes writes that line
/// with `shlex.join`, so a path with a space arrives as `'/a b/python3'` and an apostrophe as `'"'"'`; read
/// the first word the way sh does, as Hermes' own `_launchers` reader does.
fn launcher_python(script: &str) -> Option<PathBuf> {
    let line = script.lines().find_map(|l| l.strip_prefix("exec "))?;
    let exe = first_sh_word(line)?;
    // A sh launcher names a POSIX path; `Path::is_absolute` would also need a drive letter on Windows,
    // where these parse tests run in CI.
    exe.starts_with('/').then(|| PathBuf::from(exe))
}

/// The first word of a POSIX sh command line: quotes removed, adjacent quoted parts joined. `None` when
/// the line is empty or a quote is left open within that word.
fn first_sh_word(line: &str) -> Option<String> {
    let mut chars = line.trim_start().chars();
    let mut word = String::new();
    while let Some(c) = chars.next() {
        match c {
            c if c.is_whitespace() => break,
            '\'' => loop {
                match chars.next()? {
                    '\'' => break,
                    c => word.push(c),
                }
            },
            '"' => loop {
                match chars.next()? {
                    '"' => break,
                    '\\' => match chars.next()? {
                        c @ ('"' | '\\' | '$' | '`') => word.push(c),
                        c => {
                            word.push('\\');
                            word.push(c);
                        }
                    },
                    c => word.push(c),
                }
            },
            '\\' => word.push(chars.next()?),
            c => word.push(c),
        }
    }
    (!word.is_empty()).then_some(word)
}

/// The interpreter a Windows PM launcher starts, read from the file (never run). `hermes.exe` is distlib's
/// native launcher: a loader stub, then `#!<python> -I` and the zipped script; the shebang follows the
/// stub's last NUL byte before the zip, and distlib leaves the path unquoted, so it may hold a space.
/// `hermes.cmd` is `@echo off`, then `"<python>" -I -c "..." %*`, possibly after a blank line. Both are
/// read as Hermes' own `_launchers._launcher_python` reads them; the result must be a Windows absolute path.
fn windows_launcher_python(name: &Path, data: &[u8]) -> Option<PathBuf> {
    let exe = if name.extension().is_some_and(|e| e.eq_ignore_ascii_case("exe")) {
        let prefix = &data[..zip_start(data)?];
        let after_nul = prefix.iter().rposition(|&b| b == 0).map_or(0, |i| i + 1);
        let start = after_nul + prefix[after_nul..].windows(2).position(|w| w == b"#!")? + 2;
        let mut line = &prefix[start..];
        while let [rest @ .., b'\r' | b'\n'] = line {
            line = rest;
        }
        if line.contains(&b'\n') {
            return None;
        }
        let path = std::str::from_utf8(line.strip_suffix(b" -I")?).ok()?;
        path.trim_matches('"').to_string()
    } else {
        let text = std::str::from_utf8(data).ok()?;
        let mut lines = text.strip_prefix('\u{feff}').unwrap_or(text).lines();
        if !lines.next()?.trim().eq_ignore_ascii_case("@echo off") {
            return None;
        }
        first_token(lines.find(|l| !l.trim().is_empty())?)?
    };
    windows_absolute(&exe).then(|| PathBuf::from(exe))
}

/// Where the zip a distlib launcher carries begins: its End of Central Directory record holds the
/// central directory's size and its offset from the zip's own start, so the zip starts that far before
/// the directory (the zip's members may hold NUL bytes, so the stub's last NUL is searched before it).
fn zip_start(data: &[u8]) -> Option<usize> {
    let eocd = data.windows(4).rposition(|w| w == b"PK\x05\x06")?;
    let field = |at: usize| data.get(eocd + at..eocd + at + 4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]) as usize);
    let (size, offset) = (field(12)?, field(16)?);
    eocd.checked_sub(size)?.checked_sub(offset)
}

/// The first whitespace-separated token of a `.cmd` line, honouring one quote pair; never shell-lexed,
/// which would eat a Windows path's backslashes.
fn first_token(line: &str) -> Option<String> {
    let text = line.trim();
    let token = match text.chars().next()? {
        q @ ('"' | '\'') => &text[1..1 + text[1..].find(q)?],
        _ => text.split_whitespace().next()?,
    };
    (!token.is_empty()).then(|| token.to_string())
}

/// `C:\...`, `C:/...` or a UNC `\\server\share\...` path. `Path::is_absolute` cannot say this on the
/// Unix machines these parse tests also run on.
fn windows_absolute(p: &str) -> bool {
    let b = p.as_bytes();
    (b.len() > 2 && b[0].is_ascii_alphabetic() && b[1] == b':' && matches!(b[2], b'\\' | b'/')) || p.starts_with("\\\\")
}

pub fn discover_python_in<E, X, R>(env: E, exists: X, read: R, os: Os) -> Result<PathBuf, String>
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
    R: Fn(&Path) -> Option<Vec<u8>>,
{
    if let Some(p) = env("OMHER_HERMES_PYTHON").filter(|p| !p.trim().is_empty()) {
        let p = PathBuf::from(p.trim());
        if exists(&p) {
            return Ok(p);
        }
    }
    let exe: &[&str] = match os {
        Os::Unix => &["bin", "python"],
        Os::Windows => &["Scripts", "python.exe"],
    };
    let launched = |launcher: &Path| exists(launcher).then(|| read(launcher)).flatten();
    for home in hermes_homes(&env, os) {
        let agent = home.join("hermes-agent");
        let found = match os {
            Os::Unix => {
                let launcher = agent.join(".hermes").join("bin").join("hermes");
                launched(&launcher).and_then(|b| String::from_utf8(b).ok()).as_deref().and_then(launcher_python)
            }
            Os::Windows => {
                let bins = [agent.join(".hermes").join("bin"), home.join("bin")];
                bins.iter().flat_map(|bin| ["hermes.exe", "hermes.cmd"].map(|n| bin.join(n))).find_map(|launcher| {
                    let p = windows_launcher_python(&launcher, &launched(&launcher)?)?;
                    exists(&p).then_some(p)
                })
            }
        };
        if let Some(p) = found.filter(|p| exists(p)) {
            return Ok(p);
        }
        for dir in ["venv", ".venv"] {
            let p = exe.iter().fold(agent.join(dir), |p, part| p.join(part));
            if exists(&p) {
                return Ok(p);
            }
        }
    }
    Err(HERMES_NOT_FOUND.to_string())
}

/// The bridge script: the bundled resource first, then (debug builds only) the repo copy next to
/// `src-tauri`, so `tauri dev` runs the checked-out bridge.
pub fn resolve_script<X: Fn(&Path) -> bool>(
    resource_dir: Option<&Path>,
    manifest_dir: Option<&Path>,
    exists: X,
) -> Result<PathBuf, String> {
    let mut tried = Vec::new();
    if let Some(r) = resource_dir {
        for rel in [&["bridge", "omher_bridge.py"][..], &["resources", "bridge", "omher_bridge.py"][..]] {
            // one component at a time, so the path uses this OS's separator throughout
            let p = rel.iter().fold(r.to_path_buf(), |p, part| p.join(part));
            if exists(&p) {
                return Ok(p);
            }
            tried.push(p);
        }
    }
    if let Some(m) = manifest_dir {
        let p = m.join("..").join("bridge").join("omher_bridge.py");
        if exists(&p) {
            return Ok(p);
        }
        tried.push(p);
    }
    let list: Vec<String> = tried.iter().map(|p| p.display().to_string()).collect();
    Err(format!("omher bridge script not found (looked in: {})", list.join(", ")))
}

pub fn bridge_args(script: &Path, token: &str) -> Vec<String> {
    vec![
        script.display().to_string(),
        "--port".into(),
        "0".into(),
        "--token".into(),
        token.into(),
        "--exit-on-stdin-eof".into(),
    ]
}

pub fn bridge_ws_url(port: u16, token: &str) -> String {
    format!("ws://127.0.0.1:{port}/?token={token}")
}

// ---------------------------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum Phase {
    Starting,
    Ready { port: u16 },
    Failed(String),
}

struct Inner {
    phase: Phase,
    token: String,
    child: Option<Child>,
    /// Held open so the child sees EOF only when this process goes away.
    stdin: Option<ChildStdin>,
    generation: u64,
    /// Where the bundled bridge script is, kept from the last `start` so a revive finds it again.
    resource_dir: Option<PathBuf>,
    /// When the running bridge became ready.
    ready_at: Option<Instant>,
    /// Quick deaths in a row since the app last started the bridge itself (see [`revive_plan`]).
    streak: u32,
    /// The installer is running: a bridge that stops meanwhile waits for it (`release` or `start`).
    held: bool,
    /// A bridge stopped while `held`.
    died_while_held: bool,
    /// A test's stand-in for Hermes' Python; never set outside tests. Without one, a test's launch fails before it runs
    /// anything.
    python: Option<PathBuf>,
}

/// `{state: "ready"|"starting"|"failed", error?, missing?}`, the shape the UI reads. `missing:
/// "hermes"` marks the one failure the first-run screen can fix by installing Hermes.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct BridgeStatus {
    pub state: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub missing: Option<&'static str>,
}

impl BridgeStatus {
    fn of(state: &'static str, error: Option<String>) -> BridgeStatus {
        let missing = match error.as_deref() {
            Some(HERMES_NOT_FOUND) => Some("hermes"),
            _ => None,
        };
        BridgeStatus { state, error, missing }
    }
}

pub struct Bridge {
    inner: Mutex<Inner>,
    changed: Condvar,
    /// Files `media.read` served this launch (from the bridge's stdout).
    served: Mutex<HashSet<String>>,
}

impl Bridge {
    pub fn new() -> Arc<Bridge> {
        Arc::new(Bridge {
            inner: Mutex::new(Inner {
                phase: Phase::Starting,
                token: String::new(),
                child: None,
                stdin: None,
                generation: 0,
                resource_dir: None,
                ready_at: None,
                streak: 0,
                held: false,
                died_while_held: false,
                python: None,
            }),
            changed: Condvar::new(),
            served: Mutex::new(HashSet::new()),
        })
    }

    /// (Re)start the bridge in the background. Any earlier child is stopped first. This is the app's own start
    /// (boot, Retry, after an install): the count of quick deaths starts again and an install's hold ends.
    pub fn start(self: &Arc<Self>, resource_dir: Option<PathBuf>) {
        let generation = {
            let mut g = self.inner.lock().unwrap();
            stop_locked(&mut g);
            g.generation += 1;
            g.phase = Phase::Starting;
            g.resource_dir = resource_dir;
            g.streak = 0;
            g.held = false;
            g.died_while_held = false;
            g.generation
        };
        self.changed.notify_all();
        self.spawn_launch(generation, Duration::ZERO);
    }

    /// Launch `generation` after `delay` on its own thread, unless the app stopped or started the bridge meanwhile.
    /// An installer that began during the wait holds it until it ends (`release` or `start`).
    fn spawn_launch(self: &Arc<Self>, generation: u64, delay: Duration) {
        let me = Arc::clone(self);
        thread::spawn(move || {
            thread::sleep(delay);
            let resource_dir = {
                let mut g = me.inner.lock().unwrap();
                if g.generation != generation {
                    return;
                }
                if g.held {
                    g.died_while_held = true;
                    return;
                }
                g.resource_dir.clone()
            };
            if let Err(e) = me.launch(generation, resource_dir.as_deref()) {
                eprintln!("omher: bridge failed: {e}");
                me.launch_failed(generation, e);
            }
        });
    }

    /// A launch failed. The app's own start shows the failure; a revive counts it as one more quick death.
    fn launch_failed(self: &Arc<Self>, generation: u64, error: String) {
        {
            let mut g = self.inner.lock().unwrap();
            if g.generation != generation {
                return;
            }
            stop_locked(&mut g);
            if g.streak == 0 {
                g.phase = Phase::Failed(error);
            } else {
                self.revive_locked(&mut g, Duration::ZERO, error, true);
            }
        }
        self.changed.notify_all();
    }

    /// The bridge of `generation` stopped on its own (its stdout closed, or `try_wait` saw it exit). Ignored unless
    /// that bridge is the current one and was ready: the app's own stop or start already moved on.
    fn died(self: &Arc<Self>, generation: u64) {
        let changed = {
            let mut g = self.inner.lock().unwrap();
            g.generation == generation && self.died_locked(&mut g)
        };
        if changed {
            self.changed.notify_all();
        }
    }

    /// The ready bridge's exit, if it exited, handled; true when the phase changed. Caller notifies `changed`.
    fn died_locked(self: &Arc<Self>, g: &mut Inner) -> bool {
        if !matches!(g.phase, Phase::Ready { .. }) {
            return false;
        }
        let code = match g.child.as_mut().map(|c| c.try_wait()) {
            Some(Ok(None)) => {
                // stdout closed but the process lingers: it can no longer say anything, so it goes, reaped off the lock
                let mut c = g.child.take().expect("child checked above");
                let _ = c.kill();
                thread::spawn(move || {
                    let _ = c.wait();
                });
                None
            }
            Some(Ok(Some(code))) => Some(code),
            Some(Err(_)) | None => None,
        };
        let why = code.map_or_else(|| "the bridge stopped unexpectedly".to_string(), |c| format!("the bridge stopped unexpectedly ({c})"));
        eprintln!("omher: {why}");
        stop_locked(g);
        let lived = g.ready_at.map_or(Duration::ZERO, |t| t.elapsed());
        self.revive_locked(g, lived, why, false);
        true
    }

    /// Start the bridge again after [`revive_plan`]'s wait, or show `why` once it gives up. An install in progress
    /// holds the revive until it ends. `launch_error` keeps a failed launch's own message (so a Hermes that went
    /// missing still offers the install screen).
    fn revive_locked(self: &Arc<Self>, g: &mut Inner, lived: Duration, why: String, launch_error: bool) {
        g.ready_at = None;
        g.generation += 1;
        if g.held {
            eprintln!("omher: {why}; the installer is running, so the bridge starts again when it ends");
            g.died_while_held = true;
            g.phase = Phase::Starting;
            return;
        }
        let (streak, delay) = revive_plan(g.streak, lived);
        g.streak = streak;
        match delay {
            Some(delay) => {
                eprintln!("omher: starting the bridge again in {} ms ({streak} in a row)", delay.as_millis());
                g.phase = Phase::Starting;
                self.spawn_launch(g.generation, delay);
            }
            None if launch_error => g.phase = Phase::Failed(why),
            None => g.phase = Phase::Failed(format!("{why}; it stopped {streak} times in a row, so omher stopped starting it")),
        }
    }

    /// The installer is about to run: a bridge that stops while it runs is not started again until it ends.
    pub fn hold(&self) {
        self.inner.lock().unwrap().held = true;
    }

    /// The installer ended without starting the bridge: one that stopped meanwhile is started again now.
    pub fn release(self: &Arc<Self>) {
        let generation = {
            let mut g = self.inner.lock().unwrap();
            g.held = false;
            // a quit (or any stop) during the install already ended it: nothing to start
            if !std::mem::take(&mut g.died_while_held) || matches!(g.phase, Phase::Failed(_)) {
                return;
            }
            g.streak = 0;
            g.generation += 1;
            g.phase = Phase::Starting;
            g.generation
        };
        self.changed.notify_all();
        self.spawn_launch(generation, Duration::ZERO);
    }

    fn launch(self: &Arc<Self>, generation: u64, resource_dir: Option<&Path>) -> Result<(), String> {
        let pinned = self.inner.lock().unwrap().python.clone();
        let python = match pinned {
            Some(p) => p,
            None if cfg!(test) => return Err("a test launches only the interpreter it set".into()),
            None => discover_python(|k| std::env::var(k).ok(), |p| p.is_file())?,
        };
        let manifest = if cfg!(debug_assertions) { Some(Path::new(env!("CARGO_MANIFEST_DIR"))) } else { None };
        let script = resolve_script(resource_dir, manifest, |p| p.is_file())?;
        let token = new_token().map_err(|e| format!("could not make a bridge token: {e}"))?;

        let mut cmd = Command::new(&python);
        cmd.args(bridge_args(&script, &token))
            .env("PYTHONUTF8", "1") // the bridge's stdio stays UTF-8 on Windows code pages too
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        no_console_window(&mut cmd);
        crate::appimage::host_env(&mut cmd); // AppRun's PYTHONHOME would send the host Python into the image
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("could not start the bridge ({}): {e}", python.display()))?;
        eprintln!("omher: bridge pid {} started with {}", child.id(), python.display());

        let stdin = child.stdin.take();
        let stdout = child.stdout.take().ok_or("bridge stdout unavailable")?;
        let stderr = child.stderr.take().ok_or("bridge stderr unavailable")?;

        // Hand the child to the shared state right away so a quit during startup still kills it.
        {
            let mut g = self.inner.lock().unwrap();
            if g.generation != generation {
                let _ = child.kill();
                let _ = child.wait();
                return Ok(());
            }
            g.token = token.clone();
            g.child = Some(child);
            g.stdin = stdin;
        }

        let tail: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let tail_w = Arc::clone(&tail);
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("omher-bridge: {line}");
                let mut t = tail_w.lock().unwrap();
                t.push(line);
                if t.len() > STDERR_TAIL_LINES {
                    t.remove(0);
                }
            }
        });

        let (tx, rx) = mpsc::channel::<Result<u16, ()>>();
        let me = Arc::clone(self);
        thread::spawn(move || {
            let mut sent = false;
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if !sent {
                    if let Some(port) = parse_ready_line(&line) {
                        sent = true;
                        let _ = tx.send(Ok(port));
                    }
                } else if let Some(path) = parse_media_line(&line) {
                    me.remember_media(path);
                }
            }
            if sent {
                me.died(generation);
            } else {
                let _ = tx.send(Err(()));
            }
        });

        match rx.recv_timeout(READY_TIMEOUT) {
            Ok(Ok(port)) => {
                eprintln!("omher: bridge ready on 127.0.0.1:{port}");
                self.finish(generation, Phase::Ready { port });
                Ok(())
            }
            Ok(Err(())) => {
                thread::sleep(Duration::from_millis(100)); // let the stderr reader catch the last lines
                let last = tail.lock().unwrap().last().cloned().unwrap_or_default();
                Err(if last.is_empty() {
                    "the bridge exited before it was ready".to_string()
                } else {
                    format!("the bridge exited before it was ready: {last}")
                })
            }
            Err(_) => {
                self.stop_generation(generation);
                Err(format!("the bridge did not become ready within {} s", READY_TIMEOUT.as_secs()))
            }
        }
    }

    fn finish(&self, generation: u64, phase: Phase) {
        {
            let mut g = self.inner.lock().unwrap();
            if g.generation != generation {
                return;
            }
            if matches!(phase, Phase::Failed(_)) {
                stop_locked(&mut g);
            }
            g.ready_at = matches!(phase, Phase::Ready { .. }).then(Instant::now);
            g.phase = phase;
        }
        self.changed.notify_all();
    }

    fn stop_generation(&self, generation: u64) {
        let mut g = self.inner.lock().unwrap();
        if g.generation == generation {
            stop_locked(&mut g);
        }
    }

    /// Stop the child (app exit). Idempotent.
    pub fn stop(&self) {
        let mut g = self.inner.lock().unwrap();
        g.generation += 1;
        g.held = false;
        g.died_while_held = false;
        stop_locked(&mut g);
        if g.phase == Phase::Starting || matches!(g.phase, Phase::Ready { .. }) {
            g.phase = Phase::Failed("the bridge was stopped".into());
        }
        drop(g);
        self.changed.notify_all();
    }

    pub fn remember_media(&self, path: String) {
        let mut set = self.served.lock().unwrap();
        if set.len() >= MEDIA_REMEMBERED && !set.contains(&path) {
            set.clear();
        }
        set.insert(path);
    }

    /// True only for a file the bridge served through `media.read` since the app started.
    pub fn served_media(&self, path: &str) -> bool {
        self.served.lock().unwrap().contains(path)
    }

    pub fn status(self: &Arc<Self>) -> BridgeStatus {
        let mut g = self.inner.lock().unwrap();
        // A bridge that died after it was ready is started again (or, after too many quick deaths, shown).
        let changed = self.check_alive_locked(&mut g);
        let status = match &g.phase {
            Phase::Starting => BridgeStatus::of("starting", None),
            Phase::Ready { .. } => BridgeStatus::of("ready", None),
            Phase::Failed(e) => BridgeStatus::of("failed", Some(e.clone())),
        };
        drop(g);
        if changed {
            self.changed.notify_all();
        }
        status
    }

    /// The loopback URL once ready; waits (bounded) while the bridge is still starting. Never the port of a bridge
    /// that already exited: that one is started again and the URL waits for it.
    pub fn url(self: &Arc<Self>, wait: Duration) -> Result<String, String> {
        let deadline = Instant::now() + wait;
        let mut g = self.inner.lock().unwrap();
        loop {
            if self.check_alive_locked(&mut g) {
                self.changed.notify_all();
            }
            match &g.phase {
                Phase::Ready { port } => return Ok(bridge_ws_url(*port, &g.token)),
                Phase::Failed(e) => return Err(e.clone()),
                Phase::Starting => {
                    let now = Instant::now();
                    if now >= deadline {
                        return Err("the bridge is still starting".into());
                    }
                    g = self.changed.wait_timeout(g, deadline - now).unwrap().0;
                }
            }
        }
    }

    /// A ready bridge whose child has exited is handled as a death now, before its stdout reader notices.
    fn check_alive_locked(self: &Arc<Self>, g: &mut Inner) -> bool {
        let exited = matches!(g.phase, Phase::Ready { .. }) && g.child.as_mut().is_some_and(|c| matches!(c.try_wait(), Ok(Some(_))));
        exited && self.died_locked(g)
    }

    #[cfg(test)]
    fn set_ready_for_test(&self, port: u16, token: &str) {
        let mut g = self.inner.lock().unwrap();
        g.phase = Phase::Ready { port };
        g.token = token.into();
    }

    /// Ready on `port` with `child` as the bridge, after `streak` quick deaths; returns its generation.
    #[cfg(test)]
    fn set_child_for_test(&self, port: u16, child: Child, streak: u32) -> u64 {
        let mut g = self.inner.lock().unwrap();
        g.generation += 1;
        g.phase = Phase::Ready { port };
        g.token = "tok".into();
        g.child = Some(child);
        g.ready_at = Some(Instant::now());
        g.streak = streak;
        g.generation
    }
}

/// A release build on Windows has no console of its own, so a console child (python.exe) would flash a
/// terminal window. `CREATE_NO_WINDOW` keeps it hidden; elsewhere this does nothing.
#[cfg(windows)]
pub(crate) fn no_console_window(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
pub(crate) fn no_console_window(_cmd: &mut Command) {}

fn stop_locked(g: &mut Inner) {
    g.stdin = None; // EOF first: the bridge exits on its own
    if let Some(mut child) = g.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{HashMap, HashSet};

    #[test]
    fn ready_line_parses_the_port() {
        assert_eq!(parse_ready_line("OMHER_BRIDGE_READY {\"port\": 51234}"), Some(51234));
        assert_eq!(parse_ready_line("OMHER_BRIDGE_READY {\"port\":8080}\n"), Some(8080));
        assert_eq!(parse_ready_line("OMHER_BRIDGE_READY {\"port\": 7, \"extra\": true}\r\n"), Some(7));
    }

    #[test]
    fn ready_line_rejects_everything_else() {
        for bad in [
            "",
            "hello",
            "OMHER_BRIDGE_READY",
            "OMHER_BRIDGE_READY {}",
            "OMHER_BRIDGE_READY {\"port\": 0}",
            "OMHER_BRIDGE_READY {\"port\": 70000}",
            "OMHER_BRIDGE_READY {\"port\": \"80\"}",
            "OMHER_BRIDGE_READY not json",
            " OMHER_BRIDGE_READY {\"port\": 80}",
            "WARN OMHER_BRIDGE_READY {\"port\": 80}",
        ] {
            assert_eq!(parse_ready_line(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn media_line_names_one_absolute_file() {
        let abs = if cfg!(windows) { r"C:\w\a.png" } else { "/w/a.png" };
        let line = format!("OMHER_MEDIA_SERVED {}", serde_json::json!({ "path": abs }));
        assert_eq!(parse_media_line(&line), Some(abs.to_string()));
        for bad in [
            "",
            "OMHER_MEDIA_SERVED",
            "OMHER_MEDIA_SERVED {}",
            "OMHER_MEDIA_SERVED {\"path\": \"\"}",
            "OMHER_MEDIA_SERVED {\"path\": \"rel/a.png\"}",
            "OMHER_MEDIA_SERVED {\"path\": 3}",
            "WARN OMHER_MEDIA_SERVED {\"path\": \"/w/a.png\"}",
        ] {
            assert_eq!(parse_media_line(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn only_served_media_is_known() {
        let b = Bridge::new();
        assert!(!b.served_media("/w/a.png"));
        b.remember_media("/w/a.png".into());
        assert!(b.served_media("/w/a.png"));
        assert!(!b.served_media("/w/b.png"));
        assert!(!b.served_media("/w"));
    }

    fn env_of(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let m: HashMap<String, String> = pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        move |k| m.get(k).cloned()
    }

    fn fs_of(paths: &[&str]) -> impl Fn(&Path) -> bool {
        let s: HashSet<PathBuf> = paths.iter().map(PathBuf::from).collect();
        move |p| s.contains(p)
    }

    const VENV: &str = "/h/.hermes/hermes-agent/venv/bin/python";
    const DOTVENV: &str = "/h/.hermes/hermes-agent/.venv/bin/python";

    fn discover_python<E: Fn(&str) -> Option<String>, X: Fn(&Path) -> bool>(env: E, exists: X) -> Result<PathBuf, String> {
        discover_python_for(env, exists, Os::Unix)
    }

    fn win(parts: &[&str]) -> String {
        parts.iter().fold(PathBuf::new(), |p, x| p.join(x)).display().to_string()
    }

    #[test]
    fn python_on_windows_is_under_localappdata_scripts() {
        let want = win(&["C:/Users/k/AppData/Local", "hermes", "hermes-agent", "venv", "Scripts", "python.exe"]);
        let env = env_of(&[("LOCALAPPDATA", "C:/Users/k/AppData/Local"), ("USERPROFILE", "C:/Users/k")]);
        assert_eq!(discover_python_for(env, fs_of(&[&want]), Os::Windows), Ok(PathBuf::from(&want)));
    }

    #[test]
    fn python_on_windows_falls_back_to_userprofile_and_dot_venv() {
        let want = win(&["C:/Users/k", "AppData", "Local", "hermes", "hermes-agent", ".venv", "Scripts", "python.exe"]);
        let env = env_of(&[("USERPROFILE", "C:/Users/k")]);
        assert_eq!(discover_python_for(env, fs_of(&[&want]), Os::Windows), Ok(PathBuf::from(&want)));
        // A Unix-layout venv is not what Windows Hermes makes, so it is not picked there.
        let unix = win(&["C:/Users/k", "AppData", "Local", "hermes", "hermes-agent", "venv", "bin", "python"]);
        assert_eq!(discover_python_for(env_of(&[("USERPROFILE", "C:/Users/k")]), fs_of(&[&unix]), Os::Windows).unwrap_err(), HERMES_NOT_FOUND);
    }

    #[test]
    fn a_profile_home_finds_the_venv_at_its_root() {
        // Hermes runs a profile as HERMES_HOME=<root>/profiles/<name>; the venv is under <root>.
        let venv = win(&["/h/.hermes", "hermes-agent", "venv", "bin", "python"]);
        let env = env_of(&[("HERMES_HOME", "/h/.hermes/profiles/kami"), ("HOME", "/elsewhere")]);
        assert_eq!(discover_python(env, fs_of(&[&venv])), Ok(PathBuf::from(&venv)));
    }

    #[test]
    fn python_follows_hermes_home_first() {
        let custom = win(&["/srv/hermes", "hermes-agent", "venv", "bin", "python"]);
        let env = env_of(&[("HERMES_HOME", "/srv/hermes"), ("HOME", "/h")]);
        assert_eq!(discover_python(env, fs_of(&[&custom, VENV])), Ok(PathBuf::from(&custom)));
        let wcustom = win(&["D:/hermes", "hermes-agent", "venv", "Scripts", "python.exe"]);
        let wenv = env_of(&[("HERMES_HOME", "D:/hermes"), ("LOCALAPPDATA", "C:/L")]);
        assert_eq!(discover_python_for(wenv, fs_of(&[&wcustom]), Os::Windows), Ok(PathBuf::from(&wcustom)));
    }

    #[test]
    fn python_env_override_wins() {
        let env = env_of(&[("OMHER_HERMES_PYTHON", "/opt/py"), ("HOME", "/h")]);
        let got = discover_python(env, fs_of(&["/opt/py", VENV, DOTVENV]));
        assert_eq!(got, Ok(PathBuf::from("/opt/py")));
    }

    #[test]
    fn python_prefers_venv_over_dot_venv() {
        let env = env_of(&[("HOME", "/h")]);
        assert_eq!(discover_python(env_of(&[("HOME", "/h")]), fs_of(&[VENV, DOTVENV])), Ok(PathBuf::from(VENV)));
        assert_eq!(discover_python(env, fs_of(&[DOTVENV])), Ok(PathBuf::from(DOTVENV)));
    }

    #[test]
    fn python_env_override_that_does_not_exist_falls_through() {
        let env = env_of(&[("OMHER_HERMES_PYTHON", "/missing"), ("HOME", "/h")]);
        assert_eq!(discover_python(env, fs_of(&[DOTVENV])), Ok(PathBuf::from(DOTVENV)));
        let blank = env_of(&[("OMHER_HERMES_PYTHON", "  "), ("HOME", "/h")]);
        assert_eq!(discover_python(blank, fs_of(&[VENV])), Ok(PathBuf::from(VENV)));
    }

    #[test]
    fn python_falls_back_to_the_pm_launcher_interpreter() {
        const LAUNCHER: &str = "/h/.hermes/hermes-agent/.hermes/bin/hermes";
        const PM_PY: &str = "/h/.hermes/tools/python-3.14.9/bin/python3";
        let script = format!("#!/bin/sh\nexec {PM_PY} -I -c 'import os'\n");
        let read = |p: &Path| (p == Path::new(LAUNCHER)).then(|| script.clone().into_bytes());
        let env = env_of(&[("HOME", "/h")]);
        assert_eq!(discover_python_in(&env, fs_of(&[LAUNCHER, PM_PY]), read, Os::Unix), Ok(PathBuf::from(PM_PY)));
        // An install upgraded to PM keeps its old venv; `hermes` runs on the launcher's Python, so omher does too.
        assert_eq!(discover_python_in(&env, fs_of(&[LAUNCHER, PM_PY, VENV]), read, Os::Unix), Ok(PathBuf::from(PM_PY)));
        // A launcher whose interpreter is gone (a pruned tool) falls back to the venv, then to "not found".
        assert_eq!(discover_python_in(&env, fs_of(&[LAUNCHER, VENV]), read, Os::Unix), Ok(PathBuf::from(VENV)));
        let gone = discover_python_in(&env, fs_of(&[LAUNCHER]), read, Os::Unix).unwrap_err();
        assert_eq!(gone, HERMES_NOT_FOUND);
        // The override still wins over the launcher.
        let pinned = env_of(&[("HOME", "/h"), ("OMHER_HERMES_PYTHON", "/opt/py")]);
        assert_eq!(discover_python_in(&pinned, fs_of(&[LAUNCHER, PM_PY, "/opt/py"]), read, Os::Unix), Ok(PathBuf::from("/opt/py")));
    }

    const WIN_PY: &str = r"C:\Users\u\AppData\Local\hermes\tools\python-3.14.9\python.exe";

    fn wenv() -> impl Fn(&str) -> Option<String> {
        env_of(&[("LOCALAPPDATA", r"C:\Users\u\AppData\Local")])
    }

    /// `<home>\hermes-agent\.hermes\bin\<name>` (PM launcher) or `<home>\bin\<name>` (older user bin), with
    /// this OS's separators, as `discover_python_in` joins them.
    fn wlauncher(user_bin: bool, name: &str) -> PathBuf {
        let home = PathBuf::from(r"C:\Users\u\AppData\Local").join("hermes");
        let bin = if user_bin { home.join("bin") } else { home.join("hermes-agent").join(".hermes").join("bin") };
        bin.join(name)
    }

    /// distlib's native launcher layout: a loader stub holding NULs, the shebang line, then a zip whose
    /// own bytes hold NULs too (a local header and an End of Central Directory pointing back at it).
    fn fake_exe(shebang: &str) -> Vec<u8> {
        let mut out = b"MZ\x90\x00loader\x00stub\x00\x00".to_vec();
        out.extend_from_slice(shebang.as_bytes());
        let local = b"PK\x03\x04\x14\x00\x00\x00\x08\x00__main__.py\x00\x00".to_vec();
        out.extend_from_slice(&local);
        out.extend_from_slice(b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00");
        out.extend_from_slice(&0u32.to_le_bytes());
        out.extend_from_slice(&(local.len() as u32).to_le_bytes());
        out.extend_from_slice(b"\x00\x00");
        out
    }

    fn files(entries: Vec<(PathBuf, Vec<u8>)>) -> impl Fn(&Path) -> Option<Vec<u8>> {
        let m: HashMap<PathBuf, Vec<u8>> = entries.into_iter().collect();
        move |p| m.get(p).cloned()
    }

    fn fs_with(paths: &[&Path]) -> impl Fn(&Path) -> bool {
        let s: HashSet<PathBuf> = paths.iter().map(|p| p.to_path_buf()).collect();
        move |p| s.contains(p)
    }

    #[test]
    fn windows_python_comes_from_the_pm_launcher_exe() {
        let exe = wlauncher(false, "hermes.exe");
        let read = files(vec![(exe.clone(), fake_exe(&format!("#!{WIN_PY} -I\n")))]);
        let got = discover_python_in(wenv(), fs_with(&[&exe, Path::new(WIN_PY)]), read, Os::Windows);
        assert_eq!(got, Ok(PathBuf::from(WIN_PY)));
    }

    #[test]
    fn windows_launcher_exe_shebang_may_hold_a_space_or_quotes() {
        let spaced = r"C:\Users\u u\AppData\Local\hermes\tools\python-3.14.9\python.exe";
        let exe = Path::new("hermes.exe");
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!{spaced} -I\n"))), Some(PathBuf::from(spaced)));
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!\"{spaced}\" -I\n"))), Some(PathBuf::from(spaced)));
        // Vendored distlib trails the shebang with an extra CRLF before the zip.
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!{WIN_PY} -I\r\n\r\n"))), Some(PathBuf::from(WIN_PY)));
        let unc = r"\\server\share\python.exe";
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!{unc} -I\n"))), Some(PathBuf::from(unc)));
    }

    #[test]
    fn windows_python_comes_from_the_cmd_launcher() {
        let cmd = wlauncher(false, "hermes.cmd");
        let body = format!("@echo off\r\n\r\n\"{WIN_PY}\" -I -c \"import base64; exec(base64.b64decode('aW1wb3J0IG9z'))\" %*\r\n");
        let read = files(vec![(cmd.clone(), body.into_bytes())]);
        let got = discover_python_in(wenv(), fs_with(&[&cmd, Path::new(WIN_PY)]), read, Os::Windows);
        assert_eq!(got, Ok(PathBuf::from(WIN_PY)));
        // A BOM and an unquoted path read the same; a file that is not a launcher does not.
        let cmd_name = Path::new("hermes.cmd");
        let bom = format!("\u{feff}@echo off\r\n{WIN_PY} -I -c \"x\" %*\r\n");
        assert_eq!(windows_launcher_python(cmd_name, bom.as_bytes()), Some(PathBuf::from(WIN_PY)));
        assert_eq!(windows_launcher_python(cmd_name, format!("echo hi\r\n\"{WIN_PY}\" -I\r\n").as_bytes()), None);
        assert_eq!(windows_launcher_python(cmd_name, b"@echo off\r\npython.exe -I %*\r\n"), None);
    }

    #[test]
    fn windows_python_comes_from_the_older_user_bin_launcher() {
        let exe = wlauncher(true, "hermes.exe");
        let read = files(vec![(exe.clone(), fake_exe(&format!("#!{WIN_PY} -I\n")))]);
        let got = discover_python_in(wenv(), fs_with(&[&exe, Path::new(WIN_PY)]), read, Os::Windows);
        assert_eq!(got, Ok(PathBuf::from(WIN_PY)));
        // HERMES_HOME names the home whose user bin is read.
        let custom = PathBuf::from(r"D:\hermes").join("bin").join("hermes.cmd");
        let py = r"D:\hermes\tools\python.exe";
        let read = files(vec![(custom.clone(), format!("@echo off\r\n\"{py}\" -I -c \"x\" %*\r\n").into_bytes())]);
        let env = env_of(&[("HERMES_HOME", r"D:\hermes")]);
        assert_eq!(discover_python_in(env, fs_with(&[&custom, Path::new(py)]), read, Os::Windows), Ok(PathBuf::from(py)));
    }

    #[test]
    fn windows_launcher_naming_a_missing_python_falls_through() {
        let exe = wlauncher(false, "hermes.exe");
        let agent = PathBuf::from(r"C:\Users\u\AppData\Local").join("hermes").join("hermes-agent");
        let venv = agent.join("venv").join("Scripts").join("python.exe");
        let read = || files(vec![(exe.clone(), fake_exe(&format!("#!{WIN_PY} -I\n")))]);
        assert_eq!(discover_python_in(wenv(), fs_with(&[&exe, &venv]), read(), Os::Windows), Ok(venv.clone()));
        assert_eq!(discover_python_in(wenv(), fs_with(&[&exe]), read(), Os::Windows).unwrap_err(), HERMES_NOT_FOUND);
        // An install upgraded to PM keeps its old venv; the launcher's Python still wins.
        let both = fs_with(&[&exe, &venv, Path::new(WIN_PY)]);
        assert_eq!(discover_python_in(wenv(), both, read(), Os::Windows), Ok(PathBuf::from(WIN_PY)));
    }

    #[test]
    fn windows_launcher_exe_without_a_dash_i_shebang_is_ignored() {
        let exe = Path::new("hermes.exe");
        assert_eq!(windows_launcher_python(exe, &fake_exe("")), None);
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!{WIN_PY}\n"))), None);
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!{WIN_PY} -E\n"))), None);
        assert_eq!(windows_launcher_python(exe, &fake_exe("#!python.exe -I\n")), None);
        assert_eq!(windows_launcher_python(exe, &fake_exe(&format!("#!/bin/sh\nexec {WIN_PY} -I\n"))), None);
        // No zip, or a truncated directory record: nothing.
        assert_eq!(windows_launcher_python(exe, format!("MZ\0#!{WIN_PY} -I\n").as_bytes()), None);
        assert_eq!(windows_launcher_python(exe, b"\x00\x01PK\x05\x06garbage"), None);
        let launcher = wlauncher(false, "hermes.exe");
        let read = files(vec![(launcher.clone(), b"not a launcher".to_vec())]);
        let got = discover_python_in(wenv(), fs_with(&[&launcher, Path::new(WIN_PY)]), read, Os::Windows);
        assert_eq!(got.unwrap_err(), HERMES_NOT_FOUND);
    }

    #[test]
    fn windows_launcher_exe_is_read_before_the_cmd() {
        let (exe, cmd) = (wlauncher(false, "hermes.exe"), wlauncher(false, "hermes.cmd"));
        let other = r"C:\old\python.exe";
        let read = files(vec![
            (exe.clone(), fake_exe(&format!("#!{WIN_PY} -I\n"))),
            (cmd.clone(), format!("@echo off\r\n\"{other}\" -I -c \"x\" %*\r\n").into_bytes()),
        ]);
        let got = discover_python_in(wenv(), fs_with(&[&exe, &cmd, Path::new(WIN_PY), Path::new(other)]), read, Os::Windows);
        assert_eq!(got, Ok(PathBuf::from(WIN_PY)));
    }

    #[test]
    fn unix_never_reads_a_windows_launcher() {
        let exe = PathBuf::from("/h/.hermes/hermes-agent/.hermes/bin/hermes.exe");
        let read = files(vec![(exe.clone(), fake_exe("#!C:\\p\\python.exe -I\n"))]);
        let got = discover_python_in(env_of(&[("HOME", "/h")]), fs_with(&[&exe, Path::new(r"C:\p\python.exe")]), read, Os::Unix);
        assert_eq!(got.unwrap_err(), HERMES_NOT_FOUND);
    }

    #[test]
    fn launcher_python_reads_the_shlex_joined_exec_word() {
        // hermes_cli/_launchers.py writes `exec {shlex.join(command)} "$@"`.
        let spaced = "#!/bin/sh\nexec '/Users/k k/.hermes/tools/python-3.14.9/bin/python3' -I -c 'import os\nx'\n";
        assert_eq!(launcher_python(spaced), Some(PathBuf::from("/Users/k k/.hermes/tools/python-3.14.9/bin/python3")));
        let apostrophe = "#!/bin/sh\nexec '/Users/o'\"'\"'neil/py' -I\n";
        assert_eq!(launcher_python(apostrophe), Some(PathBuf::from("/Users/o'neil/py")));
        assert_eq!(launcher_python("#!/bin/sh\nexec /p/py -I -c 'a b'\n"), Some(PathBuf::from("/p/py")));
        assert_eq!(launcher_python("#!/bin/sh\nexec '/p/unterminated\n"), None);
    }

    #[test]
    fn launcher_python_needs_an_absolute_exec_target() {
        assert_eq!(launcher_python("#!/bin/sh\nexec \"/p/py\" -I\n"), Some(PathBuf::from("/p/py")));
        assert_eq!(launcher_python("#!/bin/sh\nexec python3 -I\n"), None);
        assert_eq!(launcher_python("echo hi\n"), None);
    }

    #[test]
    fn python_missing_says_install_hermes() {
        let err = discover_python(env_of(&[("HOME", "/h")]), fs_of(&[])).unwrap_err();
        assert_eq!(err, "Hermes not found: install Hermes Agent first");
        let no_home = discover_python(env_of(&[]), fs_of(&[VENV])).unwrap_err();
        assert_eq!(no_home, HERMES_NOT_FOUND);
    }

    #[test]
    fn token_is_32_lowercase_hex_chars() {
        let t = make_token(|b| {
            for (i, x) in b.iter_mut().enumerate() {
                *x = (i as u8).wrapping_mul(17).wrapping_add(250);
            }
            Ok(())
        })
        .unwrap();
        assert_eq!(t.len(), 32);
        assert!(t.chars().all(|c| matches!(c, '0'..='9' | 'a'..='f')), "{t}");
        assert_eq!(t, "fa0b1c2d3e4f60718293a4b5c6d7e8f9");
    }

    #[test]
    fn token_comes_from_the_os_and_differs_each_time() {
        let a = new_token().unwrap();
        let b = new_token().unwrap();
        assert_eq!((a.len(), b.len()), (32, 32));
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn token_source_failure_is_an_error() {
        let r = make_token(|_| Err(std::io::Error::new(std::io::ErrorKind::Other, "no entropy")));
        assert!(r.is_err());
    }

    #[test]
    fn script_prefers_the_bundled_resource() {
        let got = resolve_script(
            Some(Path::new("/app/Resources")),
            Some(Path::new("/repo/src-tauri")),
            fs_of(&["/app/Resources/bridge/omher_bridge.py", "/repo/src-tauri/../bridge/omher_bridge.py"]),
        );
        assert_eq!(got, Ok(PathBuf::from("/app/Resources/bridge/omher_bridge.py")));
    }

    #[test]
    fn script_falls_back_to_the_repo_in_dev_and_names_what_it_tried() {
        let dev = resolve_script(
            Some(Path::new("/app/Resources")),
            Some(Path::new("/repo/src-tauri")),
            fs_of(&["/repo/src-tauri/../bridge/omher_bridge.py"]),
        );
        assert_eq!(dev, Ok(PathBuf::from("/repo/src-tauri/../bridge/omher_bridge.py")));
        let none = resolve_script(Some(Path::new("/app/Resources")), None, fs_of(&[])).unwrap_err();
        let tried = Path::new("/app/Resources").join("bridge").join("omher_bridge.py");
        assert!(none.contains(&tried.display().to_string()), "{none}");
    }

    #[test]
    fn child_args_ask_for_a_free_port_and_stdin_eof_exit() {
        let a = bridge_args(Path::new("/b/omher_bridge.py"), "abc");
        assert_eq!(a, ["/b/omher_bridge.py", "--port", "0", "--token", "abc", "--exit-on-stdin-eof"]);
    }

    #[test]
    fn url_is_loopback_with_the_token() {
        assert_eq!(bridge_ws_url(4321, "t0k"), "ws://127.0.0.1:4321/?token=t0k");
    }

    #[test]
    fn status_serialises_as_the_ui_expects() {
        let ready = serde_json::to_string(&BridgeStatus::of("ready", None)).unwrap();
        assert_eq!(ready, r#"{"state":"ready"}"#);
        let failed = serde_json::to_string(&BridgeStatus::of("failed", Some("x".into()))).unwrap();
        assert_eq!(failed, r#"{"state":"failed","error":"x"}"#);
        // Only "Hermes not found" offers the installer; any other failure keeps Retry alone.
        let missing = serde_json::to_string(&BridgeStatus::of("failed", Some(HERMES_NOT_FOUND.into()))).unwrap();
        assert_eq!(missing, r#"{"state":"failed","error":"Hermes not found: install Hermes Agent first","missing":"hermes"}"#);
    }

    #[test]
    fn url_waits_for_ready_and_reports_failure() {
        let b = Bridge::new();
        assert_eq!(b.status().state, "starting");
        assert!(b.url(Duration::from_millis(20)).is_err());
        b.set_ready_for_test(9, "tok");
        assert_eq!(b.url(Duration::from_millis(20)).unwrap(), "ws://127.0.0.1:9/?token=tok");
        b.stop();
        assert_eq!(b.status().state, "failed");
    }

    /// A child that has already exited with code 3 (reaped, so `try_wait` reports it at once).
    fn exited_child() -> Child {
        let mut cmd = if cfg!(windows) { Command::new("cmd") } else { Command::new("sh") };
        cmd.args(if cfg!(windows) { ["/C", "exit 3"] } else { ["-c", "exit 3"] });
        let mut child = cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
        child.wait().unwrap();
        child
    }

    /// A child that keeps running until it is killed.
    fn live_child() -> Child {
        let mut cmd = if cfg!(windows) { Command::new("cmd") } else { Command::new("sh") };
        cmd.args(if cfg!(windows) { ["/C", "ping -n 30 127.0.0.1 >NUL"] } else { ["-c", "sleep 30"] });
        cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap()
    }

    #[test]
    fn revive_waits_double_each_quick_death_and_gives_up_after_five() {
        let quick = Duration::from_secs(1);
        let mut streak = 0;
        let mut waits = Vec::new();
        loop {
            let (next, wait) = revive_plan(streak, quick);
            streak = next;
            match wait {
                Some(w) => waits.push(w.as_millis()),
                None => break,
            }
        }
        assert_eq!(waits, [500, 1000, 2000, 4000, 8000]);
        assert_eq!(streak, MAX_QUICK_DEATHS + 1);
    }

    #[test]
    fn a_long_life_starts_the_quick_death_count_again() {
        assert_eq!(revive_plan(3, Duration::ZERO), (4, Some(Duration::from_secs(4))));
        assert_eq!(revive_plan(u32::MAX - 1, Duration::ZERO).1, None);
        // a bridge that ran a while before dying is revived at the first wait, however many died before it
        assert_eq!(revive_plan(MAX_QUICK_DEATHS, STEADY_LIFE), (1, Some(Duration::from_millis(500))));
        assert_eq!(revive_plan(MAX_QUICK_DEATHS, STEADY_LIFE * 10), (1, Some(Duration::from_millis(500))));
        assert_eq!(revive_plan(MAX_QUICK_DEATHS, STEADY_LIFE - Duration::from_millis(1)).1, None);
    }

    #[test]
    fn url_never_hands_out_the_port_of_a_bridge_that_exited() {
        let b = Bridge::new();
        let gen = b.set_child_for_test(9, exited_child(), 0);
        // the dead bridge is noticed on use: the URL waits for the revive instead of naming port 9
        assert_eq!(b.url(Duration::from_millis(20)), Err("the bridge is still starting".to_string()));
        assert_eq!(b.status(), BridgeStatus::of("starting", None));
        {
            let g = b.inner.lock().unwrap();
            assert!(g.child.is_none(), "the dead child is reaped");
            assert_eq!(g.streak, 1);
            assert!(g.generation > gen, "the revive runs as a new generation");
        }
        // the app quits before the revive's 500 ms wait ends: nothing starts
        b.stop();
        assert_eq!(b.status().state, "failed");
    }

    #[test]
    fn a_crash_loop_ends_in_the_failure_the_gate_shows() {
        let b = Bridge::new();
        b.set_child_for_test(9, exited_child(), MAX_QUICK_DEATHS);
        let status = b.status();
        assert_eq!(status.state, "failed");
        let error = status.error.unwrap();
        assert!(error.starts_with("the bridge stopped unexpectedly ("), "{error}");
        assert!(error.ends_with("it stopped 6 times in a row, so omher stopped starting it"), "{error}");
        assert_eq!(b.url(Duration::from_millis(20)), Err(error));
    }

    #[test]
    fn a_live_bridge_keeps_its_url() {
        let b = Bridge::new();
        b.set_child_for_test(9, live_child(), 0);
        assert_eq!(b.url(Duration::from_millis(20)).unwrap(), "ws://127.0.0.1:9/?token=tok");
        assert_eq!(b.status().state, "ready");
        b.stop();
    }

    #[test]
    fn a_bridge_the_app_stopped_is_not_started_again() {
        let b = Bridge::new();
        let gen = b.set_child_for_test(9, live_child(), 0);
        b.stop();
        // the stopped child's stdout reader reports its end afterwards: it belongs to a generation the app ended
        b.died(gen);
        assert_eq!(b.status(), BridgeStatus::of("failed", Some("the bridge was stopped".into())));
        assert_eq!(b.inner.lock().unwrap().streak, 0);
    }

    #[test]
    fn a_bridge_that_dies_while_the_installer_runs_waits_for_it() {
        let b = Bridge::new();
        b.set_child_for_test(9, exited_child(), 0);
        b.hold();
        assert_eq!(b.status().state, "starting", "no failure shows while the installer runs");
        let g = b.inner.lock().unwrap();
        assert!(g.died_while_held);
        assert_eq!(g.streak, 0, "no revive was planned");
        assert!(g.child.is_none());
    }

    #[test]
    fn a_revive_due_after_the_installer_started_waits_for_it() {
        let b = Bridge::new();
        b.set_child_for_test(9, exited_child(), 0);
        assert_eq!(b.status().state, "starting", "the revive is planned for 500 ms from now");
        b.hold();
        thread::sleep(Duration::from_millis(900));
        {
            let g = b.inner.lock().unwrap();
            assert!(g.died_while_held, "the planned revive left the bridge to the installer's end");
            assert!(g.child.is_none(), "nothing started while the installer runs");
        }
        b.stop();
    }

    #[test]
    fn a_quit_during_the_install_starts_nothing_when_the_installer_ends() {
        let b = Bridge::new();
        b.set_child_for_test(9, exited_child(), 0);
        b.hold();
        assert_eq!(b.status().state, "starting");
        b.stop();
        {
            let g = b.inner.lock().unwrap();
            assert!(!g.held && !g.died_while_held, "the quit ended the hold");
        }
        let gen = b.inner.lock().unwrap().generation;
        b.release();
        assert_eq!(b.inner.lock().unwrap().generation, gen, "release started nothing");
        assert_eq!(b.status(), BridgeStatus::of("failed", Some("the bridge was stopped".into())));
    }

    #[test]
    fn the_installer_ending_starts_a_bridge_that_died_meanwhile_as_a_new_generation() {
        let b = Bridge::new();
        b.set_child_for_test(9, exited_child(), 0);
        b.hold();
        assert_eq!(b.status().state, "starting");
        let gen = b.inner.lock().unwrap().generation;
        b.release();
        assert!(b.inner.lock().unwrap().generation > gen, "a fresh generation, so no launch of the old one can run too");
        // the launch ran: here it fails at once, as a test has no interpreter of its own, and that failure shows
        let deadline = Instant::now() + Duration::from_secs(5);
        while b.status().state == "starting" && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(b.status(), BridgeStatus::of("failed", Some("a test launches only the interpreter it set".into())));
    }

    /// The whole loop on a stand-in for Hermes' Python (a sh script, so Unix only): the first bridge is ready on
    /// port 40001 and exits; omher notices through its stdout, starts it again, and hands out 40002.
    #[cfg(unix)]
    #[test]
    fn a_bridge_that_exits_after_ready_comes_back_on_a_new_port() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("omher-bridge-revive-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let py = dir.join("python");
        let script = r#"#!/bin/sh
d=$(dirname "$0")
n=$(cat "$d/count" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$d/count"
echo "OMHER_BRIDGE_READY {\"port\": $((40000+n))}"
if [ $n -eq 1 ]; then sleep 0.3; exit 7; fi
cat >/dev/null
"#;
        std::fs::write(&py, script).unwrap();
        std::fs::set_permissions(&py, std::fs::Permissions::from_mode(0o755)).unwrap();
        let b = Bridge::new();
        b.inner.lock().unwrap().python = Some(py.clone());
        b.start(None);
        let first = b.url(Duration::from_secs(5)).unwrap();
        assert!(first.starts_with("ws://127.0.0.1:40001/?token="), "{first}");
        let deadline = Instant::now() + Duration::from_secs(10);
        let second = loop {
            match b.url(Duration::from_secs(2)) {
                Ok(u) if u.starts_with("ws://127.0.0.1:40002/") => break u,
                _ if Instant::now() > deadline => panic!("the bridge did not come back: {:?}", b.status()),
                _ => thread::sleep(Duration::from_millis(50)),
            }
        };
        assert_ne!(first.split("token=").nth(1), second.split("token=").nth(1), "a new token with the new port");
        assert_eq!(b.status().state, "ready");
        assert_eq!(b.inner.lock().unwrap().streak, 1);
        b.stop();
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_stdout_reader_reports_a_death_once() {
        let b = Bridge::new();
        let gen = b.set_child_for_test(9, exited_child(), 0);
        b.died(gen);
        let after = b.inner.lock().unwrap().generation;
        b.died(gen); // the second report (or a stale one) changes nothing
        assert_eq!(b.inner.lock().unwrap().generation, after);
        assert_eq!(b.inner.lock().unwrap().streak, 1);
        b.stop();
    }
}

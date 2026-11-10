//! Starts, owns and stops the omher bridge (`bridge/omher_bridge.py`).
//!
//! The app spawns the bridge with Hermes' own Python, reads its `OMHER_BRIDGE_READY {"port": N}` line
//! and hands the UI a loopback `ws://` URL carrying a per-launch random token. The child's stdin stays
//! open for the life of the app: the bridge runs with `--exit-on-stdin-eof`, so it also stops if this
//! process dies without cleaning up. The app makes no model or network call of its own.

use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

pub const READY_PREFIX: &str = "OMHER_BRIDGE_READY ";
pub const READY_TIMEOUT: Duration = Duration::from_secs(20);
pub const HERMES_NOT_FOUND: &str = "Hermes not found: install Hermes Agent first";
const STDERR_TAIL_LINES: usize = 6;

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

/// Where Hermes' Python lives, in the order the person would expect: `OMHER_HERMES_PYTHON`, then (Unix) the
/// interpreter each Hermes home's PM launcher `hermes-agent/.hermes/bin/hermes` execs, then each home's
/// `hermes-agent/venv`, then `hermes-agent/.venv` (`bin/python`, or `Scripts\python.exe` on Windows).
/// The launcher goes first because it is the Python `hermes` itself runs on: an install upgraded to the
/// unified package manager keeps its old venv, whose older Python cannot load the committed dependency
/// generation the bridge activates. `env` and `exists` are injected so tests never touch the real machine.
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
    discover_python_in(env, exists, |p| std::fs::read_to_string(p).ok(), os)
}

/// The interpreter a PM launcher script `exec`s: `exec /abs/python3 -I -c '...'`. Hermes writes that line
/// with `shlex.join`, so a path with a space arrives as `'/a b/python3'` and an apostrophe as `'"'"'`; read
/// the first word the way sh does, as Hermes' own `_launchers` reader does.
fn launcher_python(script: &str) -> Option<PathBuf> {
    let line = script.lines().find_map(|l| l.strip_prefix("exec "))?;
    let exe = first_sh_word(line)?;
    Some(PathBuf::from(exe)).filter(|p| p.is_absolute())
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

pub fn discover_python_in<E, X, R>(env: E, exists: X, read: R, os: Os) -> Result<PathBuf, String>
where
    E: Fn(&str) -> Option<String>,
    X: Fn(&Path) -> bool,
    R: Fn(&Path) -> Option<String>,
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
    for home in hermes_homes(&env, os) {
        let agent = home.join("hermes-agent");
        if os == Os::Unix {
            let launcher = agent.join(".hermes").join("bin").join("hermes");
            if let Some(p) = exists(&launcher).then(|| read(&launcher)).flatten().as_deref().and_then(launcher_python) {
                if exists(&p) {
                    return Ok(p);
                }
            }
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
            }),
            changed: Condvar::new(),
        })
    }

    /// (Re)start the bridge in the background. Any earlier child is stopped first.
    pub fn start(self: &Arc<Self>, resource_dir: Option<PathBuf>) {
        let generation = {
            let mut g = self.inner.lock().unwrap();
            stop_locked(&mut g);
            g.generation += 1;
            g.phase = Phase::Starting;
            g.generation
        };
        self.changed.notify_all();
        let me = Arc::clone(self);
        thread::spawn(move || {
            let result = me.launch(generation, resource_dir.as_deref());
            if let Err(e) = result {
                eprintln!("omher: bridge failed: {e}");
                me.finish(generation, Phase::Failed(e));
            }
        });
    }

    fn launch(self: &Arc<Self>, generation: u64, resource_dir: Option<&Path>) -> Result<(), String> {
        let python = discover_python(|k| std::env::var(k).ok(), |p| p.is_file())?;
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
        thread::spawn(move || {
            let mut sent = false;
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if !sent {
                    if let Some(port) = parse_ready_line(&line) {
                        sent = true;
                        let _ = tx.send(Ok(port));
                    }
                }
            }
            if !sent {
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
        stop_locked(&mut g);
        if g.phase == Phase::Starting || matches!(g.phase, Phase::Ready { .. }) {
            g.phase = Phase::Failed("the bridge was stopped".into());
        }
        drop(g);
        self.changed.notify_all();
    }

    pub fn status(&self) -> BridgeStatus {
        let mut g = self.inner.lock().unwrap();
        // A bridge that died after it was ready is a failure the person should see.
        if matches!(g.phase, Phase::Ready { .. }) {
            if let Some(child) = g.child.as_mut() {
                if let Ok(Some(code)) = child.try_wait() {
                    g.phase = Phase::Failed(format!("the bridge stopped unexpectedly ({code})"));
                    g.child = None;
                    g.stdin = None;
                }
            }
        }
        match &g.phase {
            Phase::Starting => BridgeStatus::of("starting", None),
            Phase::Ready { .. } => BridgeStatus::of("ready", None),
            Phase::Failed(e) => BridgeStatus::of("failed", Some(e.clone())),
        }
    }

    /// The loopback URL once ready; waits (bounded) while the bridge is still starting.
    pub fn url(&self, wait: Duration) -> Result<String, String> {
        let deadline = Instant::now() + wait;
        let mut g = self.inner.lock().unwrap();
        loop {
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

    #[cfg(test)]
    fn set_ready_for_test(&self, port: u16, token: &str) {
        let mut g = self.inner.lock().unwrap();
        g.phase = Phase::Ready { port };
        g.token = token.into();
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
        let read = |p: &Path| (p == Path::new(LAUNCHER)).then(|| script.clone());
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
}

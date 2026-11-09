//! Terminal sessions: omher starts one agent program from a FIXED list (`claude`, `codex`, `omh`, `pi`,
//! `omp`) in a pseudo-terminal, in a folder the person picked, and stops it when the session is closed or
//! the app quits.
//!
//! The UI only ever names an agent id. The program, its path and its arguments are decided here: an id that
//! is not in [`AGENTS`] is refused, and there is no way to pass a command line or extra arguments from the
//! UI. Agent discovery looks on `PATH` plus the usual install folders, because an app started from the Dock
//! or the Start menu gets a much shorter `PATH` than a terminal does.

use std::collections::HashMap;
use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;

use crate::bridge::Os;

/// One agent program omher may start.
#[derive(Debug, PartialEq, Eq)]
pub struct Agent {
    /// What the UI sends (`session_start(agent: "claude", …)`).
    pub id: &'static str,
    /// The program looked up on `PATH` and in the install folders.
    pub program: &'static str,
    pub label: &'static str,
}

/// The whole allow-list. Adding a program here is a boundary change (docs/OMHER-BOUNDARY.md rule 13).
pub const AGENTS: [Agent; 6] = [
    Agent { id: "claude", program: "claude", label: "Claude Code" },
    Agent { id: "codex", program: "codex", label: "Codex" },
    Agent { id: "omh", program: "omh", label: "oh-my-hermes" },
    Agent { id: "pi", program: "pi", label: "pi" },
    Agent { id: "omp", program: "omp", label: "oh-my-pi" },
    Agent { id: "grok", program: "grok", label: "Grok" },
];

/// The allow-list entry for `id`, or `None` for anything else (paths, command lines, other programs).
pub fn agent(id: &str) -> Option<&'static Agent> {
    AGENTS.iter().find(|a| a.id == id)
}

// ---------------------------------------------------------------------------------------------
// Discovery (pure: env, file check and OS are passed in, so both layouts are tested on any host)
// ---------------------------------------------------------------------------------------------

/// Folders to look in, in order: every `PATH` entry, then the usual per-user install folders
/// (`~/.local/bin` for Claude Code's installer, Homebrew, npm/pnpm/bun/cargo/volta globals, and on
/// Windows `%APPDATA%\npm`). Duplicates are dropped.
pub fn search_dirs<E: Fn(&str) -> Option<String>>(env: &E, os: Os) -> Vec<PathBuf> {
    let set = |k: &str| env(k).filter(|v| !v.trim().is_empty());
    let mut dirs: Vec<PathBuf> = Vec::new();
    if let Some(path) = set("PATH") {
        let sep = if os == Os::Windows { ';' } else { ':' };
        dirs.extend(path.split(sep).filter(|d| !d.trim().is_empty()).map(PathBuf::from));
    }
    let join = |base: &str, parts: &[&str]| parts.iter().fold(PathBuf::from(base), |p, c| p.join(c));
    match os {
        Os::Unix => {
            if let Some(home) = set("HOME") {
                for parts in [
                    &[".local", "bin"][..],
                    &[".bun", "bin"],
                    &[".cargo", "bin"],
                    &[".npm-global", "bin"],
                    &[".volta", "bin"],
                    &["Library", "pnpm"],
                    &[".local", "share", "pnpm"],
                ] {
                    dirs.push(join(&home, parts));
                }
            }
            if let Some(pnpm) = set("PNPM_HOME") {
                dirs.push(PathBuf::from(pnpm));
            }
            dirs.push(PathBuf::from("/opt/homebrew/bin"));
            dirs.push(PathBuf::from("/usr/local/bin"));
        }
        Os::Windows => {
            if let Some(appdata) = set("APPDATA") {
                dirs.push(join(&appdata, &["npm"]));
            }
            if let Some(profile) = set("USERPROFILE") {
                for parts in [&[".local", "bin"][..], &[".bun", "bin"], &[".cargo", "bin"], &[".volta", "bin"]] {
                    dirs.push(join(&profile, parts));
                }
            }
            if let Some(local) = set("LOCALAPPDATA") {
                dirs.push(join(&local, &["pnpm"]));
            }
            if let Some(pnpm) = set("PNPM_HOME") {
                dirs.push(PathBuf::from(pnpm));
            }
        }
    }
    let mut seen = std::collections::HashSet::new();
    dirs.retain(|d| seen.insert(d.clone()));
    dirs
}

/// File names that start `program`: the bare name on macOS/Linux; `.exe`, then the npm `.cmd` / `.bat`
/// shims on Windows (never `.ps1`, never the extension-less npm shell script).
pub fn file_names(program: &str, os: Os) -> Vec<String> {
    match os {
        Os::Unix => vec![program.to_string()],
        Os::Windows => ["exe", "cmd", "bat"].iter().map(|e| format!("{program}.{e}")).collect(),
    }
}

/// The first `dir/name` that `is_program` accepts.
pub fn resolve<X: Fn(&Path) -> bool>(program: &str, dirs: &[PathBuf], is_program: X, os: Os) -> Option<PathBuf> {
    let names = file_names(program, os);
    dirs.iter().flat_map(|d| names.iter().map(move |n| d.join(n))).find(|p| is_program(p))
}

/// argv for a resolved program. A Windows `.cmd`/`.bat` shim runs through `cmd.exe /c`, because
/// CreateProcess does not start batch files on its own. No other argument is ever added.
pub fn argv_for(path: &Path, os: Os) -> Result<Vec<OsString>, String> {
    let ext = path.extension().and_then(|e| e.to_str()).map(|e| e.to_ascii_lowercase());
    if os == Os::Windows && matches!(ext.as_deref(), Some("cmd") | Some("bat")) {
        Ok(vec!["cmd.exe".into(), "/c".into(), cmd_path_arg(&path.to_string_lossy())?.into()])
    } else {
        Ok(vec![path.as_os_str().to_owned()])
    }
}

/// The shim path as `cmd.exe /c` must see it. cmd parses that line itself, so `&`, `|`, `<`, `>`, `^`,
/// `(`, `)` and `@` in a folder name would split or change the command. Without whitespace, the path
/// reaches cmd unquoted (portable-pty quotes only on whitespace), so each of those gets a `^` escape.
/// With whitespace it arrives in quotes, and cmd keeps quotes only when no such character is inside, so
/// that case is refused, as is `%` (variable expansion, which no escape stops on a `/c` line).
pub fn cmd_path_arg(path: &str) -> Result<String, String> {
    const META: &[char] = &['&', '|', '<', '>', '^', '(', ')', '@'];
    let refuse = || Err(format!("cannot start {path} through cmd.exe: its folder name has characters cmd treats as commands"));
    if path.contains('%') || path.contains('"') {
        return refuse();
    }
    if path.chars().any(char::is_whitespace) {
        return if path.contains(META) { refuse() } else { Ok(path.to_string()) };
    }
    let mut out = String::with_capacity(path.len() + 4);
    for c in path.chars() {
        if META.contains(&c) {
            out.push('^');
        }
        out.push(c);
    }
    Ok(out)
}

fn host_env(k: &str) -> Option<String> {
    std::env::var(k).ok()
}

#[cfg(unix)]
fn is_program_file(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(p).map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
}

#[cfg(not(unix))]
fn is_program_file(p: &Path) -> bool {
    p.is_file()
}

/// `search_dirs` on this machine plus the newest nvm Node (`~/.nvm/versions/node/<v>/bin`), which npm
/// globals such as Codex live in when Node came from nvm.
fn host_dirs() -> Vec<PathBuf> {
    let os = Os::current();
    let mut dirs = search_dirs(&host_env, os);
    if os == Os::Unix {
        if let Some(home) = host_env("HOME") {
            let nvm = Path::new(&home).join(".nvm").join("versions").join("node");
            if let Ok(rd) = std::fs::read_dir(&nvm) {
                let mut vs: Vec<PathBuf> = rd.flatten().map(|e| e.path().join("bin")).filter(|p| p.is_dir()).collect();
                vs.sort();
                dirs.extend(vs.into_iter().rev());
            }
        }
    }
    dirs
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct AgentInfo {
    pub id: &'static str,
    pub label: &'static str,
    /// Where the program was found, or `None` when it is not installed.
    pub path: Option<String>,
}

/// Every allow-listed agent with where it was found on this machine.
pub fn agents_on_this_machine() -> Vec<AgentInfo> {
    let dirs = host_dirs();
    AGENTS
        .iter()
        .map(|a| AgentInfo {
            id: a.id,
            label: a.label,
            path: resolve(a.program, &dirs, is_program_file, Os::current()).map(|p| p.to_string_lossy().into_owned()),
        })
        .collect()
}

/// What omher runs for agent `id`: the allow-list entry resolved on this machine, as argv, plus the
/// `PATH` the child gets (the program's own folder and the install folders first, so `#!/usr/bin/env node`
/// shims find Node even when the app was started from the Dock).
pub fn launch_for(id: &str) -> Result<(Vec<OsString>, OsString), String> {
    let a = agent(id).ok_or_else(|| format!("unknown agent \"{id}\""))?;
    let dirs = host_dirs();
    let path = resolve(a.program, &dirs, is_program_file, Os::current())
        .ok_or_else(|| format!("{} is not installed (no `{}` found)", a.label, a.program))?;
    let mut child_dirs: Vec<PathBuf> = path.parent().map(|p| vec![p.to_path_buf()]).unwrap_or_default();
    child_dirs.extend(dirs);
    let joined = std::env::join_paths(child_dirs.iter().filter(|d| d.is_dir())).map_err(|e| e.to_string())?;
    Ok((argv_for(&path, Os::current())?, joined))
}

// ---------------------------------------------------------------------------------------------
// Live sessions
// ---------------------------------------------------------------------------------------------

/// What a session sends back: terminal bytes, then once, the exit (code; `None` when a signal ended it).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Output {
    Data(Vec<u8>),
    Exit(Option<u32>),
}

type Sink = Arc<Mutex<Box<dyn FnMut(Output) + Send>>>;

struct Live {
    master: Box<dyn MasterPty + Send>,
    /// Input for the session's writer thread. The PTY takes only about 1 KB before a write blocks, so the
    /// write happens there, never under the sessions lock.
    input: SyncSender<Vec<u8>>,
    /// Set by the writer thread when it ends.
    writer_done: Arc<AtomicBool>,
    killer: Box<dyn ChildKiller + Send + Sync>,
    pid: Option<u32>,
    exited: Arc<AtomicBool>,
}

/// Pending writes per session (keystrokes or whole pastes). A program that stops reading fills it, and
/// further writes fail at once instead of piling up.
const INPUT_QUEUE: usize = 256;

/// Reads from the PTY are merged into one message of up to this many bytes...
const COALESCE_BYTES: usize = 64 * 1024;
/// ...collected for at most this long after the first byte arrives (keeps typing echo prompt).
const COALESCE_WINDOW: Duration = Duration::from_millis(4);

/// Every running session of this app. Dropped sessions are stopped; [`Sessions::close_all`] runs on exit.
#[derive(Default)]
pub struct Sessions {
    live: Mutex<HashMap<u32, Live>>,
    next: AtomicU32,
}

fn clamp_size(cols: u16, rows: u16) -> PtySize {
    PtySize { cols: cols.clamp(2, 1000), rows: rows.clamp(2, 500), pixel_width: 0, pixel_height: 0 }
}

impl Sessions {
    pub fn new() -> Arc<Sessions> {
        Arc::new(Sessions::default())
    }

    /// Start `argv` in a new pseudo-terminal in `cwd`. Crate-internal: the app reaches it only through
    /// [`Sessions::start_agent`], so argv always comes from the allow-list (tests use it directly).
    pub(crate) fn spawn<F>(
        &self,
        argv: Vec<OsString>,
        cwd: &Path,
        path_env: Option<OsString>,
        account_env: &[(String, String)],
        cols: u16,
        rows: u16,
        sink: F,
    ) -> Result<u32, String>
    where
        F: FnMut(Output) + Send + 'static,
    {
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(format!("not a folder: {}", cwd.display()));
        }
        let pair = native_pty_system().openpty(clamp_size(cols, rows)).map_err(|e| e.to_string())?;
        let cmd = command_for(argv, cwd, path_env, account_env);
        let mut child = pair.slave.spawn_command(cmd).map_err(|e| e.to_string())?;
        drop(pair.slave); // only the child holds the terminal side, so its exit ends our reads
        let reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
        let mut writer = pair.master.take_writer().map_err(|e| e.to_string())?;
        let killer = child.clone_killer();
        let pid = child.process_id();
        let exited = Arc::new(AtomicBool::new(false));
        let sink: Sink = Arc::new(Mutex::new(Box::new(sink)));

        let id = self.next.fetch_add(1, Ordering::SeqCst) + 1;
        spawn_reader(reader, sink.clone());
        let (input, queued) = mpsc::sync_channel::<Vec<u8>>(INPUT_QUEUE);
        let writer_done = Arc::new(AtomicBool::new(false));
        {
            let done = writer_done.clone();
            thread::spawn(move || {
                for chunk in queued {
                    if writer.write_all(&chunk).and_then(|_| writer.flush()).is_err() {
                        break;
                    }
                }
                drop(writer);
                done.store(true, Ordering::SeqCst);
            });
        }
        {
            let exited = exited.clone();
            thread::spawn(move || {
                let code = match child.wait() {
                    Ok(st) if st.signal().is_none() => Some(st.exit_code()),
                    _ => None,
                };
                exited.store(true, Ordering::SeqCst);
                // let the reader drain what the program printed last
                thread::sleep(Duration::from_millis(120));
                if let Ok(mut f) = sink.lock() {
                    f(Output::Exit(code));
                }
            });
        }
        self.live.lock().unwrap().insert(id, Live { master: pair.master, input, writer_done, killer, pid, exited });
        Ok(id)
    }

    /// Start allow-listed agent `agent` in `cwd`. Anything not in [`AGENTS`] is refused before a process
    /// exists. `account_env` is `accounts::session_env` for that agent: the chosen account's home variable,
    /// or nothing.
    pub fn start_agent<F>(&self, agent_id: &str, cwd: &Path, account_env: &[(String, String)], cols: u16, rows: u16, sink: F) -> Result<u32, String>
    where
        F: FnMut(Output) + Send + 'static,
    {
        let (argv, path_env) = launch_for(agent_id)?;
        self.spawn(argv, cwd, Some(path_env), account_env, cols, rows, sink)
    }

    /// Queue `data` for session `id`'s writer thread. Never blocks: a program that is not reading its
    /// input makes this fail once the queue is full.
    pub fn write(&self, id: u32, data: &[u8]) -> Result<(), String> {
        let input = self.live.lock().unwrap().get(&id).ok_or("no such session")?.input.clone();
        match input.try_send(data.to_vec()) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => Err("the program is not reading its input".into()),
            Err(TrySendError::Disconnected(_)) => Err("the session's input is closed".into()),
        }
    }

    pub fn resize(&self, id: u32, cols: u16, rows: u16) -> Result<(), String> {
        let g = self.live.lock().unwrap();
        let s = g.get(&id).ok_or("no such session")?;
        s.master.resize(clamp_size(cols, rows)).map_err(|e| e.to_string())
    }

    /// Stop the session's program (hang-up, then a hard kill after a grace period) and forget it.
    pub fn close(&self, id: u32) {
        let live = self.live.lock().unwrap().remove(&id);
        if let Some(s) = live {
            thread::spawn(move || stop(s, Duration::from_millis(1500)));
        }
    }

    /// Stop every session now (the app is quitting).
    pub fn close_all(&self) {
        let all: Vec<Live> = self.live.lock().unwrap().drain().map(|(_, s)| s).collect();
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

/// The command a session runs: `argv` in `cwd`, with the terminal variables, the child `PATH`, and the chosen
/// account's home variable (`account_env`, empty for the CLI's own login). Nothing else is added.
fn command_for(argv: Vec<OsString>, cwd: &Path, path_env: Option<OsString>, account_env: &[(String, String)]) -> CommandBuilder {
    let mut cmd = CommandBuilder::from_argv(argv);
    cmd.cwd(cwd);
    cmd.env("TERM", "xterm-256color");
    cmd.env("COLORTERM", "truecolor");
    cmd.env("TERM_PROGRAM", "omher");
    if let Some(p) = path_env {
        cmd.env("PATH", p);
    }
    #[cfg(unix)]
    if std::env::var_os("LANG").is_none() {
        // A Dock-started app has no locale; the agents' TUIs need UTF-8.
        cmd.env("LANG", "en_US.UTF-8");
    }
    for (k, v) in account_env {
        cmd.env(k, v);
    }
    cmd
}

/// One thread reads the PTY (macOS hands out at most 1 KB per read); another merges what arrives into
/// one message per [`COALESCE_WINDOW`] / [`COALESCE_BYTES`], so a big dump is a few dozen Channel sends
/// instead of one per KB.
fn spawn_reader(mut reader: Box<dyn Read + Send>, sink: Sink) {
    let (tx, rx) = mpsc::channel::<Vec<u8>>();
    thread::spawn(move || {
        let mut buf = [0u8; 16 * 1024];
        loop {
            match reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if tx.send(buf[..n].to_vec()).is_err() {
                        break;
                    }
                }
            }
        }
    });
    thread::spawn(move || {
        coalesce(rx, COALESCE_BYTES, COALESCE_WINDOW, |b| {
            if let Ok(mut f) = sink.lock() {
                f(Output::Data(b));
            }
        })
    });
}

/// Wait for a chunk, then keep taking chunks until `max` bytes or `window` after that first chunk, and
/// emit them as one buffer. Returns when the sender is gone and everything was emitted.
fn coalesce(rx: Receiver<Vec<u8>>, max: usize, window: Duration, mut emit: impl FnMut(Vec<u8>)) {
    while let Ok(mut buf) = rx.recv() {
        let deadline = Instant::now() + window;
        let mut open = true;
        while buf.len() < max {
            let left = deadline.saturating_duration_since(Instant::now());
            match rx.recv_timeout(left) {
                Ok(more) => buf.extend_from_slice(&more),
                Err(RecvTimeoutError::Timeout) => break,
                Err(RecvTimeoutError::Disconnected) => {
                    open = false;
                    break;
                }
            }
        }
        emit(buf);
        if !open {
            return;
        }
    }
}

/// Hang up the program's process group, wait up to `grace`, then kill it hard. Dropping the master side
/// closes the terminal, which hangs up anything still attached to it. A writer thread stuck on a full PTY
/// is waited for only briefly: it ends once the terminal is gone, and nothing here waits on it for long.
fn stop(mut s: Live, grace: Duration) {
    // A program that already ended is not signalled: its pid may belong to someone else by now.
    if !s.exited.load(Ordering::SeqCst) {
        signal_group(s.pid, false);
        let _ = s.killer.kill();
    }
    let Live { master, input, writer_done, exited, pid, .. } = s;
    drop(input); // the writer thread ends after the write it is in, if any
    let wait = |flag: &AtomicBool, limit: Duration| {
        let deadline = Instant::now() + limit;
        while !flag.load(Ordering::SeqCst) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(25));
        }
        flag.load(Ordering::SeqCst)
    };
    if !wait(&exited, grace) {
        signal_group(pid, true);
    }
    drop(master);
    wait(&writer_done, Duration::from_millis(200));
}

/// SIGHUP (or SIGKILL when `hard`) to the session's process group. The child is a session leader (the
/// PTY made it one), so its group id is its pid and helpers it started go too. Windows: the ConPTY close
/// and `TerminateProcess` from the killer end it.
#[cfg(unix)]
fn signal_group(pid: Option<u32>, hard: bool) {
    if let Some(pid) = pid.filter(|p| *p > 1) {
        let sig = if hard { libc::SIGKILL } else { libc::SIGHUP };
        unsafe {
            libc::kill(-(pid as i32), sig);
            if hard {
                libc::kill(pid as i32, sig);
            }
        }
    }
}

#[cfg(not(unix))]
fn signal_group(_pid: Option<u32>, _hard: bool) {}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn env_of(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let m: HashMap<String, String> = pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        move |k| m.get(k).cloned()
    }

    fn fs_of(files: &[&Path]) -> impl Fn(&Path) -> bool {
        let set: HashSet<PathBuf> = files.iter().map(|p| p.to_path_buf()).collect();
        move |p| set.contains(p)
    }

    #[test]
    fn allow_list_is_exactly_the_five_agents() {
        let ids: Vec<&str> = AGENTS.iter().map(|a| a.id).collect();
        assert_eq!(ids, ["claude", "codex", "omh", "pi", "omp", "grok"]);
        for a in &AGENTS {
            assert_eq!(a.id, a.program, "the id is the program name; nothing else is ever run");
        }
    }

    #[test]
    fn refuses_anything_not_on_the_allow_list() {
        assert!(agent("claude").is_some());
        for bad in ["", "sh", "bash", "/bin/sh", "claude --dangerously-skip-permissions", "claude;rm -rf ~", "CLAUDE", " claude", "../claude", "codex.cmd"] {
            assert!(agent(bad).is_none(), "{bad:?} must be refused");
            assert!(launch_for(bad).is_err(), "{bad:?} must not launch");
        }
    }

    #[test]
    fn start_agent_refuses_an_unknown_id_before_any_process() {
        let s = Sessions::default();
        let tmp = std::env::temp_dir();
        let err = s.start_agent("/bin/sh", &tmp, &[], 80, 24, |_| {}).unwrap_err();
        assert!(err.contains("unknown agent"), "{err}");
        assert_eq!(s.count(), 0);
    }

    #[test]
    fn unix_dirs_are_path_then_install_folders_without_duplicates() {
        let env = env_of(&[("PATH", "/usr/bin:/bin:/opt/homebrew/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        assert_eq!(dirs[0], PathBuf::from("/usr/bin"));
        assert!(dirs.contains(&PathBuf::from("/Users/k/.local/bin")));
        assert!(dirs.contains(&PathBuf::from("/usr/local/bin")));
        assert_eq!(dirs.iter().filter(|d| **d == PathBuf::from("/opt/homebrew/bin")).count(), 1);
    }

    #[test]
    fn finds_claude_in_local_bin_when_the_app_path_is_short() {
        // A Dock-started app sees PATH=/usr/bin:/bin; Claude Code's installer puts it in ~/.local/bin.
        let env = env_of(&[("PATH", "/usr/bin:/bin"), ("HOME", "/Users/k")]);
        let dirs = search_dirs(&env, Os::Unix);
        let claude = PathBuf::from("/Users/k/.local/bin/claude");
        let codex = PathBuf::from("/opt/homebrew/bin/codex");
        let fs = fs_of(&[&claude, &codex]);
        assert_eq!(resolve("claude", &dirs, &fs, Os::Unix), Some(claude.clone()));
        assert_eq!(resolve("codex", &dirs, &fs, Os::Unix), Some(codex));
        assert_eq!(resolve("pi", &dirs, &fs, Os::Unix), None);
        assert_eq!(argv_for(&claude, Os::Unix).unwrap(), vec![OsString::from(claude.as_os_str())]);
    }

    #[test]
    fn windows_finds_npm_shims_and_runs_them_through_cmd() {
        let env = env_of(&[
            ("PATH", "C:/Windows/System32;C:/Program Files/nodejs"),
            ("APPDATA", "C:/Users/k/AppData/Roaming"),
            ("USERPROFILE", "C:/Users/k"),
        ]);
        let dirs = search_dirs(&env, Os::Windows);
        assert!(dirs.contains(&PathBuf::from("C:/Users/k/AppData/Roaming").join("npm")));
        let shim = PathBuf::from("C:/Users/k/AppData/Roaming").join("npm").join("codex.cmd");
        let script = PathBuf::from("C:/Users/k/AppData/Roaming").join("npm").join("codex");
        let exe = PathBuf::from("C:/Users/k").join(".local").join("bin").join("claude.exe");
        let fs = fs_of(&[&shim, &script, &exe]);
        // never the extension-less shell script npm also writes
        assert_eq!(resolve("codex", &dirs, &fs, Os::Windows), Some(shim.clone()));
        assert_eq!(resolve("claude", &dirs, &fs, Os::Windows), Some(exe.clone()));
        assert_eq!(argv_for(&shim, Os::Windows).unwrap(), vec![OsString::from("cmd.exe"), OsString::from("/c"), shim.into_os_string()]);
        assert_eq!(argv_for(&exe, Os::Windows).unwrap(), vec![exe.into_os_string()]);
        assert_eq!(file_names("omp", Os::Windows), ["omp.exe", "omp.cmd", "omp.bat"]);
    }

    #[test]
    fn windows_shim_paths_are_escaped_for_cmd() {
        // no whitespace: reaches cmd unquoted, so cmd's operators get a ^
        assert_eq!(cmd_path_arg(r"C:\Users\A&B\npm\codex.cmd").unwrap(), r"C:\Users\A^&B\npm\codex.cmd");
        assert_eq!(cmd_path_arg(r"C:\x^y\a|b\(1)\<c>@\codex.cmd").unwrap(), r"C:\x^^y\a^|b\^(1^)\^<c^>^@\codex.cmd");
        assert_eq!(cmd_path_arg(r"C:\Users\k\AppData\Roaming\npm\codex.cmd").unwrap(), r"C:\Users\k\AppData\Roaming\npm\codex.cmd");
        // whitespace only: quoted by the PTY layer, and cmd keeps those quotes
        assert_eq!(cmd_path_arg(r"C:\Users\Kim Lee\npm\codex.cmd").unwrap(), r"C:\Users\Kim Lee\npm\codex.cmd");
        // whitespace plus an operator, or %: cmd would split it, so refuse
        for bad in [r"C:\Users\A & B\npm\codex.cmd", r"C:\Program Files (x86)\npm\codex.cmd", r"C:\%PATH%\codex.cmd", r"C:\a\b%c\codex.cmd"] {
            assert!(cmd_path_arg(bad).is_err(), "{bad}");
        }
        let shim = PathBuf::from(r"C:\Users\A&B\npm\codex.cmd");
        assert_eq!(argv_for(&shim, Os::Windows).unwrap()[2], OsString::from(r"C:\Users\A^&B\npm\codex.cmd"));
        assert!(argv_for(Path::new(r"C:\A & B\codex.bat"), Os::Windows).is_err());
        // an .exe never goes through cmd, so its path is left alone
        let exe = PathBuf::from(r"C:\A & B\claude.exe");
        assert_eq!(argv_for(&exe, Os::Windows).unwrap(), vec![exe.into_os_string()]);
    }

    #[test]
    fn coalesce_merges_reads_up_to_the_size_cap() {
        let (tx, rx) = mpsc::channel();
        for _ in 0..200 {
            tx.send(vec![b'a'; 1024]).unwrap();
        }
        drop(tx);
        let mut out = Vec::new();
        coalesce(rx, 64 * 1024, Duration::from_secs(5), |b| out.push(b.len()));
        assert_eq!(out.iter().sum::<usize>(), 200 * 1024);
        assert_eq!(out, [64 * 1024, 64 * 1024, 64 * 1024, 8 * 1024]);
    }

    #[test]
    fn coalesce_sends_a_lone_keystroke_after_the_window() {
        let (tx, rx) = mpsc::channel();
        let (got_tx, got) = mpsc::channel();
        let t = thread::spawn(move || coalesce(rx, 64 * 1024, Duration::from_millis(4), |b| got_tx.send((b, Instant::now())).unwrap()));
        let sent = Instant::now();
        tx.send(b"k".to_vec()).unwrap();
        let (b, at) = got.recv_timeout(Duration::from_secs(2)).expect("a lone chunk must not wait for more");
        assert_eq!(b, b"k");
        assert!(at - sent < Duration::from_millis(100), "{:?}", at - sent);
        drop(tx);
        t.join().unwrap();
    }

    #[test]
    fn empty_env_still_has_system_folders() {
        let dirs = search_dirs(&env_of(&[]), Os::Unix);
        assert!(dirs.contains(&PathBuf::from("/opt/homebrew/bin")));
        assert!(search_dirs(&env_of(&[]), Os::Windows).is_empty());
    }

    #[cfg(unix)]
    fn collect(s: &Sessions, argv: &[&str], cols: u16, rows: u16) -> (u32, Arc<Mutex<Vec<u8>>>, Arc<Mutex<Option<Option<u32>>>>) {
        let out = Arc::new(Mutex::new(Vec::new()));
        let exit = Arc::new(Mutex::new(None));
        let (o, x) = (out.clone(), exit.clone());
        let id = s
            .spawn(argv.iter().map(OsString::from).collect(), &std::env::temp_dir().canonicalize().unwrap(), None, &[], cols, rows, move |ev| match ev {
                Output::Data(b) => o.lock().unwrap().extend(b),
                Output::Exit(c) => *x.lock().unwrap() = Some(c),
            })
            .unwrap();
        (id, out, exit)
    }

    #[cfg(unix)]
    fn wait_for(cond: impl Fn() -> bool) -> bool {
        let deadline = Instant::now() + Duration::from_secs(10);
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
    fn pty_runs_in_the_folder_with_the_size_and_reports_exit() {
        let s = Sessions::default();
        let (_id, out, exit) = collect(&s, &["/bin/sh", "-c", "pwd; stty size; exit 3"], 91, 27);
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "no exit");
        let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
        assert!(text.contains("27 91"), "{text:?}");
        assert!(text.contains(&std::env::temp_dir().canonicalize().unwrap().to_string_lossy().to_string()), "{text:?}");
        assert_eq!(*exit.lock().unwrap(), Some(Some(3)));
    }

    #[cfg(unix)]
    #[test]
    fn typing_reaches_the_program_and_close_stops_it() {
        let s = Sessions::default();
        let (id, out, exit) = collect(&s, &["/bin/cat"], 80, 24);
        s.write(id, b"ping\r").unwrap();
        assert!(wait_for(|| String::from_utf8_lossy(&out.lock().unwrap()).matches("ping").count() >= 2), "cat did not echo");
        s.resize(id, 100, 30).unwrap();
        s.close(id);
        assert_eq!(s.count(), 0);
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "close did not stop cat");
        assert!(s.write(id, b"x").is_err());
    }

    #[cfg(unix)]
    #[test]
    fn close_all_kills_a_program_that_ignores_hangup() {
        let s = Sessions::default();
        let (_id, out, exit) = collect(&s, &["/bin/sh", "-c", "trap '' HUP; echo ready; while :; do sleep 1; done"], 80, 24);
        assert!(wait_for(|| String::from_utf8_lossy(&out.lock().unwrap()).contains("ready")));
        s.close_all();
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "SIGHUP-ignoring program survived close_all");
    }

    #[cfg(unix)]
    #[test]
    fn a_big_write_to_a_program_that_never_reads_blocks_nothing() {
        let s = Sessions::default();
        let (id, out, exit) = collect(&s, &["/bin/sh", "-c", "stty raw -echo; echo ready; sleep 60"], 80, 24);
        let (other, other_out, _) = collect(&s, &["/bin/cat"], 80, 24);
        assert!(wait_for(|| String::from_utf8_lossy(&out.lock().unwrap()).contains("ready")));
        // 1 MB in 64 KB pastes: the PTY takes about 1 KB, the rest must not hold anything up
        let started = Instant::now();
        for _ in 0..16 {
            s.write(id, &vec![b'x'; 64 * 1024]).unwrap();
        }
        assert!(started.elapsed() < Duration::from_millis(500), "write blocked: {:?}", started.elapsed());
        // other sessions keep working while that one is stuck
        s.write(other, b"pong\r").unwrap();
        s.resize(other, 100, 30).unwrap();
        assert!(wait_for(|| String::from_utf8_lossy(&other_out.lock().unwrap()).contains("pong")), "other session stalled");
        let t = Instant::now();
        s.close_all();
        assert!(t.elapsed() < Duration::from_secs(2), "close_all took {:?}", t.elapsed());
        assert_eq!(s.count(), 0);
        assert!(wait_for(|| exit.lock().unwrap().is_some()), "the stuck program survived close_all");
    }

    #[cfg(unix)]
    #[test]
    fn a_large_dump_arrives_in_few_messages() {
        let s = Sessions::default();
        let events = Arc::new(Mutex::new(Vec::<usize>::new()));
        let exit = Arc::new(Mutex::new(None));
        let (e, x) = (events.clone(), exit.clone());
        s.spawn(
            ["/bin/sh", "-c", "head -c 524288 /dev/zero | tr '\\0' a"].iter().map(OsString::from).collect(),
            &std::env::temp_dir().canonicalize().unwrap(),
            None,
            &[],
            80,
            24,
            move |ev| match ev {
                Output::Data(b) => e.lock().unwrap().push(b.len()),
                Output::Exit(c) => *x.lock().unwrap() = Some(c),
            },
        )
        .unwrap();
        assert!(wait_for(|| exit.lock().unwrap().is_some()));
        let ev = events.lock().unwrap();
        let total: usize = ev.iter().sum();
        assert!(total >= 524288, "{total}");
        // 1 KB per read would be over 500 messages
        assert!(ev.len() < 64, "{} messages for {total} bytes", ev.len());
    }

    #[test]
    fn refuses_a_cwd_that_is_not_a_folder() {
        let s = Sessions::default();
        assert!(s.spawn(vec!["x".into()], Path::new("relative/dir"), None, &[], 80, 24, |_| {}).is_err());
        assert!(s.spawn(vec!["x".into()], &std::env::temp_dir().join("omher-no-such-dir-x9"), None, &[], 80, 24, |_| {}).is_err());
    }

    /// A temp home whose `active.json` picks `active` for claude, with that account's folder made.
    fn home_with_claude(name: &str, active: &str) -> PathBuf {
        let home = std::env::temp_dir().join(format!("omher-sess-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        let root = home.join(".omher").join("accounts");
        std::fs::create_dir_all(root.join("claude").join("work")).unwrap();
        std::fs::write(root.join("active.json"), format!(r#"{{"claude":"{active}"}}"#)).unwrap();
        home
    }

    #[test]
    fn a_claude_session_carries_the_stacked_account_home_and_this_computer_carries_none() {
        let cwd = std::env::temp_dir();
        let argv = || vec![OsString::from("/x/claude")];
        let extra = |cmd: &CommandBuilder| -> Vec<(String, String)> {
            cmd.iter_extra_env_as_str().map(|(k, v)| (k.to_string(), v.to_string())).collect()
        };
        let base = extra(&command_for(argv(), &cwd, None, &[]));

        let home = home_with_claude("stacked", "work");
        let env = crate::accounts::session_env(&home, "claude");
        let cmd = command_for(argv(), &cwd, None, &env);
        let work = home.join(".omher").join("accounts").join("claude").join("work");
        assert_eq!(cmd.get_env("CLAUDE_CONFIG_DIR"), Some(work.as_os_str()));
        assert_eq!(cmd.get_argv(), &argv(), "the account changes no argument");
        // the chosen account's home is the only thing added
        let mut added: Vec<_> = extra(&cmd).into_iter().filter(|p| !base.contains(p)).collect();
        added.sort();
        assert_eq!(added, vec![("CLAUDE_CONFIG_DIR".to_string(), work.to_string_lossy().into_owned())]);

        let mine = home_with_claude("this-computer", "default");
        let cmd = command_for(argv(), &cwd, None, &crate::accounts::session_env(&mine, "claude"));
        assert_eq!(extra(&cmd), base);
        assert!(!extra(&cmd).iter().any(|(k, _)| k == "CLAUDE_CONFIG_DIR"));
        let _ = (std::fs::remove_dir_all(home), std::fs::remove_dir_all(mine));
    }

    #[cfg(unix)]
    #[test]
    fn the_account_home_reaches_the_program() {
        let home = home_with_claude("pty", "work");
        let s = Sessions::default();
        let out = Arc::new(Mutex::new(Vec::new()));
        let exit = Arc::new(Mutex::new(None));
        let (o, x) = (out.clone(), exit.clone());
        let argv = ["/bin/sh", "-c", "echo \"cfg=${CLAUDE_CONFIG_DIR-unset}\""].iter().map(OsString::from).collect();
        s.spawn(argv, &std::env::temp_dir().canonicalize().unwrap(), None, &crate::accounts::session_env(&home, "claude"), 80, 24, move |ev| match ev {
            Output::Data(b) => o.lock().unwrap().extend(b),
            Output::Exit(c) => *x.lock().unwrap() = Some(c),
        })
        .unwrap();
        assert!(wait_for(|| exit.lock().unwrap().is_some()));
        let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
        let work = home.join(".omher").join("accounts").join("claude").join("work");
        assert!(text.contains(&format!("cfg={}", work.display())), "{text:?}");
        let _ = std::fs::remove_dir_all(home);
    }

    /// The real check on a developer machine: `claude --version` / `codex --version` through the same
    /// discovery and PTY path a session uses. Ignored by default (needs the programs installed):
    /// `cargo test real_agents_print_their_version -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_agents_print_their_version() {
        let s = Sessions::default();
        let mut ran = 0;
        for info in agents_on_this_machine() {
            println!("{:<7} {}", info.id, info.path.as_deref().unwrap_or("not installed"));
            if !matches!(info.id, "claude" | "codex") || info.path.is_none() {
                continue;
            }
            let (mut argv, path_env) = launch_for(info.id).unwrap();
            argv.push("--version".into()); // test only: sessions never take arguments
            let out = Arc::new(Mutex::new(Vec::new()));
            let exit = Arc::new(Mutex::new(None));
            let (o, x) = (out.clone(), exit.clone());
            let home = PathBuf::from(host_env("HOME").or_else(|| host_env("USERPROFILE")).unwrap());
            s.spawn(argv, &home, Some(path_env), &[], 80, 24, move |ev| match ev {
                Output::Data(b) => o.lock().unwrap().extend(b),
                Output::Exit(c) => *x.lock().unwrap() = Some(c),
            })
            .unwrap();
            let deadline = Instant::now() + Duration::from_secs(30);
            while exit.lock().unwrap().is_none() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(50));
            }
            let text = String::from_utf8_lossy(&out.lock().unwrap()).to_string();
            println!("{} --version via PTY -> exit {:?}, output {:?}", info.id, *exit.lock().unwrap(), text.trim());
            assert_eq!(*exit.lock().unwrap(), Some(Some(0)));
            assert!(text.chars().any(|c| c.is_ascii_digit()), "{text:?}");
            ran += 1;
        }
        assert!(ran > 0, "neither claude nor codex is installed");
    }
}

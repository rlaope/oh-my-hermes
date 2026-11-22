//! Which agent CLI runs in the foreground of a terminal session, so the session's row can show that CLI's mark.
//!
//! The classification is pure ([`agent_for_exe`], [`agent_for_process`]) and reads the agent tables that decide
//! what omher starts (`sessions::AGENTS`, `sessions::LAYOUTS`, `acp_agents::ACP_LIST`) plus the few CLIs people run
//! themselves ([`OTHER_PROGRAMS`], [`OTHER_PACKAGES`]). [`Probe`] reads one process (unix: the terminal's foreground
//! process group leader; Windows: the session program's process tree) with no shelling out; the per-session poller
//! is `Sessions::watch_foreground`. A shell, an unknown program, or a name that other programs share outside a known
//! install place is `None`: the row then shows the shell, never a wrong company's mark.

use std::path::Path;

use crate::acp_agents::ACP_LIST;
use crate::sessions::{holds, parts_of, AGENTS, LAYOUTS};

/// CLIs omher does not start itself but a person runs in a terminal: program name -> mark id (the ids of
/// src/ui/AgentIcon.tsx; `hermes` is Hermes Agent itself).
const OTHER_PROGRAMS: [(&str, &str); 5] = [("hermes", "hermes"), ("cursor-agent", "cursor"), ("amp", "amp"), ("goose", "goose"), ("aider", "aider")];

/// npm / bun packages of agents without a [`LAYOUTS`] row: `node_modules/<package>` in a program's real path.
const OTHER_PACKAGES: [(&str, &str); 8] = [
    ("@google/gemini-cli", "gemini"),
    ("@qwen-code/qwen-code", "qwen"),
    ("@moonshot-ai/kimi-code", "kimi"),
    ("@github/copilot", "copilot"),
    ("cline", "cline"),
    ("opencode-ai", "opencode"),
    ("@sourcegraph/amp", "amp"),
    ("@deepseek-ai/dsh", "dsh"),
];

/// Program names other programs share (Homebrew's `grok` regex tool, deepseek-bot's `dsh`, any `pi`): these count only
/// in a known install place ([`LAYOUTS`], [`OTHER_PACKAGES`], [`DSH_APP`]), never by name alone.
const SHARED_NAMES: [&str; 3] = ["grok", "pi", "dsh"];

/// DeepSeek Harness's own CLI lives inside its app.
const DSH_APP: &str = "DeepSeek Harness.app";

/// Programs that run a script named by an argument: the agent is then the script's (`node …/claude-code/cli.js`,
/// `python …/bin/omh`, `sh …/claude`). With no script argument (an interactive shell, a bare `node`) it is no agent.
fn is_interpreter(name: &str) -> bool {
    let n = name.to_ascii_lowercase();
    matches!(n.as_str(), "node" | "nodejs" | "bun" | "deno" | "sh" | "bash" | "zsh" | "dash" | "ksh" | "fish")
        || n.starts_with("python")
        || n.starts_with("pypy")
}

fn file_name(path: &str) -> &str {
    path.rsplit(['/', '\\']).next().unwrap_or(path)
}

/// A file name without the extension Windows or a script gives it (`claude.exe`, `codex.js`, `gemini.cmd`).
fn stem(name: &str) -> &str {
    for ext in [".exe", ".cmd", ".bat", ".js", ".mjs", ".cjs"] {
        let Some(cut) = name.len().checked_sub(ext.len()).filter(|c| *c > 0 && name.is_char_boundary(*c)) else { continue };
        if name[cut..].eq_ignore_ascii_case(ext) {
            return &name[..cut];
        }
    }
    name
}

fn by_name(name: &str) -> Option<&'static str> {
    if SHARED_NAMES.iter().any(|s| s.eq_ignore_ascii_case(name)) {
        return None;
    }
    let built_in = AGENTS.iter().map(|a| (a.program, a.id));
    let acp = ACP_LIST.iter().map(|e| (e.agent.program, e.agent.id));
    built_in.chain(acp).chain(OTHER_PROGRAMS).find(|(p, _)| p.eq_ignore_ascii_case(name)).map(|(_, id)| id)
}

fn by_place(path: &str) -> Option<&'static str> {
    let parts = parts_of(Path::new(path));
    let package = |pkg: &str| {
        let seq: Vec<&str> = std::iter::once("node_modules").chain(pkg.split('/')).collect();
        holds(&parts, &seq)
    };
    for l in &LAYOUTS {
        if l.packages.iter().any(|p| package(p)) || l.inside.iter().any(|seq| holds(&parts, seq)) {
            return Some(l.id);
        }
    }
    if let Some((_, id)) = OTHER_PACKAGES.iter().find(|(p, _)| package(p)) {
        return Some(id);
    }
    parts.iter().any(|p| p == DSH_APP).then_some("dsh")
}

/// The agent whose program `path` is (a file name or a path, either separator), or `None`: a shell, an interpreter,
/// anything unknown. A known install place wins over the name, so the native installers' versioned files
/// (`~/.local/share/claude/versions/2.1.3`, `~/.grok/bin/grok-1.0.4`) and npm packages' scripts
/// (`…/node_modules/@anthropic-ai/claude-code/cli.js`) are found too.
pub fn agent_for_exe(path: &str) -> Option<&'static str> {
    by_place(path).or_else(|| by_name(stem(file_name(path))))
}

/// The script argument of an interpreter's command line `argv` (`argv[0]` is the program itself): the first argument
/// that is not an option (`deno run` skipped). `None` when `exe` is not an interpreter or runs no script.
pub fn script_of<'a>(exe: &str, argv: &[&'a str]) -> Option<&'a str> {
    let name = stem(file_name(exe));
    if !is_interpreter(name) {
        return None;
    }
    // `-c` / `-e` / `--eval` run command text, which is no script path
    let mut args = argv.iter().skip(1).copied().take_while(|a| !matches!(*a, "-c" | "-e" | "--eval" | "-p" | "--print")).filter(|a| !a.starts_with('-'));
    let first = args.next()?;
    if name.eq_ignore_ascii_case("deno") && first == "run" {
        return args.next();
    }
    Some(first)
}

/// The agent a process is: its program `exe` (its real path), else the script an interpreter runs, by the script's
/// real path (`real`, links followed: an npm bin link leads into the package) and then by its own path.
pub fn agent_for_process<R: Fn(&str) -> Option<String>>(exe: &str, argv: &[&str], real: R) -> Option<&'static str> {
    if let Some(a) = agent_for_exe(exe) {
        return Some(a);
    }
    let script = script_of(exe, argv)?;
    real(script).and_then(|r| agent_for_exe(&r)).or_else(|| agent_for_exe(script))
}

fn real_path(p: &str) -> Option<String> {
    std::fs::canonicalize(p).ok().map(|r| r.to_string_lossy().into_owned())
}

// ---------------------------------------------------------------------------------------------
// Reading a process (no shelling out; buffers kept between ticks)
// ---------------------------------------------------------------------------------------------

/// Reads processes for one session's poller. The last answer is kept for the same process, program and command line,
/// so a steady foreground costs two small system calls a tick and no allocation.
#[derive(Default)]
pub struct Probe {
    pid: u32,
    exe: Vec<u8>,
    args: Vec<u8>,
    last: Option<&'static str>,
    #[cfg(unix)]
    scratch: Vec<u8>,
    #[cfg(unix)]
    argv: ArgvClock,
}

/// An interpreter's command line read on every probe in the first [`ARGV_FRESH`] after its process is first seen
/// (`sh -c '…; exec ./claude'` changes it then), afterwards at most every [`ARGV_EVERY`]; at once again when the
/// program or the parent changes (an exec, a reused pid).
#[cfg(unix)]
const ARGV_FRESH: std::time::Duration = std::time::Duration::from_secs(2);
#[cfg(unix)]
const ARGV_EVERY: std::time::Duration = std::time::Duration::from_secs(5);

/// When [`Probe`] reads an interpreter's command line again.
#[cfg(unix)]
#[derive(Default)]
struct ArgvClock {
    /// (pid, parent pid, first seen, last read)
    seen: Option<(u32, u32, std::time::Instant, std::time::Instant)>,
}

#[cfg(unix)]
impl ArgvClock {
    /// Whether to read process `pid`'s argv `now`; `same_exe`: its program is the one the last probe saw.
    fn due(&mut self, pid: u32, ppid: u32, same_exe: bool, now: std::time::Instant) -> bool {
        match &mut self.seen {
            Some((p, pp, first, last)) if *p == pid && *pp == ppid && same_exe => {
                if now.saturating_duration_since(*first) < ARGV_FRESH || now.saturating_duration_since(*last) >= ARGV_EVERY {
                    *last = now;
                    return true;
                }
                false
            }
            _ => {
                self.seen = Some((pid, ppid, now, now));
                true
            }
        }
    }
}

#[cfg(unix)]
impl Probe {
    /// The agent process `pid` (the terminal's foreground process group leader) is, or `None`.
    pub fn agent(&mut self, pid: u32) -> Option<&'static str> {
        self.agent_at(pid, std::time::Instant::now(), &mut argv_bytes)
    }

    /// [`Probe::agent`] at `now`, reading command lines with `read` (a test counts the reads).
    fn agent_at(&mut self, pid: u32, now: std::time::Instant, read: &mut dyn FnMut(u32, &mut Vec<u8>) -> bool) -> Option<&'static str> {
        let mut exe = [0u8; 4096];
        let Some(n) = exe_path(pid, &mut exe) else {
            self.pid = 0;
            return None;
        };
        let exe = &exe[..n];
        let exe_str = String::from_utf8_lossy(exe);
        let interp = is_interpreter(stem(file_name(&exe_str)));
        // an interpreter's command line can change under the same pid and program (`sh -c '…; exec ./claude'`): read
        // again while it is new, then every few seconds ([`ArgvClock`]); otherwise the one kept stands
        let args_ok = if !interp {
            self.scratch.clear();
            true
        } else if self.argv.due(pid, parent_pid(pid), self.pid == pid && self.exe == exe, now) {
            read(pid, &mut self.scratch)
        } else {
            self.scratch.clone_from(&self.args);
            true
        };
        if self.pid == pid && self.exe == exe && self.args == self.scratch {
            return self.last;
        }
        let agent = if interp && args_ok {
            let argv: Vec<String> = self.scratch.split(|b| *b == 0).map(|a| String::from_utf8_lossy(a).into_owned()).collect();
            let argv: Vec<&str> = argv.iter().map(String::as_str).collect();
            agent_for_process(&exe_str, &argv, real_path)
        } else {
            agent_for_exe(&exe_str)
        };
        self.pid = pid;
        self.exe.clear();
        self.exe.extend_from_slice(exe);
        std::mem::swap(&mut self.args, &mut self.scratch);
        self.last = agent;
        agent
    }
}

/// Process `pid`'s parent (macOS `proc_pidinfo` PROC_PIDTBSDINFO); 0 when it cannot be read.
#[cfg(target_os = "macos")]
fn parent_pid(pid: u32) -> u32 {
    let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
    let size = std::mem::size_of::<libc::proc_bsdinfo>() as libc::c_int;
    let n = unsafe { libc::proc_pidinfo(pid as libc::c_int, libc::PROC_PIDTBSDINFO, 0, (&mut info as *mut libc::proc_bsdinfo).cast(), size) };
    if n == size { info.pbi_ppid } else { 0 }
}

/// Linux: reading the parent costs a `/proc` file read, as much as the command line it would save; only a changed
/// program reads the command line again at once there.
#[cfg(all(unix, not(target_os = "macos")))]
fn parent_pid(_pid: u32) -> u32 {
    0
}

#[cfg(target_os = "macos")]
fn exe_path(pid: u32, buf: &mut [u8; 4096]) -> Option<usize> {
    let n = unsafe { libc::proc_pidpath(pid as i32, buf.as_mut_ptr().cast(), buf.len() as u32) };
    (n > 0).then_some(n as usize)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn exe_path(pid: u32, buf: &mut [u8; 4096]) -> Option<usize> {
    use std::io::Write;
    let mut link = [0u8; 32];
    let mut w = &mut link[..];
    write!(w, "/proc/{pid}/exe\0").ok()?;
    let n = unsafe { libc::readlink(link.as_ptr().cast(), buf.as_mut_ptr().cast(), buf.len()) };
    (n > 0).then_some(n as usize)
}

/// Process `pid`'s argv into `out`, NUL-separated (no trailing NUL). macOS: `KERN_PROCARGS2` (argc, the exec path,
/// padding, argv, environment); the buffer is sized to `KERN_ARGMAX` once and reused.
#[cfg(target_os = "macos")]
fn argv_bytes(pid: u32, out: &mut Vec<u8>) -> bool {
    out.clear();
    thread_local! {
        static BUF: std::cell::RefCell<Vec<u8>> = const { std::cell::RefCell::new(Vec::new()) };
    }
    BUF.with(|b| {
        let mut buf = b.borrow_mut();
        if buf.is_empty() {
            let mut max: libc::c_int = 0;
            let mut size = std::mem::size_of::<libc::c_int>();
            let mut mib = [libc::CTL_KERN, libc::KERN_ARGMAX];
            let ok = unsafe { libc::sysctl(mib.as_mut_ptr(), 2, (&mut max as *mut libc::c_int).cast(), &mut size, std::ptr::null_mut(), 0) };
            buf.resize(if ok == 0 && max > 0 { max as usize } else { 1 << 20 }, 0);
        }
        let mut mib = [libc::CTL_KERN, libc::KERN_PROCARGS2, pid as libc::c_int];
        let mut size = buf.len();
        let ok = unsafe { libc::sysctl(mib.as_mut_ptr(), 3, buf.as_mut_ptr().cast(), &mut size, std::ptr::null_mut(), 0) };
        if ok != 0 || size < 4 {
            return false;
        }
        let data = &buf[..size];
        let argc = i32::from_ne_bytes([data[0], data[1], data[2], data[3]]).max(0) as usize;
        let mut i = 4;
        while i < data.len() && data[i] != 0 {
            i += 1; // the exec path
        }
        while i < data.len() && data[i] == 0 {
            i += 1; // its padding
        }
        let start = i;
        let mut seen = 0;
        while i < data.len() && seen < argc {
            if data[i] == 0 {
                seen += 1;
            }
            i += 1;
        }
        let end = if seen == argc { i.saturating_sub(1) } else { i };
        out.extend_from_slice(&data[start..end.max(start)]);
        true
    })
}

/// Linux: `/proc/<pid>/cmdline`.
#[cfg(all(unix, not(target_os = "macos")))]
fn argv_bytes(pid: u32, out: &mut Vec<u8>) -> bool {
    use std::io::Read;
    out.clear();
    let Ok(mut f) = std::fs::File::open(format!("/proc/{pid}/cmdline")) else { return false };
    if f.read_to_end(out).is_err() {
        return false;
    }
    while out.last() == Some(&0) {
        out.pop();
    }
    true
}

/// Windows has no foreground process group: the newest process under the session's program (itself included)
/// whose image is a known CLI, else `None`. An npm CLI runs as `node.exe`, whose command line is not read here, so
/// on Windows only native CLIs (`claude.exe`, `codex.exe`, …) are found.
#[cfg(windows)]
impl Probe {
    pub fn agent(&mut self, root: u32) -> Option<&'static str> {
        let _ = (&self.exe, &self.args, self.pid);
        self.last = win::newest_agent(root);
        self.last
    }
}

#[cfg(windows)]
mod win {
    use std::ffi::c_void;

    type Handle = *mut c_void;
    const SNAPPROCESS: u32 = 0x2; // TH32CS_SNAPPROCESS
    const QUERY_LIMITED_INFORMATION: u32 = 0x1000; // PROCESS_QUERY_LIMITED_INFORMATION

    #[repr(C)]
    struct ProcessEntry {
        size: u32,
        usage: u32,
        pid: u32,
        heap: usize,
        module: u32,
        threads: u32,
        parent: u32,
        priority: i32,
        flags: u32,
        exe: [u16; 260],
    }

    #[repr(C)]
    #[derive(Default, Clone, Copy)]
    struct FileTime {
        low: u32,
        high: u32,
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> Handle;
        fn Process32FirstW(snap: Handle, entry: *mut ProcessEntry) -> i32;
        fn Process32NextW(snap: Handle, entry: *mut ProcessEntry) -> i32;
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
        fn QueryFullProcessImageNameW(process: Handle, flags: u32, name: *mut u16, size: *mut u32) -> i32;
        fn GetProcessTimes(process: Handle, created: *mut FileTime, exited: *mut FileTime, kernel: *mut FileTime, user: *mut FileTime) -> i32;
        fn CloseHandle(h: Handle) -> i32;
    }

    /// (pid, parent) of every process now.
    fn processes() -> Vec<(u32, u32)> {
        let mut all = Vec::new();
        unsafe {
            let snap = CreateToolhelp32Snapshot(SNAPPROCESS, 0);
            if snap.is_null() || snap as isize == -1 {
                return all;
            }
            let mut e: ProcessEntry = std::mem::zeroed();
            e.size = std::mem::size_of::<ProcessEntry>() as u32;
            let mut ok = Process32FirstW(snap, &mut e);
            while ok != 0 {
                all.push((e.pid, e.parent));
                ok = Process32NextW(snap, &mut e);
            }
            CloseHandle(snap);
        }
        all
    }

    /// The image path and creation time of `pid`.
    fn image(pid: u32) -> Option<(String, u64)> {
        unsafe {
            let h = OpenProcess(QUERY_LIMITED_INFORMATION, 0, pid);
            if h.is_null() {
                return None;
            }
            let mut name = [0u16; 1024];
            let mut len = name.len() as u32;
            let mut t = [FileTime::default(); 4];
            let got = QueryFullProcessImageNameW(h, 0, name.as_mut_ptr(), &mut len) != 0
                && GetProcessTimes(h, &mut t[0], &mut t[1], &mut t[2], &mut t[3]) != 0;
            CloseHandle(h);
            got.then(|| (String::from_utf16_lossy(&name[..len as usize]), ((t[0].high as u64) << 32) | t[0].low as u64))
        }
    }

    pub(super) fn newest_agent(root: u32) -> Option<&'static str> {
        let all = processes();
        let mut tree = vec![root];
        let mut i = 0;
        while i < tree.len() {
            let p = tree[i];
            let kids: Vec<u32> = all.iter().filter(|(c, parent)| *parent == p && *c != p && !tree.contains(c)).map(|(c, _)| *c).collect();
            tree.extend(kids);
            i += 1;
        }
        tree.iter()
            .filter_map(|p| image(*p))
            .filter_map(|(path, created)| super::agent_for_exe(&path).map(|a| (created, a)))
            .max_by_key(|(created, _)| *created)
            .map(|(_, a)| a)
    }
}

// ---------------------------------------------------------------------------------------------
// The conversation a terminal's Codex holds open (rule 11)
// ---------------------------------------------------------------------------------------------

/// Processes looked at in a terminal's foreground Codex and under it.
#[cfg(unix)]
const TREE_MAX: usize = 64;

/// The Codex conversation the Codex in the foreground of a terminal holds open. `fg` (the terminal's foreground
/// process) must be Codex by the allow-list match above; it and the Codex processes under it (at most [`TREE_MAX`]
/// processes: npm's `codex.js` runs the native binary as its child) have their open files listed, and a path
/// [`crate::past_chats::rollout_id`] accepts in `home` (the session's Codex home) names the conversation. Codex creates
/// its rollout once the first prompt is answered and keeps it open while it runs, so a process only ever names its
/// own. No file is opened or read, and only the id comes back; when a process holds several (a subagent's thread),
/// the earliest id. Windows lists no open files: `None` there.
#[cfg(unix)]
pub fn codex_conversation(fg: u32, home: &Path) -> Option<String> {
    let is_codex = |pid: u32| Probe::default().agent(pid) == Some("codex");
    if !is_codex(fg) {
        return None;
    }
    let mut tree = vec![fg];
    let mut i = 0;
    while i < tree.len() && tree.len() < TREE_MAX {
        for c in children(tree[i]) {
            if tree.len() < TREE_MAX && !tree.contains(&c) {
                tree.push(c);
            }
        }
        i += 1;
    }
    tree.into_iter()
        .filter(|p| is_codex(*p))
        .flat_map(open_paths)
        .filter_map(|p| crate::past_chats::rollout_id(home, &p))
        .map(|id| id.to_ascii_lowercase())
        .min()
}

#[cfg(windows)]
pub fn codex_conversation(_fg: u32, _home: &Path) -> Option<String> {
    None
}

/// The processes whose parent is `pid`.
#[cfg(target_os = "macos")]
fn children(pid: u32) -> Vec<u32> {
    let mut buf = [0 as libc::pid_t; TREE_MAX];
    let n = unsafe { libc::proc_listchildpids(pid as libc::pid_t, buf.as_mut_ptr().cast(), std::mem::size_of_val(&buf) as libc::c_int) };
    if n <= 0 {
        return Vec::new();
    }
    buf.iter().take(n as usize).filter(|p| **p > 0).map(|p| *p as u32).collect()
}

/// Linux: every `/proc/<n>/stat` whose parent field is `pid`.
#[cfg(all(unix, not(target_os = "macos")))]
fn children(pid: u32) -> Vec<u32> {
    let Ok(dir) = std::fs::read_dir("/proc") else { return Vec::new() };
    let parent = |c: u32| {
        let stat = std::fs::read_to_string(format!("/proc/{c}/stat")).ok()?;
        stat.rsplit_once(')')?.1.split_whitespace().nth(1)?.parse::<u32>().ok()
    };
    dir.filter_map(|e| e.ok()?.file_name().to_str()?.parse::<u32>().ok()).filter(|c| parent(*c) == Some(pid)).collect()
}

/// The paths of the regular files process `pid` holds open (macOS: `proc_pidinfo` PROC_PIDLISTFDS, then
/// `proc_pidfdinfo` PROC_PIDFDVNODEPATHINFO for each vnode). Nothing is opened.
#[cfg(target_os = "macos")]
fn open_paths(pid: u32) -> Vec<std::path::PathBuf> {
    use std::os::unix::ffi::OsStrExt;
    /// sys/proc_info.h
    const PROC_PIDFDVNODEPATHINFO: libc::c_int = 2;
    const VREG: libc::c_int = 1;
    #[repr(C)]
    #[allow(dead_code)]
    struct FileInfo {
        openflags: u32,
        status: u32,
        offset: libc::off_t,
        kind: i32,
        guardflags: u32,
    }
    #[repr(C)]
    struct VnodeWithPath {
        pfi: FileInfo,
        pvip: libc::vnode_info_path,
    }
    let pid = pid as libc::c_int;
    let need = unsafe { libc::proc_pidinfo(pid, libc::PROC_PIDLISTFDS, 0, std::ptr::null_mut(), 0) };
    if need <= 0 {
        return Vec::new();
    }
    let each = std::mem::size_of::<libc::proc_fdinfo>();
    let mut fds: Vec<libc::proc_fdinfo> = vec![unsafe { std::mem::zeroed() }; need as usize / each + 16];
    let got = unsafe { libc::proc_pidinfo(pid, libc::PROC_PIDLISTFDS, 0, fds.as_mut_ptr().cast(), (fds.len() * each) as libc::c_int) };
    if got <= 0 {
        return Vec::new();
    }
    fds.truncate(got as usize / each);
    let size = std::mem::size_of::<VnodeWithPath>() as libc::c_int;
    let mut out = Vec::new();
    for fd in fds.iter().filter(|f| f.proc_fdtype == libc::PROX_FDTYPE_VNODE as u32) {
        let mut info: VnodeWithPath = unsafe { std::mem::zeroed() };
        let n = unsafe { libc::proc_pidfdinfo(pid, fd.proc_fd, PROC_PIDFDVNODEPATHINFO, (&mut info as *mut VnodeWithPath).cast(), size) };
        if n != size || info.pvip.vip_vi.vi_type != VREG {
            continue;
        }
        let raw: &[u8; 1024] = unsafe { &*info.pvip.vip_path.as_ptr().cast() };
        let len = raw.iter().position(|b| *b == 0).unwrap_or(raw.len());
        out.push(std::path::PathBuf::from(std::ffi::OsStr::from_bytes(&raw[..len])));
    }
    out
}

/// Linux: where each `/proc/<pid>/fd/*` link points.
#[cfg(all(unix, not(target_os = "macos")))]
fn open_paths(pid: u32) -> Vec<std::path::PathBuf> {
    let Ok(dir) = std::fs::read_dir(format!("/proc/{pid}/fd")) else { return Vec::new() };
    dir.filter_map(|e| std::fs::read_link(e.ok()?.path()).ok()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn programs_by_name_and_path() {
        let table: &[(&str, Option<&str>)] = &[
            ("claude", Some("claude")),
            ("/usr/local/bin/claude", Some("claude")),
            ("/Users/me/.local/share/claude/versions/2.1.3", Some("claude")),
            ("/opt/homebrew/Caskroom/claude-code/2.0.1/claude", Some("claude")),
            ("C:\\Users\\me\\.local\\bin\\claude.exe", Some("claude")),
            ("/opt/homebrew/bin/codex", Some("codex")),
            ("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex", Some("codex")),
            ("/usr/lib/node_modules/@openai/codex/vendor/aarch64-apple-darwin/codex/codex", Some("codex")),
            ("opencode", Some("opencode")),
            ("gemini", Some("gemini")),
            ("/Users/me/.grok/bin/grok-1.0.4", Some("grok")),
            ("/Users/me/.grok/downloads/grok", Some("grok")),
            ("/Users/me/.local/bin/omh", Some("omh")),
            ("/Users/me/.hermes/hermes-agent/venv/bin/hermes", Some("hermes")),
            ("/Users/me/.pi/agent/bin/pi", Some("pi")),
            ("/opt/homebrew/Cellar/omp/1.2.0/bin/omp", Some("omp")),
            ("/Users/me/.local/bin/omp", Some("omp")),
            ("/Users/me/.local/bin/omo", Some("omo")),
            ("/Users/me/.local/bin/cursor-agent", Some("cursor")),
            ("aider", Some("aider")),
            ("qwen", Some("qwen")),
            ("COPILOT.EXE", Some("copilot")),
            ("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh", Some("dsh")),
        ];
        for (path, want) in table {
            assert_eq!(agent_for_exe(path), *want, "{path}");
        }
    }

    #[test]
    fn node_scripts_by_their_package() {
        let table: &[(&str, Option<&str>)] = &[
            ("/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js", Some("claude")),
            ("/usr/local/lib/node_modules/@openai/codex/bin/codex.js", Some("codex")),
            ("/Users/me/.bun/install/global/node_modules/@google/gemini-cli/dist/index.js", Some("gemini")),
            ("/usr/lib/node_modules/opencode-ai/bin/opencode", Some("opencode")),
            ("/usr/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js", Some("pi")),
            ("/usr/lib/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js", Some("omp")),
            ("/usr/lib/node_modules/omo-ai/dist/cli.js", Some("omo")),
            ("/usr/lib/node_modules/@xai-official/grok/cli.js", Some("grok")),
            ("/usr/lib/node_modules/@qwen-code/qwen-code/cli.js", Some("qwen")),
            ("C:\\Users\\me\\AppData\\Roaming\\npm\\node_modules\\@anthropic-ai\\claude-code\\cli.js", Some("claude")),
            ("/usr/lib/node_modules/@deepseek-ai/dsh/bin/dsh.js", Some("dsh")),
            ("/srv/app/node_modules/express/index.js", None),
        ];
        for (path, want) in table {
            assert_eq!(agent_for_exe(path), *want, "{path}");
        }
    }

    #[test]
    fn shells_interpreters_unknown_and_shared_names_are_none() {
        for path in [
            "/bin/zsh", "/bin/bash", "/opt/homebrew/bin/fish", "/bin/sh", "/opt/homebrew/bin/nu", "pwsh.exe", "/usr/bin/node",
            "/opt/homebrew/bin/bun", "/usr/bin/python3", "/bin/sleep", "/usr/bin/vim", "", "/",
            // names other programs share, outside an install place of the agent
            "/opt/homebrew/bin/grok", "/usr/local/bin/pi", "/Users/me/.local/bin/dsh", "/usr/lib/node_modules/express/cli.js",
            // a name that only contains an agent's
            "/usr/bin/claude-helper", "/usr/bin/xcodex",
        ] {
            assert_eq!(agent_for_exe(path), None, "{path}");
        }
    }

    #[test]
    fn interpreters_name_the_script_they_run() {
        let none = |_: &str| None;
        assert_eq!(agent_for_process("/usr/bin/node", &["node", "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js"], none), Some("claude"));
        assert_eq!(agent_for_process("/usr/bin/node", &["node", "--no-warnings", "/usr/local/bin/codex"], none), Some("codex"));
        assert_eq!(agent_for_process("/opt/homebrew/bin/bun", &["bun", "/x/node_modules/@google/gemini-cli/dist/index.js"], none), Some("gemini"));
        assert_eq!(agent_for_process("/opt/homebrew/bin/deno", &["deno", "run", "-A", "/x/node_modules/@openai/codex/bin/codex.js"], none), Some("codex"));
        assert_eq!(agent_for_process("/x/venv/bin/python3.12", &["python3", "/Users/me/.local/bin/omh", "chat"], none), Some("omh"));
        assert_eq!(agent_for_process("/usr/bin/python3", &["python3", "-m", "aider"], none), Some("aider"));
        assert_eq!(agent_for_process("/bin/bash", &["sh", "/tmp/t/claude"], none), Some("claude"));
        // an npm bin link: the link's name is shared, its real path is the package's
        let real = |p: &str| (p == "/opt/homebrew/bin/pi").then(|| "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js".to_string());
        assert_eq!(agent_for_process("/opt/homebrew/bin/node", &["node", "/opt/homebrew/bin/pi"], real), Some("pi"));
        assert_eq!(agent_for_process("/opt/homebrew/bin/node", &["node", "/opt/homebrew/bin/pi"], none), None);
        // no script: a shell at its prompt, a REPL, `sh -c`'s command text
        assert_eq!(agent_for_process("/bin/zsh", &["-zsh"], none), None);
        assert_eq!(agent_for_process("/bin/zsh", &["/bin/zsh", "-l"], none), None);
        assert_eq!(agent_for_process("/usr/bin/node", &["node"], none), None);
        assert_eq!(agent_for_process("/bin/sh", &["sh", "-c", "sleep 1; claude"], none), None);
        assert_eq!(agent_for_process("/bin/sh", &["sh", "-c", "claude"], none), None);
        assert_eq!(agent_for_process("/usr/bin/node", &["node", "-e", "require('/x/node_modules/@openai/codex')"], none), None);
        assert_eq!(agent_for_process("/usr/bin/node", &["node", "/srv/app/server.js"], none), None);
        // a program that is no interpreter: its arguments do not count
        assert_eq!(agent_for_process("/usr/bin/vim", &["vim", "/tmp/claude"], none), None);
        assert_eq!(agent_for_process("/usr/local/bin/claude", &["claude", "--resume"], none), Some("claude"));
    }

    #[test]
    fn every_agent_omher_starts_is_found_by_its_program() {
        for a in AGENTS.iter().filter(|a| !SHARED_NAMES.contains(&a.program)) {
            assert_eq!(agent_for_exe(a.program), Some(a.id), "{}", a.id);
        }
        for e in &ACP_LIST {
            assert_eq!(agent_for_exe(e.agent.program), Some(e.agent.id), "{}", e.agent.id);
        }
    }

    #[cfg(unix)]
    #[test]
    fn the_probe_reads_this_process() {
        let mut p = Probe::default();
        // the test binary is no agent, and asking again answers from what was kept
        assert_eq!(p.agent(std::process::id()), None);
        assert_eq!(p.agent(std::process::id()), None);
        assert!(!p.exe.is_empty());
        // a pid nobody has
        assert_eq!(p.agent(0x7fff_fff0), None);
    }

    #[cfg(unix)]
    #[test]
    fn an_interpreters_argv_is_read_while_new_then_every_five_seconds() {
        use std::time::{Duration, Instant};
        let t0 = Instant::now();
        let at = |s: u64| t0 + Duration::from_millis(s);
        let mut c = ArgvClock::default();
        assert!(c.due(7, 1, false, at(0)), "first seen");
        assert!(c.due(7, 1, true, at(1000)), "within 2 s");
        assert!(c.due(7, 1, true, at(1999)));
        assert!(!c.due(7, 1, true, at(2000)), "past 2 s, 1 s after the last read");
        assert!(!c.due(7, 1, true, at(6998)));
        assert!(c.due(7, 1, true, at(6999)), "5 s after the last read");
        assert!(!c.due(7, 1, true, at(8000)));
        // an exec (other program), a reused pid (other parent) and another process: read at once, new again
        assert!(c.due(7, 1, false, at(8100)));
        assert!(c.due(7, 1, true, at(9000)));
        assert!(!c.due(7, 1, true, at(10200)));
        assert!(c.due(7, 2, true, at(10300)));
        assert!(c.due(8, 2, true, at(10400)));
        assert!(c.due(8, 2, true, at(12300)));
        assert!(!c.due(8, 2, true, at(12500)));
    }

    /// 60 probes of one interpreter process a second apart (the poller's cadence while a terminal is busy): the argv
    /// is read 13 times, not 60, and every answer is the one an uncached probe gives.
    #[cfg(unix)]
    #[test]
    fn sixty_probes_of_an_interpreter_read_its_argv_thirteen_times() {
        use std::time::{Duration, Instant};
        let tmp = std::env::temp_dir().join(format!("omher-fg-argv-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let script = tmp.join("claude");
        std::fs::write(&script, "sleep 30\n").unwrap();
        let mut child = std::process::Command::new("/bin/sh").arg(&script).stdin(std::process::Stdio::null()).spawn().unwrap();
        let pid = child.id();
        assert_eq!(wait_for(|| Probe::default().agent(pid).map(String::from)).as_deref(), Some("claude"));
        let t0 = Instant::now();
        // the cache is what is under test, not the OS: read the real argv once (retrying, as a loaded macOS runner's
        // KERN_PROCARGS2 can fail for a moment) and hand those bytes to every read the cache asks for
        let mut real = Vec::new();
        assert!(wait_for(|| argv_bytes(pid, &mut real).then(String::new)).is_some(), "the real argv could not be read");
        let mut reads = 0;
        let mut counted = |_: u32, out: &mut Vec<u8>| {
            reads += 1;
            out.clear();
            out.extend_from_slice(&real);
            true
        };
        let mut p = Probe::default();
        for i in 0..60 {
            let got = p.agent_at(pid, t0 + Duration::from_secs(i), &mut counted);
            // the uncached reference reads the argv afresh, and on a loaded macOS runner that read can fail for a
            // moment (KERN_PROCARGS2), answering None once; retry it so the comparison is about the cache
            let fresh = wait_for(|| Probe::default().agent(pid).map(String::from));
            assert_eq!(got, fresh.as_deref(), "probe {i}");
            assert_eq!(got, Some("claude"));
        }
        let _ = child.kill();
        let _ = child.wait();
        let _ = std::fs::remove_dir_all(&tmp);
        assert_eq!(reads, 13, "argv reads over 60 probes (before this cache: 60)");
    }

    /// A Codex stand-in: `sh <dir>/codex <file>` is Codex by its script's name, and holds `<file>` open (fd 3) while
    /// it waits on a `sleep`. `body` replaces that when given.
    #[cfg(unix)]
    fn fake_codex(dir: &Path, file: &Path, body: Option<String>) -> std::process::Child {
        let script = dir.join("codex");
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(&script, body.unwrap_or_else(|| "exec 3<\"$1\"\nsleep 30\nexit 0\n".into())).unwrap();
        std::process::Command::new("/bin/sh").arg(&script).arg(file).stdin(std::process::Stdio::null()).spawn().unwrap()
    }

    #[cfg(unix)]
    fn wait_for(mut f: impl FnMut() -> Option<String>) -> Option<String> {
        for _ in 0..100 {
            if let Some(v) = f() {
                return Some(v);
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        None
    }

    #[cfg(unix)]
    #[test]
    fn a_running_codex_names_the_rollout_it_holds_open_and_nothing_else() {
        let tmp = std::env::temp_dir().join(format!("omher-fg-codex-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        let home = tmp.join("codex-home");
        let id = "01a1f468-1e1a-7ef3-903a-6d156e670edf";
        let rollout = home.join(format!("sessions/2026/01/01/rollout-x-{id}.jsonl"));
        std::fs::create_dir_all(rollout.parent().unwrap()).unwrap();
        std::fs::write(&rollout, "{}\n").unwrap();
        let mut codex = fake_codex(&tmp.join("bin"), &rollout, None);
        let pid = codex.id();
        // right after spawn the child can still be the forked test binary (Linux: before its exec of /bin/sh)
        assert_eq!(wait_for(|| Probe::default().agent(pid).map(String::from)).as_deref(), Some("codex"));
        assert_eq!(wait_for(|| codex_conversation(pid, &home)).as_deref(), Some(id));
        // only the open files of that process count, and only in its own Codex home
        assert!(open_paths(pid).iter().any(|p| p.ends_with(format!("rollout-x-{id}.jsonl"))));
        assert_eq!(codex_conversation(pid, &tmp.join("other-home")), None);
        // a program that is not Codex holds nothing for it, even with a rollout open: this test, after opening one
        let held = std::fs::File::open(&rollout).unwrap();
        assert_eq!(codex_conversation(std::process::id(), &home), None);
        drop(held);
        // Codex started by something that is Codex too (npm's codex.js runs the binary as its child)
        let inner = tmp.join("inner");
        std::fs::create_dir_all(&inner).unwrap();
        std::fs::write(inner.join("codex"), "exec 3<\"$1\"\nsleep 30\nexit 0\n").unwrap();
        let mut parent = fake_codex(&tmp.join("outer"), &rollout, Some(format!("/bin/sh {} \"$1\"\nexit 0\n", inner.join("codex").display())));
        assert!(!open_paths(parent.id()).iter().any(|p| p.ends_with(format!("rollout-x-{id}.jsonl"))));
        assert_eq!(wait_for(|| codex_conversation(parent.id(), &home)).as_deref(), Some(id));
        // a process that ended holds nothing
        let _ = codex.kill();
        let _ = codex.wait();
        assert_eq!(codex_conversation(pid, &home), None);
        for c in children(parent.id()) {
            unsafe { libc::kill(c as libc::pid_t, libc::SIGKILL) };
        }
        let _ = parent.kill();
        let _ = parent.wait();
        let _ = std::fs::remove_dir_all(&tmp);
    }
}

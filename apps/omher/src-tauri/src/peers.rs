//! SSH peers: Hermes bots that live on another computer, reached over the person's own `ssh` (BOUNDARY rule 31).
//!
//! A peer is one row of `~/.omher/peers.json` (id, label, host, optional port), written only by the confirm card's
//! Connect and checked on every read. omher stores no password or key: `ssh` runs with `BatchMode=yes`, so only a key
//! or the agent can log in, and a host that wants a password fails with a plain line naming `ssh-copy-id`.
//!
//! The link is one `ssh` child per peer with a fixed argv built here ([`ssh_args`]): a loopback forward
//! `127.0.0.1:<local>` -> the remote's `127.0.0.1:<remote>`, and one fixed `sh -c` script ([`remote_script`]) whose
//! only inputs are numbers and hex this module made. On the remote it finds Hermes' Python the way the local shell
//! does (`OMHER_HERMES_PYTHON`, the PM launcher's interpreter, `venv`, `.venv`), keeps omher's own bridge script at
//! `~/.omher/peer/omher_bridge-<sha12>.py` (the only place it writes there; sent over stdin only when that file is
//! missing or does not match), and starts it with `--exit-on-stdin-eof`. Closing the child's stdin (peer removed, app
//! quit, this process gone) ends the remote bridge. The UI never supplies a command: it names a host the shell checks.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::bridge::{bridge_ws_url, hex, new_token, no_console_window, parse_ready_line};

/// The fixed `-o` options every link runs with: key or agent login only, a bounded connect, and an exit (not a
/// half-open tunnel) when the forward cannot be set up or the link goes quiet.
pub const SSH_OPTIONS: [&str; 5] = [
    "BatchMode=yes",
    "ConnectTimeout=10",
    "ExitOnForwardFailure=yes",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
];
/// How long a link may take from `ssh` start to the remote bridge's ready line (a first copy of the script included).
pub const READY_TIMEOUT: Duration = Duration::from_secs(45);
/// Port tries when a chosen port turns out to be taken (here or there).
const PORT_TRIES: u32 = 4;
const TAIL_LINES: usize = 8;
const MAX_PEERS: usize = 16;
/// A Check's tunnel closes by itself after this, if the card never closed it.
const CHECK_TTL: Duration = Duration::from_secs(180);

// ---------------------------------------------------------------------------------------------
// Validation (every read of peers.json, every value from the page)
// ---------------------------------------------------------------------------------------------

/// `^[a-z0-9][a-z0-9-]{0,31}$`, and not `fold` / `agent` (the UI's own chat-key prefixes).
pub fn valid_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 32
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'-')
        && id != "fold"
        && id != "agent"
}

/// 1 to 40 characters, no control characters, not blank.
pub fn valid_label(label: &str) -> bool {
    let n = label.chars().count();
    (1..=40).contains(&n) && !label.trim().is_empty() && !label.chars().any(char::is_control)
}

/// An ssh config alias or `[user@]host`: the user `^[A-Za-z0-9_][A-Za-z0-9._-]{0,31}$`, the host
/// `^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$` (a name, alias or IPv4 address). Nothing that could read as an option (no
/// leading `-`), no space, quote, colon or other shell character; a port is a separate number.
pub fn valid_host(host: &str) -> bool {
    let (user, name) = match host.split_once('@') {
        Some((u, h)) => (Some(u), h),
        None => (None, host),
    };
    let user_ok = user.map_or(true, |u| {
        let b = u.as_bytes();
        !b.is_empty()
            && b.len() <= 32
            && (b[0].is_ascii_alphanumeric() || b[0] == b'_')
            && b.iter().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-'))
    });
    let n = name.as_bytes();
    user_ok
        && !n.is_empty()
        && n.len() <= 253
        && n[0].is_ascii_alphanumeric()
        && n.iter().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'-'))
}

pub fn valid_port(port: Option<u16>) -> bool {
    port.map_or(true, |p| p > 0)
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Peer {
    pub id: String,
    pub label: String,
    pub host: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,
}

impl Peer {
    pub fn valid(&self) -> bool {
        valid_id(&self.id) && valid_label(&self.label) && valid_host(&self.host) && valid_port(self.port)
    }
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct PeersFile {
    #[serde(default)]
    peers: Vec<serde_json::Value>,
}

pub fn peers_path(home: &Path) -> PathBuf {
    home.join(".omher").join("peers.json")
}

/// The peers in `~/.omher/peers.json` that pass every check (a bad or duplicate row is skipped, never used).
pub fn read_peers(home: &Path) -> Vec<Peer> {
    let Ok(text) = std::fs::read_to_string(peers_path(home)) else { return Vec::new() };
    parse_peers(&text)
}

pub fn parse_peers(text: &str) -> Vec<Peer> {
    let file: PeersFile = serde_json::from_str(text).unwrap_or_default();
    let mut out: Vec<Peer> = Vec::new();
    for v in file.peers {
        let Ok(p) = serde_json::from_value::<Peer>(v) else { continue };
        if p.valid() && !out.iter().any(|o| o.id == p.id) && out.len() < MAX_PEERS {
            out.push(p);
        }
    }
    out
}

/// Write the list (each row checked again) through a temp file in the same folder.
pub fn write_peers(home: &Path, peers: &[Peer]) -> Result<(), String> {
    if peers.iter().any(|p| !p.valid()) {
        return Err("a remote machine in the list is not valid".into());
    }
    let path = peers_path(home);
    let dir = path.parent().ok_or("no folder for peers.json")?;
    std::fs::create_dir_all(dir).map_err(|e| format!("could not make {}: {e}", dir.display()))?;
    let body = serde_json::to_string_pretty(&serde_json::json!({ "peers": peers })).map_err(|e| e.to_string())?;
    let tmp = dir.join("peers.json.tmp");
    std::fs::write(&tmp, body + "\n").map_err(|e| format!("could not write {}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, &path).map_err(|e| format!("could not write {}: {e}", path.display()))
}

/// An id for a new peer from its label (`Mac mini` -> `mac-mini`), unique among `taken`.
pub fn id_for(label: &str, taken: &[String]) -> String {
    let mut slug = String::new();
    for c in label.chars().flat_map(char::to_lowercase) {
        if c.is_ascii_alphanumeric() {
            slug.push(c);
        } else if !slug.ends_with('-') && !slug.is_empty() {
            slug.push('-');
        }
    }
    let mut base: String = slug.trim_matches('-').chars().take(24).collect();
    base = base.trim_matches('-').to_string();
    if !valid_id(&base) {
        base = "peer".into();
    }
    if !taken.contains(&base) {
        return base;
    }
    (2..).map(|n| format!("{base}-{n}")).find(|c| !taken.contains(c)).unwrap()
}

/// The `Host` aliases in an ssh config's text, for the host field's suggestions: wildcard and negated patterns
/// (`*`, `?`, `!`) are skipped, and so is anything [`valid_host`] would refuse. Read-only; `Include` is not followed.
pub fn ssh_config_hosts(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        let (key, rest) = match line.find(|c: char| c.is_whitespace() || c == '=') {
            Some(i) => (&line[..i], line[i..].trim_start_matches(|c: char| c.is_whitespace() || c == '=')),
            None => continue,
        };
        if !key.eq_ignore_ascii_case("host") {
            continue;
        }
        for name in rest.split_whitespace() {
            if name.starts_with('#') {
                break;
            }
            let name = name.trim_matches('"');
            if name.contains(['*', '?', '!']) || !valid_host(name) || out.iter().any(|o| o == name) {
                continue;
            }
            out.push(name.to_string());
        }
    }
    out
}

// ---------------------------------------------------------------------------------------------
// The fixed command
// ---------------------------------------------------------------------------------------------

/// The first 12 hex characters of the bridge script's SHA-256: its file name on the remote.
pub fn script_sha12(script: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    hex(&Sha256::digest(script))[..12].to_string()
}

/// The POSIX sh script the remote runs. Its only inputs are the sha (hex), the script size, the remote port and the
/// token (hex), all made here; it holds no backslash, so the single-quote wrapping in [`ssh_args`] reads the same in
/// sh, bash, zsh and fish login shells.
pub fn remote_script(sha12: &str, size: usize, remote_port: u16, token: &str) -> String {
    debug_assert!(sha12.len() == 12 && sha12.bytes().all(|c| c.is_ascii_hexdigit()));
    debug_assert!(token.bytes().all(|c| c.is_ascii_hexdigit()));
    // no `!` anywhere (csh history), no backslash (fish single quotes)
    let check = r#"import hashlib,sys;h=hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:12];sys.exit(0 if h==sys.argv[2] else 1)"#;
    format!(
        r#"set -u
umask 077
{discover}
d="$HOME/.omher/peer"
f="$d/omher_bridge-{sha12}.py"
mkdir -p "$d" || exit 4
if [ -f "$f" ] && "$py" -c '{check}' "$f" {sha12}; then
  echo OMHER_PEER_HAVE
else
  echo OMHER_PEER_NEED
  t="$f.part.$$"
  if head -c {size} > "$t" && "$py" -c '{check}' "$t" {sha12}; then mv -f "$t" "$f"; else rm -f "$t"; echo OMHER_PEER_BAD_COPY; exit 5; fi
fi
OMHER_BRIDGE_TOKEN={token} exec "$py" "$f" --port {remote_port} --exit-on-stdin-eof"#,
        discover = DISCOVER_PYTHON,
    )
}

/// Find Hermes' Python on a macOS or Linux home, in the order the local shell uses (`bridge::discover_python_in`):
/// `OMHER_HERMES_PYTHON`, then the interpreter the PM launcher `hermes-agent/.hermes/bin/hermes` execs (its first
/// word, unquoted or in single quotes), then `venv`, then `.venv`. A `HERMES_HOME` that names a profile is raised to
/// its root. Prints `OMHER_PEER_PYTHON`, `OMHER_PEER_PYVER`, or `OMHER_PEER_NO_HERMES` and exit 3.
pub const DISCOVER_PYTHON: &str = r#"h="${HERMES_HOME:-$HOME/.hermes}"
case "$h" in */profiles/*) r="${h%/profiles/*}"; [ -f "$r/config.yaml" ] && h="$r" ;; esac
py=""
if [ -n "${OMHER_HERMES_PYTHON:-}" ] && [ -x "$OMHER_HERMES_PYTHON" ]; then py="$OMHER_HERMES_PYTHON"; fi
l="$h/hermes-agent/.hermes/bin/hermes"
if [ -z "$py" ] && [ -f "$l" ]; then
  w=$(sed -n "s/^exec //p" "$l" | head -n 1)
  case "$w" in
    "'"*) w="${w#?}"; w="${w%%"'"*}" ;;
    *) w="${w%% *}" ;;
  esac
  case "$w" in /*) [ -x "$w" ] && py="$w" ;; esac
fi
for v in venv .venv; do
  if [ -z "$py" ] && [ -x "$h/hermes-agent/$v/bin/python" ]; then py="$h/hermes-agent/$v/bin/python"; fi
done
if [ -z "$py" ]; then echo "OMHER_PEER_NO_HERMES $h"; exit 3; fi
echo "OMHER_PEER_PYTHON $py"
echo "OMHER_PEER_PYVER $("$py" -c "import sys;print(sys.version.split()[0])" 2>/dev/null)""#;

/// `script` as one single-quoted sh word (`'` becomes `'"'"'`).
pub fn sh_quote(script: &str) -> String {
    format!("'{}'", script.replace('\'', r#"'"'"'"#))
}

/// The whole argv after `ssh`, fixed except for the checked host and port and the numbers and hex made here.
pub fn ssh_args(host: &str, port: Option<u16>, local_port: u16, remote_port: u16, remote: &str) -> Vec<String> {
    let mut a: Vec<String> = Vec::new();
    for o in SSH_OPTIONS {
        a.push("-o".into());
        a.push(o.into());
    }
    a.push("-T".into());
    a.push("-L".into());
    a.push(format!("127.0.0.1:{local_port}:127.0.0.1:{remote_port}"));
    if let Some(p) = port {
        a.push("-p".into());
        a.push(p.to_string());
    }
    a.push("--".into());
    a.push(host.into());
    a.push(format!("sh -c {}", sh_quote(remote)));
    a
}

/// The command as the confirm card shows it: every argument but the script, which the card shows under it.
pub fn shown_command(args: &[String]) -> String {
    let mut parts = vec!["ssh".to_string()];
    for (i, a) in args.iter().enumerate() {
        parts.push(if i + 1 == args.len() { "sh -c '<remote script>'".to_string() } else { a.clone() });
    }
    parts.join(" ")
}

/// A free loopback port, by asking the OS for one (a later bind can still lose a race: the link then retries).
fn free_local_port() -> Result<u16, String> {
    let l = TcpListener::bind(("127.0.0.1", 0)).map_err(|e| format!("no free port on this computer: {e}"))?;
    l.local_addr().map(|a| a.port()).map_err(|e| e.to_string())
}

/// A remote port in 20000..60000 from the OS random source.
fn random_remote_port() -> u16 {
    let mut b = [0u8; 2];
    let _ = getrandom::fill(&mut b);
    20000 + (u16::from_le_bytes(b) % 40000)
}

// ---------------------------------------------------------------------------------------------
// Failures in plain words
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FailKind {
    /// Key login refused: the person runs `ssh-copy-id` themselves.
    Auth,
    /// The host's key is not known yet (BatchMode cannot ask).
    HostKey,
    Unreachable,
    Timeout,
    NoHermes,
    /// The bridge script did not arrive whole.
    BadCopy,
    /// The remote bridge exited before it was ready.
    Bridge,
    /// A port was taken: try again with others.
    Port,
    /// The link went away after it was up.
    Dropped,
    /// `ssh` is not on this computer.
    NoSsh,
}

impl FailKind {
    /// Kinds a retry cannot fix: the link waits for the person (Check again / Retry).
    pub fn permanent(self) -> bool {
        matches!(self, FailKind::Auth | FailKind::HostKey | FailKind::NoHermes | FailKind::BadCopy | FailKind::NoSsh)
    }
}

/// Which failure `ssh`'s output (stderr and the script's stdout lines, newest last) shows.
pub fn classify(lines: &[String], ready: bool) -> FailKind {
    let all = lines.join("\n");
    let low = all.to_ascii_lowercase();
    if all.contains("OMHER_PEER_NO_HERMES") {
        FailKind::NoHermes
    } else if all.contains("OMHER_PEER_BAD_COPY") {
        FailKind::BadCopy
    } else if low.contains("permission denied") || low.contains("too many authentication failures") {
        FailKind::Auth
    } else if low.contains("host key verification failed") || low.contains("no ecdsa host key") || low.contains("host key for") {
        FailKind::HostKey
    } else if low.contains("address already in use") || low.contains("could not request local forwarding") {
        FailKind::Port
    } else if low.contains("timed out") {
        FailKind::Timeout
    } else if low.contains("could not resolve hostname")
        || low.contains("no route to host")
        || low.contains("connection refused")
        || low.contains("network is unreachable")
        || low.contains("name or service not known")
    {
        FailKind::Unreachable
    } else if ready {
        FailKind::Dropped
    } else {
        FailKind::Bridge
    }
}

/// The last line worth showing: not one of the script's own markers, not blank.
pub fn last_line(lines: &[String]) -> String {
    lines
        .iter()
        .rev()
        .map(|l| l.trim())
        .find(|l| !l.is_empty() && !l.starts_with("OMHER_"))
        .unwrap_or("")
        .chars()
        .take(300)
        .collect()
}

// ---------------------------------------------------------------------------------------------
// Reconnect plan (pure, unit tested)
// ---------------------------------------------------------------------------------------------

/// Wait before reconnect attempt `attempt` (1-based): 2, 4, 8, 16, 32, then 60 s.
pub fn backoff(attempt: u32) -> Duration {
    Duration::from_secs(2u64.saturating_pow(attempt.clamp(1, 6)).min(60))
}

#[derive(Debug, Clone, PartialEq)]
pub enum Plan {
    Retry { attempt: u32, wait: Duration },
    Stop,
}

/// What follows a link that ended with `kind` after `attempt` failed tries in a row: a permanent failure stops and
/// waits for the person; anything else tries again, later each time.
pub fn after_exit(kind: FailKind, attempt: u32) -> Plan {
    if kind.permanent() {
        Plan::Stop
    } else {
        let next = attempt.saturating_add(1);
        Plan::Retry { attempt: next, wait: backoff(next) }
    }
}

// ---------------------------------------------------------------------------------------------
// One link
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Found {
    pub python: String,
    pub pyver: String,
    /// The command as shown on the card, and the remote script it runs.
    pub command: String,
    pub script: String,
}

#[derive(Debug)]
pub struct Up {
    pub url: String,
    pub found: Found,
    child: Child,
    stdin: Option<ChildStdin>,
    tail: Arc<Mutex<Vec<String>>>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Failure {
    pub kind: FailKind,
    pub line: String,
}

fn push_tail(tail: &Mutex<Vec<String>>, line: String) {
    let mut t = tail.lock().unwrap();
    t.push(line);
    if t.len() > TAIL_LINES {
        t.remove(0);
    }
}

/// The ONE place a process is started for peers: `ssh` with the argv from [`ssh_args`].
fn spawn_ssh(args: &[String]) -> std::io::Result<Child> {
    let mut cmd = Command::new("ssh");
    cmd.args(args).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    no_console_window(&mut cmd);
    crate::appimage::host_env(&mut cmd);
    cmd.spawn()
}

/// Bring one link up: start `ssh`, copy the bridge script when the remote asks for it, and wait for the remote
/// bridge's ready line. A taken port is tried again with new ports.
pub fn connect(host: &str, port: Option<u16>, script: &[u8]) -> Result<Up, Failure> {
    if !valid_host(host) || !valid_port(port) {
        return Err(Failure { kind: FailKind::Unreachable, line: "not a host omher can use".into() });
    }
    let mut last = Failure { kind: FailKind::Port, line: String::new() };
    for _ in 0..PORT_TRIES {
        match connect_once(host, port, script) {
            Err(f) if f.kind == FailKind::Port => last = f,
            other => return other,
        }
    }
    Err(last)
}

fn connect_once(host: &str, port: Option<u16>, script: &[u8]) -> Result<Up, Failure> {
    let fail = |kind, line: String| Failure { kind, line };
    let local = free_local_port().map_err(|e| fail(FailKind::Port, e))?;
    let remote_port = random_remote_port();
    let token = new_token().map_err(|e| fail(FailKind::Bridge, e.to_string()))?;
    let sha = script_sha12(script);
    let remote = remote_script(&sha, script.len(), remote_port, &token);
    let args = ssh_args(host, port, local, remote_port, &remote);
    let mut child = spawn_ssh(&args).map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound {
            fail(FailKind::NoSsh, "ssh is not on this computer".into())
        } else {
            fail(FailKind::Unreachable, format!("could not start ssh: {e}"))
        }
    })?;
    let mut stdin = child.stdin.take();
    let stdout = child.stdout.take().ok_or_else(|| fail(FailKind::Bridge, "no ssh stdout".into()))?;
    let stderr = child.stderr.take().ok_or_else(|| fail(FailKind::Bridge, "no ssh stderr".into()))?;
    let tail: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let t_err = Arc::clone(&tail);
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            eprintln!("omher-peer: {line}");
            push_tail(&t_err, line);
        }
    });
    enum Line {
        Need,
        Python(String),
        PyVer(String),
        Ready(u16),
        Other(String),
    }
    let (tx, rx) = mpsc::channel::<Line>();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let msg = if line.trim() == "OMHER_PEER_NEED" {
                Line::Need
            } else if let Some(p) = line.strip_prefix("OMHER_PEER_PYTHON ") {
                Line::Python(p.trim().to_string())
            } else if let Some(v) = line.strip_prefix("OMHER_PEER_PYVER ") {
                Line::PyVer(v.trim().to_string())
            } else if let Some(p) = parse_ready_line(&line) {
                Line::Ready(p)
            } else {
                Line::Other(line)
            };
            // keep draining after the link is up: a full pipe would stall the remote bridge's prints
            let _ = tx.send(msg);
        }
    });
    let mut found = Found { python: String::new(), pyver: String::new(), command: shown_command(&args), script: remote.replace(&token, "<token>") };
    let deadline = Instant::now() + READY_TIMEOUT;
    let stop = |child: &mut Child, stdin: &mut Option<ChildStdin>| {
        stdin.take();
        let _ = child.kill();
        let _ = child.wait();
    };
    loop {
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            stop(&mut child, &mut stdin);
            return Err(fail(FailKind::Timeout, format!("no answer from {host} within {} s", READY_TIMEOUT.as_secs())));
        }
        match rx.recv_timeout(left.min(Duration::from_millis(200))) {
            Ok(Line::Need) => {
                let ok = stdin.as_mut().is_some_and(|w| w.write_all(script).and_then(|_| w.flush()).is_ok());
                if !ok {
                    stop(&mut child, &mut stdin);
                    return Err(fail(FailKind::BadCopy, "could not send omher's bridge script".into()));
                }
            }
            Ok(Line::Python(p)) => found.python = p,
            Ok(Line::PyVer(v)) => found.pyver = v,
            Ok(Line::Ready(p)) if p == remote_port => {
                return Ok(Up { url: bridge_ws_url(local, &token), found, child, stdin, tail });
            }
            Ok(Line::Ready(_)) => {}
            Ok(Line::Other(l)) => push_tail(&tail, l),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                if let Ok(Some(_)) = child.try_wait() {
                    // give the readers the last lines, then say what they show
                    thread::sleep(Duration::from_millis(150));
                    while let Ok(m) = rx.try_recv() {
                        if let Line::Other(l) = m {
                            push_tail(&tail, l);
                        }
                    }
                    let lines = tail.lock().unwrap().clone();
                    return Err(fail(classify(&lines, false), last_line(&lines)));
                }
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                let _ = child.wait();
                thread::sleep(Duration::from_millis(150));
                let lines = tail.lock().unwrap().clone();
                return Err(fail(classify(&lines, false), last_line(&lines)));
            }
        }
    }
}

impl Up {
    /// Stop the link: EOF first (the remote bridge exits on it), then the `ssh` child.
    pub fn stop(mut self) {
        self.stdin.take();
        thread::sleep(Duration::from_millis(150));
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

// ---------------------------------------------------------------------------------------------
// Every peer's link, its status, and Check tunnels
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PeerStatus {
    pub id: String,
    pub label: String,
    pub host: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,
    /// `connecting` | `connected` | `reconnecting` | `failed` | `removed`
    pub state: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kind: Option<FailKind>,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub reason: String,
    pub attempt: u32,
}

impl PeerStatus {
    fn of(p: &Peer, state: &'static str) -> PeerStatus {
        PeerStatus { id: p.id.clone(), label: p.label.clone(), host: p.host.clone(), port: p.port, state, url: None, kind: None, reason: String::new(), attempt: 0 }
    }
}

type Sink = Arc<dyn Fn(PeerStatus) + Send + Sync>;

struct Link {
    peer: Peer,
    status: PeerStatus,
    generation: u64,
    up: Option<Up>,
}

pub struct Peers {
    home: PathBuf,
    script: Mutex<Option<PathBuf>>,
    links: Mutex<HashMap<String, Link>>,
    sinks: Mutex<Vec<Sink>>,
    checks: Mutex<HashMap<String, (Up, Instant)>>,
    generation: Mutex<u64>,
}

impl Peers {
    pub fn new(home: PathBuf) -> Arc<Peers> {
        Arc::new(Peers {
            home,
            script: Mutex::new(None),
            links: Mutex::new(HashMap::new()),
            sinks: Mutex::new(Vec::new()),
            checks: Mutex::new(HashMap::new()),
            generation: Mutex::new(0),
        })
    }

    pub fn set_script(&self, path: PathBuf) {
        *self.script.lock().unwrap() = Some(path);
    }

    fn script_bytes(&self) -> Result<Vec<u8>, Failure> {
        let path = self.script.lock().unwrap().clone();
        let path = path.ok_or_else(|| Failure { kind: FailKind::Bridge, line: "omher's bridge script was not found".into() })?;
        std::fs::read(&path).map_err(|e| Failure { kind: FailKind::Bridge, line: format!("could not read {}: {e}", path.display()) })
    }

    pub fn watch(&self, sink: Sink) {
        self.sinks.lock().unwrap().push(sink);
    }

    fn publish(&self, st: PeerStatus) {
        for s in self.sinks.lock().unwrap().iter() {
            s(st.clone());
        }
    }

    pub fn statuses(&self) -> Vec<PeerStatus> {
        let links = self.links.lock().unwrap();
        let mut out: Vec<PeerStatus> = read_peers(&self.home)
            .iter()
            .map(|p| links.get(&p.id).map(|l| l.status.clone()).unwrap_or_else(|| PeerStatus::of(p, "connecting")))
            .collect();
        out.sort_by(|a, b| a.label.cmp(&b.label));
        out
    }

    /// Start a link for every peer in peers.json (app start).
    pub fn start_all(self: &Arc<Self>) {
        for p in read_peers(&self.home) {
            self.start(p);
        }
    }

    fn next_generation(&self) -> u64 {
        let mut g = self.generation.lock().unwrap();
        *g += 1;
        *g
    }

    fn start(self: &Arc<Self>, peer: Peer) {
        let generation = self.next_generation();
        let status = PeerStatus::of(&peer, "connecting");
        {
            let mut links = self.links.lock().unwrap();
            if let Some(old) = links.remove(&peer.id) {
                if let Some(up) = old.up {
                    thread::spawn(move || up.stop());
                }
            }
            links.insert(peer.id.clone(), Link { peer: peer.clone(), status: status.clone(), generation, up: None });
        }
        self.publish(status);
        let me = Arc::clone(self);
        thread::spawn(move || me.run(peer, generation));
    }

    fn current(&self, id: &str, generation: u64) -> bool {
        self.links.lock().unwrap().get(id).is_some_and(|l| l.generation == generation)
    }

    fn set(&self, id: &str, generation: u64, f: impl FnOnce(&mut Link)) -> Option<PeerStatus> {
        let mut links = self.links.lock().unwrap();
        let link = links.get_mut(id).filter(|l| l.generation == generation)?;
        f(link);
        Some(link.status.clone())
    }

    /// One peer's life: connect, watch the child, and on a drop reconnect with backoff until removed or stopped by
    /// a failure a retry cannot fix.
    fn run(self: Arc<Self>, peer: Peer, generation: u64) {
        let mut attempt = 0u32;
        loop {
            if !self.current(&peer.id, generation) {
                return;
            }
            let result = self.script_bytes().and_then(|s| connect(&peer.host, peer.port, &s));
            let kind = match result {
                Ok(up) => {
                    attempt = 0;
                    let url = up.url.clone();
                    let mut up = Some(up);
                    let st = self.set(&peer.id, generation, |l| {
                        l.status = PeerStatus { state: "connected", url: Some(url), ..PeerStatus::of(&l.peer, "connected") };
                        l.up = up.take();
                    });
                    match st {
                        Some(st) => self.publish(st),
                        None => {
                            if let Some(up) = up {
                                up.stop();
                            }
                            return;
                        }
                    }
                    // follow the process, not its pipes
                    let (code, lines) = loop {
                        thread::sleep(Duration::from_millis(250));
                        let mut links = self.links.lock().unwrap();
                        let Some(link) = links.get_mut(&peer.id).filter(|l| l.generation == generation) else { return };
                        let Some(up) = link.up.as_mut() else { return };
                        if let Ok(Some(code)) = up.child.try_wait() {
                            let lines = up.tail.lock().unwrap().clone();
                            link.up = None;
                            break (code, lines);
                        }
                    };
                    eprintln!("omher: peer {} link ended ({code})", peer.id);
                    let k = classify(&lines, true);
                    (if k == FailKind::Bridge { FailKind::Dropped } else { k }, last_line(&lines))
                }
                Err(f) => (f.kind, f.line),
            };
            let (kind, line) = kind;
            match after_exit(kind, attempt) {
                Plan::Stop => {
                    if let Some(st) = self.set(&peer.id, generation, |l| {
                        l.status = PeerStatus { kind: Some(kind), reason: line.clone(), ..PeerStatus::of(&l.peer, "failed") };
                    }) {
                        self.publish(st);
                    }
                    return;
                }
                Plan::Retry { attempt: next, wait } => {
                    attempt = next;
                    if let Some(st) = self.set(&peer.id, generation, |l| {
                        l.status = PeerStatus { kind: Some(kind), reason: line.clone(), attempt: next, ..PeerStatus::of(&l.peer, "reconnecting") };
                    }) {
                        self.publish(st);
                    }
                    let until = Instant::now() + wait;
                    while Instant::now() < until {
                        if !self.current(&peer.id, generation) {
                            return;
                        }
                        thread::sleep(Duration::from_millis(250));
                    }
                }
            }
        }
    }

    /// Try a failed or waiting peer again now.
    pub fn retry(self: &Arc<Self>, id: &str) -> Result<(), String> {
        let peer = read_peers(&self.home).into_iter().find(|p| p.id == id).ok_or("no such remote machine")?;
        self.start(peer);
        Ok(())
    }

    /// Check a host before it is saved: bring a link up, keep it for the card (the UI reads the remote's bots
    /// through it), and say what was found. Writes nothing on this computer.
    pub fn check(&self, host: &str, port: Option<u16>) -> Result<(String, String, Found), Failure> {
        self.reap_checks();
        let script = self.script_bytes()?;
        let up = connect(host, port, &script)?;
        let id = format!("c{}", self.next_generation());
        let (url, found) = (up.url.clone(), up.found.clone());
        self.checks.lock().unwrap().insert(id.clone(), (up, Instant::now()));
        Ok((id, url, found))
    }

    pub fn check_close(&self, id: &str) {
        let up = self.checks.lock().unwrap().remove(id);
        if let Some((up, _)) = up {
            up.stop();
        }
    }

    fn reap_checks(&self) {
        let old: Vec<Up> = {
            let mut checks = self.checks.lock().unwrap();
            let gone: Vec<String> = checks.iter().filter(|(_, (_, at))| at.elapsed() > CHECK_TTL).map(|(k, _)| k.clone()).collect();
            gone.into_iter().filter_map(|k| checks.remove(&k).map(|(u, _)| u)).collect()
        };
        for up in old {
            up.stop();
        }
    }

    /// The confirm card's Connect: the one write of peers.json that adds a row. A check tunnel the card used is
    /// closed first; the link then starts as its own `ssh`.
    pub fn add(self: &Arc<Self>, label: &str, host: &str, port: Option<u16>, check: Option<&str>) -> Result<PeerStatus, String> {
        let label = label.trim();
        if !valid_label(label) {
            return Err("the name must be 1 to 40 characters".into());
        }
        if !valid_host(host) || !valid_port(port) {
            return Err("not a host omher can use".into());
        }
        if let Some(c) = check {
            self.check_close(c);
        }
        let mut peers = read_peers(&self.home);
        if peers.iter().any(|p| p.host == host && p.port == port) {
            return Err("that computer is already connected".into());
        }
        if peers.len() >= MAX_PEERS {
            return Err(format!("at most {MAX_PEERS} remote machines"));
        }
        let taken: Vec<String> = peers.iter().map(|p| p.id.clone()).collect();
        let peer = Peer { id: id_for(label, &taken), label: label.to_string(), host: host.to_string(), port };
        peers.push(peer.clone());
        write_peers(&self.home, &peers)?;
        self.start(peer.clone());
        Ok(PeerStatus::of(&peer, "connecting"))
    }

    /// Remove a peer: its row leaves peers.json and its link stops (the remote bridge ends on stdin EOF).
    pub fn remove(&self, id: &str) -> Result<(), String> {
        let mut peers = read_peers(&self.home);
        let Some(peer) = peers.iter().find(|p| p.id == id).cloned() else { return Err("no such remote machine".into()) };
        peers.retain(|p| p.id != id);
        write_peers(&self.home, &peers)?;
        let link = self.links.lock().unwrap().remove(id);
        if let Some(up) = link.and_then(|l| l.up) {
            up.stop();
        }
        self.publish(PeerStatus::of(&peer, "removed"));
        Ok(())
    }

    /// App exit: every link and check tunnel stops.
    pub fn stop_all(&self) {
        let ups: Vec<Up> = self.links.lock().unwrap().drain().filter_map(|(_, l)| l.up).collect();
        let checks: Vec<Up> = self.checks.lock().unwrap().drain().map(|(_, (u, _))| u).collect();
        for up in ups.into_iter().chain(checks) {
            up.stop();
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_follow_the_pattern_and_skip_the_chat_prefixes() {
        for ok in ["mini", "mac-mini", "a", "0x", "a-b-c", &"a".repeat(32)] {
            assert!(valid_id(ok), "{ok}");
        }
        for bad in ["", "-a", "A", "a_b", "a b", "a:b", &"a".repeat(33), "fold", "agent", "mini/x", "ü"] {
            assert!(!valid_id(bad), "{bad}");
        }
    }

    #[test]
    fn labels_are_short_plain_text() {
        assert!(valid_label("Mac mini"));
        assert!(valid_label("맥미니"));
        assert!(valid_label(&"x".repeat(40)));
        assert!(!valid_label(&"x".repeat(41)));
        assert!(!valid_label(""));
        assert!(!valid_label("   "));
        assert!(!valid_label("a\nb"));
    }

    #[test]
    fn hosts_are_aliases_or_user_at_host_and_never_options_or_shell() {
        for ok in ["mini", "sionic@10.1.145.204", "build-box.local", "u_1@host-2", "10.0.0.7", "_svc@h"] {
            assert!(valid_host(ok), "{ok}");
        }
        for bad in [
            "", "-oProxyCommand=x", "a b", "a;b", "a|b", "$(id)", "`id`", "a'b", "a\"b", "host:22", "@host", "user@",
            "u@-h", "-u@h", "a\\b", "h/x", "u@h@x", "a\nb", "*", "?x", "[::1]", "~", "a&b", ">x",
        ] {
            assert!(!valid_host(bad), "{bad:?}");
        }
        assert!(valid_port(None) && valid_port(Some(22)) && !valid_port(Some(0)));
    }

    #[test]
    fn peers_json_rows_are_checked_on_every_read() {
        let text = r#"{"peers": [
            {"id": "mini", "label": "Mac mini", "host": "sionic@10.1.145.204"},
            {"id": "mini", "label": "dup", "host": "x"},
            {"id": "Bad", "label": "x", "host": "x"},
            {"id": "evil", "label": "x", "host": "-oProxyCommand=sh"},
            {"id": "fold", "label": "x", "host": "x"},
            {"id": "box", "label": "Box", "host": "box", "port": 2222},
            {"id": "zero", "label": "x", "host": "x", "port": 0},
            {"id": "extra", "label": "x", "host": "x", "command": "rm -rf /"},
            "nope"
        ]}"#;
        let got = parse_peers(text);
        let ids: Vec<&str> = got.iter().map(|p| p.id.as_str()).collect();
        assert_eq!(ids, ["mini", "box", "extra"]);
        assert_eq!(got[1].port, Some(2222));
        // an unknown key is dropped, never kept or used
        assert_eq!(serde_json::to_value(&got[2]).unwrap(), serde_json::json!({"id": "extra", "label": "x", "host": "x"}));
        assert!(parse_peers("not json").is_empty());
        assert!(parse_peers("{}").is_empty());
    }

    #[test]
    fn write_then_read_round_trips_and_refuses_a_bad_row() {
        let dir = std::env::temp_dir().join(format!("omher-peers-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let p = Peer { id: "mini".into(), label: "Mac mini".into(), host: "sionic@10.1.145.204".into(), port: None };
        write_peers(&dir, &[p.clone()]).unwrap();
        assert_eq!(read_peers(&dir), vec![p.clone()]);
        let text = std::fs::read_to_string(peers_path(&dir)).unwrap();
        assert!(!text.contains("password") && !text.contains("key"), "{text}");
        let bad = Peer { host: "a b".into(), ..p };
        assert!(write_peers(&dir, &[bad]).is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn new_ids_come_from_the_label() {
        assert_eq!(id_for("Mac mini", &[]), "mac-mini");
        assert_eq!(id_for("Mac mini", &["mac-mini".into()]), "mac-mini-2");
        assert_eq!(id_for("맥미니", &[]), "peer");
        assert_eq!(id_for("fold", &[]), "peer");
        assert_eq!(id_for("  GPU box #2 ", &[]), "gpu-box-2");
        assert!(valid_id(&id_for(&"long name ".repeat(9), &[])));
    }

    #[test]
    fn ssh_config_aliases_skip_patterns_and_bad_names() {
        let cfg = "# mine\nHost mini macmini\n  HostName 10.1.145.204\n  User sionic\nHost *\n  ServerAliveInterval 30\n\
                   host build-* !nope gpu?\nHOST=box # trailing comment\nMatch host x\nHost \"quoted\" -bad mini\n\tHost tabbed\n";
        assert_eq!(ssh_config_hosts(cfg), ["mini", "macmini", "box", "quoted", "tabbed"]);
        assert!(ssh_config_hosts("").is_empty());
    }

    #[test]
    fn the_argv_is_fixed_and_the_host_comes_after_double_dash() {
        let a = ssh_args("sionic@10.1.145.204", None, 50001, 40002, "echo hi");
        assert_eq!(
            a,
            [
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ExitOnForwardFailure=yes", "-o",
                "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-T", "-L", "127.0.0.1:50001:127.0.0.1:40002",
                "--", "sionic@10.1.145.204", "sh -c 'echo hi'",
            ]
        );
        let p = ssh_args("box", Some(2222), 1, 2, "x");
        assert_eq!(&p[13..17], ["-p", "2222", "--", "box"]);
        assert_eq!(shown_command(&a).split(' ').next(), Some("ssh"));
        assert!(shown_command(&a).ends_with("-- sionic@10.1.145.204 sh -c '<remote script>'"));
    }

    #[test]
    fn the_remote_script_writes_only_under_omher_peer_and_has_no_backslash() {
        let s = remote_script("0123456789ab", 1234, 40002, "deadbeef");
        assert!(!s.contains('\\'), "a backslash would read differently inside fish's single quotes");
        assert!(s.contains("d=\"$HOME/.omher/peer\""));
        assert!(s.contains("f=\"$d/omher_bridge-0123456789ab.py\""));
        assert!(s.contains("head -c 1234 > \"$t\""));
        // the token rides the environment, never the remote process list
        assert!(s.ends_with("OMHER_BRIDGE_TOKEN=deadbeef exec \"$py\" \"$f\" --port 40002 --exit-on-stdin-eof"));
        assert!(!s.contains("--token") && !s.contains('!'));
        assert!(!s.contains(".hermes/peer") && !s.contains("> \"$h"), "never writes under the Hermes home");
        // every redirect or move targets $t or $f, both under ~/.omher/peer
        for w in s.split_whitespace().filter(|w| w.starts_with('>')) {
            assert_eq!(w, ">", "{s}");
        }
        assert_eq!(s.matches(" > \"$t\"").count(), 1);
        assert_eq!(s.matches("mv -f \"$t\" \"$f\"").count(), 1);
    }

    #[test]
    fn sh_quote_survives_single_quotes() {
        assert_eq!(sh_quote("a'b"), r#"'a'"'"'b'"#);
    }

    /// The discovery part runs in a real `/bin/sh` against fixture homes: the launcher's interpreter (plain and
    /// quoted), venv before .venv, a profile HERMES_HOME raised to its root, and the override first.
    #[cfg(unix)]
    #[test]
    fn remote_python_discovery_follows_the_local_order() {
        use std::os::unix::fs::PermissionsExt;
        let root = std::env::temp_dir().join(format!("omher-peer-sh-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let exe = |p: &Path| {
            std::fs::create_dir_all(p.parent().unwrap()).unwrap();
            std::fs::write(p, "#!/bin/sh\necho 3.14.9\n").unwrap();
            std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o755)).unwrap();
        };
        let run = |home: &Path, env: &[(&str, &str)]| -> String {
            let mut c = Command::new("/bin/sh");
            c.arg("-c").arg(DISCOVER_PYTHON).env_clear().env("HOME", home).env("PATH", "/usr/bin:/bin");
            for (k, v) in env {
                c.env(k, v);
            }
            let out = c.output().unwrap();
            String::from_utf8_lossy(&out.stdout).lines().next().unwrap_or("").to_string()
        };
        // PM install: no venv, the launcher names a store Python
        let pm = root.join("pm");
        let store = pm.join(".hermes/tools/python-3.14.9/bin/python3");
        exe(&store);
        let launcher = pm.join(".hermes/hermes-agent/.hermes/bin/hermes");
        std::fs::create_dir_all(launcher.parent().unwrap()).unwrap();
        std::fs::write(&launcher, format!("#!/bin/sh\nexec {} -I -c 'import os' \"$@\"\n", store.display())).unwrap();
        assert_eq!(run(&pm, &[]), format!("OMHER_PEER_PYTHON {}", store.display()));
        // an upgraded install keeps its venv: the launcher still wins
        exe(&pm.join(".hermes/hermes-agent/venv/bin/python"));
        assert_eq!(run(&pm, &[]), format!("OMHER_PEER_PYTHON {}", store.display()));
        // a quoted interpreter with a space
        let spaced = root.join("sp ace");
        let sp_store = spaced.join("py/bin/python3");
        exe(&sp_store);
        let sp_l = spaced.join(".hermes/hermes-agent/.hermes/bin/hermes");
        std::fs::create_dir_all(sp_l.parent().unwrap()).unwrap();
        std::fs::write(&sp_l, format!("#!/bin/sh\nexec '{}' -I -c 'x'\n", sp_store.display())).unwrap();
        assert_eq!(run(&spaced, &[]), format!("OMHER_PEER_PYTHON {}", sp_store.display()));
        // the launcher's interpreter is gone: venv, then .venv
        let old = root.join("old");
        let gone_l = old.join(".hermes/hermes-agent/.hermes/bin/hermes");
        std::fs::create_dir_all(gone_l.parent().unwrap()).unwrap();
        std::fs::write(&gone_l, "#!/bin/sh\nexec /nowhere/python3 -I\n").unwrap();
        exe(&old.join(".hermes/hermes-agent/.venv/bin/python"));
        assert_eq!(run(&old, &[]), format!("OMHER_PEER_PYTHON {}", old.join(".hermes/hermes-agent/.venv/bin/python").display()));
        exe(&old.join(".hermes/hermes-agent/venv/bin/python"));
        assert_eq!(run(&old, &[]), format!("OMHER_PEER_PYTHON {}", old.join(".hermes/hermes-agent/venv/bin/python").display()));
        // HERMES_HOME naming a profile is raised to its root
        std::fs::write(old.join(".hermes/config.yaml"), "x: 1\n").unwrap();
        let prof = old.join(".hermes/profiles/kami");
        std::fs::create_dir_all(&prof).unwrap();
        assert_eq!(
            run(&root.join("elsewhere"), &[("HERMES_HOME", prof.to_str().unwrap())]),
            format!("OMHER_PEER_PYTHON {}", old.join(".hermes/hermes-agent/venv/bin/python").display())
        );
        // the override wins
        let pinned = root.join("pinned/python");
        exe(&pinned);
        assert_eq!(run(&pm, &[("OMHER_HERMES_PYTHON", pinned.to_str().unwrap())]), format!("OMHER_PEER_PYTHON {}", pinned.display()));
        // nothing there
        let none = root.join("none");
        std::fs::create_dir_all(&none).unwrap();
        assert!(run(&none, &[]).starts_with("OMHER_PEER_NO_HERMES "));
        let _ = std::fs::remove_dir_all(&root);
    }

    /// The whole remote script in a real `/bin/sh` with a fake Python: the first run asks for the file, takes
    /// exactly `size` bytes from stdin, stores it under ~/.omher/peer and execs it; the second run reuses it.
    #[cfg(unix)]
    #[test]
    fn the_remote_script_copies_once_and_reuses_a_matching_file() {
        use std::os::unix::fs::PermissionsExt;
        let Ok(py3) = which("python3") else { return };
        let home = std::env::temp_dir().join(format!("omher-peer-run-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        let venv = home.join(".hermes/hermes-agent/venv/bin/python");
        std::fs::create_dir_all(venv.parent().unwrap()).unwrap();
        // a "python" that runs real python3 for -c and prints its args for the bridge
        std::fs::write(&venv, format!("#!/bin/sh\nif [ \"$1\" = -c ]; then exec {} \"$@\"; fi\necho \"BRIDGE $* token=$OMHER_BRIDGE_TOKEN\"\n", py3.display())).unwrap();
        std::fs::set_permissions(&venv, std::fs::Permissions::from_mode(0o755)).unwrap();
        let body = b"print('omher bridge')\n".to_vec();
        let sha = script_sha12(&body);
        let script = remote_script(&sha, body.len(), 40123, "abcdef01");
        let go = |input: &[u8]| -> String {
            // exactly what ssh hands the remote login shell: `sh -c '<script>'`, parsed once more by a shell
            let mut c = Command::new("/bin/sh");
            c.arg("-c").arg(format!("sh -c {}", sh_quote(&script))).env_clear().env("HOME", &home).env("PATH", "/usr/bin:/bin");
            c.stdin(Stdio::piped()).stdout(Stdio::piped());
            let mut ch = c.spawn().unwrap();
            ch.stdin.take().unwrap().write_all(input).unwrap();
            String::from_utf8_lossy(&ch.wait_with_output().unwrap().stdout).to_string()
        };
        let first = go(&body);
        assert!(first.contains("OMHER_PEER_NEED"), "{first}");
        let stored = home.join(format!(".omher/peer/omher_bridge-{sha}.py"));
        assert_eq!(std::fs::read(&stored).unwrap(), body);
        assert!(first.contains(&format!("BRIDGE {} --port 40123 --exit-on-stdin-eof token=abcdef01", stored.display())), "{first}");
        let second = go(b"");
        assert!(second.contains("OMHER_PEER_HAVE") && !second.contains("NEED"), "{second}");
        // a corrupt copy is never kept
        std::fs::remove_file(&stored).unwrap();
        let bad = go(b"print('evil')\n");
        assert!(bad.contains("OMHER_PEER_BAD_COPY"), "{bad}");
        assert!(!stored.exists());
        // the script wrote only ~/.omher/peer (macOS's python3 stub may add its own ~/Library cache) and left the
        // Hermes home as it was
        let omher: Vec<String> = std::fs::read_dir(home.join(".omher")).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
        assert_eq!(omher, ["peer"]);
        let hermes: Vec<String> = std::fs::read_dir(home.join(".hermes")).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
        assert_eq!(hermes, ["hermes-agent"]);
        assert!(!home.join(".hermes/hermes-agent/venv/bin").read_dir().unwrap().any(|e| e.unwrap().file_name() != "python"));
        let _ = std::fs::remove_dir_all(&home);
    }

    #[cfg(unix)]
    fn which(name: &str) -> Result<PathBuf, ()> {
        for d in ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"] {
            let p = Path::new(d).join(name);
            if p.is_file() {
                return Ok(p);
            }
        }
        Err(())
    }

    #[test]
    fn failures_read_as_plain_kinds() {
        let l = |s: &str| s.lines().map(String::from).collect::<Vec<_>>();
        assert_eq!(classify(&l("sionic@10.1.145.204: Permission denied (publickey,password)."), false), FailKind::Auth);
        assert_eq!(classify(&l("Host key verification failed."), false), FailKind::HostKey);
        assert_eq!(classify(&l("ssh: connect to host 10.9.9.9 port 22: Operation timed out"), false), FailKind::Timeout);
        assert_eq!(classify(&l("ssh: Could not resolve hostname nowhere: nodename nor servname provided"), false), FailKind::Unreachable);
        assert_eq!(classify(&l("ssh: connect to host h port 22: Connection refused"), false), FailKind::Unreachable);
        assert_eq!(classify(&l("bind [127.0.0.1]:5000: Address already in use\nCould not request local forwarding."), false), FailKind::Port);
        assert_eq!(classify(&l("OSError: [Errno 48] address already in use"), false), FailKind::Port);
        assert_eq!(classify(&l("OMHER_PEER_NO_HERMES /home/u/.hermes"), false), FailKind::NoHermes);
        assert_eq!(classify(&l("OMHER_PEER_BAD_COPY"), false), FailKind::BadCopy);
        assert_eq!(classify(&l("ModuleNotFoundError: No module named 'websockets'"), false), FailKind::Bridge);
        assert_eq!(classify(&l("Connection to h closed by remote host."), true), FailKind::Dropped);
        assert_eq!(last_line(&l("OMHER_PEER_PYTHON /x\nModuleNotFoundError: No module named 'websockets'\nOMHER_PEER_NEED\n")), "ModuleNotFoundError: No module named 'websockets'");
    }

    #[test]
    fn reconnect_backs_off_and_stops_on_what_a_retry_cannot_fix() {
        assert_eq!((1..=8).map(|n| backoff(n).as_secs()).collect::<Vec<_>>(), [2, 4, 8, 16, 32, 60, 60, 60]);
        assert_eq!(after_exit(FailKind::Dropped, 0), Plan::Retry { attempt: 1, wait: Duration::from_secs(2) });
        assert_eq!(after_exit(FailKind::Unreachable, 3), Plan::Retry { attempt: 4, wait: Duration::from_secs(16) });
        assert_eq!(after_exit(FailKind::Timeout, 9), Plan::Retry { attempt: 10, wait: Duration::from_secs(60) });
        assert_eq!(after_exit(FailKind::Bridge, 0), Plan::Retry { attempt: 1, wait: Duration::from_secs(2) });
        for k in [FailKind::Auth, FailKind::HostKey, FailKind::NoHermes, FailKind::BadCopy, FailKind::NoSsh] {
            assert_eq!(after_exit(k, 0), Plan::Stop, "{k:?}");
        }
    }

    #[test]
    fn statuses_serialise_for_the_ui() {
        let p = Peer { id: "mini".into(), label: "Mac mini".into(), host: "mini".into(), port: None };
        let s = PeerStatus { kind: Some(FailKind::Auth), reason: "Permission denied".into(), ..PeerStatus::of(&p, "failed") };
        assert_eq!(
            serde_json::to_value(&s).unwrap(),
            serde_json::json!({"id": "mini", "label": "Mac mini", "host": "mini", "state": "failed", "kind": "auth", "reason": "Permission denied", "attempt": 0})
        );
    }

    #[test]
    fn a_host_the_shell_refuses_never_reaches_ssh() {
        let f = connect("-oProxyCommand=touch /tmp/x", None, b"x").unwrap_err();
        assert_eq!(f.line, "not a host omher can use");
    }

    /// The real link against one remote machine, through this module's own code path (connect, the copy, the ready
    /// line), then `hello` and `bots.list` over the tunnel and nothing else. Runs only with
    /// `OMHER_PEER_LIVE_HOST=<user@host>`; omher's bridge script is read from the repo.
    #[test]
    fn live_peer_hello_and_bots_list() {
        let Ok(host) = std::env::var("OMHER_PEER_LIVE_HOST") else {
            eprintln!("skipped: set OMHER_PEER_LIVE_HOST to run");
            return;
        };
        let script = std::fs::read(Path::new(env!("CARGO_MANIFEST_DIR")).join("../bridge/omher_bridge.py")).unwrap();
        let t0 = Instant::now();
        let up = connect(&host, None, &script).unwrap_or_else(|f| panic!("{f:?}"));
        println!("LIVE ready in {:.1}s url={}", t0.elapsed().as_secs_f32(), up.url.split("?token=").next().unwrap());
        println!("LIVE python={} pyver={}", up.found.python, up.found.pyver);
        println!("LIVE command={}", up.found.command);
        let port: u16 = up.url.trim_start_matches("ws://127.0.0.1:").split('/').next().unwrap().parse().unwrap();
        let token = up.url.split("token=").nth(1).unwrap().to_string();
        let mut ws = live_ws::Ws::open(port, &token);
        let hello = ws.call(r#"{"id":"h","op":"hello"}"#);
        println!("LIVE hello={hello}");
        let bots = ws.call(r#"{"id":"b","op":"bots.list"}"#);
        println!("LIVE bots.list={bots}");
        assert!(hello.contains("\"ok\": true") || hello.contains("\"ok\":true"), "{hello}");
        assert!(bots.contains("\"bots\""), "{bots}");
        if let Ok(local) = std::env::var("OMHER_PEER_LIVE_LOCAL_BRIDGE") {
            // the local bridge's multiplexer against the same tunnel: probe, attach, merged list, detach
            let (lport, ltoken) = local.split_once(':').unwrap();
            let mut l = live_ws::Ws::open(lport.parse().unwrap(), ltoken);
            let url = up.url.clone();
            println!("LIVE local peers.probe={}", l.call(&format!(r#"{{"id":"p","op":"peers.probe","url":"{url}"}}"#)));
            println!("LIVE local peers.attach={}", l.call(&format!(r#"{{"id":"a","op":"peers.attach","peer":"mini","label":"Mac mini","host":"{host}","url":"{url}"}}"#)));
            println!("LIVE local bots.list={}", l.call(r#"{"id":"l","op":"bots.list"}"#));
            println!("LIVE local peers.detach={}", l.call(r#"{"id":"d","op":"peers.detach","peer":"mini"}"#));
        }
        drop(ws);
        up.stop();
        println!("LIVE stopped after {:.1}s", t0.elapsed().as_secs_f32());
    }

    /// A tiny WebSocket client for the live test only (text frames, masked as a client must).
    mod live_ws {
        use std::io::{Read, Write};
        use std::net::TcpStream;
        use std::time::Duration;

        pub struct Ws(TcpStream);

        impl Ws {
            pub fn open(port: u16, token: &str) -> Ws {
                let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
                s.set_read_timeout(Some(Duration::from_secs(20))).unwrap();
                write!(s, "GET /?token={token} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").unwrap();
                let mut head = Vec::new();
                let mut b = [0u8; 1];
                while !head.ends_with(b"\r\n\r\n") {
                    s.read_exact(&mut b).unwrap();
                    head.push(b[0]);
                }
                assert!(String::from_utf8_lossy(&head).starts_with("HTTP/1.1 101"), "{}", String::from_utf8_lossy(&head));
                Ws(s)
            }

            pub fn call(&mut self, frame: &str) -> String {
                let id = frame.split("\"id\":\"").nth(1).unwrap().split('"').next().unwrap().to_string();
                self.send(frame);
                loop {
                    let msg = self.recv();
                    if msg.contains(&format!("\"id\": \"{id}\"")) || msg.contains(&format!("\"id\":\"{id}\"")) {
                        return msg;
                    }
                }
            }

            fn send(&mut self, text: &str) {
                let data = text.as_bytes();
                let mut f = vec![0x81u8];
                if data.len() < 126 {
                    f.push(0x80 | data.len() as u8);
                } else {
                    f.push(0x80 | 126);
                    f.extend_from_slice(&(data.len() as u16).to_be_bytes());
                }
                let mask = [0x12u8, 0x34, 0x56, 0x78];
                f.extend_from_slice(&mask);
                f.extend(data.iter().enumerate().map(|(i, c)| c ^ mask[i % 4]));
                self.0.write_all(&f).unwrap();
            }

            fn recv(&mut self) -> String {
                let mut h = [0u8; 2];
                self.0.read_exact(&mut h).unwrap();
                let mut len = (h[1] & 0x7f) as u64;
                if len == 126 {
                    let mut l = [0u8; 2];
                    self.0.read_exact(&mut l).unwrap();
                    len = u16::from_be_bytes(l) as u64;
                } else if len == 127 {
                    let mut l = [0u8; 8];
                    self.0.read_exact(&mut l).unwrap();
                    len = u64::from_be_bytes(l);
                }
                let mut data = vec![0u8; len as usize];
                self.0.read_exact(&mut data).unwrap();
                String::from_utf8_lossy(&data).into_owned()
            }
        }
    }
}

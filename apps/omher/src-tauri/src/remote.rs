//! Remote-only mode: omher with nothing installed on this computer, talking to the Hermes on a server over the
//! person's own `ssh` (BOUNDARY rule 47, built on rule 31's peer link).
//!
//! The mode is one file, `~/.omher/remote.json` (`{"v":1,"host":"user@host","port":22|null,"label":"..."}`), which
//! only the shell writes (the gate's Connect) and which is checked on every read: a symlink, a file over 4 KiB, bad
//! JSON, another version or a host, port or label the peer rules refuse all read as "no remote mode". Present and
//! valid, the shell starts no local bridge and no Python and runs no peer links; it keeps ONE link made by
//! [`peers::connect`] (the same fixed `ssh` argv and script), reconnects it with [`peers::after_exit`] /
//! [`peers::backoff`] as a peer link does, and hands its loopback URL to the page as `bridge_url`. Disconnect deletes
//! the file and starts the local bridge again.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::bridge::{Bridge, BridgeStatus};
use crate::peers::{self, after_exit, classify, last_line, valid_host, valid_label, valid_port, FailKind, Failure, Peers, Plan, Up};

/// The mode file is a few dozen bytes; anything larger is not one omher wrote.
pub const MAX_MODE_FILE: u64 = 4096;

// ---------------------------------------------------------------------------------------------
// The mode file
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RemoteMode {
    pub v: u32,
    pub host: String,
    #[serde(default)]
    pub port: Option<u16>,
    pub label: String,
}

impl RemoteMode {
    /// A mode from the page's values, checked with the peer rules (the label is trimmed first).
    pub fn new(label: &str, host: &str, port: Option<u16>) -> Result<RemoteMode, String> {
        let mode = RemoteMode { v: 1, host: host.to_string(), port, label: label.trim().to_string() };
        if !valid_label(&mode.label) {
            return Err("the name must be 1 to 40 characters".into());
        }
        if !mode.valid() {
            return Err("not a host omher can use".into());
        }
        Ok(mode)
    }

    pub fn valid(&self) -> bool {
        self.v == 1 && valid_host(&self.host) && valid_port(self.port) && valid_label(&self.label)
    }
}

pub fn mode_path(home: &Path) -> PathBuf {
    home.join(".omher").join("remote.json")
}

/// The mode in `~/.omher/remote.json`, or `None` (local mode) when it is missing, a symlink or not a plain file,
/// larger than [`MAX_MODE_FILE`], not JSON, or fails any check.
pub fn read_mode(home: &Path) -> Option<RemoteMode> {
    let path = mode_path(home);
    let meta = std::fs::symlink_metadata(&path).ok()?;
    if !meta.file_type().is_file() || meta.len() > MAX_MODE_FILE {
        return None;
    }
    let mut text = String::new();
    std::fs::File::open(&path).ok()?.take(MAX_MODE_FILE + 1).read_to_string(&mut text).ok()?;
    if text.len() as u64 > MAX_MODE_FILE {
        return None;
    }
    parse_mode(&text)
}

pub fn parse_mode(text: &str) -> Option<RemoteMode> {
    serde_json::from_str::<RemoteMode>(text).ok().filter(RemoteMode::valid)
}

/// Write the mode (checked again) through a new temp file in the same folder, owner-only on Unix.
pub fn write_mode(home: &Path, mode: &RemoteMode) -> Result<(), String> {
    use std::io::Write;
    if !mode.valid() {
        return Err("not a host omher can use".into());
    }
    let path = mode_path(home);
    let dir = path.parent().ok_or("no folder for remote.json")?;
    std::fs::create_dir_all(dir).map_err(|e| format!("could not make {}: {e}", dir.display()))?;
    let body = serde_json::to_string_pretty(mode).map_err(|e| e.to_string())? + "\n";
    let tmp = dir.join("remote.json.tmp");
    let _ = std::fs::remove_file(&tmp);
    let mut open = std::fs::OpenOptions::new();
    // create_new: never writes through a symlink someone left at the temp name
    open.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        open.mode(0o600);
    }
    let written = open.open(&tmp).and_then(|mut f| f.write_all(body.as_bytes()).and_then(|_| f.sync_all()));
    if let Err(e) = written {
        let _ = std::fs::remove_file(&tmp);
        return Err(format!("could not write {}: {e}", tmp.display()));
    }
    std::fs::rename(&tmp, &path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        format!("could not write {}: {e}", path.display())
    })
}

/// Delete the mode file (back to local mode). A file already gone is fine.
pub fn clear_mode(home: &Path) -> Result<(), String> {
    let path = mode_path(home);
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(format!("could not delete {}: {e}", path.display())),
    }
}

// ---------------------------------------------------------------------------------------------
// The one link
// ---------------------------------------------------------------------------------------------

/// A live link to the remote bridge. [`Up`] is the real one; tests use a stand-in.
pub trait Link: Send {
    fn url(&self) -> String;
    /// The link's last output lines once it has ended, `None` while it runs.
    fn ended(&mut self) -> Option<Vec<String>>;
    fn stop(self: Box<Self>);
}

impl Link for Up {
    fn url(&self) -> String {
        self.url.clone()
    }
    fn ended(&mut self) -> Option<Vec<String>> {
        Up::ended(self)
    }
    fn stop(self: Box<Self>) {
        Up::stop(*self)
    }
}

/// How a link is made: `peers::connect` in the app, a stand-in in tests.
pub type Connect = Arc<dyn Fn(&str, Option<u16>) -> Result<Box<dyn Link>, Failure> + Send + Sync>;

/// The app's connector: omher's bridge script as [`Peers::set_script`] resolved it, through [`peers::connect`].
pub fn ssh_connector(peers: Arc<Peers>) -> Connect {
    Arc::new(move |host: &str, port: Option<u16>| {
        let script = peers.script_bytes()?;
        peers::connect(host, port, &script).map(|up| Box::new(up) as Box<dyn Link>)
    })
}

/// `{mode: "remote"|"local", host?, port?, label?, state?, kind?, reason?, attempt?}`: what `remote_status` returns.
/// `state` is `connecting` | `connected` | `reconnecting` | `failed` in remote mode and absent in local mode.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RemoteStatus {
    pub mode: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub host: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub state: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kind: Option<FailKind>,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub reason: String,
    #[serde(skip_serializing_if = "is_zero")]
    pub attempt: u32,
}

fn is_zero(n: &u32) -> bool {
    *n == 0
}

impl RemoteStatus {
    fn local() -> RemoteStatus {
        RemoteStatus { mode: "local", host: None, port: None, label: None, state: None, kind: None, reason: String::new(), attempt: 0 }
    }
}

struct Inner {
    mode: Option<RemoteMode>,
    generation: u64,
    state: &'static str,
    url: Option<String>,
    kind: Option<FailKind>,
    reason: String,
    attempt: u32,
    link: Option<Box<dyn Link>>,
}

pub struct Remote {
    connect: Connect,
    inner: Mutex<Inner>,
    changed: Condvar,
    /// How often a live link is looked at, and the cap on a reconnect wait (tests run fast).
    poll: Duration,
    max_wait: Duration,
}

impl Remote {
    pub fn new(connect: Connect) -> Arc<Remote> {
        Remote::with_pace(connect, Duration::from_millis(250), Duration::MAX)
    }

    fn with_pace(connect: Connect, poll: Duration, max_wait: Duration) -> Arc<Remote> {
        Arc::new(Remote {
            connect,
            inner: Mutex::new(Inner { mode: None, generation: 0, state: "connecting", url: None, kind: None, reason: String::new(), attempt: 0, link: None }),
            changed: Condvar::new(),
            poll,
            max_wait,
        })
    }

    /// True in remote-only mode.
    pub fn active(&self) -> bool {
        self.inner.lock().unwrap().mode.is_some()
    }

    /// Enter (or restart) remote mode on `mode`: any earlier link stops, and the new one starts in the background.
    /// `adopt` is a link already up for the same host (the gate's Check), used instead of a first connect.
    pub fn start(self: &Arc<Self>, mode: RemoteMode, adopt: Option<Box<dyn Link>>) {
        let (old, generation) = {
            let mut g = self.inner.lock().unwrap();
            g.generation += 1;
            g.mode = Some(mode.clone());
            g.state = "connecting";
            g.url = None;
            g.kind = None;
            g.reason.clear();
            g.attempt = 0;
            (g.link.take(), g.generation)
        };
        self.changed.notify_all();
        if let Some(old) = old {
            thread::spawn(move || old.stop());
        }
        let me = Arc::clone(self);
        thread::spawn(move || me.run(generation, mode, adopt));
    }

    /// Try a failed link again now (the failed screen's Retry). Nothing in local mode.
    pub fn retry(self: &Arc<Self>) -> bool {
        let mode = self.inner.lock().unwrap().mode.clone();
        match mode {
            Some(m) => {
                self.start(m, None);
                true
            }
            None => false,
        }
    }

    /// Leave remote mode in memory and stop the link (app exit, Disconnect). The mode file is not touched here.
    pub fn stop(&self) {
        let old = {
            let mut g = self.inner.lock().unwrap();
            g.generation += 1;
            g.mode = None;
            g.state = "connecting";
            g.url = None;
            g.kind = None;
            g.reason.clear();
            g.attempt = 0;
            g.link.take()
        };
        self.changed.notify_all();
        if let Some(old) = old {
            old.stop();
        }
    }

    pub fn status(&self) -> RemoteStatus {
        let g = self.inner.lock().unwrap();
        let Some(m) = g.mode.as_ref() else { return RemoteStatus::local() };
        RemoteStatus {
            mode: "remote",
            host: Some(m.host.clone()),
            port: m.port,
            label: Some(m.label.clone()),
            state: Some(g.state),
            kind: g.kind,
            reason: g.reason.clone(),
            attempt: g.attempt,
        }
    }

    /// The link's loopback URL once connected; waits (bounded) while it connects or reconnects, as `Bridge::url`.
    pub fn url(&self, wait: Duration) -> Result<String, String> {
        let deadline = Instant::now() + wait;
        let mut g = self.inner.lock().unwrap();
        loop {
            if g.mode.is_none() {
                return Err("not in remote mode".into());
            }
            if let Some(u) = g.url.as_ref() {
                return Ok(u.clone());
            }
            if g.state == "failed" {
                return Err(if g.reason.is_empty() { "the connection to the server failed".into() } else { g.reason.clone() });
            }
            let now = Instant::now();
            if now >= deadline {
                return Err("the connection to the server is still starting".into());
            }
            g = self.changed.wait_timeout(g, deadline - now).unwrap().0;
        }
    }

    fn update(&self, generation: u64, f: impl FnOnce(&mut Inner)) -> bool {
        let ok = {
            let mut g = self.inner.lock().unwrap();
            if g.generation != generation {
                return false;
            }
            f(&mut g);
            true
        };
        self.changed.notify_all();
        ok
    }

    fn current(&self, generation: u64) -> bool {
        self.inner.lock().unwrap().generation == generation
    }

    /// The link's life, as a peer link's (`Peers::run`): connect, watch it, and on a drop reconnect with backoff until
    /// the mode is left or a failure a retry cannot fix stops it.
    fn run(self: Arc<Self>, generation: u64, mode: RemoteMode, mut adopt: Option<Box<dyn Link>>) {
        let mut attempt = 0u32;
        loop {
            if !self.current(generation) {
                if let Some(l) = adopt.take() {
                    l.stop();
                }
                return;
            }
            let result = match adopt.take() {
                Some(l) => Ok(l),
                None => (self.connect)(&mode.host, mode.port),
            };
            let (kind, line) = match result {
                Ok(link) => {
                    attempt = 0;
                    let url = link.url();
                    let mut link = Some(link);
                    let kept = self.update(generation, |g| {
                        g.state = "connected";
                        g.url = Some(url);
                        g.kind = None;
                        g.reason.clear();
                        g.attempt = 0;
                        g.link = link.take();
                    });
                    if !kept {
                        if let Some(l) = link {
                            l.stop();
                        }
                        return;
                    }
                    // follow the link until it ends
                    let lines = loop {
                        thread::sleep(self.poll);
                        let mut g = self.inner.lock().unwrap();
                        if g.generation != generation {
                            return;
                        }
                        let Some(l) = g.link.as_mut() else { return };
                        if let Some(lines) = l.ended() {
                            g.link = None;
                            g.url = None;
                            break lines;
                        }
                    };
                    eprintln!("omher: remote link to {} ended", mode.host);
                    let k = classify(&lines, true);
                    (if k == FailKind::Bridge { FailKind::Dropped } else { k }, last_line(&lines))
                }
                Err(f) => (f.kind, f.line),
            };
            match after_exit(kind, attempt) {
                Plan::Stop => {
                    self.update(generation, |g| {
                        g.state = "failed";
                        g.url = None;
                        g.kind = Some(kind);
                        g.reason = line;
                    });
                    return;
                }
                Plan::Retry { attempt: next, wait } => {
                    attempt = next;
                    if !self.update(generation, |g| {
                        g.state = "reconnecting";
                        g.url = None;
                        g.kind = Some(kind);
                        g.reason = line;
                        g.attempt = next;
                    }) {
                        return;
                    }
                    let until = Instant::now() + wait.min(self.max_wait);
                    while Instant::now() < until {
                        if !self.current(generation) {
                            return;
                        }
                        thread::sleep(self.poll.min(until.saturating_duration_since(Instant::now())));
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------
// The switch: what the page's bridge commands see, and moving between the modes
// ---------------------------------------------------------------------------------------------

/// `bridge_status`: the local bridge's status (`mode: "local"`), or the remote link's as `{state, error?, mode:
/// "remote", host}` (connecting and reconnecting read as `starting`, with the last failure as `error`).
pub fn bridge_status(remote: &Remote, bridge: &Arc<Bridge>) -> BridgeStatus {
    let st = remote.status();
    let Some(host) = st.host else { return bridge.status() };
    let state = match st.state {
        Some("connected") => "ready",
        Some("failed") => "failed",
        _ => "starting",
    };
    let error = if state == "ready" {
        None
    } else if st.reason.is_empty() {
        (state == "failed").then(|| "the connection to the server failed".to_string())
    } else {
        Some(st.reason)
    };
    BridgeStatus::remote(state, error, host)
}

/// `bridge_url`: the local bridge's URL, or the remote link's, each waiting at most `wait`.
pub fn bridge_url(remote: &Remote, bridge: &Arc<Bridge>, wait: Duration) -> Result<String, String> {
    if remote.active() {
        remote.url(wait)
    } else {
        bridge.url(wait)
    }
}

/// `remote_use`: save the mode, bring the remote link up now, and stop the local bridge and any peer links. The mode
/// is set before the bridge stops, so an installer ending meanwhile (`after_install`) either sees it and starts
/// nothing, or started the local bridge before it and this stop ends that one.
pub fn use_remote(home: &Path, remote: &Arc<Remote>, bridge: &Bridge, peers: &Peers, mode: RemoteMode, adopt: Option<Box<dyn Link>>) -> Result<RemoteStatus, String> {
    write_mode(home, &mode)?;
    remote.start(mode, adopt);
    bridge.stop();
    peers.stop_all();
    Ok(remote.status())
}

/// The end of `install_engine`: a clean install starts the local bridge, any other end releases the installer's hold,
/// unless remote-only mode began while the installer ran (a Connect meanwhile): then nothing local starts. Decided
/// under the link's lock, so it never interleaves with `use_remote` setting the mode. False when it was skipped.
pub fn after_install(remote: &Remote, bridge: &Arc<Bridge>, clean: bool, resource_dir: Option<PathBuf>) -> bool {
    let g = remote.inner.lock().unwrap();
    if g.mode.is_some() {
        return false;
    }
    if clean {
        bridge.start(resource_dir);
    } else {
        bridge.release();
    }
    drop(g);
    true
}

/// `remote_leave`: delete the mode file, stop the link, and start the local bridge and peer links again (the gate
/// then shows Install when Hermes is missing here).
pub fn leave_remote(home: &Path, remote: &Remote, bridge: &Arc<Bridge>, peers: &Arc<Peers>, resource_dir: Option<PathBuf>) -> Result<RemoteStatus, String> {
    clear_mode(home)?;
    if remote.active() {
        remote.stop();
        bridge.start(resource_dir);
        peers.start_all();
    }
    Ok(remote.status())
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    fn tmp_home(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("omher-remote-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    fn mode() -> RemoteMode {
        RemoteMode::new("VPS", "demo@host.example", Some(2222)).unwrap()
    }

    #[test]
    fn the_mode_file_round_trips_owner_only() {
        let home = tmp_home("rt");
        assert_eq!(read_mode(&home), None, "missing file = local mode");
        write_mode(&home, &mode()).unwrap();
        assert_eq!(read_mode(&home), Some(mode()));
        let text = std::fs::read_to_string(mode_path(&home)).unwrap();
        assert_eq!(serde_json::from_str::<serde_json::Value>(&text).unwrap(), serde_json::json!({"v": 1, "host": "demo@host.example", "port": 2222, "label": "VPS"}));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(std::fs::metadata(mode_path(&home)).unwrap().permissions().mode() & 0o777, 0o600);
        }
        assert!(!home.join(".omher/remote.json.tmp").exists());
        clear_mode(&home).unwrap();
        assert_eq!(read_mode(&home), None);
        clear_mode(&home).unwrap(); // already gone is fine
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn the_mode_file_is_checked_on_every_read() {
        assert_eq!(parse_mode(r#"{"v":1,"host":"mini","port":null,"label":"Mini"}"#).map(|m| m.port), Some(None));
        assert!(parse_mode(r#"{"v":1,"host":"mini","label":"Mini"}"#).is_some());
        for bad in [
            r#"{"v":1,"host":"-oProxyCommand=sh","port":null,"label":"x"}"#,
            r#"{"v":1,"host":"a b","port":null,"label":"x"}"#,
            r#"{"v":1,"host":"$(id)","port":null,"label":"x"}"#,
            r#"{"v":1,"host":"mini","port":0,"label":"x"}"#,
            r#"{"v":1,"host":"mini","port":70000,"label":"x"}"#,
            r#"{"v":1,"host":"mini","port":null,"label":""}"#,
            r#"{"v":1,"host":"mini","port":null,"label":"a\nb"}"#,
            r#"{"v":2,"host":"mini","port":null,"label":"x"}"#,
            r#"{"host":"mini","label":"x"}"#,
            "not json",
            "",
        ] {
            assert_eq!(parse_mode(bad), None, "{bad}");
        }
        assert!(RemoteMode::new("x", "u@-h", None).is_err());
        assert!(RemoteMode::new("   ", "mini", None).is_err());
        assert_eq!(RemoteMode::new("  VPS ", "mini", None).unwrap().label, "VPS");
        // a bad file on disk is local mode, and write refuses a bad mode
        let home = tmp_home("bad");
        std::fs::create_dir_all(home.join(".omher")).unwrap();
        std::fs::write(mode_path(&home), r#"{"v":1,"host":"a;b","port":null,"label":"x"}"#).unwrap();
        assert_eq!(read_mode(&home), None);
        let bad = RemoteMode { host: "a b".into(), ..mode() };
        assert!(write_mode(&home, &bad).is_err());
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn an_oversize_file_or_a_folder_is_refused() {
        let home = tmp_home("big");
        std::fs::create_dir_all(home.join(".omher")).unwrap();
        let pad = " ".repeat(MAX_MODE_FILE as usize);
        std::fs::write(mode_path(&home), format!(r#"{{"v":1,"host":"mini","port":null,"label":"x"}}{pad}"#)).unwrap();
        assert_eq!(read_mode(&home), None);
        std::fs::remove_file(mode_path(&home)).unwrap();
        std::fs::create_dir_all(mode_path(&home)).unwrap();
        assert_eq!(read_mode(&home), None);
        let _ = std::fs::remove_dir_all(&home);
    }

    #[cfg(unix)]
    #[test]
    fn a_symlinked_mode_file_is_refused() {
        let home = tmp_home("link");
        std::fs::create_dir_all(home.join(".omher")).unwrap();
        let target = home.join("elsewhere.json");
        std::fs::write(&target, r#"{"v":1,"host":"mini","port":null,"label":"x"}"#).unwrap();
        std::os::unix::fs::symlink(&target, mode_path(&home)).unwrap();
        assert_eq!(read_mode(&home), None);
        // a symlink at the temp name is never written through
        std::os::unix::fs::symlink(&target, home.join(".omher/remote.json.tmp")).unwrap();
        std::fs::remove_file(mode_path(&home)).unwrap();
        write_mode(&home, &mode()).unwrap();
        assert_eq!(read_mode(&home), Some(mode()));
        assert_eq!(std::fs::read_to_string(&target).unwrap(), r#"{"v":1,"host":"mini","port":null,"label":"x"}"#);
        let _ = std::fs::remove_dir_all(&home);
    }

    // ---- a stand-in connector ----

    struct Fake {
        url: String,
        dead: Arc<AtomicBool>,
        stopped: Arc<AtomicUsize>,
    }

    impl Link for Fake {
        fn url(&self) -> String {
            self.url.clone()
        }
        fn ended(&mut self) -> Option<Vec<String>> {
            self.dead.load(Ordering::SeqCst).then(|| vec!["Connection to h closed by remote host.".to_string()])
        }
        fn stop(self: Box<Self>) {
            self.stopped.fetch_add(1, Ordering::SeqCst);
        }
    }

    /// Each connect takes the next planned result: `Ok(n)` is a live link on port `n`, `Err(kind)` a failure.
    struct Scripted {
        results: Mutex<VecDeque<Result<u16, FailKind>>>,
        calls: AtomicUsize,
        hosts: Mutex<Vec<(String, Option<u16>)>>,
        dead: Arc<AtomicBool>,
        stopped: Arc<AtomicUsize>,
    }

    fn fake(results: Vec<Result<u16, FailKind>>) -> (Arc<Remote>, Arc<Scripted>) {
        let plan = Arc::new(Scripted {
            results: Mutex::new(results.into()),
            calls: AtomicUsize::new(0),
            hosts: Mutex::new(Vec::new()),
            dead: Arc::new(AtomicBool::new(false)),
            stopped: Arc::new(AtomicUsize::new(0)),
        });
        let p = Arc::clone(&plan);
        let connect: Connect = Arc::new(move |host: &str, port: Option<u16>| {
            p.calls.fetch_add(1, Ordering::SeqCst);
            p.hosts.lock().unwrap().push((host.to_string(), port));
            match p.results.lock().unwrap().pop_front().unwrap_or(Err(FailKind::Timeout)) {
                Ok(n) => {
                    p.dead.store(false, Ordering::SeqCst);
                    Ok(Box::new(Fake { url: format!("ws://127.0.0.1:{n}/?token=t"), dead: Arc::clone(&p.dead), stopped: Arc::clone(&p.stopped) }) as Box<dyn Link>)
                }
                Err(kind) => Err(Failure { kind, line: format!("{kind:?}") }),
            }
        });
        (Remote::with_pace(connect, Duration::from_millis(5), Duration::from_millis(20)), plan)
    }

    fn wait_for(r: &Remote, state: &str) -> RemoteStatus {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let st = r.status();
            if st.state == Some(state) {
                return st;
            }
            assert!(Instant::now() < deadline, "never {state}: {st:?}");
            thread::sleep(Duration::from_millis(5));
        }
    }

    #[test]
    fn the_link_comes_up_and_reconnects_after_a_drop() {
        let (r, plan) = fake(vec![Err(FailKind::Unreachable), Ok(5001), Ok(5002)]);
        assert_eq!(r.status(), RemoteStatus::local());
        assert!(r.url(Duration::from_millis(10)).is_err());
        r.start(mode(), None);
        assert!(r.active());
        // the first try fails: the URL waits, then the retry brings it up
        assert_eq!(r.url(Duration::from_secs(5)).unwrap(), "ws://127.0.0.1:5001/?token=t");
        assert_eq!(plan.hosts.lock().unwrap()[0], ("demo@host.example".to_string(), Some(2222)));
        // the link drops: reconnecting, then a new URL
        plan.dead.store(true, Ordering::SeqCst);
        let deadline = Instant::now() + Duration::from_secs(5);
        while r.url(Duration::from_millis(50)).ok().as_deref() != Some("ws://127.0.0.1:5002/?token=t") {
            assert!(Instant::now() < deadline, "{:?}", r.status());
        }
        assert_eq!(plan.calls.load(Ordering::SeqCst), 3);
        r.stop();
        assert!(!r.active());
        assert_eq!(plan.stopped.load(Ordering::SeqCst), 1, "leaving stops the live link");
    }

    #[test]
    fn a_failure_a_retry_cannot_fix_stops_until_retry() {
        let (r, plan) = fake(vec![Err(FailKind::Auth), Ok(6001)]);
        r.start(mode(), None);
        let st = wait_for(&r, "failed");
        assert_eq!(st.kind, Some(FailKind::Auth));
        thread::sleep(Duration::from_millis(50));
        assert_eq!(plan.calls.load(Ordering::SeqCst), 1, "no retry on its own");
        assert_eq!(r.url(Duration::from_secs(1)), Err("Auth".into()));
        assert!(r.retry());
        assert_eq!(r.url(Duration::from_secs(5)).unwrap(), "ws://127.0.0.1:6001/?token=t");
        r.stop();
        assert!(!r.retry(), "nothing to retry in local mode");
    }

    #[test]
    fn an_adopted_check_link_is_used_without_a_connect() {
        let (r, plan) = fake(vec![]);
        let adopt = Box::new(Fake { url: "ws://127.0.0.1:7001/?token=c".into(), dead: Arc::new(AtomicBool::new(false)), stopped: Arc::clone(&plan.stopped) });
        r.start(mode(), Some(adopt));
        assert_eq!(r.url(Duration::from_secs(5)).unwrap(), "ws://127.0.0.1:7001/?token=c");
        assert_eq!(plan.calls.load(Ordering::SeqCst), 0);
        r.stop();
        assert_eq!(plan.stopped.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn status_has_a_mode_and_host_in_both_modes() {
        let bridge = Bridge::new();
        let (r, _plan) = fake(vec![Ok(8001)]);
        // local mode: the local bridge's own status, marked local
        let local = serde_json::to_value(bridge_status(&r, &bridge)).unwrap();
        assert_eq!(local, serde_json::json!({"state": "starting", "mode": "local"}));
        assert_eq!(serde_json::to_value(r.status()).unwrap(), serde_json::json!({"mode": "local"}));
        r.start(mode(), None);
        r.url(Duration::from_secs(5)).unwrap();
        assert_eq!(serde_json::to_value(bridge_status(&r, &bridge)).unwrap(), serde_json::json!({"state": "ready", "mode": "remote", "host": "demo@host.example"}));
        assert_eq!(
            serde_json::to_value(r.status()).unwrap(),
            serde_json::json!({"mode": "remote", "host": "demo@host.example", "port": 2222, "label": "VPS", "state": "connected"})
        );
        r.stop();
        bridge.stop();
    }

    #[test]
    fn a_link_that_stops_reads_as_failed_with_the_reason() {
        let bridge = Bridge::new();
        let (r, _plan) = fake(vec![Err(FailKind::Timeout), Err(FailKind::Timeout), Err(FailKind::Timeout), Err(FailKind::NoHermes)]);
        r.start(mode(), None);
        let st = wait_for(&r, "failed");
        assert_eq!(st.kind, Some(FailKind::NoHermes));
        assert_eq!(
            serde_json::to_value(bridge_status(&r, &bridge)).unwrap(),
            serde_json::json!({"state": "failed", "error": "NoHermes", "mode": "remote", "host": "demo@host.example"})
        );
        r.stop();
    }

    #[test]
    fn using_and_leaving_switch_the_url_without_a_restart() {
        let home = tmp_home("switch");
        let bridge = Bridge::new();
        bridge.set_ready_for_test(9, "local");
        let peers = Peers::new(home.clone());
        let (r, _plan) = fake(vec![Ok(9101)]);
        assert_eq!(bridge_url(&r, &bridge, Duration::from_millis(50)).unwrap(), "ws://127.0.0.1:9/?token=local");
        let st = use_remote(&home, &r, &bridge, &peers, mode(), None).unwrap();
        assert_eq!(st.mode, "remote");
        assert_eq!(read_mode(&home), Some(mode()), "Connect writes the mode file");
        assert_eq!(bridge.status().state, "failed", "the local bridge is stopped");
        assert_eq!(bridge_url(&r, &bridge, Duration::from_secs(5)).unwrap(), "ws://127.0.0.1:9101/?token=t");
        // Disconnect: the file goes, the link stops, the local bridge starts again
        let st = leave_remote(&home, &r, &bridge, &peers, None).unwrap();
        assert_eq!(st, RemoteStatus::local());
        assert_eq!(read_mode(&home), None);
        assert_eq!(bridge_status(&r, &bridge).mode, "local");
        // the restart's launch runs (a test has no interpreter, so it fails at once) before the next step
        let deadline = Instant::now() + Duration::from_secs(5);
        while bridge.status().state == "starting" {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(5));
        }
        // leaving again while local deletes nothing more and does not restart the local bridge
        bridge.set_ready_for_test(10, "again");
        leave_remote(&home, &r, &bridge, &peers, None).unwrap();
        assert_eq!(bridge.status().state, "ready");
        bridge.stop();
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn an_install_is_refused_in_remote_mode_and_one_ending_after_connect_starts_no_local_bridge() {
        let home = tmp_home("install");
        let bridge = Bridge::new();
        let peers = Peers::new(home.clone());
        let (r, _plan) = fake(vec![Ok(9102)]);
        // local mode: the install may run, and its clean end starts the local bridge
        assert_eq!(crate::refuse_local_hermes_in_remote(&r), Ok(()));
        bridge.hold();
        assert!(after_install(&r, &bridge, true, None));
        assert_eq!(bridge.status().state, "starting");
        bridge.stop();
        // an installer is running (the bridge held) when the person presses Connect
        bridge.set_ready_for_test(9, "local");
        bridge.hold();
        use_remote(&home, &r, &bridge, &peers, mode(), None).unwrap();
        // its clean end (or a failed one) starts and revives nothing here: the server link is the bridge now
        assert!(!after_install(&r, &bridge, true, None));
        assert!(!after_install(&r, &bridge, false, None));
        assert_eq!(bridge.status().state, "failed", "the local bridge stays stopped");
        assert_eq!(bridge_url(&r, &bridge, Duration::from_secs(5)).unwrap(), "ws://127.0.0.1:9102/?token=t");
        // and a new install is refused before anything runs
        let err = crate::refuse_local_hermes_in_remote(&r).unwrap_err();
        assert!(err.contains("omher uses a server"), "{err}");
        r.stop();
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn a_bad_mode_is_never_saved_and_changes_nothing() {
        let home = tmp_home("refuse");
        let bridge = Bridge::new();
        bridge.set_ready_for_test(9, "local");
        let peers = Peers::new(home.clone());
        let (r, plan) = fake(vec![]);
        let bad = RemoteMode { host: "-oProxyCommand=x".into(), ..mode() };
        assert!(use_remote(&home, &r, &bridge, &peers, bad, None).is_err());
        assert!(!r.active());
        assert_eq!(bridge.status().state, "ready");
        assert_eq!(plan.calls.load(Ordering::SeqCst), 0);
        bridge.stop();
        let _ = std::fs::remove_dir_all(&home);
    }
}

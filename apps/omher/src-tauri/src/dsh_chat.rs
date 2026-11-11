//! DSH chats: DeepSeek Harness (deepseek-ai/deepseek-harness) as an omher chat.
//!
//! The harness ships no terminal profile and no long-lived stdio mode a person can answer approvals in, so each
//! message is one run of its headless profile, `dsh --profile headless --patch <overlay> --json [--session-id
//! session-<uuid>] -`, with the message on stdin ([`crate::sessions::dsh_turn_args`]). The first run reports the
//! harness's session id; every later message continues that session with `--session-id`. Its `--json` events
//! (`session`, `status`, `thinking`, `text`, `tool_call`, `tool_result`, `final`, `error`) become the bot chat's
//! events ([`Dsh`], pure, tested on recorded streams).
//!
//! Approvals: headless runs under the harness's own `workspace-write` sandbox (pinned with `DSH_PERMISSION_MODE`)
//! and has no approval channel, so anything that needs a person's yes (writing outside the folder, a wider
//! sandbox) is refused by the harness, never allowed. omher shows those refusals as failed steps.

use std::ffi::OsString;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::agent_chat::{call_detail, clip, ev, exit_reason, exit_turn_end, s, tool_kind, ChatOut, Event, Input, Picture};
use crate::sessions::{dsh_patch_path, dsh_turn_args, launch_for, resume_args, DSH_HEADLESS_PATCH};

/// The harness's `--json` run events for one DSH chat, across its messages. Pure: lines in, events out.
#[derive(Default)]
pub struct Dsh {
    cwd: String,
    /// `session-<uuid>`, once the harness reported it (or the one this chat continues)
    pub session: String,
    msg: u64,
    turn: bool,
    interrupted: bool,
    /// the last `turn_end` reason: kind and error message
    reason: Option<(String, String)>,
}

impl Dsh {
    pub fn new(cwd: &str, session: Option<&str>) -> Dsh {
        Dsh { cwd: cwd.into(), session: session.unwrap_or_default().into(), ..Dsh::default() }
    }

    /// A message was sent: a run starts.
    pub fn begin(&mut self) -> Vec<Event> {
        self.turn = true;
        self.interrupted = false;
        self.reason = None;
        vec![ev("turn.start", json!({}))]
    }

    /// The person pressed Stop; the run's end then reads as interrupted.
    pub fn interrupt(&mut self) {
        self.interrupted = true;
    }

    fn end(&mut self, kind: &str, err: &str) -> Vec<Event> {
        if !self.turn {
            return vec![];
        }
        self.turn = false;
        let outcome = match kind {
            _ if self.interrupted => "interrupted",
            "aborted" | "interrupted" => "interrupted",
            "error" => "error",
            _ => "done",
        };
        let mut f = json!({"outcome": outcome});
        if outcome == "error" {
            f["error"] = Value::String(if err.is_empty() { "DeepSeek Harness stopped".into() } else { friendly(err) });
        }
        vec![ev("turn.end", f)]
    }

    /// One line of the harness's stdout.
    pub fn on_line(&mut self, line: &str) -> Vec<Event> {
        let Ok(v) = serde_json::from_str::<Value>(line) else { return vec![] };
        match s(&v, "type").as_str() {
            "session" => {
                let id = s(&v, "sessionId");
                if id.is_empty() || id == self.session {
                    return vec![];
                }
                self.session = id.clone();
                vec![ev("session.info", json!({"agent_session": id}))]
            }
            "thinking" => vec![ev("thinking", json!({}))],
            "text" => {
                let t = s(&v, "text");
                if t.trim().is_empty() {
                    return vec![];
                }
                self.msg += 1;
                vec![ev("message", json!({"id": format!("dsh-m{}", self.msg), "text": t}))]
            }
            "tool_call" => {
                let name = s(&v, "tool");
                let input = v.get("input").cloned().unwrap_or(Value::Null);
                vec![ev("tool.start", json!({"tool_id": s(&v, "callId"), "name": tool_kind(&name), "detail": call_detail(&name, &input, &self.cwd)}))]
            }
            "tool_result" => {
                let ok = s(&v, "status") == "completed" && v.get("error").is_none();
                vec![ev("tool.end", json!({"tool_id": s(&v, "callId"), "name": "", "ok": ok, "ms": 0}))]
            }
            "status" if s(&v, "phase") == "turn_end" => {
                let r = &v["reason"];
                self.reason = Some((s(r, "kind"), r.get("error").map(|e| s(e, "message")).unwrap_or_default()));
                vec![]
            }
            "final" => {
                let (kind, err) = match v.get("reason").filter(|r| r.is_object()) {
                    Some(r) => (s(r, "kind"), r.get("error").map(|e| s(e, "message")).unwrap_or_default()),
                    None => self.reason.clone().unwrap_or_else(|| ("completed".into(), String::new())),
                };
                self.end(&kind, &err)
            }
            // a failure outside a turn (an unknown session, a usage error): the stream ends without `final`
            "error" => self.end("error", &s(&v, "message")),
            _ => vec![],
        }
    }

    /// The run's process ended. A run that wrote no `final` ends here, with the reason from its stderr.
    pub fn finish(&mut self, code: Option<i32>, err: &str) -> Vec<Event> {
        if !self.turn {
            return vec![];
        }
        if self.interrupted {
            return self.end("aborted", "");
        }
        self.turn = false;
        vec![exit_turn_end(code, &friendly(err))]
    }
}

/// The message with each attached picture named by its saved path (the UI's wording for attached files).
fn with_pictures(text: &str, images: &[Picture]) -> String {
    if images.is_empty() {
        return text.to_string();
    }
    let head = if images.len() == 1 { "Attached file (a copy omher saved; open it with your tools):" } else { "Attached files (copies omher saved; open them with your tools):" };
    let list: Vec<String> = images.iter().map(|p| format!("- {}", p.path)).collect();
    [text.trim().to_string(), format!("{head}\n{}", list.join("\n"))].into_iter().filter(|s| !s.is_empty()).collect::<Vec<_>>().join("\n\n")
}

/// A calm line for a harness error: a missing key says where to add one, anything else its first line.
pub fn friendly(err: &str) -> String {
    let e = err.trim().trim_start_matches("dsh: ");
    if e.contains("MISSING_CREDENTIAL") || e.contains("no credential for provider") {
        return "DeepSeek Harness has no key for its model. Add one in the DeepSeek Harness app (Models), then send again.".into();
    }
    clip(e.lines().find(|l| !l.trim().is_empty()).unwrap_or(e), 200)
}

// ---------------------------------------------------------------------------------------------
// One DSH chat: a run per message
// ---------------------------------------------------------------------------------------------

type Sink = Arc<Mutex<Box<dyn FnMut(ChatOut) + Send>>>;

struct Run {
    child: Arc<Mutex<Child>>,
    pid: u32,
    exited: Arc<AtomicBool>,
}

struct Inner {
    cwd: PathBuf,
    patch: PathBuf,
    /// the harness CLI as `launch_for("dsh")` resolved it, and the child PATH
    launch: Vec<OsString>,
    path_env: OsString,
    state: Mutex<Dsh>,
    sink: Sink,
    run: Mutex<Option<Run>>,
}

/// A DSH chat. Cloning shares it.
#[derive(Clone)]
pub struct DshChat(Arc<Inner>);

fn deliver(sink: &Sink, events: Vec<Event>) {
    if events.is_empty() {
        return;
    }
    if let Ok(mut f) = sink.lock() {
        for e in events {
            f(ChatOut::Event(e));
        }
    }
}

/// Write the fixed overlay ([`DSH_HEADLESS_PATCH`]) to `path` unless it already holds exactly that. Refuses a
/// symlink, so the write never lands anywhere but omher's own folder.
pub fn write_patch(path: &Path) -> Result<(), String> {
    if path.is_symlink() || path.parent().is_some_and(Path::is_symlink) {
        return Err(format!("{} is a link; omher does not write through it", path.display()));
    }
    if std::fs::read_to_string(path).is_ok_and(|t| t == DSH_HEADLESS_PATCH) {
        return Ok(());
    }
    std::fs::create_dir_all(path.parent().ok_or("no folder")?).map_err(|e| e.to_string())?;
    std::fs::write(path, DSH_HEADLESS_PATCH).map_err(|e| e.to_string())
}

fn home() -> Result<PathBuf, String> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| "no home folder".to_string())
}

impl DshChat {
    /// A DSH chat in `cwd`, continuing harness session `resume` (`session-<uuid>`) when given. Nothing runs yet:
    /// each message starts one run.
    pub fn start<F>(cwd: &Path, resume: Option<&str>, sink: F) -> Result<DshChat, String>
    where
        F: FnMut(ChatOut) + Send + 'static,
    {
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(format!("not a folder: {}", cwd.display()));
        }
        if let Some(r) = resume {
            resume_args("dsh", r)?;
        }
        let (launch, path_env) = launch_for("dsh")?;
        let chat = DshChat(Arc::new(Inner {
            cwd: cwd.to_path_buf(),
            patch: dsh_patch_path(&home()?),
            launch,
            path_env,
            state: Mutex::new(Dsh::new(&cwd.to_string_lossy(), resume)),
            sink: Arc::new(Mutex::new(Box::new(sink))),
            run: Mutex::new(None),
        }));
        if let Some(r) = resume {
            deliver(&chat.0.sink, vec![ev("session.info", json!({"agent_session": r}))]);
        }
        Ok(chat)
    }

    pub fn input(&self, input: Input) -> Result<(), String> {
        match input {
            // headless takes text only: attached pictures are named by their saved copy, as other files are
            Input::Send { text, images } => self.send(&with_pictures(&text, &images)),
            Input::Interrupt => {
                let run = self.0.run.lock().unwrap();
                let r = run.as_ref().ok_or("nothing is running")?;
                self.0.state.lock().unwrap().interrupt();
                interrupt(r);
                Ok(())
            }
            Input::Approve { .. } | Input::Clarify { .. } => Err("DeepSeek Harness asks nothing in this chat".into()),
            Input::Model { .. } => Err("DeepSeek Harness uses the model set in its own app".into()),
        }
    }

    fn send(&self, text: &str) -> Result<(), String> {
        let inner = &self.0;
        let mut slot = inner.run.lock().unwrap();
        if slot.is_some() {
            return Err("DeepSeek Harness is still answering; send this when it is done".into());
        }
        write_patch(&inner.patch)?;
        let session = inner.state.lock().unwrap().session.clone();
        let mut argv = inner.launch.clone();
        argv.extend(dsh_turn_args(&inner.patch, Some(session.as_str()).filter(|s| !s.is_empty()))?);
        let mut cmd = command_for(&argv, &inner.cwd, &inner.path_env)?;
        let mut child = cmd.spawn().map_err(|e| format!("{}: {e}", Path::new(&argv[0]).display()))?;
        let mut stdin = child.stdin.take().ok_or("no stdin")?;
        let mut stdout = child.stdout.take().ok_or("no stdout")?;
        let mut stderr = child.stderr.take().ok_or("no stderr")?;
        let task = text.to_string();
        thread::spawn(move || {
            let _ = stdin.write_all(task.as_bytes());
        });
        let pid = child.id();
        let child = Arc::new(Mutex::new(child));
        let exited = Arc::new(AtomicBool::new(false));
        *slot = Some(Run { child: child.clone(), pid, exited: exited.clone() });
        drop(slot);
        deliver(&inner.sink, inner.state.lock().unwrap().begin());

        let tail = Arc::new(Mutex::new(String::new()));
        {
            let tail = tail.clone();
            thread::spawn(move || {
                let mut buf = [0u8; 4096];
                while let Ok(n) = stderr.read(&mut buf) {
                    if n == 0 {
                        break;
                    }
                    let mut t = tail.lock().unwrap();
                    t.push_str(&String::from_utf8_lossy(&buf[..n]));
                    if t.len() > 4000 {
                        let cut = (t.len() - 2000..t.len()).find(|i| t.is_char_boundary(*i)).unwrap_or(t.len());
                        t.drain(..cut);
                    }
                }
            });
        }
        let read_done = Arc::new(AtomicBool::new(false));
        {
            let (me, done) = (self.clone(), read_done.clone());
            thread::spawn(move || {
                let mut pending: Vec<u8> = Vec::new();
                let mut buf = [0u8; 16 * 1024];
                let feed = |raw: &[u8]| {
                    let line = String::from_utf8_lossy(raw);
                    let events = me.0.state.lock().unwrap().on_line(line.trim_end_matches('\r'));
                    deliver(&me.0.sink, events);
                };
                loop {
                    match stdout.read(&mut buf) {
                        Ok(0) | Err(_) => break,
                        Ok(n) => {
                            pending.extend_from_slice(&buf[..n]);
                            while let Some(i) = pending.iter().position(|c| *c == b'\n') {
                                let rest = pending.split_off(i + 1);
                                let line = std::mem::replace(&mut pending, rest);
                                feed(&line[..line.len() - 1]);
                            }
                        }
                    }
                }
                if !pending.is_empty() {
                    feed(&pending);
                }
                done.store(true, Ordering::SeqCst);
            });
        }
        {
            let me = self.clone();
            thread::spawn(move || {
                let code = loop {
                    if let Ok(Some(st)) = child.lock().unwrap().try_wait() {
                        break st.code();
                    }
                    thread::sleep(Duration::from_millis(40));
                };
                exited.store(true, Ordering::SeqCst);
                let deadline = Instant::now() + Duration::from_millis(800);
                while !read_done.load(Ordering::SeqCst) && Instant::now() < deadline {
                    thread::sleep(Duration::from_millis(10));
                }
                let err = exit_reason(&tail.lock().unwrap());
                let events = me.0.state.lock().unwrap().finish(code, &err);
                *me.0.run.lock().unwrap() = None;
                deliver(&me.0.sink, events);
            });
        }
        Ok(())
    }

    /// Stop a running message (interrupt, then a hard kill after `grace`). The chat itself holds no process.
    pub fn stop(&self, grace: Duration) {
        let run = self.0.run.lock().unwrap().take();
        if let Some(r) = run {
            interrupt(&r);
            let deadline = Instant::now() + grace;
            while !r.exited.load(Ordering::SeqCst) && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(25));
            }
            if !r.exited.load(Ordering::SeqCst) {
                crate::sessions::signal_group(Some(r.pid), true);
                let _ = r.child.lock().unwrap().kill();
            }
        }
    }
}

/// SIGINT to the run's process group (the harness's own interrupt: it ends the turn as aborted); Windows has no
/// such signal for a console-less child, so the run is ended there.
fn interrupt(r: &Run) {
    if r.exited.load(Ordering::SeqCst) {
        return;
    }
    #[cfg(unix)]
    unsafe {
        if r.pid > 1 {
            libc::kill(-(r.pid as i32), libc::SIGINT);
        }
    }
    #[cfg(not(unix))]
    {
        let _ = r.child.lock().unwrap().kill();
    }
}

/// One run's command: `argv` in `cwd` on pipes, with the child PATH and `DSH_PERMISSION_MODE=workspace-write`
/// (the harness's own default, pinned so an inherited setting cannot widen it). Nothing else is added.
fn command_for(argv: &[OsString], cwd: &Path, path_env: &OsString) -> Result<Command, String> {
    let (prog, rest) = argv.split_first().ok_or("empty argv")?;
    let mut cmd = Command::new(prog);
    cmd.args(rest).current_dir(cwd).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    cmd.env("PATH", path_env);
    cmd.env("DSH_PERMISSION_MODE", "workspace-write");
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
        if std::env::var_os("LANG").is_none() {
            cmd.env("LANG", "en_US.UTF-8");
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    Ok(cmd)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The real harness, started the way omher starts it: `launch_for("dsh")` (detection, which must land on
    /// DeepSeek Harness's own CLI), then a DSH chat's own runs (the overlay, `--profile headless --json`, then
    /// `--session-id`). One message, then one that needs the first. The CLI runs under `sh -c '"$0" "$@" | tee'`
    /// only so its raw lines land in `OMHER_DSH_RECORD` for the fixtures; argv, env and stdin are the chat's own.
    /// Spends two real turns: `OMHER_DSH_RECORD=<file> cargo test real_dsh_chat -- --ignored --nocapture`.
    #[test]
    #[ignore]
    fn real_dsh_chat_continues_its_session() {
        let dir = std::env::temp_dir().join(format!("omher-real-dsh-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let dir = dir.canonicalize().unwrap();
        let (launch, path_env) = launch_for("dsh").unwrap();
        println!("dsh = {launch:?}");
        assert!(launch[0].to_string_lossy().contains("DeepSeek Harness"), "{launch:?}");
        let rec = std::env::var("OMHER_DSH_RECORD").unwrap_or_else(|_| dir.join("rec.jsonl").to_string_lossy().into_owned());
        let mut wrapped: Vec<OsString> = vec!["/bin/sh".into(), "-c".into(), format!("\"$0\" \"$@\" | tee -a '{rec}'").into()];
        wrapped.extend(launch);
        let out = Arc::new(Mutex::new(Vec::<Event>::new()));
        let o = out.clone();
        let chat = DshChat(Arc::new(Inner {
            cwd: dir.clone(),
            patch: dsh_patch_path(&home().unwrap()),
            launch: wrapped,
            path_env,
            state: Mutex::new(Dsh::new(&dir.to_string_lossy(), None)),
            sink: Arc::new(Mutex::new(Box::new(move |x| {
                if let ChatOut::Event(e) = x {
                    if s(&e, "event") != "thinking" {
                        println!("event {e}");
                    }
                    o.lock().unwrap().push(e)
                }
            }))),
            run: Mutex::new(None),
        }));
        let idle = || {
            let deadline = Instant::now() + Duration::from_secs(240);
            thread::sleep(Duration::from_millis(300));
            while chat.0.run.lock().unwrap().is_some() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(100));
            }
        };
        chat.input(Input::Send { text: "Pick one fruit and one whole number between 10 and 99. Reply with only those two, like: mango 37".into(), images: vec![] }).unwrap();
        idle();
        chat.input(Input::Send { text: "Multiply the number you just picked by 3. Reply with only the fruit and the result.".into(), images: vec![] }).unwrap();
        idle();
        let got = out.lock().unwrap().clone();
        let msgs: Vec<String> = got.iter().filter(|e| s(e, "event") == "message").map(|e| s(e, "text")).collect();
        let sessions: Vec<String> = got.iter().filter(|e| s(e, "event") == "session.info").map(|e| s(e, "agent_session")).collect();
        println!("answers {msgs:?} session {sessions:?}");
        assert_eq!(sessions.len(), 1, "{got:?}");
        assert_eq!(msgs.len(), 2, "{got:?}");
        let _ = std::fs::remove_dir_all(dir);
    }

    /// A stream recorded from DeepSeek Harness 0.2.1-rc.2 (`dsh --profile headless --patch … --json -`, the way
    /// a DSH chat runs it), folder paths rewritten to /w/proj.
    fn real(name: &str) -> Vec<String> {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("real").join(name);
        std::fs::read_to_string(p).unwrap().lines().filter(|l| !l.trim().is_empty()).map(String::from).collect()
    }

    fn run(d: &mut Dsh, lines: &[String]) -> Vec<Event> {
        let mut out = d.begin();
        for l in lines {
            out.extend(d.on_line(l));
        }
        out
    }

    fn names(events: &[Event]) -> Vec<String> {
        events.iter().map(|e| s(e, "event")).collect()
    }

    fn of<'a>(events: &'a [Event], name: &str) -> Vec<&'a Event> {
        events.iter().filter(|e| s(e, "event") == name).collect()
    }

    #[test]
    fn real_two_messages_one_session() {
        let mut d = Dsh::new("/w/proj", None);
        let first = run(&mut d, &real("dsh-1-first.jsonl"));
        let info = of(&first, "session.info");
        assert_eq!(info.len(), 1);
        let sid = s(info[0], "agent_session");
        assert!(sid.starts_with("session-") && crate::sessions::is_uuid(&sid["session-".len()..]), "{sid}");
        assert_eq!(d.session, sid);
        assert_eq!(names(&first).first().map(String::as_str), Some("turn.start"));
        assert_eq!(names(&first).last().map(String::as_str), Some("turn.end"));
        assert_eq!(s(of(&first, "turn.end")[0], "outcome"), "done");
        assert_eq!(of(&first, "message").len(), 1);
        assert!(!d.turn);
        // the second message continues the same session: --session-id <it>, and no new session.info
        let args = dsh_turn_args(Path::new("/h/.omher/dsh/headless.patch.yml"), Some(&d.session)).unwrap();
        assert_eq!(args[args.len() - 3..], [OsString::from("--session-id"), OsString::from(&sid), OsString::from("-")]);
        let second = run(&mut d, &real("dsh-2-second.jsonl"));
        assert!(of(&second, "session.info").is_empty());
        assert_eq!(s(of(&second, "turn.end")[0], "outcome"), "done");
        let ids: Vec<String> = of(&first, "message").iter().chain(of(&second, "message").iter()).map(|e| s(e, "id")).collect();
        assert_eq!(ids, ["dsh-m1", "dsh-m2"]);
    }

    #[test]
    fn real_tool_steps_and_a_refused_escalation() {
        // the harness refuses a write outside the folder, then its escalation: "no approval channel is available"
        let mut d = Dsh::new("/w/proj", None);
        let ev = run(&mut d, &real("dsh-3-escalate.jsonl"));
        let starts: Vec<(String, String)> = of(&ev, "tool.start").iter().map(|e| (s(e, "name"), s(e, "detail"))).collect();
        let one = ("terminal".to_string(), "touch ../outside-probe.txt".to_string());
        assert_eq!(starts, [one.clone(), one]);
        let oks: Vec<bool> = of(&ev, "tool.end").iter().map(|e| e["ok"].as_bool().unwrap()).collect();
        // the first returned (its shell command failed inside), the escalation was refused
        assert_eq!(oks, [true, false]);
        assert!(of(&ev, "approval.request").is_empty());
        assert_eq!(of(&ev, "message").len(), 1);
        assert_eq!(s(of(&ev, "turn.end")[0], "outcome"), "done");
        assert!(names(&ev).contains(&"thinking".to_string()));
    }

    #[test]
    fn real_missing_key_says_where_to_add_one() {
        let mut d = Dsh::new("/w/proj", None);
        let ev = run(&mut d, &real("dsh-4-no-key.jsonl"));
        let end = of(&ev, "turn.end");
        assert_eq!(end.len(), 1);
        assert_eq!(s(end[0], "outcome"), "error");
        assert!(s(end[0], "error").starts_with("DeepSeek Harness has no key"), "{}", s(end[0], "error"));
        assert!(of(&ev, "message").is_empty());
        // the exit after `final` adds nothing
        assert!(d.finish(Some(1), "dsh: MISSING_CREDENTIAL: …").is_empty());
    }

    #[test]
    fn an_error_event_or_a_silent_exit_ends_the_turn_once() {
        let mut d = Dsh::new("/w/proj", None);
        d.begin();
        let ev = d.on_line(r#"{"type":"error","message":"session \"session-00000000-0000-4000-8000-000000000000\" does not exist; omit --session-id to start a new Session"}"#);
        assert_eq!(s(&ev[0], "outcome"), "error");
        assert!(s(&ev[0], "error").contains("does not exist"));
        assert!(d.finish(Some(1), "x").is_empty());
        // a run that died without writing anything ends with its stderr
        d.begin();
        let ev = d.finish(Some(1), "dsh: boom");
        assert_eq!((s(&ev[0], "outcome"), s(&ev[0], "error")), ("error".into(), "boom".into()));
        // Stop: the run's end reads as interrupted, however it ended
        d.begin();
        d.interrupt();
        let ev = d.finish(Some(130), "");
        assert_eq!(s(&ev[0], "outcome"), "interrupted");
        d.begin();
        d.interrupt();
        let ev = d.on_line(r#"{"type":"final","text":"","reason":{"kind":"aborted"}}"#);
        assert_eq!(s(&ev[0], "outcome"), "interrupted");
        // garbage and unknown events are ignored
        assert!(d.on_line("not json").is_empty() && d.on_line(r#"{"type":"later"}"#).is_empty());
    }

    #[test]
    fn pictures_are_named_in_the_message() {
        assert_eq!(with_pictures("look", &[]), "look");
        let p = Picture::from("/h/.omher/sessions/s1/shot.png".to_string());
        assert_eq!(with_pictures("look", &[p.clone()]), "look\n\nAttached file (a copy omher saved; open it with your tools):\n- /h/.omher/sessions/s1/shot.png");
        assert!(with_pictures("", &[p.clone(), p]).starts_with("Attached files (copies omher saved; open them with your tools):\n- "));
    }

    #[test]
    fn the_overlay_is_fixed_text_and_never_written_through_a_link() {
        let dir = std::env::temp_dir().join(format!("omher-dsh-patch-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let p = dsh_patch_path(&dir);
        assert!(p.ends_with(Path::new(".omher").join("dsh").join("headless.patch.yml")));
        write_patch(&p).unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), DSH_HEADLESS_PATCH);
        std::fs::write(&p, "- id: something-else\n").unwrap();
        write_patch(&p).unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), DSH_HEADLESS_PATCH);
        // only the three credential rows, each turned on; nothing that loads code or widens the sandbox
        let ids: Vec<&str> = DSH_HEADLESS_PATCH.lines().filter_map(|l| l.strip_prefix("- id: ")).collect();
        assert_eq!(ids, ["credentials", "authorization", "deepseek-account"]);
        assert_eq!(DSH_HEADLESS_PATCH.matches("disabled: false").count(), 3);
        for bad in ["name:", "!!js", "insert", "sandbox", "config"] {
            assert!(!DSH_HEADLESS_PATCH.contains(bad), "{bad}");
        }
        #[cfg(unix)]
        {
            let link = dir.join("link.yml");
            std::os::unix::fs::symlink(dir.join("elsewhere.yml"), &link).unwrap();
            assert!(write_patch(&link).is_err());
            assert!(!dir.join("elsewhere.yml").exists());
        }
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn inputs_other_than_send_and_stop_are_refused() {
        let tmp = std::env::temp_dir().canonicalize().unwrap();
        // a stand-in chat (no harness needed): the launch argv is never run by these inputs
        let chat = DshChat(Arc::new(Inner {
            cwd: tmp.clone(),
            patch: tmp.join("p.yml"),
            launch: vec!["/nonexistent".into()],
            path_env: OsString::new(),
            state: Mutex::new(Dsh::new("/w", None)),
            sink: Arc::new(Mutex::new(Box::new(|_| {}))),
            run: Mutex::new(None),
        }));
        assert!(chat.input(Input::Interrupt).is_err());
        assert!(chat.input(Input::Approve { request_id: "a".into(), choice: "once".into() }).is_err());
        assert!(chat.input(Input::Clarify { request_id: "a".into(), answer: Value::Null }).is_err());
        assert!(chat.input(Input::Model { model: "x".into() }).is_err());
        assert!(!chat.0.run.lock().unwrap().is_some());
        // a resume that is not a harness session id is refused before anything else
        assert!(DshChat::start(&tmp, Some("eee5079a-c52e-4526-b633-f3d8cb7d6394"), |_| {}).is_err());
        assert!(DshChat::start(&tmp, Some("session-x --yolo"), |_| {}).is_err());
    }

    /// A stand-in harness on pipes: reads the message from stdin, prints a recorded run, and the chat shows it;
    /// the next message carries the session id the first one reported.
    #[cfg(unix)]
    #[test]
    fn a_stand_in_harness_runs_one_process_per_message() {
        let tmp = std::env::temp_dir().canonicalize().unwrap().join(format!("omher-dsh-run-{}", std::process::id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let fx = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join("real");
        let script = tmp.join("dsh");
        // logs its argv and stdin, then replays the first or the second recorded run
        std::fs::write(
            &script,
            format!(
                "#!/bin/sh\necho \"$@\" >> '{log}'\ncat >> '{log}'\necho >> '{log}'\ncase \"$*\" in *--session-id*) cat '{b}';; *) cat '{a}';; esac\n",
                log = tmp.join("log").display(),
                a = fx.join("dsh-1-first.jsonl").display(),
                b = fx.join("dsh-2-second.jsonl").display()
            ),
        )
        .unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        let out = Arc::new(Mutex::new(Vec::<Event>::new()));
        let o = out.clone();
        let chat = DshChat(Arc::new(Inner {
            cwd: tmp.clone(),
            patch: tmp.join(".omher").join("dsh").join("headless.patch.yml"),
            launch: vec![script.clone().into()],
            path_env: std::env::var_os("PATH").unwrap_or_default(),
            state: Mutex::new(Dsh::new(&tmp.to_string_lossy(), None)),
            sink: Arc::new(Mutex::new(Box::new(move |x| {
                if let ChatOut::Event(e) = x {
                    o.lock().unwrap().push(e)
                }
            }))),
            run: Mutex::new(None),
        }));
        let ends = || out.lock().unwrap().iter().filter(|e| s(e, "event") == "turn.end").count();
        let wait = |n: usize| {
            let deadline = Instant::now() + Duration::from_secs(10);
            while ends() < n && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(20));
            }
            ends() == n
        };
        chat.input(Input::Send { text: "first message".into(), images: vec![] }).unwrap();
        assert!(wait(1));
        let deadline = Instant::now() + Duration::from_secs(5);
        while chat.0.run.lock().unwrap().is_some() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
        }
        chat.input(Input::Send { text: "second message".into(), images: vec![] }).unwrap();
        assert!(wait(2));
        let log = std::fs::read_to_string(tmp.join("log")).unwrap();
        let lines: Vec<&str> = log.lines().collect();
        let patch = tmp.join(".omher").join("dsh").join("headless.patch.yml");
        assert_eq!(lines[0], format!("--profile headless --patch {} --json -", patch.display()));
        assert_eq!(lines[1], "first message");
        let sid = out.lock().unwrap().iter().find(|e| s(e, "event") == "session.info").map(|e| s(e, "agent_session")).unwrap();
        assert_eq!(lines[2], format!("--profile headless --patch {} --json --session-id {sid} -", patch.display()));
        assert_eq!(lines[3], "second message");
        assert_eq!(std::fs::read_to_string(patch).unwrap(), DSH_HEADLESS_PATCH);
        let _ = std::fs::remove_dir_all(tmp);
    }
}

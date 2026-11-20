//! What a bot may know of a TERMINALS session it holds a link to, and how it asks to type into one.
//!
//! While a TERMINALS session is listed, omher keeps one small status file for it:
//! `<home>/.omher/terminals/<link id>.json`, owner-only (0600), in an owner-only folder (0700). It holds the session's
//! title, its CLI, its folder (`~`-relative), its state (working, waiting, done, ended), when it started, the last line
//! it printed (one line, at most [`LINE_MAX`] characters, the row's second line) and when the file was written. Nothing
//! else of the terminal is written there. The file goes when the session is closed, the files of sessions no longer
//! listed go when omher starts, and every one goes when omher quits.
//!
//! Next to it sits the session's inbox, `<link id>.inbox/` (0700), made with the status file. A bot (the OMH tool
//! `omh_omher_terminal`) asks to type a prompt by putting one JSON file there: `{"prompt", "from", "session"}`.
//! omher reads an inbox file only when it is a plain file (never a link: it is opened without following one), owned by
//! the user omher runs as, readable and writable by that user only (0600) and at most [`REQUEST_MAX`] bytes. Every
//! file it looks at is removed, taken or refused. The prompt comes back with control characters taken out (a newline
//! stays). Nothing here types anything: the page shows the request as a card, and only the person's Allow types it.
//!
//! Sharing is off on Windows ([`ENABLED`]): the owner-only folder, file mode, no-follow open and owner check above are
//! POSIX, and Windows would leave the files to inherited permissions. There no status file or inbox is made and no
//! inbox is read; Copy link and the link chip still work.

use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

/// Characters kept of the last printed line.
pub const LINE_MAX: usize = 200;
/// Characters kept of the title.
pub const TITLE_MAX: usize = 120;
/// Bytes an inbox file may have.
pub const REQUEST_MAX: u64 = 16 * 1024;
/// Characters kept of the asking bot's name.
pub const FROM_MAX: usize = 64;
/// Inbox files looked at per call (the rest wait for the next look).
pub const TAKE_MAX: usize = 16;
/// The states a status file may say.
pub const STATES: [&str; 4] = ["working", "waiting", "done", "ended"];

/// Whether status files and inboxes are kept on this system (off on Windows, where the owner-only checks cannot hold).
pub const ENABLED: bool = cfg!(not(windows));

/// `<home>/.omher/terminals`.
pub fn root(home: &Path) -> PathBuf {
    home.join(".omher").join("terminals")
}

/// A link id: 10 characters of lowercase base32 (term_link.rs takes links the same way).
pub fn valid_id(id: &str) -> bool {
    id.len() == 10 && id.bytes().all(|b| b.is_ascii_lowercase() || (b'2'..=b'7').contains(&b))
}

/// What the page knows of a session (it reads its own list and terminal).
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub title: String,
    pub agent: String,
    pub cwd: String,
    pub state: String,
    /// ms since the epoch
    pub started: f64,
    #[serde(default)]
    pub last_line: String,
}

/// The status file as written.
#[derive(Debug, Serialize, Deserialize, PartialEq)]
pub struct StatusFile {
    pub link: String,
    pub title: String,
    pub agent: String,
    pub folder: String,
    pub state: String,
    /// seconds since the epoch
    pub started: u64,
    pub last_line: String,
    /// seconds since the epoch
    pub updated_at: u64,
}

/// A bot's request, as the page gets it.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Request {
    /// the inbox file's name without `.json`
    pub id: String,
    pub link: String,
    pub prompt: String,
    pub from: String,
    pub session: String,
}

fn now_s() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// Control characters out (C0, DEL, C1), a newline kept.
pub fn clean_prompt(s: &str) -> String {
    s.chars().filter(|&c| c == '\n' || !c.is_control()).collect()
}

/// One line: control characters and runs of white space made one space, trimmed, at most `max` characters.
pub fn one_line(s: &str, max: usize) -> String {
    let flat: String = s.chars().map(|c| if c.is_control() || c.is_whitespace() { ' ' } else { c }).collect();
    let flat = flat.split(' ').filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= max {
        return flat;
    }
    let mut out: String = flat.chars().take(max - 1).collect();
    out.push('…');
    out
}

/// `cwd` relative to `home` (`~`, `~/code/x`), else as it is.
pub fn tilde(cwd: &str, home: &Path) -> String {
    let h = home.to_string_lossy();
    let h = h.trim_end_matches(['/', '\\']);
    if h.is_empty() {
        return cwd.to_string();
    }
    if cwd == h {
        return "~".into();
    }
    match cwd.strip_prefix(h) {
        Some(rest) if rest.starts_with('/') || rest.starts_with('\\') => format!("~{rest}"),
        _ => cwd.to_string(),
    }
}

/// Refuse a link anywhere on the way (`.omher`, `terminals`, and `more`).
fn no_links(home: &Path, more: &[&Path]) -> Result<(), String> {
    for p in [home.join(".omher"), root(home)].iter().map(PathBuf::as_path).chain(more.iter().copied()) {
        if p.is_symlink() {
            return Err(format!("{} is a link", p.display()));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn owner_only_dir(p: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(p, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())
}
#[cfg(not(unix))]
fn owner_only_dir(_p: &Path) -> Result<(), String> {
    Ok(())
}

fn file_of(home: &Path, id: &str) -> Result<PathBuf, String> {
    if !valid_id(id) {
        return Err("bad link id".into());
    }
    Ok(root(home).join(format!("{id}.json")))
}

fn inbox_of(home: &Path, id: &str) -> PathBuf {
    root(home).join(format!("{id}.inbox"))
}

/// The file for session `id` as `write` makes it (a pure step, for tests).
pub fn status_file(id: &str, s: &Status, home: &Path, now: u64) -> Result<StatusFile, String> {
    if !valid_id(id) {
        return Err("bad link id".into());
    }
    if !STATES.contains(&s.state.as_str()) {
        return Err("bad state".into());
    }
    let started = if s.started.is_finite() && s.started > 0.0 { (s.started / 1000.0) as u64 } else { 0 };
    Ok(StatusFile {
        link: format!("omher://terminal/{id}"),
        title: one_line(&s.title, TITLE_MAX),
        agent: one_line(&s.agent, 40),
        folder: one_line(&tilde(&s.cwd, home), 400),
        state: s.state.clone(),
        started,
        last_line: one_line(&s.last_line, LINE_MAX),
        updated_at: now,
    })
}

/// Write session `id`'s status file (owner-only, replacing the last one) and make its inbox.
pub fn write(home: &Path, id: &str, s: &Status) -> Result<(), String> {
    let file = file_of(home, id)?;
    if !ENABLED {
        return Ok(()); // nothing is kept for bots on this system
    }
    let body = serde_json::to_vec_pretty(&status_file(id, s, home, now_s())?).map_err(|e| e.to_string())?;
    let inbox = inbox_of(home, id);
    no_links(home, &[&file, &inbox])?;
    fs::create_dir_all(root(home)).map_err(|e| e.to_string())?;
    owner_only_dir(&root(home))?;
    no_links(home, &[&file, &inbox])?;
    if !inbox.is_dir() {
        fs::create_dir(&inbox).map_err(|e| e.to_string())?;
    }
    owner_only_dir(&inbox)?;
    let tmp = root(home).join(format!(".{id}.tmp"));
    if tmp.is_symlink() {
        return Err(format!("{} is a link", tmp.display()));
    }
    let _ = fs::remove_file(&tmp);
    let mut o = fs::OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut o, 0o600);
    let mut f = o.open(&tmp).map_err(|e| e.to_string())?;
    f.write_all(&body).map_err(|e| e.to_string())?;
    drop(f);
    fs::rename(&tmp, &file).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        e.to_string()
    })
}

/// Remove session `id`'s status file and its inbox (the session was closed).
pub fn remove(home: &Path, id: &str) -> Result<(), String> {
    let file = file_of(home, id)?;
    no_links(home, &[])?;
    match fs::remove_file(&file) {
        Err(e) if e.kind() != std::io::ErrorKind::NotFound => return Err(e.to_string()),
        _ => {}
    }
    let inbox = inbox_of(home, id);
    if inbox.is_symlink() {
        return fs::remove_file(&inbox).map_err(|e| e.to_string());
    }
    match fs::remove_dir_all(&inbox) {
        Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
        _ => Ok(()),
    }
}

/// Remove the files of every session not in `keep` (omher started, or quits with `keep` empty). Only names made of a
/// valid link id are touched.
pub fn prune(home: &Path, keep: &[String]) -> Result<(), String> {
    let root = root(home);
    if no_links(home, &[]).is_err() || !root.is_dir() {
        return Ok(());
    }
    for e in fs::read_dir(&root).map_err(|e| e.to_string())?.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        let id = name.strip_suffix(".json").or_else(|| name.strip_suffix(".inbox"));
        if let Some(id) = id {
            if valid_id(id) && !keep.iter().any(|k| k == id) {
                remove(home, id)?;
            }
        }
    }
    Ok(())
}

/// Why an inbox file was refused (tests read it; the page never sees refused files).
#[derive(Debug, PartialEq)]
pub enum Refused {
    Link,
    NotFile,
    NotOwner,
    Mode,
    TooBig,
    NotJson,
    NoPrompt,
}

#[cfg(unix)]
fn my_uid() -> u32 {
    // SAFETY: geteuid has no preconditions and cannot fail.
    unsafe { libc::geteuid() }
}

/// Open inbox file `p` without following a link and check it is the user's own owner-only plain file, small enough.
fn open_checked(p: &Path) -> Result<fs::File, Refused> {
    let meta = fs::symlink_metadata(p).map_err(|_| Refused::NotFile)?;
    if meta.file_type().is_symlink() {
        return Err(Refused::Link);
    }
    let mut o = fs::OpenOptions::new();
    o.read(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::custom_flags(&mut o, libc::O_NOFOLLOW | libc::O_NONBLOCK);
    let f = o.open(p).map_err(|_| Refused::Link)?;
    // what was opened, not the name: a file swapped after the first look is judged as it is
    let meta = f.metadata().map_err(|_| Refused::NotFile)?;
    if !meta.is_file() {
        return Err(Refused::NotFile);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if meta.uid() != my_uid() {
            return Err(Refused::NotOwner);
        }
        if meta.mode() & 0o7777 != 0o600 {
            return Err(Refused::Mode);
        }
    }
    if meta.len() > REQUEST_MAX {
        return Err(Refused::TooBig);
    }
    Ok(f)
}

/// Read one inbox file into a request, or say why not.
pub fn read_request(link: &str, p: &Path) -> Result<Request, Refused> {
    let f = open_checked(p)?;
    let mut buf = Vec::new();
    f.take(REQUEST_MAX + 1).read_to_end(&mut buf).map_err(|_| Refused::NotFile)?;
    if buf.len() as u64 > REQUEST_MAX {
        return Err(Refused::TooBig);
    }
    let v: serde_json::Value = serde_json::from_slice(&buf).map_err(|_| Refused::NotJson)?;
    let field = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    let prompt = clean_prompt(&field("prompt"));
    if prompt.trim().is_empty() {
        return Err(Refused::NoPrompt);
    }
    let from = one_line(&field("from"), FROM_MAX);
    let id = p.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    Ok(Request { id, link: link.to_string(), prompt, from, session: one_line(&field("session"), 120) })
}

/// The inbox folder of `id` when it is the user's own plain folder.
fn inbox_ok(home: &Path, id: &str) -> Option<PathBuf> {
    let inbox = inbox_of(home, id);
    no_links(home, &[&inbox]).ok()?;
    let meta = fs::symlink_metadata(&inbox).ok()?;
    if !meta.is_dir() {
        return None;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if meta.uid() != my_uid() {
            return None;
        }
    }
    Some(inbox)
}

/// Take what waits in the inboxes of `links` (link ids): each request file is removed, taken or refused. Names
/// starting with a dot (a file the tool is still writing) and other names are left alone. At most [`TAKE_MAX`] files
/// per call. Returns the requests and, for tests, what was refused.
pub fn take(home: &Path, links: &[String]) -> (Vec<Request>, Vec<(String, Refused)>) {
    let mut got = Vec::new();
    let mut refused = Vec::new();
    if !ENABLED {
        return (got, refused); // no inbox is read on this system
    }
    let mut looked = 0;
    for id in links.iter().filter(|id| valid_id(id)) {
        let Some(inbox) = inbox_ok(home, id) else { continue };
        let Ok(rd) = fs::read_dir(&inbox) else { continue };
        let mut names: Vec<String> = rd.flatten().map(|e| e.file_name().to_string_lossy().into_owned()).filter(|n| !n.starts_with('.') && n.ends_with(".json")).collect();
        names.sort();
        for name in names {
            if looked >= TAKE_MAX {
                return (got, refused);
            }
            looked += 1;
            let p = inbox.join(&name);
            let r = read_request(id, &p);
            // removed whatever it was: a link goes, never what it points at
            let _ = fs::remove_file(&p);
            match r {
                Ok(req) => got.push(req),
                Err(why) => refused.push((name, why)),
            }
        }
    }
    (got, refused)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sharing_is_off_on_windows_only() {
        assert_eq!(ENABLED, !cfg!(windows));
    }

    /// Windows: no status file, no inbox, and an inbox file someone put there is never read.
    #[cfg(windows)]
    #[test]
    fn windows_keeps_and_reads_nothing() {
        let h = home("off");
        write(&h, "abcdefgh23", &st(&h)).unwrap();
        assert!(!root(&h).exists());
        let inbox = root(&h).join("abcdefgh23.inbox");
        fs::create_dir_all(&inbox).unwrap();
        fs::write(inbox.join("1.json"), br#"{"prompt":"x","from":"b","session":""}"#).unwrap();
        let (got, refused) = take(&h, &["abcdefgh23".into()]);
        assert!(got.is_empty() && refused.is_empty());
        assert!(inbox.join("1.json").exists());
    }

    fn home(tag: &str) -> PathBuf {
        let h = std::env::temp_dir().join(format!("omher-term-share-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&h);
        fs::create_dir_all(&h).unwrap();
        h.canonicalize().unwrap()
    }

    fn st(home: &Path) -> Status {
        Status {
            title: "fix\tthe\nlogin  redirect".into(),
            agent: "claude".into(),
            cwd: format!("{}/code/web-app", home.display()),
            state: "working".into(),
            started: 1_700_000_000_000.0,
            last_line: format!("Running tests\x1b[0m {}", "x".repeat(400)),
        }
    }

    #[cfg(unix)]
    fn put(dir: &Path, name: &str, body: &str, mode: u32) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let p = dir.join(name);
        fs::write(&p, body).unwrap();
        fs::set_permissions(&p, fs::Permissions::from_mode(mode)).unwrap();
        p
    }

    // sharing is off on Windows (`ENABLED`); `windows_keeps_and_reads_nothing` covers it there
    #[cfg(not(windows))]
    #[test]
    fn writes_only_the_listed_fields_owner_only_and_removes_them() {
        let h = home("write");
        write(&h, "abcdefgh23", &st(&h)).unwrap();
        let f = root(&h).join("abcdefgh23.json");
        let got: serde_json::Value = serde_json::from_slice(&fs::read(&f).unwrap()).unwrap();
        let mut keys: Vec<&str> = got.as_object().unwrap().keys().map(String::as_str).collect();
        keys.sort();
        assert_eq!(keys, ["agent", "folder", "last_line", "link", "started", "state", "title", "updated_at"]);
        assert_eq!(got["link"], "omher://terminal/abcdefgh23");
        assert_eq!(got["title"], "fix the login redirect");
        assert_eq!(got["folder"], "~/code/web-app");
        assert_eq!(got["started"], 1_700_000_000);
        let line = got["last_line"].as_str().unwrap();
        assert_eq!(line.chars().count(), LINE_MAX);
        assert!(!line.contains('\x1b') && line.starts_with("Running tests [0m x"), "{line}");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&f).unwrap().permissions().mode() & 0o777, 0o600);
            assert_eq!(fs::metadata(root(&h)).unwrap().permissions().mode() & 0o777, 0o700);
            assert_eq!(fs::metadata(root(&h).join("abcdefgh23.inbox")).unwrap().permissions().mode() & 0o777, 0o700);
        }
        // no temp file left, nothing else in the folder
        let mut names: Vec<String> = fs::read_dir(root(&h)).unwrap().flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["abcdefgh23.inbox", "abcdefgh23.json"]);
        remove(&h, "abcdefgh23").unwrap();
        remove(&h, "abcdefgh23").unwrap();
        assert_eq!(fs::read_dir(root(&h)).unwrap().count(), 0);
        let _ = fs::remove_dir_all(&h);
    }

    // sharing is off on Windows (`ENABLED`); `windows_keeps_and_reads_nothing` covers it there
    #[cfg(not(windows))]
    #[test]
    fn refuses_bad_ids_states_and_links_on_the_way() {
        let h = home("bad");
        for bad in ["", "abc", "ABCDEFGH23", "abcdefgh01", "../abcdefg", "abcdefgh2/", "abcdefgh234"] {
            assert!(write(&h, bad, &st(&h)).is_err(), "{bad}");
            assert!(remove(&h, bad).is_err(), "{bad}");
        }
        let mut s = st(&h);
        s.state = "running".into();
        assert!(write(&h, "abcdefgh23", &s).is_err());
        #[cfg(unix)]
        {
            let elsewhere = h.join("elsewhere");
            fs::create_dir_all(&elsewhere).unwrap();
            fs::create_dir_all(h.join(".omher")).unwrap();
            std::os::unix::fs::symlink(&elsewhere, root(&h)).unwrap();
            assert!(write(&h, "abcdefgh23", &st(&h)).is_err());
            assert_eq!(fs::read_dir(&elsewhere).unwrap().count(), 0);
        }
        let _ = fs::remove_dir_all(&h);
    }

    // sharing is off on Windows (`ENABLED`); `windows_keeps_and_reads_nothing` covers it there
    #[cfg(not(windows))]
    #[test]
    fn prune_keeps_listed_sessions_and_other_files() {
        let h = home("prune");
        for id in ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc"] {
            write(&h, id, &st(&h)).unwrap();
        }
        fs::write(root(&h).join("notes.md"), "keep").unwrap();
        prune(&h, &["bbbbbbbbbb".into()]).unwrap();
        let mut names: Vec<String> = fs::read_dir(root(&h)).unwrap().flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["bbbbbbbbbb.inbox", "bbbbbbbbbb.json", "notes.md"]);
        prune(&h, &[]).unwrap();
        assert_eq!(fs::read_dir(root(&h)).unwrap().count(), 1);
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn strips_control_characters_but_keeps_newlines() {
        assert_eq!(clean_prompt("run\x1b[31m tests\r\nnow\x07\x7f\u{9b}2J\tok"), "run[31m tests\nnow2Jok");
        assert_eq!(one_line("  a\n\tb  c ", 10), "a b c");
        assert_eq!(tilde("/home/u", Path::new("/home/u")), "~");
        assert_eq!(tilde("/home/u/x", Path::new("/home/u/")), "~/x");
        assert_eq!(tilde("/home/user2/x", Path::new("/home/u")), "/home/user2/x");
    }

    #[cfg(unix)]
    #[test]
    fn takes_only_the_users_own_small_owner_only_plain_files_and_removes_every_one() {
        let h = home("take");
        write(&h, "abcdefgh23", &st(&h)).unwrap();
        let inbox = root(&h).join("abcdefgh23.inbox");
        let ok = r#"{"prompt": "run the tests\u001b[2J\nthen stop", "from": "Kami", "session": "s-1"}"#;
        put(&inbox, "1.json", ok, 0o600);
        put(&inbox, "2.json", ok, 0o644);
        put(&inbox, "3.json", ok, 0o640);
        put(&inbox, "4.json", &format!(r#"{{"prompt": "{}", "from": "x"}}"#, "a".repeat(REQUEST_MAX as usize)), 0o600);
        put(&inbox, "5.json", "not json", 0o600);
        put(&inbox, "6.json", r#"{"prompt": "\u0007\u001b", "from": "x"}"#, 0o600);
        let target = put(&h, "target.json", ok, 0o600);
        std::os::unix::fs::symlink(&target, inbox.join("7.json")).unwrap();
        fs::create_dir(inbox.join("8.json")).unwrap();
        put(&inbox, ".9.tmp", ok, 0o600);
        put(&inbox, "notes.txt", ok, 0o600);
        let (got, refused) = take(&h, &["abcdefgh23".into(), "../escape0".into()]);
        assert_eq!(got, vec![Request { id: "1".into(), link: "abcdefgh23".into(), prompt: "run the tests[2J\nthen stop".into(), from: "Kami".into(), session: "s-1".into() }]);
        let why: Vec<(&str, &Refused)> = refused.iter().map(|(n, w)| (n.as_str(), w)).collect();
        assert_eq!(
            why,
            vec![("2.json", &Refused::Mode), ("3.json", &Refused::Mode), ("4.json", &Refused::TooBig), ("5.json", &Refused::NotJson), ("6.json", &Refused::NoPrompt), ("7.json", &Refused::Link), ("8.json", &Refused::NotFile)]
        );
        // every file looked at is gone (the link, not its target); a file being written and other names stay
        let mut left: Vec<String> = fs::read_dir(&inbox).unwrap().flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect();
        left.sort();
        assert_eq!(left, [".9.tmp", "8.json", "notes.txt"]);
        assert!(target.exists());
        assert!(take(&h, &["abcdefgh23".into()]).0.is_empty());
        let _ = fs::remove_dir_all(&h);
    }

    #[cfg(unix)]
    #[test]
    fn a_linked_inbox_or_one_of_another_user_is_not_read() {
        let h = home("inboxlink");
        write(&h, "abcdefgh23", &st(&h)).unwrap();
        let inbox = root(&h).join("abcdefgh23.inbox");
        fs::remove_dir(&inbox).unwrap();
        let other = h.join("other");
        fs::create_dir(&other).unwrap();
        put(&other, "1.json", r#"{"prompt": "x", "from": "y"}"#, 0o600);
        std::os::unix::fs::symlink(&other, &inbox).unwrap();
        let (got, refused) = take(&h, &["abcdefgh23".into()]);
        assert!(got.is_empty() && refused.is_empty());
        assert!(other.join("1.json").exists());
        let _ = fs::remove_dir_all(&h);
    }

    #[cfg(unix)]
    #[test]
    fn a_file_not_owned_by_the_user_is_refused() {
        // root may own anything here; anyone else cannot chown, so check the owner test through a file root owns
        let p = Path::new("/etc/hosts");
        if my_uid() != 0 && p.exists() {
            assert!(matches!(read_request("abcdefgh23", p), Err(Refused::NotOwner) | Err(Refused::Mode)));
            use std::os::unix::fs::MetadataExt;
            assert_ne!(fs::metadata(p).unwrap().uid(), my_uid());
            assert_eq!(open_checked(p).err(), Some(Refused::NotOwner));
        }
    }

    // sharing is off on Windows (`ENABLED`); `windows_keeps_and_reads_nothing` covers it there
    #[cfg(not(windows))]
    #[test]
    fn takes_at_most_a_few_files_per_look() {
        let h = home("many");
        write(&h, "abcdefgh23", &st(&h)).unwrap();
        let inbox = root(&h).join("abcdefgh23.inbox");
        for i in 0..TAKE_MAX + 4 {
            let p = inbox.join(format!("{i:03}.json"));
            let mut o = fs::OpenOptions::new();
            o.write(true).create_new(true);
            #[cfg(unix)]
            std::os::unix::fs::OpenOptionsExt::mode(&mut o, 0o600);
            o.open(&p).unwrap().write_all(br#"{"prompt": "p", "from": "b"}"#).unwrap();
        }
        assert_eq!(take(&h, &["abcdefgh23".into()]).0.len(), TAKE_MAX);
        assert_eq!(take(&h, &["abcdefgh23".into()]).0.len(), 4);
        let _ = fs::remove_dir_all(&h);
    }
}

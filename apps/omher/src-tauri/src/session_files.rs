//! Files the person attaches in a SESSIONS chat (or drops on its terminal). Each is saved under omher's own
//! folder, one folder per session: `<home>/.omher/session-files/<session id>/`, never in the project folder and
//! never in a Hermes profile. The agent then gets a picture as its own image input where it has one (the shell
//! reads the saved copy back for it), and any other file named by the saved copy's absolute path. A session's
//! folder is removed when the session is closed; folders of sessions that are no longer in the list are removed
//! when omher starts.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

/// The bot chat's limit for one file (`att.tooBig`), checked again here.
pub const MAX_BYTES: usize = 100 * 1024 * 1024;
/// Pictures up to this size go in as the agent's own image input; a bigger one is named by its path (the agents'
/// image inputs refuse very large pictures; their own file tools scale them).
pub const INLINE_MAX: u64 = 5 * 1024 * 1024;

/// `<home>/.omher/session-files`.
pub fn root(home: &Path) -> PathBuf {
    home.join(".omher").join("session-files")
}

/// A SESSIONS id as the UI makes it (`s` and up to nine digits), so it is always one plain folder name.
pub fn valid_session(id: &str) -> bool {
    let b = id.as_bytes();
    b.len() >= 2 && b.len() <= 10 && b[0] == b's' && b[1..].iter().all(u8::is_ascii_digit)
}

/// The file name to save under: the last path part of `name`, without control characters or the characters
/// a file name cannot hold on any of the three systems, at most 120 characters, never hidden; `file` if
/// nothing is left.
pub fn safe_name(name: &str) -> String {
    let last = name.rsplit(['/', '\\']).next().unwrap_or("");
    let cleaned: String = last
        .chars()
        .filter(|c| !c.is_control())
        .map(|c| if matches!(c, ':' | '*' | '?' | '"' | '<' | '>' | '|') { '_' } else { c })
        .take(120)
        .collect();
    let trimmed = cleaned.trim().trim_start_matches('.').trim();
    if trimmed.is_empty() {
        "file".into()
    } else {
        trimmed.into()
    }
}

/// The folder a session's files go in, made when missing. Refuses a symlinked root or session folder. A Claude Code
/// chat gets this one folder as its `--add-dir` (made before the chat starts, so its copies read without a card).
pub fn session_dir(home: &Path, session: &str) -> Result<PathBuf, String> {
    if !valid_session(session) {
        return Err("bad session id".into());
    }
    let root = root(home);
    for d in [home.join(".omher"), root.clone(), root.join(session)] {
        if d.is_symlink() {
            return Err(format!("{} is a link", d.display()));
        }
    }
    let dir = root.join(session);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}

/// Save one attached file for `session` and return the saved copy's absolute path. Never overwrites: each
/// copy is `<n>-<name>` with the next free `n`.
pub fn save(home: &Path, session: &str, name: &str, data: &[u8]) -> Result<PathBuf, String> {
    if data.len() > MAX_BYTES {
        return Err("over 100 MB".into());
    }
    let dir = session_dir(home, session)?;
    let name = safe_name(name);
    for n in 1..10_000u32 {
        let path = dir.join(format!("{n}-{name}"));
        match fs::OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut f) => {
                f.write_all(data).map_err(|e| e.to_string())?;
                return Ok(path);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("too many files in this session".into())
}

/// Remove a session's saved files (the session was closed).
pub fn remove(home: &Path, session: &str) -> Result<(), String> {
    if !valid_session(session) {
        return Err("bad session id".into());
    }
    let dir = root(home).join(session);
    if dir.is_symlink() {
        return fs::remove_file(&dir).map_err(|e| e.to_string());
    }
    match fs::remove_dir_all(&dir) {
        Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
        _ => Ok(()),
    }
}

/// Remove the folders of every session not in `keep` (omher started: those sessions are gone).
pub fn prune(home: &Path, keep: &[String]) -> Result<(), String> {
    let root = root(home);
    if root.is_symlink() || !root.is_dir() {
        return Ok(());
    }
    for e in fs::read_dir(&root).map_err(|e| e.to_string())?.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        if valid_session(&name) && !keep.iter().any(|k| k == &name) {
            remove(home, &name)?;
        }
    }
    Ok(())
}

/// `path` when it is a plain file omher saved for a session (under [`root`], no link on the way), else an error.
/// The chat's input names files by path; nothing else is read back.
pub fn check(home: &Path, path: &str) -> Result<PathBuf, String> {
    let p = PathBuf::from(path);
    let refuse = || format!("not a file omher saved: {path}");
    if !p.is_absolute() || p.is_symlink() || !p.is_file() {
        return Err(refuse());
    }
    let real = p.canonicalize().map_err(|_| refuse())?;
    let root = root(home).canonicalize().map_err(|_| refuse())?;
    let rel = real.strip_prefix(&root).map_err(|_| refuse())?;
    let parts: Vec<_> = rel.components().collect();
    if parts.len() != 2 || !valid_session(&parts[0].as_os_str().to_string_lossy()) {
        return Err(refuse());
    }
    Ok(real)
}

/// The picture type an agent's image input takes for this file name, by its extension: PNG, JPEG, GIF, WebP.
pub fn image_mime(name: &str) -> Option<&'static str> {
    let ext = name.rsplit_once('.')?.1.to_ascii_lowercase();
    match ext.as_str() {
        "png" => Some("image/png"),
        "jpg" | "jpeg" => Some("image/jpeg"),
        "gif" => Some("image/gif"),
        "webp" => Some("image/webp"),
        _ => None,
    }
}

/// Standard base64 with padding (an agent's inline picture).
pub fn base64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let n = (u32::from(c[0]) << 16) | (u32::from(*c.get(1).unwrap_or(&0)) << 8) | u32::from(*c.get(2).unwrap_or(&0));
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}

/// `%XX` decoding of a header value (the UI sends the file name with `encodeURIComponent`).
pub fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Some(v) = std::str::from_utf8(&b[i + 1..i + 3]).ok().and_then(|h| u8::from_str_radix(h, 16).ok()) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn home(tag: &str) -> PathBuf {
        let h = std::env::temp_dir().join(format!("omher-session-files-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&h);
        fs::create_dir_all(&h).unwrap();
        h.canonicalize().unwrap()
    }

    #[test]
    fn saves_under_the_session_folder_without_overwriting_and_close_removes_it() {
        let h = home("save");
        let a = save(&h, "s3", "../../etc/passwd", b"one").unwrap();
        let b = save(&h, "s3", "passwd", b"two").unwrap();
        assert_eq!(a, h.join(".omher/session-files/s3/1-passwd"));
        assert_eq!(b, h.join(".omher/session-files/s3/2-passwd"));
        assert_eq!(fs::read(&a).unwrap(), b"one");
        assert_eq!(check(&h, &a.to_string_lossy()).unwrap(), a);
        remove(&h, "s3").unwrap();
        assert!(!h.join(".omher/session-files/s3").exists());
        remove(&h, "s3").unwrap();
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn refuses_bad_session_ids_names_and_paths_outside_the_folder() {
        let h = home("refuse");
        for bad in ["", "s", "../s1", "s1/..", "x1", "s12345678901", "s1 "] {
            assert!(save(&h, bad, "a.txt", b"x").is_err(), "{bad}");
            assert!(remove(&h, bad).is_err(), "{bad}");
        }
        assert_eq!(safe_name("C:\\Users\\me\\.secret"), "secret");
        assert_eq!(safe_name("a\u{0}b:c?.png"), "ab_c_.png");
        assert_eq!(safe_name("..."), "file");
        assert_eq!(safe_name("스크린샷 1.png"), "스크린샷 1.png");
        let outside = h.join("outside.txt");
        fs::write(&outside, b"x").unwrap();
        assert!(check(&h, &outside.to_string_lossy()).is_err());
        let saved = save(&h, "s1", "a.txt", b"x").unwrap();
        assert!(check(&h, &format!("{}/../../outside.txt", saved.parent().unwrap().display())).is_err());
        assert!(check(&h, "relative/a.txt").is_err());
        assert!(save(&h, "s1", "big", &vec![0u8; MAX_BYTES + 1]).is_err());
        #[cfg(unix)]
        {
            let link = h.join(".omher/session-files/s1/9-link.txt");
            std::os::unix::fs::symlink(&outside, &link).unwrap();
            assert!(check(&h, &link.to_string_lossy()).is_err());
            std::os::unix::fs::symlink(&h, h.join(".omher/session-files/s7")).unwrap();
            assert!(save(&h, "s7", "a.txt", b"x").is_err());
        }
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn prune_keeps_only_the_listed_sessions() {
        let h = home("prune");
        save(&h, "s1", "a", b"x").unwrap();
        save(&h, "s2", "a", b"x").unwrap();
        fs::create_dir_all(root(&h).join("other")).unwrap();
        prune(&h, &["s2".into()]).unwrap();
        assert!(!root(&h).join("s1").exists());
        assert!(root(&h).join("s2").exists());
        assert!(root(&h).join("other").exists(), "only session folders are touched");
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn base64_mime_and_percent_decoding() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(&[0xff, 0xfe, 0x00, 0x10]), "//4AEA==");
        assert_eq!(image_mime("a.PNG"), Some("image/png"));
        assert_eq!(image_mime("a.jpeg"), Some("image/jpeg"));
        assert_eq!(image_mime("a.svg"), None);
        assert_eq!(image_mime("png"), None);
        assert_eq!(percent_decode("%EC%8A%A4%ED%81%AC%EB%A6%B0%EC%83%B7%201.png"), "스크린샷 1.png");
        assert_eq!(percent_decode("100%"), "100%");
        assert_eq!(percent_decode("a%2"), "a%2");
    }
}

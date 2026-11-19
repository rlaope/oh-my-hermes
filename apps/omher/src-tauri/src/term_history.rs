//! What a terminal showed, kept across an omher restart. The page serializes each TERMINALS session's and each
//! bottom-panel tab's buffer (`@xterm/addon-serialize`) and hands the text here; it is written only under omher's own
//! folder, one file per terminal: `<home>/.omher/term-history/<key>.txt`, where the key is a SESSIONS id (`s` and
//! digits) or a panel tab (`panel-` and digits), never a path from the page. A file is readable by its owner only
//! (0600), holds at most the last [`MAX_LINES`] lines and [`MAX_BYTES`] bytes, and is never followed through a link.
//! It is removed when its terminal is closed, the files of terminals no longer listed are removed when omher starts,
//! and Settings › Terminal can remove them all at once. Nothing else is written there and nothing else is read.

use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

/// When history was last turned off ([`clear`]), in milliseconds since the epoch; 0 when it was not since omher
/// started. Writes and the clear take this lock, so a write the page sent before the person turned history off, but
/// that arrives after the clear, is refused instead of making the file again.
static CLEARED_AT: Mutex<f64> = Mutex::new(0.0);

fn now_ms() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64() * 1000.0).unwrap_or(0.0)
}

/// Lines kept of one terminal (its newest).
pub const MAX_LINES: usize = 2000;
/// Bytes kept of one terminal (its newest, cut at a line).
pub const MAX_BYTES: usize = 1024 * 1024;

/// `<home>/.omher/term-history`.
pub fn root(home: &Path) -> PathBuf {
    home.join(".omher").join("term-history")
}

/// A key as the page makes it: a SESSIONS id (`s` and 1 to 9 digits) or a panel tab (`panel-` and 1 to 9 digits).
pub fn valid_key(key: &str) -> bool {
    let digits = |d: &str| (1..=9).contains(&d.len()) && d.bytes().all(|b| b.is_ascii_digit());
    key.strip_prefix("panel-").map_or_else(|| key.strip_prefix('s').is_some_and(digits), digits)
}

fn file_of(home: &Path, key: &str) -> Result<PathBuf, String> {
    if !valid_key(key) {
        return Err("bad terminal key".into());
    }
    Ok(root(home).join(format!("{key}.txt")))
}

/// The newest part of `text`: at most [`MAX_LINES`] lines and [`MAX_BYTES`] bytes, starting at a line.
pub fn tail(text: &str) -> &str {
    let mut start = 0;
    if text.len() > MAX_BYTES {
        let mut cut = text.len() - MAX_BYTES;
        while !text.is_char_boundary(cut) {
            cut += 1;
        }
        start = text[cut..].find('\n').map_or(text.len(), |i| cut + i + 1);
    }
    let kept = &text[start..];
    let lines = kept.matches('\n').count() + 1;
    if lines <= MAX_LINES {
        return kept;
    }
    let mut skip = lines - MAX_LINES;
    for (i, b) in kept.bytes().enumerate() {
        if b == b'\n' {
            skip -= 1;
            if skip == 0 {
                return &kept[i + 1..];
            }
        }
    }
    kept
}

/// Refuse a link anywhere on the way (`.omher`, the folder, the file).
fn no_links(home: &Path, file: &Path) -> Result<(), String> {
    for p in [home.join(".omher"), root(home), file.to_path_buf()] {
        if p.is_symlink() {
            return Err(format!("{} is a link", p.display()));
        }
    }
    Ok(())
}

/// Write terminal `key`'s text (its newest part, [`tail`]), replacing what was kept, owner-only. `since` is when
/// history was last turned on in the page that sent it (milliseconds since the epoch): a write from before the last
/// [`clear`] is dropped, writing nothing.
pub fn save(home: &Path, key: &str, text: &str, since: f64) -> Result<(), String> {
    let cleared = CLEARED_AT.lock().unwrap_or_else(|e| e.into_inner());
    if !(since > *cleared) {
        return Ok(());
    }
    let file = file_of(home, key)?;
    no_links(home, &file)?;
    fs::create_dir_all(root(home)).map_err(|e| e.to_string())?;
    no_links(home, &file)?;
    let tmp = root(home).join(format!(".{key}.tmp"));
    if tmp.is_symlink() {
        return Err(format!("{} is a link", tmp.display()));
    }
    let _ = fs::remove_file(&tmp);
    let mut o = fs::OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    std::os::unix::fs::OpenOptionsExt::mode(&mut o, 0o600);
    let mut f = o.open(&tmp).map_err(|e| e.to_string())?;
    f.write_all(tail(text).as_bytes()).map_err(|e| e.to_string())?;
    drop(f);
    fs::rename(&tmp, &file).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        e.to_string()
    })
}

/// Terminal `key`'s kept text and when it was written (seconds since the epoch), or `None`.
pub fn read(home: &Path, key: &str) -> Result<Option<(String, f64)>, String> {
    let file = file_of(home, key)?;
    no_links(home, &file)?;
    let Ok(meta) = fs::symlink_metadata(&file) else { return Ok(None) };
    if !meta.is_file() {
        return Ok(None);
    }
    let at = meta.modified().ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let mut buf = Vec::new();
    fs::File::open(&file).and_then(|f| f.take(MAX_BYTES as u64).read_to_end(&mut buf)).map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&buf).into_owned();
    Ok(Some((tail(&text).to_string(), at)))
}

/// Remove terminal `key`'s file (it was closed).
pub fn remove(home: &Path, key: &str) -> Result<(), String> {
    let file = file_of(home, key)?;
    match fs::remove_file(&file) {
        Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e.to_string()),
        _ => Ok(()),
    }
}

/// Remove the files of every terminal not in `keep` (omher started; the others are gone). Only files named by a
/// valid key are touched.
pub fn prune(home: &Path, keep: &[String]) -> Result<(), String> {
    let root = root(home);
    if root.is_symlink() || !root.is_dir() {
        return Ok(());
    }
    for e in fs::read_dir(&root).map_err(|e| e.to_string())?.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        if let Some(key) = name.strip_suffix(".txt") {
            if valid_key(key) && !keep.iter().any(|k| k == key) {
                remove(home, key)?;
            }
        }
    }
    Ok(())
}

/// Remove every kept terminal (Settings › Terminal turned history off); a write sent before now is refused from here on.
pub fn clear(home: &Path) -> Result<(), String> {
    let mut cleared = CLEARED_AT.lock().unwrap_or_else(|e| e.into_inner());
    *cleared = now_ms().max(*cleared);
    prune(home, &[])
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A page that turned history on long after any clear a test makes (the clear time is process-wide).
    const ON: f64 = f64::MAX;

    fn home(tag: &str) -> PathBuf {
        let h = std::env::temp_dir().join(format!("omher-term-history-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&h);
        fs::create_dir_all(&h).unwrap();
        h.canonicalize().unwrap()
    }

    #[test]
    fn keys_are_session_ids_or_panel_tabs_only() {
        for ok in ["s1", "s123456789", "panel-1", "panel-42"] {
            assert!(valid_key(ok), "{ok}");
        }
        for bad in ["", "s", "s1234567890", "panel-", "panel-x", "x1", "../s1", "s1/..", "s1.txt", "panel-1/../../a", "S1", " s1", "panel-1 "] {
            assert!(valid_key(bad) == false, "{bad}");
        }
    }

    #[test]
    fn saves_owner_only_inside_its_folder_and_reads_back() {
        let h = home("save");
        save(&h, "s3", "one\r\ntwo\r\n", ON).unwrap();
        let f = h.join(".omher/term-history/s3.txt");
        assert_eq!(fs::read_to_string(&f).unwrap(), "one\r\ntwo\r\n");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&f).unwrap().permissions().mode() & 0o777, 0o600);
        }
        save(&h, "s3", "three", ON).unwrap();
        assert_eq!(read(&h, "s3").unwrap().unwrap().0, "three");
        assert!(read(&h, "s4").unwrap().is_none());
        save(&h, "panel-2", "p", ON).unwrap();
        // only <key>.txt files sit in the folder: no temp file is left behind
        let mut names: Vec<String> = fs::read_dir(root(&h)).unwrap().flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["panel-2.txt", "s3.txt"]);
        for bad in ["../s1", "s1/../../x", "/etc/passwd", "panel-../x"] {
            assert!(save(&h, bad, "x", ON).is_err(), "{bad}");
            assert!(read(&h, bad).is_err(), "{bad}");
            assert!(remove(&h, bad).is_err(), "{bad}");
        }
        assert!(!h.join("x.txt").exists() && !h.join(".omher/x.txt").exists());
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn keeps_only_the_newest_lines_and_bytes_cut_at_a_line() {
        let many: String = (0..MAX_LINES + 500).map(|i| format!("line {i}\r\n")).collect();
        let t = tail(&many);
        assert!(t.starts_with("line 501\r\n"), "{}", &t[..20]);
        assert_eq!(t.matches('\n').count() + 1, MAX_LINES);
        let wide = format!("{}\n", "가".repeat(400));
        let big: String = wide.repeat(1000); // 1.2 MB of multi-byte text, 1000 lines
        let t = tail(&big);
        assert!(t.len() <= MAX_BYTES);
        assert!(t.starts_with('가') && t.ends_with('\n'));
        let h = home("cap");
        save(&h, "s1", &big, ON).unwrap();
        assert!(fs::metadata(h.join(".omher/term-history/s1.txt")).unwrap().len() as usize <= MAX_BYTES);
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn close_prune_and_clear_remove_only_terminal_files() {
        let h = home("prune");
        for k in ["s1", "s2", "panel-1", "panel-2"] {
            save(&h, k, "x", ON).unwrap();
        }
        fs::write(root(&h).join("notes.md"), "keep").unwrap();
        remove(&h, "s1").unwrap();
        remove(&h, "s1").unwrap();
        prune(&h, &["s2".into(), "panel-2".into()]).unwrap();
        assert!(!root(&h).join("panel-1.txt").exists());
        assert!(root(&h).join("s2.txt").exists() && root(&h).join("panel-2.txt").exists());
        clear(&h).unwrap();
        assert!(!root(&h).join("s2.txt").exists() && !root(&h).join("panel-2.txt").exists());
        assert!(root(&h).join("notes.md").exists(), "only terminal files are touched");
        let _ = fs::remove_dir_all(&h);
    }

    #[test]
    fn a_write_sent_before_history_was_turned_off_never_makes_the_file_again() {
        let h = home("off");
        let before = now_ms();
        save(&h, "s7", "kept", before).unwrap();
        // the page sent a write while history was on; the person turns it off before it arrives
        std::thread::sleep(std::time::Duration::from_millis(5));
        clear(&h).unwrap();
        save(&h, "s7", "late", before).unwrap();
        assert!(!root(&h).join("s7.txt").exists());
        // turned on again: writes sent from then on are kept
        std::thread::sleep(std::time::Duration::from_millis(5));
        save(&h, "s7", "again", now_ms()).unwrap();
        assert_eq!(read(&h, "s7").unwrap().unwrap().0, "again");
        let _ = fs::remove_dir_all(&h);
    }

    #[cfg(unix)]
    #[test]
    fn refuses_links() {
        let h = home("links");
        let away = h.join("away");
        fs::create_dir_all(&away).unwrap();
        fs::create_dir_all(h.join(".omher")).unwrap();
        std::os::unix::fs::symlink(&away, root(&h)).unwrap();
        assert!(save(&h, "s1", "x", ON).is_err());
        assert!(read(&h, "s1").is_err());
        assert!(!away.join("s1.txt").exists());
        fs::remove_file(root(&h)).unwrap();
        fs::create_dir_all(root(&h)).unwrap();
        let target = away.join("t.txt");
        fs::write(&target, "secret").unwrap();
        std::os::unix::fs::symlink(&target, root(&h).join("s2.txt")).unwrap();
        assert!(save(&h, "s2", "x", ON).is_err());
        assert!(read(&h, "s2").is_err());
        assert_eq!(fs::read_to_string(&target).unwrap(), "secret");
        let _ = fs::remove_dir_all(&h);
    }
}

//! Free space on the volume that holds the home folder, so the page can warn before builds and agents fail on a full
//! disk. One `omher-disk` thread reads ONE filesystem statistic (unix `statfs`/`statvfs`, Windows
//! `GetDiskFreeSpaceExW`) every [`EVERY`]: no file is opened or read, no program runs, nothing is ever deleted.
//! The value is the space available to the user (`df`'s Avail). The page hears [`EVENT`] `{level, free_bytes, volume}`
//! only when the level gets worse (ok -> low, low -> critical, ok -> critical; at startup that is "already low"), and
//! reads the current state through [`disk_watch`], which also hands over Settings › General's warn value.

use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

/// The page's event: the level got worse.
pub const EVENT: &str = "disk-level";
/// How often the free space is read.
const EVERY: Duration = Duration::from_secs(60);
/// Decimal gigabytes, as Finder and Explorer's "GB" (and `df -H`).
const GB: u64 = 1_000_000_000;
/// Critical below this when the warning is at 20 GB or more.
const CRITICAL: u64 = 5 * GB;
/// Back to a better level only this far above its threshold, so a disk hovering at a threshold does not flap.
const MARGIN: u64 = 2 * GB;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Level {
    #[default]
    Ok,
    Low,
    Critical,
}

/// `(warn, critical)` in bytes for Settings' warn value in GB; `None` when the warning is off (0). Critical is 5 GB, or a
/// quarter of the warn value when that is under 20 GB.
pub fn limits(warn_gb: u64) -> Option<(u64, u64)> {
    if warn_gb == 0 {
        return None;
    }
    let warn = warn_gb.saturating_mul(GB);
    Some((warn, if warn < 20 * GB { warn / 4 } else { CRITICAL }))
}

/// The level for `free` bytes after `prev`: worse at once, better only past the threshold plus [`MARGIN`].
pub fn level_for(prev: Level, free: u64, (warn, crit): (u64, u64)) -> Level {
    let raw = if free < crit {
        Level::Critical
    } else if free < warn {
        Level::Low
    } else {
        Level::Ok
    };
    if raw >= prev {
        return raw;
    }
    if free >= warn + MARGIN {
        Level::Ok
    } else if prev == Level::Critical && free >= crit + MARGIN {
        Level::Low
    } else {
        prev
    }
}

/// The level over time. Starts at ok, so a disk that is already low is "worse" on the first reading.
#[derive(Default)]
pub struct Watch {
    level: Level,
}

impl Watch {
    /// Take one reading (`None`: it failed, the level stays) under `limits` (`None`: the warning is off, so ok). The new
    /// level when the page should hear it: only when it got worse.
    pub fn step(&mut self, free: Option<u64>, limits: Option<(u64, u64)>) -> Option<Level> {
        let next = match (free, limits) {
            (_, None) => Level::Ok,
            (None, Some(_)) => self.level,
            (Some(f), Some(l)) => level_for(self.level, f, l),
        };
        let prev = std::mem::replace(&mut self.level, next);
        (next > prev).then_some(next)
    }
    pub fn level(&self) -> Level {
        self.level
    }
}

/// The event's payload and [`disk_watch`]'s answer.
#[derive(Clone, Debug, Default, Serialize)]
pub struct DiskState {
    pub level: Level,
    pub free_bytes: u64,
    /// Where the home folder's volume is mounted (`/`, `C:\`).
    pub volume: String,
}

/// A warn value for the watcher and where its next reading goes.
type Ask = (u64, Sender<DiskState>);

/// The watcher's handle in the app state.
pub struct Disk {
    tx: Mutex<Option<Sender<Ask>>>,
    sent: Mutex<Option<u64>>,
    now: Arc<Mutex<DiskState>>,
}

impl Disk {
    /// Start the `omher-disk` thread for the volume holding `home`. It measures nothing until the page sends the
    /// warn value ([`disk_watch`]), so a person who turned the warning off never hears it at startup.
    pub fn start(app: AppHandle, home: Option<PathBuf>) -> Disk {
        let (tx, rx) = channel::<Ask>();
        let now = Arc::new(Mutex::new(DiskState::default()));
        let shared = now.clone();
        let started = home.is_some()
            && std::thread::Builder::new()
                .name("omher-disk".into())
                .spawn(move || {
                    let Some(home) = home else { return };
                    let Ok((mut warn, mut reply)) = rx.recv() else { return };
                    let mut replies = vec![reply];
                    let mut watch = Watch::default();
                    loop {
                        let read = free_space(&home);
                        let worse = watch.step(read.as_ref().map(|r| r.0), limits(warn));
                        let state = {
                            let mut s = shared.lock().unwrap();
                            s.level = watch.level();
                            if let Some((free, volume)) = read {
                                s.free_bytes = free;
                                s.volume = volume;
                            }
                            s.clone()
                        };
                        for r in replies.drain(..) {
                            let _ = r.send(state.clone());
                        }
                        if worse.is_some() {
                            let _ = app.emit(EVENT, state);
                        }
                        match rx.recv_timeout(EVERY) {
                            Ok(ask) => {
                                (warn, reply) = ask;
                                replies.push(reply);
                                for (w, r) in rx.try_iter() {
                                    warn = w;
                                    replies.push(r);
                                }
                            }
                            Err(RecvTimeoutError::Timeout) => {}
                            Err(RecvTimeoutError::Disconnected) => return,
                        }
                    }
                })
                .is_ok();
        Disk { tx: Mutex::new(started.then_some(tx)), sent: Mutex::new(None), now }
    }
}

/// Settings › General's warn value in GB (0 = off) for the watcher, answered with the level and free space. A new
/// value is measured at once and answered with that reading; the same value again answers the last reading.
#[tauri::command]
pub async fn disk_watch(warn_gb: u64, disk: State<'_, Disk>) -> Result<DiskState, String> {
    let wait = {
        let mut sent = disk.sent.lock().unwrap();
        if *sent == Some(warn_gb) {
            None
        } else {
            *sent = Some(warn_gb);
            let (tx, rx) = channel();
            disk.tx.lock().unwrap().as_ref().and_then(|t| t.send((warn_gb, tx)).ok()).map(|_| rx)
        }
    };
    if let Some(rx) = wait {
        let got = tauri::async_runtime::spawn_blocking(move || rx.recv_timeout(Duration::from_secs(5)).ok()).await.ok().flatten();
        if let Some(state) = got {
            return Ok(state);
        }
    }
    Ok(disk.now.lock().unwrap().clone())
}

/// Test builds (debug only): `OMHER_DISK_FAKE_FREE=<bytes>` stands in for the reading.
fn fake_free() -> Option<u64> {
    if !cfg!(debug_assertions) {
        return None;
    }
    std::env::var("OMHER_DISK_FAKE_FREE").ok()?.trim().parse().ok()
}

/// `(available bytes, mount point)` of the volume holding `path`: one system call.
fn free_space(path: &Path) -> Option<(u64, String)> {
    let read = volume_free(path);
    match fake_free() {
        Some(f) => Some((f, read.map(|r| r.1).unwrap_or_else(|| path.display().to_string()))),
        None => read,
    }
}

#[cfg(target_os = "macos")]
fn volume_free(path: &Path) -> Option<(u64, String)> {
    use std::os::unix::ffi::OsStrExt;
    let c = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut st: libc::statfs = unsafe { std::mem::zeroed() };
    if unsafe { libc::statfs(c.as_ptr(), &mut st) } != 0 {
        return None;
    }
    let mount = unsafe { std::ffi::CStr::from_ptr(st.f_mntonname.as_ptr()) }.to_string_lossy().into_owned();
    // the home folder sits on the Data half of the system volume; people know that volume as `/`
    let mount = if mount == "/System/Volumes/Data" { "/".to_string() } else { mount };
    Some((st.f_bavail.saturating_mul(st.f_bsize as u64), mount))
}

/// Linux and the other unixes: `statvfs` names no mount point, so the volume is named by the home folder.
#[cfg(all(unix, not(target_os = "macos")))]
fn volume_free(path: &Path) -> Option<(u64, String)> {
    use std::os::unix::ffi::OsStrExt;
    let c = std::ffi::CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    if unsafe { libc::statvfs(c.as_ptr(), &mut st) } != 0 {
        return None;
    }
    Some(((st.f_bavail as u64).saturating_mul(st.f_frsize as u64), path.display().to_string()))
}

#[cfg(windows)]
fn volume_free(path: &Path) -> Option<(u64, String)> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetDiskFreeSpaceExW(dir: *const u16, avail: *mut u64, total: *mut u64, free: *mut u64) -> i32;
    }
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
    let (mut avail, mut total, mut free) = (0u64, 0u64, 0u64);
    if unsafe { GetDiskFreeSpaceExW(wide.as_ptr(), &mut avail, &mut total, &mut free) } == 0 {
        return None;
    }
    let s = path.display().to_string();
    let volume = match s.get(..2) {
        Some(d) if d.ends_with(':') => format!("{d}\\"),
        _ => s,
    };
    Some((avail, volume))
}

#[cfg(test)]
mod tests {
    use super::*;
    use Level::*;

    const L20: (u64, u64) = (20 * GB, 5 * GB);

    #[test]
    fn limits_follow_the_setting() {
        assert_eq!(limits(0), None);
        assert_eq!(limits(20), Some((20 * GB, 5 * GB)));
        assert_eq!(limits(50), Some((50 * GB, 5 * GB)));
        assert_eq!(limits(10), Some((10 * GB, 10 * GB / 4)));
        assert_eq!(limits(5), Some((5 * GB, 5 * GB / 4)));
    }

    #[test]
    fn levels_go_down_at_once_and_up_only_past_the_margin() {
        assert_eq!(level_for(Ok, 25 * GB, L20), Ok);
        assert_eq!(level_for(Ok, 19 * GB, L20), Low);
        assert_eq!(level_for(Ok, 4 * GB, L20), Critical);
        assert_eq!(level_for(Low, 4 * GB, L20), Critical);
        // up: threshold + 2 GB
        assert_eq!(level_for(Low, 21 * GB, L20), Low);
        assert_eq!(level_for(Low, 22 * GB, L20), Ok);
        assert_eq!(level_for(Critical, 6 * GB, L20), Critical);
        assert_eq!(level_for(Critical, 7 * GB, L20), Low);
        assert_eq!(level_for(Critical, 21 * GB, L20), Low);
        assert_eq!(level_for(Critical, 22 * GB, L20), Ok);
    }

    #[test]
    fn the_page_hears_only_a_worse_level() {
        let mut w = Watch::default();
        assert_eq!(w.step(Some(30 * GB), Some(L20)), None);
        assert_eq!(w.step(Some(19 * GB), Some(L20)), Some(Low));
        assert_eq!(w.step(Some(18 * GB), Some(L20)), None, "still low: no second event");
        assert_eq!(w.step(Some(4 * GB), Some(L20)), Some(Critical));
        assert_eq!(w.step(Some(8 * GB), Some(L20)), None, "better: no event");
        assert_eq!(w.level(), Low);
        assert_eq!(w.step(Some(4 * GB), Some(L20)), Some(Critical), "worse again");
        assert_eq!(w.step(Some(30 * GB), Some(L20)), None);
        assert_eq!(w.level(), Ok);
        // a failed reading keeps the level and says nothing
        assert_eq!(w.step(Some(19 * GB), Some(L20)), Some(Low));
        assert_eq!(w.step(None, Some(L20)), None);
        assert_eq!(w.level(), Low);
        // the warning turned off: ok, silently; back on while still low: heard again
        assert_eq!(w.step(Some(19 * GB), None), None);
        assert_eq!(w.level(), Ok);
        assert_eq!(w.step(Some(19 * GB), Some(L20)), Some(Low));
    }

    #[test]
    fn already_low_at_startup_is_heard_once() {
        let mut w = Watch::default();
        assert_eq!(w.step(Some(3 * GB), Some(L20)), Some(Critical));
        assert_eq!(w.step(Some(3 * GB), Some(L20)), None);
    }

    #[test]
    fn this_volume_has_a_reading() {
        let (free, volume) = volume_free(&std::env::temp_dir()).expect("statfs");
        assert!(free > 0);
        assert!(!volume.is_empty());
    }
}

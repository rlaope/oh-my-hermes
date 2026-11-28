//! Another app keeping a CPU core busy, so the page can say so once. One `omher-cpu` thread reads, every [`EVERY`], the
//! CPU time the person's own processes have used so far (macOS `proc_listallpids` + `proc_pid_rusage`, Linux
//! `/proc/<pid>/stat`): a few system calls, no program runs, other users' processes are skipped, nothing is sent
//! anywhere. omher itself and every process under it (the TERMINALS sessions: the person's own work, shown on their rows)
//! are left out, and so is the rest of omher's own app bundle.
//!
//! An app's usage is the CPU time it used between two readings over the time between them (one core = 100 %). Its hot
//! streak goes up one for a reading at [`HOG_PCT`] or more and down one otherwise (a spinning app on a busy machine dips
//! now and then); [`HOG_POLLS`] in a row (about a minute) make it a hog. The page hears [`EVENT`] `{name, pct, pid}` when
//! there is a hog it has not been told about: ONE warning naming the hottest such app, and every current hog counts as
//! told from then on. An app is told about again only an hour later ([`REWARN`]) or after it cooled down fully, so two
//! hogs taking turns as the hottest never repeat the warning. [`STATE_EVENT`] carries the current hogs (the sidebar
//! chip) whenever that list changes. Windows and the other systems: not supported, the thread does not start.
//! Env `OMHER_CPU_HOG_PCT` / `OMHER_CPU_HOG_POLLS` lower the thresholds (tests, manual checks).

use std::collections::{HashMap, HashSet};
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

/// The page's warning: a hog it has not been told about.
pub const EVENT: &str = "cpu-hog";
/// The current hogs changed (the chip).
pub const STATE_EVENT: &str = "cpu-hogs";
/// How often the CPU times are read.
const EVERY: Duration = Duration::from_secs(5);
/// A reading at this usage (% of one core) or more is hot.
const HOG_PCT: f64 = 85.0;
/// This many hot readings (net) make a hog: about a minute at [`EVERY`].
const HOG_POLLS: u32 = 12;
/// A hog already told about is told about again after this long.
const REWARN: u64 = 3600;

/// `(pct, polls)`: [`HOG_PCT`] and [`HOG_POLLS`], or the env overrides.
pub fn thresholds() -> (f64, u32) {
    let pct = std::env::var("OMHER_CPU_HOG_PCT").ok().and_then(|v| v.trim().parse::<f64>().ok()).filter(|p| *p > 0.0);
    let polls = std::env::var("OMHER_CPU_HOG_POLLS").ok().and_then(|v| v.trim().parse::<u32>().ok()).filter(|n| *n > 0);
    (pct.unwrap_or(HOG_PCT), polls.unwrap_or(HOG_POLLS))
}

/// Usage in % of one core: CPU time used over wall time passed, both in ms. 0 when the gap is under a second (too
/// short to say).
pub fn usage_pct(cpu_ms: u64, wall_ms: u64) -> f64 {
    if wall_ms < 1000 {
        return 0.0;
    }
    cpu_ms as f64 * 100.0 / wall_ms as f64
}

/// The next hot streak: one up for a hot reading, one down (never below 0) otherwise, at most `2 * polls` so a hog
/// that stops cools within about a minute.
pub fn next_streak(streak: u32, hot: bool, polls: u32) -> u32 {
    if hot {
        (streak + 1).min(polls.saturating_mul(2))
    } else {
        streak.saturating_sub(1)
    }
}

/// One app's usage in a reading.
#[derive(Clone, Debug, PartialEq)]
pub struct Usage {
    /// What makes it one app across readings (its bundle, or its process).
    pub key: String,
    pub name: String,
    pub pct: f64,
    /// Its busiest process.
    pub pid: u32,
}

/// A hog as the page hears it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Hog {
    pub name: String,
    /// Usage in the last reading, % of one core, rounded.
    pub pct: u32,
    pub pid: u32,
}

/// Streaks and what the page was told, over readings. Pure: the clock comes in.
pub struct Tracker {
    pct: f64,
    polls: u32,
    streak: HashMap<String, u32>,
    /// Hogs told about, and when (s).
    warned: HashMap<String, u64>,
}

impl Tracker {
    pub fn new((pct, polls): (f64, u32)) -> Tracker {
        Tracker { pct, polls: polls.max(1), streak: HashMap::new(), warned: HashMap::new() }
    }

    /// Take one reading at `now` (s). Returns the current hogs, hottest first, and the warning to send, if any.
    pub fn step(&mut self, usage: &[Usage], now: u64) -> (Vec<Hog>, Option<Hog>) {
        let mut next = HashMap::new();
        for u in usage {
            let s = next_streak(self.streak.get(&u.key).copied().unwrap_or(0), u.pct >= self.pct, self.polls);
            if s > 0 {
                next.insert(u.key.clone(), s);
            }
        }
        // an app that cooled down fully, or is gone, is forgotten: next time it is new again
        self.warned.retain(|k, _| next.contains_key(k));
        self.streak = next;
        let mut hogs: Vec<&Usage> = usage.iter().filter(|u| self.streak.get(&u.key).is_some_and(|s| *s >= self.polls)).collect();
        hogs.sort_by(|a, b| b.pct.total_cmp(&a.pct).then_with(|| a.key.cmp(&b.key)));
        let due = hogs.iter().find(|u| self.warned.get(&u.key).is_none_or(|at| now.saturating_sub(*at) >= REWARN));
        let warn = due.map(|u| hog(u));
        if warn.is_some() {
            for u in &hogs {
                self.warned.insert(u.key.clone(), now);
            }
        }
        (hogs.into_iter().map(hog).collect(), warn)
    }
}

fn hog(u: &Usage) -> Hog {
    Hog { name: u.name.clone(), pct: u.pct.round().clamp(0.0, u32::MAX as f64) as u32, pid: u.pid }
}

/// One process in a reading.
#[derive(Clone, Debug)]
pub struct Proc {
    pub pid: u32,
    pub ppid: u32,
    /// When it started (any unit): a reused pid is a different process.
    pub start: u64,
    /// CPU time used so far, ns.
    pub cpu_ns: u64,
    pub key: String,
    pub name: String,
}

/// Turns process readings into app usages.
pub struct Sampler {
    /// omher's own pid: it and everything under it are left out (`None`: nothing is, for tests).
    me: Option<u32>,
    /// omher's own bundle key, left out too (its helpers do not run under it).
    my_key: Option<String>,
    last: Option<(Instant, HashMap<(u32, u64), u64>)>,
}

impl Sampler {
    pub fn new(me: Option<u32>) -> Sampler {
        let my_key = me.and_then(|_| std::env::current_exe().ok()).and_then(|p| bundle_of(&p.to_string_lossy()));
        Sampler { me, my_key, last: None }
    }

    /// Read the processes now; `None` when this system is not supported.
    pub fn sample(&mut self) -> Option<Vec<Usage>> {
        let procs = read_procs()?;
        Some(self.usage(procs, Instant::now()))
    }

    /// App usages for `procs` read at `at`: the CPU time each app's processes used since the last reading. An app, or a
    /// process, seen for the first time counts 0.
    pub fn usage(&mut self, procs: Vec<Proc>, at: Instant) -> Vec<Usage> {
        let skip = self.me.map(|me| descendants(&procs, me)).unwrap_or_default();
        let gap = self.last.as_ref().map(|(t, _)| at.saturating_duration_since(*t).as_millis() as u64).unwrap_or(0);
        let prev = self.last.take().map(|(_, m)| m).unwrap_or_default();
        let mut now = HashMap::new();
        let mut apps: HashMap<String, (String, u64, u32, u64)> = HashMap::new();
        for p in procs {
            if skip.contains(&p.pid) || (self.my_key.is_some() && self.my_key.as_deref() == Some(p.key.as_str())) {
                continue;
            }
            let used = prev.get(&(p.pid, p.start)).map(|was| p.cpu_ns.saturating_sub(*was)).unwrap_or(0);
            now.insert((p.pid, p.start), p.cpu_ns);
            let e = apps.entry(p.key).or_insert_with(|| (p.name, 0, p.pid, 0));
            e.1 += used;
            if used > e.3 {
                e.2 = p.pid;
                e.3 = used;
            }
        }
        self.last = Some((at, now));
        apps.into_iter()
            .map(|(key, (name, ns, pid, _))| Usage { key, name, pct: usage_pct(ns / 1_000_000, gap), pid })
            .collect()
    }
}

/// `me` and every process under it.
fn descendants(procs: &[Proc], me: u32) -> HashSet<u32> {
    let mut kids: HashMap<u32, Vec<u32>> = HashMap::new();
    for p in procs {
        kids.entry(p.ppid).or_default().push(p.pid);
    }
    let mut out = HashSet::from([me]);
    let mut todo = vec![me];
    while let Some(p) = todo.pop() {
        for k in kids.get(&p).into_iter().flatten() {
            if *k != p && out.insert(*k) {
                todo.push(*k);
            }
        }
    }
    out
}

/// The outermost `.app` bundle a program path lies in (`/Applications/Foo.app/…/Helper.app/…` -> `/Applications/Foo.app`).
pub fn bundle_of(path: &str) -> Option<String> {
    let i = path.find(".app/")?;
    Some(path[..i + 4].to_string())
}

/// A bundle path's app name (`/Applications/Foo Bar.app` -> `Foo Bar`).
fn bundle_name(bundle: &str) -> String {
    bundle.rsplit('/').next().unwrap_or(bundle).trim_end_matches(".app").to_string()
}

#[cfg(target_os = "macos")]
fn read_procs() -> Option<Vec<Proc>> {
    use std::ffi::{c_int, c_void, CStr};
    use std::sync::OnceLock;
    // proc_pid_rusage counts in mach time units, which are not ns on every Mac
    static TB: OnceLock<(u64, u64)> = OnceLock::new();
    let (numer, denom) = *TB.get_or_init(|| {
        let mut tb = libc::mach_timebase_info { numer: 0, denom: 0 };
        if unsafe { libc::mach_timebase_info(&mut tb) } == 0 && tb.denom != 0 {
            (tb.numer as u64, tb.denom as u64)
        } else {
            (1, 1)
        }
    });
    let n = unsafe { libc::proc_listallpids(std::ptr::null_mut(), 0) };
    if n <= 0 {
        return None;
    }
    let mut pids = vec![0 as c_int; n as usize + 64];
    let n = unsafe { libc::proc_listallpids(pids.as_mut_ptr() as *mut c_void, (pids.len() * std::mem::size_of::<c_int>()) as c_int) };
    if n <= 0 {
        return None;
    }
    pids.truncate(n as usize);
    let uid = unsafe { libc::getuid() };
    let mut out = Vec::with_capacity(pids.len());
    let mut path = vec![0u8; libc::PROC_PIDPATHINFO_MAXSIZE as usize];
    for pid in pids {
        if pid <= 0 {
            continue;
        }
        let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
        let size = std::mem::size_of::<libc::proc_bsdinfo>() as c_int;
        if unsafe { libc::proc_pidinfo(pid, libc::PROC_PIDTBSDINFO, 0, &mut info as *mut _ as *mut c_void, size) } != size {
            continue;
        }
        if info.pbi_uid != uid {
            continue;
        }
        let mut ru: libc::rusage_info_v2 = unsafe { std::mem::zeroed() };
        if unsafe { libc::proc_pid_rusage(pid, libc::RUSAGE_INFO_V2, &mut ru as *mut _ as *mut libc::rusage_info_t) } != 0 {
            continue;
        }
        let ticks = ru.ri_user_time.saturating_add(ru.ri_system_time);
        let cpu_ns = (ticks as u128 * numer as u128 / denom as u128) as u64;
        let len = unsafe { libc::proc_pidpath(pid, path.as_mut_ptr() as *mut c_void, path.len() as u32) };
        let exe = if len > 0 { String::from_utf8_lossy(&path[..len as usize]).into_owned() } else { String::new() };
        let own = |s: &[libc::c_char]| unsafe { CStr::from_ptr(s.as_ptr()) }.to_string_lossy().into_owned();
        let (key, name) = match bundle_of(&exe) {
            Some(b) => (b.clone(), bundle_name(&b)),
            None => {
                let name = Some(own(&info.pbi_name)).filter(|s| !s.is_empty()).unwrap_or_else(|| own(&info.pbi_comm));
                (format!("pid:{pid}:{}", info.pbi_start_tvsec), name)
            }
        };
        let start = info.pbi_start_tvsec.saturating_mul(1_000_000).saturating_add(info.pbi_start_tvusec);
        out.push(Proc { pid: pid as u32, ppid: info.pbi_ppid, start, cpu_ns, key, name });
    }
    Some(out)
}

#[cfg(target_os = "linux")]
fn read_procs() -> Option<Vec<Proc>> {
    use std::os::unix::fs::MetadataExt;
    let tick = unsafe { libc::sysconf(libc::_SC_CLK_TCK) };
    let tick = if tick > 0 { tick as u64 } else { 100 };
    let uid = unsafe { libc::getuid() };
    let mut out = Vec::new();
    for e in std::fs::read_dir("/proc").ok()?.flatten() {
        let Some(pid) = e.file_name().to_str().and_then(|s| s.parse::<u32>().ok()) else { continue };
        if e.metadata().map(|m| m.uid() != uid).unwrap_or(true) {
            continue;
        }
        let Ok(stat) = std::fs::read_to_string(format!("/proc/{pid}/stat")) else { continue };
        let Some(p) = parse_stat(pid, &stat, tick) else { continue };
        out.push(p);
    }
    Some(out)
}

/// One `/proc/<pid>/stat` line: `pid (comm) state ppid … utime stime … starttime …`, CPU in clock ticks of `tick` Hz.
#[cfg(any(target_os = "linux", test))]
fn parse_stat(pid: u32, stat: &str, tick: u64) -> Option<Proc> {
    let open = stat.find('(')?;
    let close = stat.rfind(')')?;
    let name = stat.get(open + 1..close)?.to_string();
    let f: Vec<&str> = stat.get(close + 1..)?.split_whitespace().collect();
    // f[0] is field 3 (state)
    let num = |i: usize| f.get(i).and_then(|s| s.parse::<u64>().ok());
    let ppid = num(1)? as u32;
    let ticks = num(11)?.saturating_add(num(12)?);
    let start = num(19)?;
    Some(Proc { pid, ppid, start, cpu_ns: ticks.saturating_mul(1_000_000_000 / tick.max(1)), key: format!("pid:{pid}:{start}"), name })
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn read_procs() -> Option<Vec<Proc>> {
    None
}

/// [`cpu_watch`]'s answer: the current hogs, hottest first.
#[derive(Clone, Debug, Default, Serialize)]
pub struct CpuState {
    pub hogs: Vec<Hog>,
    /// False on a system the watcher does not read (Windows).
    pub supported: bool,
}

/// The watcher's handle in the app state.
pub struct Cpu {
    tx: Mutex<Option<Sender<bool>>>,
    now: Arc<Mutex<CpuState>>,
}

impl Cpu {
    /// Start the `omher-cpu` thread. It reads nothing until the page turns the warning on ([`cpu_watch`]).
    pub fn start(app: AppHandle) -> Cpu {
        let supported = cfg!(any(target_os = "macos", target_os = "linux"));
        let now = Arc::new(Mutex::new(CpuState { hogs: vec![], supported }));
        let shared = now.clone();
        let (tx, rx) = channel::<bool>();
        let started = supported
            && std::thread::Builder::new()
                .name("omher-cpu".into())
                .spawn(move || {
                    let born = Instant::now();
                    let mut on = false;
                    let mut sampler = Sampler::new(Some(std::process::id()));
                    let mut tracker = Tracker::new(thresholds());
                    loop {
                        if !on {
                            match rx.recv() {
                                Ok(v) => on = v,
                                Err(_) => return,
                            }
                            continue;
                        }
                        let usage = sampler.sample().unwrap_or_default();
                        let (hogs, warn) = tracker.step(&usage, born.elapsed().as_secs());
                        publish(&app, &shared, hogs);
                        if let Some(w) = warn {
                            let _ = app.emit(EVENT, w);
                        }
                        // a message mid-wait (the page asking again) never cuts the 5 s short: a reading under a
                        // second apart would count as cool
                        let due = Instant::now() + EVERY;
                        loop {
                            match rx.recv_timeout(due.saturating_duration_since(Instant::now())) {
                                Ok(v) => {
                                    on = v;
                                    if !on {
                                        break;
                                    }
                                }
                                Err(RecvTimeoutError::Timeout) => break,
                                Err(RecvTimeoutError::Disconnected) => return,
                            }
                        }
                        if !on {
                            // off: forget everything, so turning it back on starts fresh
                            sampler = Sampler::new(Some(std::process::id()));
                            tracker = Tracker::new(thresholds());
                            publish(&app, &shared, vec![]);
                        }
                    }
                })
                .is_ok();
        Cpu { tx: Mutex::new(started.then_some(tx)), now }
    }
}

/// Keep `hogs` as the current state; the page hears it when the list of apps changed.
fn publish(app: &AppHandle, shared: &Mutex<CpuState>, hogs: Vec<Hog>) {
    let state = {
        let mut s = shared.lock().unwrap();
        let same = s.hogs.len() == hogs.len() && s.hogs.iter().zip(&hogs).all(|(a, b)| a.name == b.name);
        s.hogs = hogs;
        (!same).then(|| s.clone())
    };
    if let Some(s) = state {
        let _ = app.emit(STATE_EVENT, s);
    }
}

/// Settings › General's "Warn when another app keeps the CPU busy" for the watcher (off: it reads nothing and forgets
/// what it saw), answered with the current hogs.
#[tauri::command]
pub async fn cpu_watch(on: bool, cpu: State<'_, Cpu>) -> Result<CpuState, String> {
    if let Some(tx) = cpu.tx.lock().unwrap().as_ref() {
        let _ = tx.send(on);
    }
    let mut s = cpu.now.lock().unwrap().clone();
    if !on {
        s.hogs.clear();
    }
    Ok(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(key: &str, pct: f64) -> Usage {
        Usage { key: key.into(), name: key.to_uppercase(), pct, pid: key.len() as u32 }
    }

    /// Run `polls` readings 5 s apart from `t0`, each from `f(i)`; the warnings sent.
    fn run(tr: &mut Tracker, t0: u64, polls: u64, f: impl Fn(u64) -> Vec<Usage>) -> Vec<Hog> {
        (0..polls).filter_map(|i| tr.step(&f(i), t0 + i * 5).1).collect()
    }

    #[test]
    fn cpu_usage_is_cpu_time_over_wall_time() {
        assert_eq!(usage_pct(5000, 5000), 100.0);
        assert_eq!(usage_pct(2500, 5000), 50.0);
        assert_eq!(usage_pct(10_000, 5000), 200.0, "two cores");
        assert_eq!(usage_pct(900, 999), 0.0, "under a second: too short to say");
        assert_eq!(usage_pct(0, 0), 0.0);
    }

    #[test]
    fn cpu_streak_goes_up_and_down_one_at_a_time() {
        assert_eq!(next_streak(0, true, 12), 1);
        assert_eq!(next_streak(11, true, 12), 12);
        assert_eq!(next_streak(12, false, 12), 11, "one low reading does not reset it");
        assert_eq!(next_streak(0, false, 12), 0);
        assert_eq!(next_streak(24, true, 12), 24, "capped at twice the polls");
    }

    #[test]
    fn cpu_one_hog_warns_once_after_a_minute() {
        let mut tr = Tracker::new((85.0, 12));
        let warns = run(&mut tr, 0, 40, |_| vec![u("a", 99.0), u("b", 3.0)]);
        assert_eq!(warns, vec![Hog { name: "A".into(), pct: 99, pid: 1 }]);
        let mut tr = Tracker::new((85.0, 12));
        let first = (0..40).position(|i| tr.step(&[u("a", 99.0)], i * 5).1.is_some());
        assert_eq!(first, Some(11), "the 12th hot reading");
    }

    #[test]
    fn cpu_a_spinning_app_that_dips_now_and_then_is_still_one_warning() {
        let mut tr = Tracker::new((85.0, 12));
        let warns = run(&mut tr, 0, 200, |i| vec![u("a", if i % 4 == 3 { 80.0 } else { 92.0 })]);
        assert_eq!(warns.len(), 1);
    }

    #[test]
    fn cpu_two_hogs_taking_turns_as_hottest_warn_exactly_once() {
        let mut tr = Tracker::new((85.0, 12));
        // both hot for a minute, then 20 readings where the hottest flips every reading
        let warns = run(&mut tr, 0, 12 + 20, |i| if i % 2 == 0 { vec![u("a", 99.0), u("b", 91.0)] } else { vec![u("a", 90.0), u("b", 98.0)] });
        assert_eq!(warns.len(), 1, "{warns:?}");
    }

    #[test]
    fn cpu_a_new_third_hog_warns_once_more() {
        let mut tr = Tracker::new((85.0, 12));
        let both = |i: u64| if i % 2 == 0 { vec![u("a", 99.0), u("b", 91.0)] } else { vec![u("a", 90.0), u("b", 98.0)] };
        assert_eq!(run(&mut tr, 0, 20, both).len(), 1);
        let warns = run(&mut tr, 100, 40, |i| {
            let mut v = both(i);
            v.push(u("ccc", 95.0));
            v
        });
        assert_eq!(warns, vec![Hog { name: "CCC".into(), pct: 95, pid: 3 }], "named: the hottest app not yet told about");
    }

    #[test]
    fn cpu_the_same_hogs_warn_again_after_an_hour() {
        let mut tr = Tracker::new((85.0, 12));
        let hogs = |_| vec![u("a", 99.0), u("b", 95.0)];
        assert_eq!(run(&mut tr, 0, 20, hogs).len(), 1);
        assert_eq!(run(&mut tr, 100, 600, hogs).len(), 0, "warned at 55 s; quiet until 3655 s");
        let again = run(&mut tr, 3655, 3, hogs);
        assert_eq!(again.len(), 1);
        assert_eq!(again[0].name, "A");
    }

    #[test]
    fn cpu_a_hog_that_cools_then_heats_warns_again() {
        let mut tr = Tracker::new((85.0, 12));
        assert_eq!(run(&mut tr, 0, 30, |_| vec![u("a", 99.0)]).len(), 1);
        let (hogs, w) = tr.step(&[u("a", 99.0)], 150);
        assert_eq!((hogs.len(), w), (1, None));
        // cooling: the chip clears once it is under the hog line, the memory once it is fully cool
        let mut cleared = None;
        for i in 0..30 {
            if tr.step(&[u("a", 2.0)], 155 + i * 5).0.is_empty() && cleared.is_none() {
                cleared = Some(i);
            }
        }
        assert_eq!(cleared, Some(12), "24 -> 11 after 13 cool readings");
        assert_eq!(run(&mut tr, 400, 30, |_| vec![u("a", 99.0)]).len(), 1);
    }

    #[test]
    fn cpu_a_hog_that_exits_is_forgotten() {
        let mut tr = Tracker::new((85.0, 2));
        assert_eq!(run(&mut tr, 0, 4, |_| vec![u("a", 99.0)]).len(), 1);
        assert_eq!(tr.step(&[], 20), (vec![], None));
        assert_eq!(run(&mut tr, 25, 4, |_| vec![u("a", 99.0)]).len(), 1);
    }

    fn p(pid: u32, ppid: u32, cpu_ms: u64, key: &str) -> Proc {
        Proc { pid, ppid, start: 7, cpu_ns: cpu_ms * 1_000_000, key: key.into(), name: key.into() }
    }

    #[test]
    fn cpu_omher_and_everything_under_it_are_left_out_and_bundles_add_up() {
        let mut s = Sampler { me: Some(10), my_key: Some("/Applications/omher.app".into()), last: None };
        let t0 = Instant::now();
        let read = |extra: u64| {
            vec![
                p(10, 1, 100 + extra, "/Applications/omher.app"),
                p(11, 10, 100 + extra, "pid:11"), // a TERMINALS shell
                p(12, 11, 100 + extra, "pid:12"), // a build under it
                p(13, 1, 100 + extra, "/Applications/omher.app"), // omher's own helper
                p(20, 1, 100 + extra / 2, "/Applications/Web.app"),
                p(21, 1, 100 + extra / 2, "/Applications/Web.app"),
                p(30, 1, 100, "pid:30"),
            ]
        };
        let first = s.usage(read(0), t0);
        assert!(first.iter().all(|u| u.pct == 0.0), "first reading: 0");
        let mut second = s.usage(read(5000), t0 + Duration::from_secs(5));
        second.sort_by(|a, b| a.key.cmp(&b.key));
        let got: Vec<(&str, f64)> = second.iter().map(|u| (u.key.as_str(), u.pct)).collect();
        assert_eq!(got, vec![("/Applications/Web.app", 100.0), ("pid:30", 0.0)]);
        // a pid reused by a new process counts 0, not a jump
        let mut r = read(5000);
        r[6] = Proc { start: 8, cpu_ns: 9_000_000_000, ..r[6].clone() };
        let third = s.usage(r, t0 + Duration::from_secs(10));
        assert_eq!(third.iter().find(|u| u.key == "pid:30").unwrap().pct, 0.0);
    }

    #[test]
    fn cpu_bundles_and_stat_lines_read_right() {
        assert_eq!(bundle_of("/Applications/Google Chrome.app/Contents/Frameworks/X.framework/Helpers/Helper (GPU).app/Contents/MacOS/h").as_deref(), Some("/Applications/Google Chrome.app"));
        assert_eq!(bundle_of("/usr/bin/yes"), None);
        assert_eq!(bundle_name("/Applications/Google Chrome.app"), "Google Chrome");
        let line = "4242 (my (odd) prog) R 17 4242 4242 0 -1 4194304 100 0 0 0 250 50 0 0 20 0 1 0 98765 1000 10 0";
        let pr = parse_stat(4242, line, 100).unwrap();
        assert_eq!((pr.ppid, pr.name.as_str(), pr.cpu_ns, pr.start), (17, "my (odd) prog", 3_000_000_000, 98765));
    }

    /// The real reader on this machine: a busy-loop child is a hog within POLLS readings, and is left out when it runs
    /// under the process the watcher treats as omher. Thresholds from `OMHER_CPU_HOG_PCT` / `OMHER_CPU_HOG_POLLS`
    /// (POLLS defaults to 2 here). Run by hand: on a loaded machine or a CI runner the loop gets less than a core.
    #[test]
    #[ignore = "needs a mostly idle core; run: OMHER_CPU_HOG_POLLS=2 cargo test cpu_live -- --ignored --nocapture"]
    #[cfg(any(target_os = "macos", target_os = "linux"))]
    fn cpu_live_busy_loop_is_seen_as_a_hog() {
        let mut child = std::process::Command::new("/bin/sh").args(["-c", "while :; do :; done"]).spawn().expect("sh");
        let pid = child.id();
        let pct = thresholds().0;
        let polls = std::env::var("OMHER_CPU_HOG_POLLS").ok().and_then(|v| v.parse().ok()).unwrap_or(2);
        let mut open = Sampler::new(None);
        let mut mine = Sampler::new(Some(std::process::id()));
        let mut tr = Tracker::new((pct, polls));
        let mut warned = None;
        let mut seen = vec![];
        for i in 0..4u64 {
            let a = open.sample().expect("supported");
            let b = mine.sample().expect("supported");
            assert!(b.iter().all(|u| u.pid != pid), "under omher: left out");
            if let Some(x) = a.iter().find(|u| u.pid == pid) {
                seen.push(x.pct);
            }
            if let (_, Some(w)) = tr.step(&a.into_iter().filter(|u| u.pid == pid).collect::<Vec<_>>(), i * 2) {
                warned.get_or_insert(w);
            }
            std::thread::sleep(Duration::from_millis(2000));
        }
        let _ = child.kill();
        let _ = child.wait();
        eprintln!("busy loop pid {pid}: usage per reading {seen:?}, warning {warned:?}");
        let w = warned.expect("a hog");
        assert_eq!(w.pid, pid);
        assert!(w.pct as f64 >= pct, "{w:?}");
    }
}

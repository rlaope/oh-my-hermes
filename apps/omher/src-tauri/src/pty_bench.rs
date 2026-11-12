//! The PTY flow bench (`apps/omher/bench/pty/`): how fast a program's output reaches the page, what piles up when
//! the page is slower than the program, how long Ctrl+C takes under a flood, and how long a keystroke's echo takes.
//! Real programs (`/bin/cat`, `/usr/bin/yes`) run through the same [`Sessions::spawn`] a session uses, and this
//! file stands in for the page in two ways ([`Page`]). Neither is a webview: no number here is the app window's.
//!
//! One test here is one run of one scenario; `bench/pty/run.mjs` starts each run as its own process (so one run's
//! memory never counts in the next) and folds the numbers. Ignored by default.

use std::ffi::OsString;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::mpsc::{self, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};

use crate::sessions::{Output, Sessions, PTY_READ_BYTES};

/// The page's acknowledgement of `n` drawn bytes. The seam commit has no such call.
fn ack(_s: &Sessions, _id: u32, _n: usize) {}

/// The sessions a run uses; `marks` (high, low) is for the sweep. The seam commit has no marks.
fn sessions(_marks: Option<(u64, u64)>) -> Arc<Sessions> {
    Sessions::new()
}

/// What stands in for the page.
#[derive(Clone, Copy)]
enum Page {
    /// The sink itself takes this long per message, then acknowledges it: the sink holds the shell back.
    Sink(Duration),
    /// The sink returns at once (as the Tauri channel's `send` does) and the message waits on a queue without a
    /// limit (the webview's own); a page thread takes them in order, spends this long drawing each, and
    /// acknowledges once per [`SLICE`] of work.
    Queued(Duration),
}

/// xterm takes its write queue in slices of 12 ms; `TauriHost` sends one `session_ack` for all a slice drew.
const SLICE: Duration = Duration::from_millis(12);

/// What the sink and the page saw.
#[derive(Default)]
struct Probe {
    /// bytes handed to the sink
    sunk: AtomicU64,
    /// messages handed to the sink
    msgs: AtomicU64,
    /// bytes the page has drawn
    drawn: AtomicU64,
    exit: AtomicBool,
    /// when the page last drew
    last: Mutex<Option<Instant>>,
    /// echo: when each message reached the sink
    each: Mutex<Option<Sender<Instant>>>,
}

impl Probe {
    fn draw(&self, n: usize) {
        self.drawn.fetch_add(n as u64, Ordering::SeqCst);
        *self.last.lock().unwrap() = Some(Instant::now());
    }
}

/// The session's id, once `spawn` has returned it (output can arrive before that).
fn id_of(cell: &AtomicU32) -> u32 {
    while cell.load(Ordering::SeqCst) == 0 {
        thread::yield_now();
    }
    cell.load(Ordering::SeqCst)
}

fn start(s: &Arc<Sessions>, argv: &[&str], page: Page, probe: &Arc<Probe>) -> u32 {
    let cell = Arc::new(AtomicU32::new(0));
    let (queue, waiting) = mpsc::channel::<Vec<u8>>();
    if let Page::Queued(delay) = page {
        let (s, cell, p) = (s.clone(), cell.clone(), probe.clone());
        thread::spawn(move || {
            while let Ok(first) = waiting.recv() {
                let slice_end = Instant::now() + SLICE;
                let mut owed = 0usize;
                let mut next = Some(first);
                while let Some(b) = next {
                    if !delay.is_zero() {
                        thread::sleep(delay);
                    }
                    p.draw(b.len());
                    owed += b.len();
                    next = if Instant::now() < slice_end { waiting.try_recv().ok() } else { None };
                }
                ack(&s, id_of(&cell), owed);
            }
        });
    }
    let (s2, c2, p) = (s.clone(), cell.clone(), probe.clone());
    let cwd = std::env::temp_dir().canonicalize().unwrap();
    let id = s
        .spawn(argv.iter().map(OsString::from).collect(), &cwd, None, &[], 120, 40, move |ev| match ev {
            Output::Data(b) => {
                p.sunk.fetch_add(b.len() as u64, Ordering::SeqCst);
                p.msgs.fetch_add(1, Ordering::SeqCst);
                if let Some(tx) = p.each.lock().unwrap().as_ref() {
                    let _ = tx.send(Instant::now());
                }
                match page {
                    Page::Sink(delay) => {
                        if !delay.is_zero() {
                            thread::sleep(delay);
                        }
                        p.draw(b.len());
                        ack(&s2, id_of(&c2), b.len());
                    }
                    Page::Queued(_) => {
                        let _ = queue.send(b);
                    }
                }
            }
            Output::Exit(_) => p.exit.store(true, Ordering::SeqCst),
        })
        .unwrap();
    cell.store(id, Ordering::SeqCst);
    id
}

const MB: f64 = 1024.0 * 1024.0;

fn usage() -> libc::rusage {
    let mut u: libc::rusage = unsafe { std::mem::zeroed() };
    unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut u) };
    u
}

/// The most memory this process has held, in MB (`ru_maxrss`: bytes on macOS, KB elsewhere).
fn peak_rss_mb() -> f64 {
    let v = usage().ru_maxrss as f64;
    if cfg!(target_os = "macos") {
        v / MB
    } else {
        v / 1024.0
    }
}

/// CPU time this process has used (user and system), in ms.
fn cpu_ms() -> f64 {
    let u = usage();
    let ms = |t: libc::timeval| t.tv_sec as f64 * 1000.0 + t.tv_usec as f64 / 1000.0;
    ms(u.ru_utime) + ms(u.ru_stime)
}

/// Wait until the program ended and the page has drawn all the sink was handed, with nothing new for `quiet`.
fn settled(p: &Probe, quiet: Duration, limit: Duration) -> bool {
    let end = Instant::now() + limit;
    while Instant::now() < end {
        let last = *p.last.lock().unwrap();
        let all = p.drawn.load(Ordering::SeqCst) == p.sunk.load(Ordering::SeqCst);
        if p.exit.load(Ordering::SeqCst) && all && last.map_or(true, |t| t.elapsed() >= quiet) {
            return true;
        }
        thread::sleep(Duration::from_millis(20));
    }
    false
}

fn named(prefix: &str, pairs: &[(&str, f64)]) -> Value {
    Value::Object(pairs.iter().map(|(k, v)| (format!("{prefix}{k}"), json!(v))).collect::<Map<String, Value>>())
}

/// `cat` of the bench file (200 MB with no newline in it, so the terminal adds no byte): MB/s to the last byte
/// drawn, and this process's CPU time per MB. Every byte must arrive.
fn cat(s: &Arc<Sessions>, page: Page, prefix: &str) -> Value {
    let file = std::env::var("OMHER_PTY_BENCH_FILE").expect("OMHER_PTY_BENCH_FILE names the file to cat");
    let size = std::fs::metadata(&file).unwrap().len();
    let p = Arc::new(Probe::default());
    let (t, cpu) = (Instant::now(), cpu_ms());
    start(s, &["/bin/cat", file.as_str()], page, &p);
    assert!(settled(&p, Duration::from_millis(300), Duration::from_secs(900)), "cat did not finish");
    let took = p.last.lock().unwrap().unwrap().saturating_duration_since(t);
    let cpu = cpu_ms() - cpu;
    assert_eq!(p.drawn.load(Ordering::SeqCst), size, "bytes were lost or added");
    let mb = size as f64 / MB;
    named(prefix, &[("cat_200mb_mb_s", mb / took.as_secs_f64()), ("cat_200mb_cpu_ms_per_mb", cpu / mb)])
}

/// `yes` for 5 s: MB/s drawn and messages/s handed to the sink.
fn yes(s: &Arc<Sessions>, page: Page, prefix: &str) -> Value {
    let p = Arc::new(Probe::default());
    start(s, &["/usr/bin/yes"], page, &p);
    thread::sleep(Duration::from_millis(300));
    let (b0, m0, t0) = (p.drawn.load(Ordering::SeqCst), p.msgs.load(Ordering::SeqCst), Instant::now());
    thread::sleep(Duration::from_secs(5));
    let secs = t0.elapsed().as_secs_f64();
    let rate = (p.drawn.load(Ordering::SeqCst) - b0) as f64 / MB / secs;
    named(prefix, &[("yes_5s_mb_s", rate), ("yes_5s_messages_per_s", (p.msgs.load(Ordering::SeqCst) - m0) as f64 / secs)])
}

/// `yes` for 10 s against a slow page: the most memory the process held, what was read from the PTY and not yet
/// drawn at the end (all of it is inside this process), and the rate drawn.
fn slow(s: &Arc<Sessions>, page: Page, prefix: &str) -> Value {
    let p = Arc::new(Probe::default());
    start(s, &["/usr/bin/yes"], page, &p);
    let t = Instant::now();
    thread::sleep(Duration::from_secs(10));
    let drawn = p.drawn.load(Ordering::SeqCst);
    let queued = PTY_READ_BYTES.load(Ordering::SeqCst).saturating_sub(drawn);
    named(prefix, &[("10s_peak_rss_mb", peak_rss_mb()), ("10s_queued_mb", queued as f64 / MB), ("10s_drawn_mb_s", drawn as f64 / MB / t.elapsed().as_secs_f64())])
}

/// `yes` against a slow page; after 2 s Ctrl+C is written: the time until the last byte was drawn, and how much
/// was drawn after the key.
fn interrupt(s: &Arc<Sessions>, page: Page, prefix: &str) -> Value {
    let p = Arc::new(Probe::default());
    let id = start(s, &["/usr/bin/yes"], page, &p);
    thread::sleep(Duration::from_secs(2));
    let before = p.drawn.load(Ordering::SeqCst);
    let key = Instant::now();
    s.write(id, b"\x03").unwrap();
    assert!(settled(&p, Duration::from_millis(500), Duration::from_secs(1500)), "yes survived Ctrl+C");
    let last = p.last.lock().unwrap().unwrap();
    let after = p.drawn.load(Ordering::SeqCst) - before;
    named(prefix, &[("ms_to_last_byte", last.saturating_duration_since(key).as_secs_f64() * 1000.0), ("mb_after_key", after as f64 / MB)])
}

fn percentile(v: &[f64], q: f64) -> f64 {
    let mut s = v.to_vec();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap());
    s[((s.len() as f64 * q).ceil() as usize).clamp(1, s.len()) - 1]
}

/// One byte typed at `cat` with the terminal in raw mode, 200 times: the time until its echo reached the sink.
fn echo(s: &Arc<Sessions>) -> Value {
    let p = Arc::new(Probe::default());
    let id = start(s, &["/bin/sh", "-c", "stty raw -echo; echo ready; exec /bin/cat"], Page::Sink(Duration::ZERO), &p);
    let end = Instant::now() + Duration::from_secs(10);
    while p.sunk.load(Ordering::SeqCst) < 5 && Instant::now() < end {
        thread::sleep(Duration::from_millis(10));
    }
    thread::sleep(Duration::from_millis(300));
    let (tx, rx) = mpsc::channel();
    *p.each.lock().unwrap() = Some(tx);
    let mut out = Vec::with_capacity(200);
    for i in 0..200usize {
        thread::sleep(Duration::from_millis(12));
        let sent = Instant::now();
        s.write(id, &[b'a' + (i % 26) as u8]).unwrap();
        let got = rx.recv_timeout(Duration::from_secs(5)).expect("no echo");
        out.push(got.saturating_duration_since(sent).as_secs_f64() * 1000.0);
    }
    named("echo_200_", &[("median_ms", percentile(&out, 0.5)), ("p95_ms", percentile(&out, 0.95))])
}

/// One run of the scenario `OMHER_PTY_BENCH_ONE` names; its numbers go out as one `PTY_BENCH {json}` line.
#[test]
#[ignore]
fn pty_bench_one() {
    let Ok(which) = std::env::var("OMHER_PTY_BENCH_ONE") else {
        println!("run through bench/pty/run.mjs");
        return;
    };
    let marks = std::env::var("OMHER_PTY_BENCH_MARKS").ok().and_then(|m| {
        let (h, l) = m.split_once(',')?;
        Some((h.parse().ok()?, l.parse().ok()?))
    });
    let s = sessions(marks);
    let ms = Duration::from_millis;
    let res = match which.as_str() {
        // the sink in place of the page
        "sink_cat" => cat(&s, Page::Sink(Duration::ZERO), "sink_"),
        "sink_yes" => yes(&s, Page::Sink(Duration::ZERO), "sink_"),
        "sink_slow_2ms" => slow(&s, Page::Sink(ms(2)), "sink_slow_2ms_"),
        "sink_interrupt_2ms" => interrupt(&s, Page::Sink(ms(2)), "sink_interrupt_2ms_"),
        "echo" => echo(&s),
        // a page behind a sink that returns at once
        "page_cat" => cat(&s, Page::Queued(Duration::ZERO), "page_"),
        "page_yes" => yes(&s, Page::Queued(Duration::ZERO), "page_"),
        "page_slow_20ms" => slow(&s, Page::Queued(ms(20)), "page_slow_20ms_"),
        "page_interrupt_2ms" => interrupt(&s, Page::Queued(ms(2)), "page_interrupt_2ms_"),
        "page_interrupt_20ms" => interrupt(&s, Page::Queued(ms(20)), "page_interrupt_20ms_"),
        other => panic!("unknown scenario {other}"),
    };
    println!("PTY_BENCH {res}");
    // the programs stop here; the process ends with the test, and whatever is still queued goes with it
    s.close_all();
}

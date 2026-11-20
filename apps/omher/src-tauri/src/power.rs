//! Keep the computer awake while agents work (Settings › General, on by default). The page sends `power_busy` edges
//! (a TERMINALS agent printing, a bot turn running; never one call per output) and this holds one OS power assertion
//! from the first busy edge until LINGER after the last idle edge, and lets it go on quit.
//!
//! macOS: `IOPMAssertionCreateWithName(PreventUserIdleSystemSleep)` (IOKit, linked here, no crate). Windows:
//! `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` (kernel32, linked here), always from the one worker
//! thread, since that state belongs to the thread that set it. Linux: nothing is held. Either way only idle sleep is
//! stopped: closing the lid still sleeps the computer.

use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::Mutex;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

/// How long the assertion stays after the page says the work stopped.
pub const LINGER: Duration = Duration::from_secs(60);

/// What holds and lets go of the OS assertion (a fake one in the tests).
pub trait Backend {
    /// Take the assertion; false when the system refused.
    fn hold(&mut self) -> bool;
    fn release(&mut self);
}

/// The busy/idle state machine, on a clock the caller passes in.
pub struct Awake<B: Backend> {
    backend: B,
    held: bool,
    busy: bool,
    release_at: Option<Instant>,
}

impl<B: Backend> Awake<B> {
    pub fn new(backend: B) -> Self {
        Awake { backend, held: false, busy: false, release_at: None }
    }

    pub fn held(&self) -> bool {
        self.held
    }

    /// An edge from the page. `now_release` (the setting turned off): an idle edge lets go at once.
    pub fn set_busy(&mut self, busy: bool, now_release: bool, now: Instant) {
        self.busy = busy;
        if busy {
            self.release_at = None;
            if !self.held {
                self.held = self.backend.hold();
            }
        } else if now_release {
            self.let_go();
        } else if self.held && self.release_at.is_none() {
            self.release_at = Some(now + LINGER);
        }
    }

    /// The clock moved: let go once LINGER has passed since the idle edge.
    pub fn tick(&mut self, now: Instant) {
        if !self.busy && self.release_at.is_some_and(|at| now >= at) {
            self.let_go();
        }
    }

    /// When `tick` next has something to do.
    pub fn deadline(&self) -> Option<Instant> {
        self.release_at
    }

    /// omher quits: nothing stays held.
    pub fn quit(&mut self) {
        self.busy = false;
        self.let_go();
    }

    fn let_go(&mut self) {
        self.release_at = None;
        if self.held {
            self.backend.release();
            self.held = false;
        }
    }
}

#[cfg(target_os = "macos")]
mod os {
    use std::ffi::{c_char, c_void};

    type CFStringRef = *const c_void;
    const UTF8: u32 = 0x0800_0100;
    const LEVEL_ON: u32 = 255;

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFStringCreateWithCString(alloc: *const c_void, s: *const c_char, encoding: u32) -> CFStringRef;
        fn CFRelease(p: *const c_void);
    }
    #[link(name = "IOKit", kind = "framework")]
    extern "C" {
        fn IOPMAssertionCreateWithName(kind: CFStringRef, level: u32, name: CFStringRef, id: *mut u32) -> i32;
        fn IOPMAssertionRelease(id: u32) -> i32;
    }

    #[derive(Default)]
    pub struct Os {
        id: Option<u32>,
    }

    impl super::Backend for Os {
        fn hold(&mut self) -> bool {
            // SAFETY: both strings are NUL-terminated literals; each CFString made here is released here.
            unsafe {
                let kind = CFStringCreateWithCString(std::ptr::null(), c"PreventUserIdleSystemSleep".as_ptr(), UTF8);
                let name = CFStringCreateWithCString(std::ptr::null(), c"omher: agents are working".as_ptr(), UTF8);
                if kind.is_null() || name.is_null() {
                    for p in [kind, name] {
                        if !p.is_null() {
                            CFRelease(p);
                        }
                    }
                    return false;
                }
                let mut id = 0u32;
                let ok = IOPMAssertionCreateWithName(kind, LEVEL_ON, name, &mut id) == 0;
                CFRelease(kind);
                CFRelease(name);
                if ok {
                    self.id = Some(id);
                }
                ok
            }
        }
        fn release(&mut self) {
            if let Some(id) = self.id.take() {
                // SAFETY: `id` came from IOPMAssertionCreateWithName and is released once.
                unsafe {
                    IOPMAssertionRelease(id);
                }
            }
        }
    }
}

#[cfg(windows)]
mod os {
    const ES_CONTINUOUS: u32 = 0x8000_0000;
    const ES_SYSTEM_REQUIRED: u32 = 0x0000_0001;

    #[link(name = "kernel32")]
    extern "system" {
        fn SetThreadExecutionState(flags: u32) -> u32;
    }

    #[derive(Default)]
    pub struct Os;

    impl super::Backend for Os {
        fn hold(&mut self) -> bool {
            // SAFETY: a plain flags call; it only changes this (the worker) thread's state.
            unsafe { SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) != 0 }
        }
        fn release(&mut self) {
            // SAFETY: as above; ES_CONTINUOUS alone clears what hold set.
            unsafe {
                SetThreadExecutionState(ES_CONTINUOUS);
            }
        }
    }
}

#[cfg(not(any(target_os = "macos", windows)))]
mod os {
    /// Linux: nothing is held.
    #[derive(Default)]
    pub struct Os;

    impl super::Backend for Os {
        fn hold(&mut self) -> bool {
            false
        }
        fn release(&mut self) {}
    }
}

enum Msg {
    Busy { busy: bool, now: bool },
    Quit,
}

/// The worker thread that owns the assertion; the app keeps one.
pub struct Power {
    tx: Mutex<Option<Sender<Msg>>>,
    worker: Mutex<Option<JoinHandle<()>>>,
}

impl Power {
    pub fn start() -> Self {
        Self::start_with(os::Os::default())
    }

    pub fn start_with<B: Backend + Send + 'static>(backend: B) -> Self {
        let (tx, rx) = channel::<Msg>();
        let worker = std::thread::Builder::new()
            .name("omher-power".into())
            .spawn(move || {
                let mut m = Awake::new(backend);
                loop {
                    let msg = match m.deadline() {
                        Some(at) => rx.recv_timeout(at.saturating_duration_since(Instant::now())),
                        None => rx.recv().map_err(|_| RecvTimeoutError::Disconnected),
                    };
                    match msg {
                        Ok(Msg::Busy { busy, now }) => m.set_busy(busy, now, Instant::now()),
                        Err(RecvTimeoutError::Timeout) => m.tick(Instant::now()),
                        Ok(Msg::Quit) | Err(RecvTimeoutError::Disconnected) => {
                            m.quit();
                            break;
                        }
                    }
                }
            })
            .ok();
        Power { tx: Mutex::new(Some(tx)), worker: Mutex::new(worker) }
    }

    pub fn busy(&self, busy: bool, now: bool) {
        if let Some(tx) = self.tx.lock().unwrap_or_else(|e| e.into_inner()).as_ref() {
            let _ = tx.send(Msg::Busy { busy, now });
        }
    }

    /// Let go and stop the worker (on quit).
    pub fn quit(&self) {
        if let Some(tx) = self.tx.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = tx.send(Msg::Quit);
        }
        if let Some(w) = self.worker.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = w.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex as M};

    #[derive(Clone, Default)]
    struct Fake(Arc<M<Vec<&'static str>>>);
    impl Backend for Fake {
        fn hold(&mut self) -> bool {
            self.0.lock().unwrap().push("hold");
            true
        }
        fn release(&mut self) {
            self.0.lock().unwrap().push("release");
        }
    }
    impl Fake {
        fn log(&self) -> Vec<&'static str> {
            self.0.lock().unwrap().clone()
        }
    }

    #[test]
    fn holds_on_activity_and_lets_go_a_minute_after_it_stops() {
        let f = Fake::default();
        let mut m = Awake::new(f.clone());
        let t = Instant::now();
        m.set_busy(true, false, t);
        assert!(m.held());
        m.set_busy(true, false, t + Duration::from_secs(5));
        assert_eq!(f.log(), ["hold"], "a second busy edge takes nothing more");
        m.set_busy(false, false, t + Duration::from_secs(10));
        m.tick(t + Duration::from_secs(69));
        assert!(m.held(), "still held before the minute is up");
        m.tick(t + Duration::from_secs(70));
        assert!(!m.held());
        assert_eq!(f.log(), ["hold", "release"]);
        m.tick(t + Duration::from_secs(200));
        assert_eq!(f.log(), ["hold", "release"]);
    }

    #[test]
    fn activity_inside_the_minute_keeps_it() {
        let f = Fake::default();
        let mut m = Awake::new(f.clone());
        let t = Instant::now();
        m.set_busy(true, false, t);
        m.set_busy(false, false, t + Duration::from_secs(1));
        m.set_busy(true, false, t + Duration::from_secs(30));
        assert_eq!(m.deadline(), None);
        m.tick(t + Duration::from_secs(120));
        assert!(m.held());
        m.set_busy(false, false, t + Duration::from_secs(121));
        assert_eq!(m.deadline(), Some(t + Duration::from_secs(181)));
        assert_eq!(f.log(), ["hold"]);
    }

    #[test]
    fn quit_and_setting_off_let_go_at_once() {
        let f = Fake::default();
        let mut m = Awake::new(f.clone());
        let t = Instant::now();
        m.set_busy(true, false, t);
        m.quit();
        assert!(!m.held());
        m.set_busy(true, false, t);
        m.set_busy(false, true, t);
        assert!(!m.held());
        assert_eq!(f.log(), ["hold", "release", "hold", "release"]);
        m.quit();
        assert_eq!(f.log().len(), 4, "quit with nothing held calls nothing");
    }

    #[test]
    fn idle_with_nothing_held_does_nothing() {
        let f = Fake::default();
        let mut m = Awake::new(f.clone());
        m.set_busy(false, false, Instant::now());
        assert_eq!(m.deadline(), None);
        assert!(f.log().is_empty());
    }

    #[test]
    fn the_worker_lets_go_on_quit() {
        let f = Fake::default();
        let p = Power::start_with(f.clone());
        p.busy(true, false);
        p.quit();
        assert_eq!(f.log(), ["hold", "release"]);
        p.busy(true, false); // after quit: ignored, no panic
    }
}

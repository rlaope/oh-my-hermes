//! A SESSIONS row's menu: show the session's folder in the file manager, or open the person's own system terminal
//! in it (BOUNDARY rule 30). Neither runs anything in the folder: the file manager is the system opener, and the
//! terminal starts the person's own shell there with no command and nothing typed into it. That terminal is not the
//! agent's terminal view inside omher (sessions.rs); it is the desktop's own Terminal / console window.
//!
//! The folder is the only thing that crosses from the page. It must be an absolute path to a folder that exists. It
//! is never put into a shell string: on macOS it is one argument to `open -a Terminal`, elsewhere it is only the new
//! process's working folder (and one `--working-directory=` style argument for the Linux terminals that need it).
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::accounts::{resolve, search_dirs};
use crate::bridge::Os;
use crate::hermes_auth::Desk;

/// `cwd` when it is an absolute path to an existing folder (links followed: a project folder may be one).
pub fn folder(cwd: &str) -> Result<PathBuf, String> {
    let p = PathBuf::from(cwd);
    if cwd.is_empty() || !p.is_absolute() || cwd.contains('\0') {
        return Err("not a folder".into());
    }
    let real = p.canonicalize().map_err(|_| "the folder is not there".to_string())?;
    if !real.is_dir() {
        return Err("not a folder".into());
    }
    Ok(real)
}

/// Terminal programs to try, in order, as (program, argv). Each runs with `dir` as its working folder.
pub fn launchers(desk: Desk, dir: &Path) -> Vec<(String, Vec<OsString>)> {
    let with = |flag: &str| -> OsString {
        let mut s = OsString::from(flag);
        s.push(dir.as_os_str());
        s
    };
    match desk {
        // LaunchServices opens Terminal with a new window in that folder
        Desk::Mac => vec![("open".into(), vec!["-a".into(), "Terminal".into(), dir.as_os_str().to_owned()])],
        // `start` opens a new console window running `cmd` in the working folder; its first quoted argument is
        // the window title. The folder is not on the command line, so `cmd` never parses it.
        Desk::Windows => vec![("cmd".into(), vec!["/c".into(), "start".into(), "".into(), "cmd".into()])],
        Desk::Linux => vec![
            ("x-terminal-emulator".into(), vec![]),
            ("gnome-terminal".into(), vec![with("--working-directory=")]),
            ("konsole".into(), vec!["--workdir".into(), dir.as_os_str().to_owned()]),
            ("xfce4-terminal".into(), vec![with("--working-directory=")]),
            ("xterm".into(), vec![]),
        ],
    }
}

fn host_env(k: &str) -> Option<String> {
    std::env::var(k).ok()
}

#[cfg(unix)]
fn is_program(p: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(p).map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
}

#[cfg(not(unix))]
fn is_program(p: &Path) -> bool {
    p.is_file()
}

/// Open the system terminal in folder `cwd`, running the person's own shell. Returns once the terminal program has
/// handed the window off (or exited).
pub fn open_terminal(cwd: &str) -> Result<(), String> {
    let dir = folder(cwd)?;
    let os = Os::current();
    let dirs = search_dirs(&host_env, os);
    let desk = Desk::current();
    let mut last = String::from("no terminal program found");
    for (program, argv) in launchers(desk, &dir) {
        let exe = if desk == Desk::Linux {
            match resolve(&program, &dirs, is_program, os) {
                Some(p) => p,
                None => continue,
            }
        } else {
            PathBuf::from(&program)
        };
        let mut cmd = Command::new(&exe);
        cmd.args(&argv).current_dir(&dir).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        crate::appimage::host_env(&mut cmd);
        match cmd.status() {
            Ok(s) if s.success() => return Ok(()),
            Ok(s) => last = format!("{program} exited with {s}"),
            Err(e) => last = format!("{program}: {e}"),
        }
    }
    Err(last)
}

/// Show folder `cwd` in the file manager (Finder, Explorer, the desktop's own) through the system opener.
pub fn reveal(cwd: &str) -> Result<(), String> {
    let dir = folder(cwd)?;
    #[cfg(target_os = "linux")]
    {
        crate::appimage::open(&dir.to_string_lossy())
    }
    #[cfg(not(target_os = "linux"))]
    {
        tauri_plugin_opener::open_path(&dir, None::<&str>).map_err(|e| e.to_string())
    }
}

/// The small amber dot omher lays over its Windows taskbar button while asks wait (Windows has no badge count).
pub fn overlay_dot() -> (Vec<u8>, u32) {
    const N: u32 = 16;
    let mut rgba = Vec::with_capacity((N * N * 4) as usize);
    let c = (N as f32 - 1.0) / 2.0;
    for y in 0..N {
        for x in 0..N {
            let d = ((x as f32 - c).powi(2) + (y as f32 - c).powi(2)).sqrt();
            // a 1px soft edge
            let a = (7.5 - d).clamp(0.0, 1.0);
            rgba.extend_from_slice(&[0xf5, 0xa5, 0x24, (a * 255.0) as u8]);
        }
    }
    (rgba, N)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_an_existing_absolute_folder_is_taken() {
        let d = std::env::temp_dir().join(format!("omher-folder-open-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        assert_eq!(folder(d.to_str().unwrap()).unwrap(), d.canonicalize().unwrap());
        let f = d.join("file.txt");
        std::fs::write(&f, "x").unwrap();
        for bad in ["", "relative/dir", "~/code", f.to_str().unwrap(), d.join("missing").to_str().unwrap(), "/tmp/a\0b"] {
            assert!(folder(bad).is_err(), "{bad:?}");
        }
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn the_terminal_runs_no_command_and_the_folder_is_never_a_shell_string() {
        let dir = Path::new("/Users/k k/it's; rm -rf ~ & x");
        let os = |v: &[&str]| v.iter().map(OsString::from).collect::<Vec<_>>();
        let mac = launchers(Desk::Mac, dir);
        assert_eq!(mac, vec![("open".to_string(), os(&["-a", "Terminal", "/Users/k k/it's; rm -rf ~ & x"]))]);
        // Windows: the folder is only the working folder, never on cmd's command line
        let win = launchers(Desk::Windows, dir);
        assert_eq!(win, vec![("cmd".to_string(), os(&["/c", "start", "", "cmd"]))]);
        let lin = launchers(Desk::Linux, dir);
        assert_eq!(lin.iter().map(|l| l.0.as_str()).collect::<Vec<_>>(), ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]);
        assert_eq!(lin[1].1, os(&["--working-directory=/Users/k k/it's; rm -rf ~ & x"]));
        assert_eq!(lin[2].1, os(&["--workdir", "/Users/k k/it's; rm -rf ~ & x"]));
        // no launcher carries a command to run (-e, -x, --command, /k)
        for (_, argv) in mac.iter().chain(&win).chain(&lin) {
            for a in argv {
                assert!(!["-e", "-x", "--", "--command", "/k", "-c"].contains(&a.to_str().unwrap()), "{a:?}");
            }
        }
    }

    #[test]
    fn the_overlay_dot_is_a_round_16px_picture() {
        let (rgba, n) = overlay_dot();
        assert_eq!((n, rgba.len()), (16, 16 * 16 * 4));
        assert_eq!(rgba[3], 0, "the corner is clear");
        let mid = ((8 * 16 + 8) * 4) as usize;
        assert_eq!(rgba[mid + 3], 255);
    }
}

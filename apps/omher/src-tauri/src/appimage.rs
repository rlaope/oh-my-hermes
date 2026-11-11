//! Opening links and files from inside a Linux AppImage.
//!
//! An AppImage starts omher through its `AppRun`, which points `LD_LIBRARY_PATH`, `GTK_PATH`,
//! `XDG_DATA_DIRS`, `GIO_EXTRA_MODULES` and friends at the libraries bundled under `$APPDIR` (built on
//! Ubuntu 22.04). The system opener (`xdg-open`, then `gio open`, `kde-open`, ...) is a host program: given
//! that environment it loads the bundled libraries against a newer host and dies, or reads the wrong MIME
//! database, and a click on a link does nothing. So inside an AppImage omher runs the same launchers the
//! `open` crate (the opener plugin's backend) would, in the same order, with every `$APPDIR` entry taken out
//! of the environment and the working folder moved out of the mounted image. Outside an AppImage (a `.deb`
//! install, `cargo run`) nothing changes: the opener plugin is used as on macOS and Windows.
//!
//! The same goes for every other host program omher starts (the Hermes bridge Python, the agent CLIs, the
//! sign-in and install commands): AppRun also exports `PYTHONHOME=$APPDIR/usr/`, and a host Python given that
//! looks for its standard library inside the image and dies with `No module named 'encodings'`. Each spawn
//! site calls [`host_env`] last, which applies [`host_env_edits`] to the command's whole environment.

use std::collections::BTreeMap;
use std::ffi::{OsStr, OsString};

/// For each variable whose value names `appdir`, what it should be for a host program: the
/// `:`-separated entries under `appdir` removed (`Some(rest)`), or the variable removed entirely (`None`)
/// when nothing else is left. Variables that do not mention `appdir` are not listed. Works entry by entry
/// rather than from a list of names, since AppImage hooks set different variables from one build to the next.
pub(crate) fn host_env_edits<I>(vars: I, appdir: &OsStr) -> Vec<(OsString, Option<OsString>)>
where
    I: IntoIterator<Item = (OsString, OsString)>,
{
    let root = appdir.to_string_lossy().trim_end_matches('/').to_string();
    if root.is_empty() || root == "/" {
        return Vec::new();
    }
    let inside = |entry: &str| entry == root || entry.starts_with(&format!("{root}/"));
    let mut edits = Vec::new();
    for (key, value) in vars {
        let v = value.to_string_lossy();
        if !v.contains(root.as_str()) {
            continue;
        }
        let kept: Vec<&str> = v.split(':').filter(|e| !e.is_empty() && !inside(e)).collect();
        if kept.is_empty() {
            edits.push((key, None));
        } else if kept.len() != v.split(':').filter(|e| !e.is_empty()).count() {
            edits.push((key, Some(OsString::from(kept.join(":")))));
        }
    }
    edits
}

/// The mounted image's folder when omher runs as a Linux AppImage (`APPIMAGE` and `APPDIR` both set), read
/// through `get`. Always `None` on macOS and Windows.
fn appdir_from(get: impl Fn(&str) -> Option<OsString>) -> Option<OsString> {
    if !cfg!(target_os = "linux") {
        return None;
    }
    get("APPIMAGE").and(get("APPDIR")).filter(|d| !d.is_empty())
}

fn appdir() -> Option<OsString> {
    appdir_from(|k| std::env::var_os(k))
}

/// A command omher is about to start: the whole environment the child would get, and a way to change it.
pub(crate) trait HostCommand {
    fn child_env(&self) -> Vec<(OsString, OsString)>;
    fn set_env(&mut self, key: &OsStr, value: Option<&OsStr>);
}

impl HostCommand for std::process::Command {
    fn child_env(&self) -> Vec<(OsString, OsString)> {
        let mut env: BTreeMap<OsString, OsString> = std::env::vars_os().collect();
        for (k, v) in self.get_envs() {
            match v {
                Some(v) => env.insert(k.to_owned(), v.to_owned()),
                None => env.remove(k),
            };
        }
        env.into_iter().collect()
    }
    fn set_env(&mut self, key: &OsStr, value: Option<&OsStr>) {
        match value {
            Some(v) => self.env(key, v),
            None => self.env_remove(key),
        };
    }
}

impl HostCommand for portable_pty::CommandBuilder {
    fn child_env(&self) -> Vec<(OsString, OsString)> {
        // The builder holds its own copy of omher's environment plus what was set on it.
        self.iter_full_env_as_str().map(|(k, v)| (k.into(), v.into())).collect()
    }
    fn set_env(&mut self, key: &OsStr, value: Option<&OsStr>) {
        match value {
            Some(v) => self.env(key, v),
            None => self.env_remove(key),
        }
    }
}

/// Give `cmd` the host environment when omher runs inside an AppImage: every `$APPDIR` entry taken out of
/// every variable, and a variable dropped when nothing is left (`PYTHONHOME`, `GTK_PATH`, ...). Call it after
/// the command's own variables are set. Outside an AppImage, and on macOS and Windows, it changes nothing.
pub(crate) fn host_env<C: HostCommand>(cmd: &mut C) {
    if let Some(appdir) = appdir() {
        host_env_in(cmd, &appdir);
    }
}

fn host_env_in<C: HostCommand>(cmd: &mut C, appdir: &OsStr) {
    for (k, v) in host_env_edits(cmd.child_env(), appdir) {
        cmd.set_env(&k, v.as_deref());
    }
}

#[cfg(target_os = "linux")]
mod imp {
    use std::path::Path;
    use std::process::Stdio;
    use std::time::{Duration, Instant};

    /// How long a launcher gets to fail before omher counts the hand-off as done (the `open` crate's own value).
    const SETTLE: Duration = Duration::from_millis(250);

    /// Hand `target` (a URL or an absolute file path) to the desktop's default handler.
    pub(crate) fn open(target: &str) -> Result<(), String> {
        let Some(appdir) = super::appdir() else {
            return if target.starts_with('/') {
                tauri_plugin_opener::open_path(target, None::<&str>).map_err(|e| e.to_string())
            } else {
                tauri_plugin_opener::open_url(target, None::<&str>).map_err(|e| e.to_string())
            };
        };
        let cwd = std::env::var_os("HOME").filter(|h| Path::new(h).is_dir()).unwrap_or_else(|| "/".into());
        let mut last = String::from("no program to open links with (install xdg-utils)");
        for mut cmd in open::commands(target) {
            super::host_env_in(&mut cmd, &appdir);
            cmd.current_dir(&cwd).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
            let name = cmd.get_program().to_string_lossy().to_string();
            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    last = format!("{name}: {e}");
                    continue;
                }
            };
            let start = Instant::now();
            loop {
                match child.try_wait() {
                    Ok(Some(status)) if status.success() => return Ok(()),
                    Ok(Some(status)) => {
                        last = format!("{name} exited with {status}");
                        break;
                    }
                    Ok(None) if start.elapsed() >= SETTLE => {
                        // Still running: the handler has it. Reap it whenever it ends.
                        std::thread::spawn(move || child.wait());
                        return Ok(());
                    }
                    Ok(None) => std::thread::sleep(Duration::from_millis(20)),
                    Err(e) => {
                        last = format!("{name}: {e}");
                        break;
                    }
                }
            }
        }
        Err(last)
    }
}

#[cfg(target_os = "linux")]
pub(crate) use imp::open;

#[cfg(test)]
mod tests {
    use super::{appdir_from, host_env_edits, host_env_in};
    use std::ffi::{OsStr, OsString};

    fn vars(list: &[(&str, &str)]) -> Vec<(OsString, OsString)> {
        list.iter().map(|(k, v)| (OsString::from(k), OsString::from(v))).collect()
    }

    #[test]
    fn strips_only_the_appimage_entries() {
        let env = vars(&[
            ("LD_LIBRARY_PATH", "/tmp/.mount_omherX/usr/lib:/tmp/.mount_omherX/usr/lib/x86_64-linux-gnu"),
            ("XDG_DATA_DIRS", "/tmp/.mount_omherX/usr/share:/usr/local/share:/usr/share"),
            ("PATH", "/tmp/.mount_omherX/usr/bin:/home/k/.local/bin:/usr/bin"),
            ("GTK_PATH", "/tmp/.mount_omherX/usr/lib/gtk-3.0"),
            ("APPDIR", "/tmp/.mount_omherX"),
            ("APPIMAGE", "/home/k/.local/bin/omher"),
            ("HOME", "/home/k"),
            ("SHELL", "/bin/bash"),
        ]);
        let mut got = host_env_edits(env, OsStr::new("/tmp/.mount_omherX/"));
        got.sort();
        let want: Vec<(OsString, Option<OsString>)> = vec![
            ("APPDIR".into(), None),
            ("GTK_PATH".into(), None),
            ("LD_LIBRARY_PATH".into(), None),
            ("PATH".into(), Some("/home/k/.local/bin:/usr/bin".into())),
            ("XDG_DATA_DIRS".into(), Some("/usr/local/share:/usr/share".into())),
        ];
        assert_eq!(got, want);
    }

    #[test]
    fn a_lookalike_folder_is_not_the_appdir() {
        let env = vars(&[("XDG_DATA_DIRS", "/tmp/.mount_omherXY/usr/share:/usr/share")]);
        // contains the prefix as text, but no entry is inside /tmp/.mount_omherX
        assert!(host_env_edits(env, OsStr::new("/tmp/.mount_omherX")).is_empty());
    }

    #[test]
    fn no_appdir_means_no_edits() {
        let env = vars(&[("PATH", "/usr/bin")]);
        assert!(host_env_edits(env.clone(), OsStr::new("")).is_empty());
        assert!(host_env_edits(env, OsStr::new("/")).is_empty());
    }

    const APPDIR: &str = "/tmp/.mount_omherX";

    /// The variables the omher AppImage's AppRun exports (observed in CI: PYTHONHOME, PYTHONPATH, and the
    /// library paths), next to host-only values that must survive.
    fn set_apprun_env<F: FnMut(&str, &str)>(mut set: F) {
        set("PYTHONHOME", "/tmp/.mount_omherX/usr/");
        set("PYTHONPATH", "/tmp/.mount_omherX/usr/share/pyshared/:");
        set("LD_LIBRARY_PATH", "/tmp/.mount_omherX/usr/lib:/opt/host/lib");
        set("PATH", "/tmp/.mount_omherX/usr/bin:/usr/bin");
    }

    #[test]
    fn the_bridge_command_gets_the_host_python_environment() {
        let mut cmd = std::process::Command::new("/home/k/.hermes/hermes-agent/venv/bin/python");
        cmd.env("PYTHONUTF8", "1");
        set_apprun_env(|k, v| {
            cmd.env(k, v);
        });
        host_env_in(&mut cmd, OsStr::new(APPDIR));
        let env: std::collections::HashMap<_, _> =
            cmd.get_envs().map(|(k, v)| (k.to_string_lossy().into_owned(), v.map(|v| v.to_string_lossy().into_owned()))).collect();
        assert_eq!(env["PYTHONHOME"], None, "PYTHONHOME must be gone");
        assert_eq!(env["PYTHONPATH"], None);
        assert_eq!(env["LD_LIBRARY_PATH"].as_deref(), Some("/opt/host/lib"));
        assert_eq!(env["PATH"].as_deref(), Some("/usr/bin"));
        assert_eq!(env["PYTHONUTF8"].as_deref(), Some("1"), "the command's own variables stay");
    }

    #[test]
    fn a_terminal_session_gets_the_host_environment_too() {
        let mut cmd = portable_pty::CommandBuilder::new("/usr/bin/claude");
        set_apprun_env(|k, v| cmd.env(k, v));
        cmd.env("TERM", "xterm-256color");
        host_env_in(&mut cmd, OsStr::new(APPDIR));
        assert_eq!(cmd.get_env("PYTHONHOME"), None);
        assert_eq!(cmd.get_env("PYTHONPATH"), None);
        assert_eq!(cmd.get_env("LD_LIBRARY_PATH"), Some(OsStr::new("/opt/host/lib")));
        assert_eq!(cmd.get_env("TERM"), Some(OsStr::new("xterm-256color")));
        assert!(cmd.iter_full_env_as_str().all(|(_, v)| !v.contains(APPDIR)));
    }

    #[test]
    fn only_a_linux_appimage_has_an_appdir() {
        let env = |list: &'static [(&'static str, &'static str)]| {
            move |k: &str| list.iter().find(|(n, _)| *n == k).map(|(_, v)| OsString::from(v))
        };
        assert_eq!(appdir_from(env(&[("APPDIR", APPDIR)])), None, "APPDIR alone is not an AppImage");
        assert_eq!(appdir_from(env(&[("APPIMAGE", "/home/k/omher.AppImage")])), None);
        assert_eq!(appdir_from(env(&[("APPIMAGE", "/home/k/omher.AppImage"), ("APPDIR", "")])), None);
        let both = appdir_from(env(&[("APPIMAGE", "/home/k/omher.AppImage"), ("APPDIR", APPDIR)]));
        if cfg!(target_os = "linux") {
            assert_eq!(both, Some(OsString::from(APPDIR)));
        } else {
            assert_eq!(both, None, "macOS and Windows never edit a command's environment");
        }
    }
}

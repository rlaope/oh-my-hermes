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

use std::ffi::{OsStr, OsString};

/// For each variable whose value names `appdir`, what it should be for a host program: the
/// `:`-separated entries under `appdir` removed (`Some(rest)`), or the variable removed entirely (`None`)
/// when nothing else is left. Variables that do not mention `appdir` are not listed. Works entry by entry
/// rather than from a list of names, since AppImage hooks set different variables from one build to the next.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))] // used on Linux only; its tests run everywhere
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

#[cfg(target_os = "linux")]
mod imp {
    use std::path::Path;
    use std::process::Stdio;
    use std::time::{Duration, Instant};

    /// How long a launcher gets to fail before omher counts the hand-off as done (the `open` crate's own value).
    const SETTLE: Duration = Duration::from_millis(250);

    fn appdir() -> Option<std::ffi::OsString> {
        std::env::var_os("APPIMAGE").and(std::env::var_os("APPDIR")).filter(|d| !d.is_empty())
    }

    /// Hand `target` (a URL or an absolute file path) to the desktop's default handler.
    pub(crate) fn open(target: &str) -> Result<(), String> {
        let Some(appdir) = appdir() else {
            return if target.starts_with('/') {
                tauri_plugin_opener::open_path(target, None::<&str>).map_err(|e| e.to_string())
            } else {
                tauri_plugin_opener::open_url(target, None::<&str>).map_err(|e| e.to_string())
            };
        };
        let edits = super::host_env_edits(std::env::vars_os(), &appdir);
        let cwd = std::env::var_os("HOME").filter(|h| Path::new(h).is_dir()).unwrap_or_else(|| "/".into());
        let mut last = String::from("no program to open links with (install xdg-utils)");
        for mut cmd in open::commands(target) {
            for (k, v) in &edits {
                match v {
                    Some(v) => cmd.env(k, v),
                    None => cmd.env_remove(k),
                };
            }
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
    use super::host_env_edits;
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
}

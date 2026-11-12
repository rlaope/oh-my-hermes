//! First run without Hermes: the one installer omher may run.
//!
//! When the shell cannot find Hermes' Python, the UI offers to install Hermes and oh-my-hermes. The
//! command is FIXED here: OMH's own one-line installer with the `omher@beta` argument and
//! `OMH_WITH_DESKTOP=0` (Hermes when missing, then OMH; the app is already installed). Nothing the UI
//! sends reaches the command line: the Tauri command takes no text from the page.
//!
//! Neither command pipes the download into the interpreter. `curl … | sh` exits 0 when curl fails (sh
//! runs an empty script), and `install.ps1` run as a script block never reaches its own `exit`, so a
//! failed install would look like a clean one. Unix downloads to a temp file first and runs it only
//! when the download succeeded; Windows ends the command with `exit $LASTEXITCODE`, which
//! `install.ps1` sets on failure, and turns a failed download into exit 1.

use std::io::{BufRead, BufReader, Read};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;

use serde::Serialize;

use crate::bridge::Os;

/// The program, arguments and extra environment of the one installer run. All `'static`: there is no
/// way to build it from a runtime string.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstallCommand {
    pub program: &'static str,
    pub args: &'static [&'static str],
    pub env: &'static [(&'static str, &'static str)],
}

const ENV: &[(&str, &str)] = &[("OMH_WITH_DESKTOP", "0"), ("NO_COLOR", "1")];

const UNIX: InstallCommand = InstallCommand {
    program: "/bin/sh",
    args: &[
        "-c",
        "f=$(mktemp) && trap 'rm -f \"$f\"' EXIT && curl -fsSL -o \"$f\" https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh && sh \"$f\" omher@beta",
    ],
    env: ENV,
};

const WINDOWS: InstallCommand = InstallCommand {
    program: "powershell.exe",
    args: &[
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "$ErrorActionPreference = 'Stop'; try { & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta } catch { $_.Exception.Message; exit 1 }; exit $LASTEXITCODE",
    ],
    env: ENV,
};

pub fn install_command(os: Os) -> &'static InstallCommand {
    match os {
        Os::Unix => &UNIX,
        Os::Windows => &WINDOWS,
    }
}

/// What the setup screen shows as "this is what will run", in the form a person would type it: the
/// documented one-liner with the same URL, argument and `OMH_WITH_DESKTOP=0`. The run itself downloads
/// first (see the module note), which matters for its exit status, not for what it installs.
pub fn display_line(os: Os) -> &'static str {
    match os {
        Os::Unix => "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_WITH_DESKTOP=0 sh -s -- omher@beta",
        Os::Windows => "$env:OMH_WITH_DESKTOP = '0'; & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta",
    }
}

/// One line for the screen: colour codes and carriage-return redraws (progress bars) removed, so the
/// person sees the newest state of the line as plain text.
pub fn clean_line(raw: &str) -> String {
    let last = raw.trim_end_matches(['\r', '\n']).rsplit('\r').next().unwrap_or("");
    let mut out = String::with_capacity(last.len());
    let mut chars = last.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            if chars.peek() == Some(&'[') {
                chars.next();
                // CSI: parameters and intermediates, then one final byte in @..~
                for d in chars.by_ref() {
                    if ('@'..='~').contains(&d) {
                        break;
                    }
                }
            } else {
                chars.next();
            }
            continue;
        }
        if c.is_control() && c != '\t' {
            continue;
        }
        out.push(c);
    }
    out.trim_end().to_string()
}

/// What the screen is told after an installer that exited 0 when Hermes still cannot be found.
pub const INSTALLED_BUT_NOT_FOUND: &str =
    "Install finished but Hermes was not found. The output above shows where the installer put it.";

/// Exit 0 is trusted only when Hermes can now be found; anything else is returned as it came.
pub fn check_installed(code: Option<i32>, hermes_found: bool) -> Result<Option<i32>, String> {
    if code == Some(0) && !hermes_found {
        return Err(INSTALLED_BUT_NOT_FOUND.to_string());
    }
    Ok(code)
}

/// Streamed to the setup screen through a Tauri channel.
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum InstallEvent {
    Line { text: String },
    Exit { code: Option<i32> },
}

/// Run the fixed installer, sending every output line to `emit`, and return its exit code.
pub fn run_install<F: FnMut(InstallEvent)>(cmd: &InstallCommand, mut emit: F) -> Result<Option<i32>, String> {
    let mut command = Command::new(cmd.program);
    command.args(cmd.args).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    for (k, v) in cmd.env {
        command.env(k, v);
    }
    crate::bridge::no_console_window(&mut command);
    crate::appimage::host_env(&mut command);
    let mut child = command.spawn().map_err(|e| format!("could not start the installer ({}): {e}", cmd.program))?;
    let (tx, rx) = mpsc::channel::<String>();
    let readers: Vec<_> = [
        child.stdout.take().map(|s| Box::new(s) as Box<dyn Read + Send>),
        child.stderr.take().map(|s| Box::new(s) as Box<dyn Read + Send>),
    ]
    .into_iter()
    .flatten()
    .map(|stream| {
        let tx = tx.clone();
        thread::spawn(move || {
            for line in BufReader::new(stream).split(b'\n').map_while(Result::ok) {
                let _ = tx.send(String::from_utf8_lossy(&line).into_owned());
            }
        })
    })
    .collect();
    drop(tx);
    for raw in rx {
        let text = clean_line(&raw);
        if !text.is_empty() {
            emit(InstallEvent::Line { text });
        }
    }
    for r in readers {
        let _ = r.join();
    }
    let status = child.wait().map_err(|e| format!("the installer did not finish: {e}"))?;
    emit(InstallEvent::Exit { code: status.code() });
    Ok(status.code())
}

#[cfg(test)]
mod tests {
    use super::*;

    const INSTALL_SH_URL: &str = "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh";
    const INSTALL_PS1_URL: &str = "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1";

    /// Test only: the production Unix command with its URL swapped for `url`, so a run never touches the
    /// network. Everything else (the download-then-run script, the argument, the env) is the real one.
    #[cfg(unix)]
    fn unix_command_from(url: &str) -> InstallCommand {
        let script = UNIX.args[1];
        assert_eq!(script.matches(INSTALL_SH_URL).count(), 1);
        let leaked: &'static str = Box::leak(script.replace(INSTALL_SH_URL, url).into_boxed_str());
        let args: &'static [&'static str] = Box::leak(vec!["-c", leaked].into_boxed_slice());
        InstallCommand { program: UNIX.program, args, env: UNIX.env }
    }

    #[cfg(unix)]
    fn scratch(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("omher-setup-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[cfg(unix)]
    #[test]
    fn a_failed_download_is_a_failed_install_not_exit_0() {
        // the old `curl … | sh -s` form exited 0 here: sh ran an empty script
        let dir = scratch("missing");
        let cmd = unix_command_from(&format!("file://{}/no-such-install.sh", dir.display()));
        let code = run_install(&cmd, |_| {}).unwrap();
        assert!(matches!(code, Some(c) if c != 0), "{code:?}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn a_failing_installer_script_passes_its_exit_code_through() {
        let dir = scratch("failing");
        let script = dir.join("install.sh");
        std::fs::write(&script, "echo \"[failed] args=$* desktop=$OMH_WITH_DESKTOP\"\nexit 7\n").unwrap();
        let cmd = unix_command_from(&format!("file://{}", script.display()));
        let mut seen = Vec::new();
        let code = run_install(&cmd, |e| seen.push(e)).unwrap();
        assert_eq!(code, Some(7));
        assert!(seen.contains(&InstallEvent::Line { text: "[failed] args=omher@beta desktop=0".into() }), "{seen:?}");
        // and a script that succeeds is exit 0, with the temp file gone afterwards
        std::fs::write(&script, "echo ok\n").unwrap();
        assert_eq!(run_install(&cmd, |_| {}).unwrap(), Some(0));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn exit_0_counts_only_when_hermes_is_found_afterwards() {
        assert_eq!(check_installed(Some(0), true), Ok(Some(0)));
        assert_eq!(check_installed(Some(0), false), Err(INSTALLED_BUT_NOT_FOUND.to_string()));
        assert!(INSTALLED_BUT_NOT_FOUND.starts_with("Install finished but Hermes was not found"));
        assert_eq!(check_installed(Some(3), false), Ok(Some(3)));
        assert_eq!(check_installed(None, true), Ok(None));
    }

    #[test]
    fn the_command_is_the_fixed_omher_beta_one_liner_without_the_app() {
        let unix = install_command(Os::Unix);
        assert_eq!(unix.program, "/bin/sh");
        assert_eq!(
            unix.args,
            [
                "-c",
                "f=$(mktemp) && trap 'rm -f \"$f\"' EXIT && curl -fsSL -o \"$f\" https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh && sh \"$f\" omher@beta"
            ]
        );
        // downloaded to a file, never piped: a failed curl must not reach sh
        assert!(unix.args[1].contains(&format!("curl -fsSL -o \"$f\" {INSTALL_SH_URL} && sh")));
        assert!(!unix.args[1].contains('|'));
        let win = install_command(Os::Windows);
        assert_eq!(win.program, "powershell.exe");
        assert_eq!(
            win.args.last().copied(),
            Some("$ErrorActionPreference = 'Stop'; try { & ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta } catch { $_.Exception.Message; exit 1 }; exit $LASTEXITCODE")
        );
        assert!(win.args.last().unwrap().ends_with("; exit $LASTEXITCODE"));
        assert!(win.args.last().unwrap().contains(INSTALL_PS1_URL));
        for cmd in [unix, win] {
            assert!(cmd.env.contains(&("OMH_WITH_DESKTOP", "0")), "{cmd:?}");
            assert_eq!(cmd.env.len(), 2, "{cmd:?}");
        }
    }

    #[test]
    fn the_tauri_command_takes_no_text_from_the_page() {
        // The command's parameters are the app state and the output channel, nothing a page could fill.
        // a Windows checkout has CRLF line endings (git autocrlf); read the source with LF so the searches hold
        let lib = include_str!("lib.rs").replace("\r\n", "\n");
        let lib = lib.as_str();
        let start = lib.find("async fn install_engine(").expect("install_engine command");
        let sig = &lib[start..start + lib[start..].find(") ->").unwrap()];
        assert!(!sig.contains("String") && !sig.contains("&str") && !sig.contains("Vec<"), "{sig}");
        assert!(sig.contains("Channel<InstallEvent>"), "{sig}");
        // and it runs exactly the fixed command
        let body_end = start + lib[start..].find("\n}\n").unwrap();
        let body = &lib[start..body_end];
        assert!(body.contains("install_command(Os::current())"), "{body}");
        assert_eq!(lib.matches("run_install(").count(), 1);
    }

    #[test]
    fn display_lines_show_the_same_command() {
        for os in [Os::Unix, Os::Windows] {
            let shown = display_line(os);
            let cmd = install_command(os);
            let script = cmd.args.last().unwrap();
            // The shown line is the documented one-liner: the same URL and argument as the run, with the
            // one env var written inline.
            assert!(shown.contains("OMH_WITH_DESKTOP") && shown.contains("omher@beta"), "{shown}");
            let url = if os == Os::Unix { INSTALL_SH_URL } else { INSTALL_PS1_URL };
            assert!(shown.contains(url) && script.contains(url), "{shown}");
            assert!(script.contains(" omher@beta"), "{script}");
        }
    }

    #[test]
    fn lines_lose_colour_codes_and_progress_redraws() {
        assert_eq!(clean_line("\u{1b}[1;32m[ok]\u{1b}[0m done\n"), "[ok] done");
        assert_eq!(clean_line("Downloading 10%\rDownloading 55%\rDownloading 100%\r\n"), "Downloading 100%");
        assert_eq!(clean_line("tab\tkept\u{7}"), "tab\tkept");
        assert_eq!(clean_line("\u{1b}[2K\u{1b}[1Gplain"), "plain");
    }

    #[cfg(unix)]
    #[test]
    fn run_install_streams_both_streams_and_reports_the_exit_code() {
        let cmd = InstallCommand {
            program: "/bin/sh",
            args: &["-c", "echo \"one $OMH_WITH_DESKTOP\"; printf 'two\\r three\\n' >&2; exit 3"],
            env: ENV,
        };
        let mut seen = Vec::new();
        let code = run_install(&cmd, |e| seen.push(e)).unwrap();
        assert_eq!(code, Some(3));
        let lines: Vec<String> = seen
            .iter()
            .filter_map(|e| match e {
                InstallEvent::Line { text } => Some(text.clone()),
                _ => None,
            })
            .collect();
        assert!(lines.contains(&"one 0".to_string()), "{lines:?}");
        assert!(lines.contains(&" three".to_string()), "{lines:?}");
        assert_eq!(seen.last(), Some(&InstallEvent::Exit { code: Some(3) }));
    }

    #[test]
    fn events_serialise_for_the_screen() {
        assert_eq!(
            serde_json::to_string(&InstallEvent::Line { text: "x".into() }).unwrap(),
            r#"{"kind":"line","text":"x"}"#
        );
        assert_eq!(serde_json::to_string(&InstallEvent::Exit { code: Some(0) }).unwrap(), r#"{"kind":"exit","code":0}"#);
    }
}

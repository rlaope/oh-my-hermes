//! First run without Hermes: the one installer omher may run.
//!
//! When the shell cannot find Hermes' Python, the UI offers to install Hermes and oh-my-hermes. The
//! command is FIXED here: OMH's own one-line installer with the `omher@beta` argument and
//! `OMH_WITH_DESKTOP=0` (Hermes when missing, then OMH; the app is already installed). Nothing the UI
//! sends reaches the command line: the Tauri command takes no text from the page.

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
        "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta",
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
        "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta",
    ],
    env: ENV,
};

pub fn install_command(os: Os) -> &'static InstallCommand {
    match os {
        Os::Unix => &UNIX,
        Os::Windows => &WINDOWS,
    }
}

/// What the setup screen shows as "this is what will run", in the form a person would type it.
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

    #[test]
    fn the_command_is_the_fixed_omher_beta_one_liner_without_the_app() {
        let unix = install_command(Os::Unix);
        assert_eq!(unix.program, "/bin/sh");
        assert_eq!(
            unix.args,
            ["-c", "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta"]
        );
        assert!(unix.args[1].starts_with(&format!("curl -fsSL {INSTALL_SH_URL} |")));
        let win = install_command(Os::Windows);
        assert_eq!(win.program, "powershell.exe");
        assert_eq!(
            win.args.last().copied(),
            Some("& ([scriptblock]::Create((irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1))) omher@beta")
        );
        assert!(win.args.last().unwrap().contains(INSTALL_PS1_URL));
        for cmd in [unix, win] {
            assert!(cmd.env.contains(&("OMH_WITH_DESKTOP", "0")), "{cmd:?}");
            assert_eq!(cmd.env.len(), 2, "{cmd:?}");
        }
    }

    #[test]
    fn the_tauri_command_takes_no_text_from_the_page() {
        // The command's parameters are the app state and the output channel, nothing a page could fill.
        let lib = include_str!("lib.rs");
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
            // The shown line is the run command with the one env var written inline.
            assert!(shown.contains("OMH_WITH_DESKTOP") && shown.contains("omher@beta"), "{shown}");
            assert_eq!(shown.replace("OMH_WITH_DESKTOP=0 ", "").replace("$env:OMH_WITH_DESKTOP = '0'; ", ""), *script);
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

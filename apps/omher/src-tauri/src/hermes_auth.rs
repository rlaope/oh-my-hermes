//! Settings › Providers "Add key": open the person's own system terminal running exactly
//! `hermes auth add <provider> --type api-key` (BOUNDARY rule 23). Hermes asks for the key in that terminal
//! and stores it itself; omher never asks for, accepts, reads or shows it, and never types into the window
//! (that is why this is not one of omher's own pseudo-terminals).
//!
//! The chat's connect block opens the same terminal with the second fixed form, `hermes auth add <id>` (no
//! `--type`: Hermes runs that provider's own sign-in), only for the ids in `SIGN_IN`; any other id is refused.
//!
//! The provider id is checked with `^[a-z0-9][a-z0-9_-]{0,40}$` and is always one argument; nothing from the
//! page becomes a shell string. On macOS the terminal is opened through LaunchServices with a one-off
//! `.command` file (no Apple Events permission needed) that is written from the shell-quoted `hermes` path
//! plus the checked id and deletes itself when it runs.
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::accounts::{resolve, search_dirs};
use crate::bridge::Os;

/// Which desktop the terminal is opened on. Passed in so every platform's argv is tested on any host.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Desk {
    Mac,
    Windows,
    Linux,
}

impl Desk {
    pub fn current() -> Desk {
        if cfg!(target_os = "macos") {
            Desk::Mac
        } else if cfg!(windows) {
            Desk::Windows
        } else {
            Desk::Linux
        }
    }
}

/// `^[a-z0-9][a-z0-9_-]{0,40}$`: a Hermes provider id (`openrouter`, `nous`, `claude-proxy`, `og`).
pub fn valid_provider(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 41
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-')
}

/// The arguments after `hermes`, fixed apart from the checked provider id.
pub fn auth_args(provider: &str) -> Result<[String; 5], String> {
    if !valid_provider(provider) {
        return Err("not a provider id".into());
    }
    Ok(["auth".into(), "add".into(), provider.into(), "--type".into(), "api-key".into()])
}

/// The only providers whose own sign-in the chat's connect block may open: ChatGPT / Codex, Claude, Nous Portal.
pub const SIGN_IN: [&str; 3] = ["openai-codex", "anthropic", "nous"];

/// The arguments after `hermes` for a sign-in: `auth add <id>`, the id one of `SIGN_IN`.
pub fn sign_in_args(provider: &str) -> Result<[String; 3], String> {
    if !SIGN_IN.contains(&provider) {
        return Err("not a sign-in provider".into());
    }
    Ok(["auth".into(), "add".into(), provider.into()])
}

/// Which of the two fixed argv forms: Settings' "Add key", or the connect block's sign-in.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Form {
    ApiKey,
    SignIn,
}

/// The arguments after `hermes` for one form.
pub fn form_args(form: Form, provider: &str) -> Result<Vec<String>, String> {
    match form {
        Form::ApiKey => auth_args(provider).map(Vec::from),
        Form::SignIn => sign_in_args(provider).map(Vec::from),
    }
}

/// `'…'` for a POSIX shell: the only special character inside single quotes is `'` itself.
pub fn sh_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', r"'\''"))
}

/// The body of the macOS `.command` file: remove itself, then exec `hermes auth add <id>` in the form's argv.
pub fn command_file(hermes: &Path, form: Form, provider: &str) -> Result<String, String> {
    let args = form_args(form, provider)?;
    let line: Vec<String> = std::iter::once(sh_quote(&hermes.to_string_lossy())).chain(args.iter().map(|a| sh_quote(a))).collect();
    Ok(format!("#!/bin/sh\nrm -f \"$0\"\nexec {}\n", line.join(" ")))
}

/// Terminal programs to try, in order, as (program, argv). `file` is the macOS `.command` path.
pub fn launchers(desk: Desk, hermes: &Path, form: Form, provider: &str, file: Option<&Path>) -> Result<Vec<(String, Vec<OsString>)>, String> {
    let args = form_args(form, provider)?;
    let tail = || -> Vec<OsString> { std::iter::once(hermes.as_os_str().to_owned()).chain(args.iter().map(OsString::from)).collect() };
    let with = |head: &[&str]| -> Vec<OsString> { head.iter().map(OsString::from).chain(tail()).collect() };
    Ok(match desk {
        Desk::Mac => {
            let f = file.ok_or("no command file")?;
            vec![("open".into(), vec!["-a".into(), "Terminal".into(), f.as_os_str().to_owned()])]
        }
        // `start` opens a new console window; its first quoted argument is the window title.
        Desk::Windows => vec![("cmd".into(), with(&["/c", "start", "", "cmd", "/k"]))],
        Desk::Linux => vec![
            ("x-terminal-emulator".into(), with(&["-e"])),
            ("gnome-terminal".into(), with(&["--"])),
            ("konsole".into(), with(&["-e"])),
            ("xfce4-terminal".into(), with(&["-x"])),
            ("xterm".into(), with(&["-e"])),
        ],
    })
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

#[cfg(unix)]
fn write_command_file(body: &str) -> Result<PathBuf, String> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let mut rnd = [0u8; 8];
    getrandom::fill(&mut rnd).map_err(|e| e.to_string())?;
    let name: String = rnd.iter().map(|b| format!("{b:02x}")).collect();
    let path = std::env::temp_dir().join(format!("omher-hermes-auth-{name}.command"));
    let mut f = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o700).open(&path).map_err(|e| e.to_string())?;
    f.write_all(body.as_bytes()).map_err(|e| e.to_string())?;
    Ok(path)
}

#[cfg(not(unix))]
fn write_command_file(_body: &str) -> Result<PathBuf, String> {
    Err("no command file on this system".into())
}

/// Open the system terminal running the form's `hermes auth add …`. Returns once the terminal program has
/// handed the window off (or exited).
pub fn open(form: Form, provider: &str) -> Result<(), String> {
    form_args(form, provider)?;
    let os = Os::current();
    let dirs = search_dirs(&host_env, os);
    let hermes = resolve("hermes", &dirs, is_program, os).ok_or("Hermes is not on this computer")?;
    let desk = Desk::current();
    let file = if desk == Desk::Mac { Some(write_command_file(&command_file(&hermes, form, provider)?)?) } else { None };
    let mut last = String::from("no terminal program found");
    for (program, argv) in launchers(desk, &hermes, form, provider, file.as_deref())? {
        let exe = if desk == Desk::Linux {
            match resolve(&program, &dirs, is_program, os) {
                Some(p) => p,
                None => continue,
            }
        } else {
            PathBuf::from(&program)
        };
        let mut cmd = Command::new(&exe);
        cmd.args(&argv).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        crate::appimage::host_env(&mut cmd);
        match cmd.status() {
            Ok(s) if s.success() => return Ok(()),
            Ok(s) => last = format!("{program} exited with {s}"),
            Err(e) => last = format!("{program}: {e}"),
        }
    }
    if let Some(f) = file {
        let _ = std::fs::remove_file(f);
    }
    Err(last)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_ids_are_checked() {
        for ok in ["openrouter", "nous", "claude-proxy", "og", "openai_codex", "0x", &"a".repeat(41)] {
            assert!(valid_provider(ok), "{ok}");
        }
        for bad in [
            "",
            "openrouter; rm -rf",
            "openrouter; rm -rf ~",
            "Openrouter",
            "-type",
            "_x",
            "a b",
            "a/b",
            "$(id)",
            "`id`",
            "a\"b",
            "a'b",
            "x\n",
            "é",
            &"a".repeat(42),
        ] {
            assert!(!valid_provider(bad), "{bad:?}");
            assert!(auth_args(bad).is_err());
            assert!(launchers(Desk::Linux, Path::new("/h/hermes"), Form::ApiKey, bad, None).is_err());
            assert!(command_file(Path::new("/h/hermes"), Form::ApiKey, bad).is_err());
        }
    }

    #[test]
    fn the_argv_is_fixed_apart_from_the_id() {
        assert_eq!(auth_args("openrouter").unwrap(), ["auth", "add", "openrouter", "--type", "api-key"]);
        let h = Path::new("/usr/local/bin/hermes");
        let tail = ["/usr/local/bin/hermes", "auth", "add", "nous", "--type", "api-key"];
        let os = |v: &[&str]| v.iter().map(OsString::from).collect::<Vec<_>>();
        let win = launchers(Desk::Windows, h, Form::ApiKey, "nous", None).unwrap();
        assert_eq!(win, vec![("cmd".to_string(), os(&[&["/c", "start", "", "cmd", "/k"][..], &tail].concat()))]);
        let lin = launchers(Desk::Linux, h, Form::ApiKey, "nous", None).unwrap();
        assert_eq!(lin[0], ("x-terminal-emulator".to_string(), os(&[&["-e"][..], &tail].concat())));
        assert_eq!(lin[1], ("gnome-terminal".to_string(), os(&[&["--"][..], &tail].concat())));
        assert_eq!(lin.iter().map(|l| l.0.as_str()).collect::<Vec<_>>(), ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]);
        // every launcher ends with the same six arguments, the id as one element
        for (_, argv) in &lin {
            assert_eq!(&argv[argv.len() - 6..], os(&tail).as_slice());
        }
        let mac = launchers(Desk::Mac, h, Form::ApiKey, "nous", Some(Path::new("/tmp/x.command"))).unwrap();
        assert_eq!(mac, vec![("open".to_string(), os(&["-a", "Terminal", "/tmp/x.command"]))]);
        assert!(launchers(Desk::Mac, h, Form::ApiKey, "nous", None).is_err());
    }

    #[test]
    fn the_command_file_quotes_the_path_and_runs_only_hermes_auth_add() {
        let body = command_file(Path::new("/Users/k k/it's/.local/bin/hermes"), Form::ApiKey, "openrouter").unwrap();
        assert_eq!(
            body,
            "#!/bin/sh\nrm -f \"$0\"\nexec '/Users/k k/it'\\''s/.local/bin/hermes' 'auth' 'add' 'openrouter' '--type' 'api-key'\n"
        );
        assert_eq!(body.lines().count(), 3);
    }

    #[test]
    fn sign_in_takes_only_the_three_ids() {
        for id in SIGN_IN {
            assert_eq!(sign_in_args(id).unwrap(), ["auth", "add", id]);
            assert_eq!(form_args(Form::SignIn, id).unwrap(), ["auth", "add", id]);
        }
        assert_eq!(SIGN_IN, ["openai-codex", "anthropic", "nous"]);
        // valid provider ids that are not on the list, look-alikes and injections are all refused
        for bad in [
            "openrouter",
            "openai",
            "claude-proxy",
            "og",
            "xai-oauth",
            "qwen-oauth",
            "Anthropic",
            "anthropic ",
            " nous",
            "nous\n",
            "openai-codex --type api-key",
            "anthropic; rm -rf ~",
            "$(id)",
            "",
        ] {
            assert!(sign_in_args(bad).is_err(), "{bad:?}");
            assert!(form_args(Form::SignIn, bad).is_err(), "{bad:?}");
            assert!(launchers(Desk::Linux, Path::new("/h/hermes"), Form::SignIn, bad, None).is_err(), "{bad:?}");
            assert!(launchers(Desk::Windows, Path::new("/h/hermes"), Form::SignIn, bad, None).is_err(), "{bad:?}");
            assert!(command_file(Path::new("/h/hermes"), Form::SignIn, bad).is_err(), "{bad:?}");
        }
        // the api-key form still takes any well-formed id, the sign-in form never adds `--type`
        assert!(form_args(Form::ApiKey, "openrouter").is_ok());
        assert!(!form_args(Form::SignIn, "anthropic").unwrap().iter().any(|a| a.starts_with("--")));
    }

    #[test]
    fn sign_in_uses_the_same_launchers_with_the_short_argv() {
        let h = Path::new("/usr/local/bin/hermes");
        let os = |v: &[&str]| v.iter().map(OsString::from).collect::<Vec<_>>();
        let tail = ["/usr/local/bin/hermes", "auth", "add", "anthropic"];
        let win = launchers(Desk::Windows, h, Form::SignIn, "anthropic", None).unwrap();
        assert_eq!(win, vec![("cmd".to_string(), os(&[&["/c", "start", "", "cmd", "/k"][..], &tail].concat()))]);
        let lin = launchers(Desk::Linux, h, Form::SignIn, "anthropic", None).unwrap();
        assert_eq!(lin.iter().map(|l| l.0.as_str()).collect::<Vec<_>>(), ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]);
        for (_, argv) in &lin {
            assert_eq!(&argv[argv.len() - 4..], os(&tail).as_slice());
        }
        let mac = launchers(Desk::Mac, h, Form::SignIn, "anthropic", Some(Path::new("/tmp/x.command"))).unwrap();
        assert_eq!(mac, vec![("open".to_string(), os(&["-a", "Terminal", "/tmp/x.command"]))]);
        let body = command_file(Path::new("/Users/k k/.local/bin/hermes"), Form::SignIn, "openai-codex").unwrap();
        assert_eq!(body, "#!/bin/sh\nrm -f \"$0\"\nexec '/Users/k k/.local/bin/hermes' 'auth' 'add' 'openai-codex'\n");
    }
}

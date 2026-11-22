// `main` hands `omher --statusline-relay <account>` to the relay before anything of the app starts (claude_usage.rs):
// the built binary, run as a TERMINALS Claude Code's status line runs it, records the usage and prints the person's own
// status line unchanged. Unix only: the relay runs only on macOS and Linux.
#![cfg(unix)]
use std::io::Write;
use std::process::{Command, Stdio};

fn run(home: &std::path::Path, args: &[&str], input: &str) -> (Vec<u8>, i32) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_omher"))
        .args(args)
        .env("HOME", home)
        .env_remove("CLAUDE_CONFIG_DIR")
        .env_remove("CLAUDE_CODE_SHELL_PREFIX")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(input.as_bytes()).unwrap();
    let out = child.wait_with_output().unwrap();
    (out.stdout, out.status.code().unwrap_or(-1))
}

#[test]
fn main_runs_the_relay_before_the_app_and_prints_the_person_s_line() {
    let home = std::env::temp_dir().join(format!("omher-relay-main-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(home.join(".claude")).unwrap();
    let input = r#"{"workspace":{"project_dir":"/nonexistent-omher"},"rate_limits":{"seven_day":{"used_percentage":6,"resets_at":4102444800}}}"#;
    // no status line of their own: nothing printed, exit 0, the record written
    assert_eq!(run(&home, &["--statusline-relay", "default"], input), (Vec::new(), 0));
    let rec = std::fs::read_to_string(home.join(".omher/usage/claude/default.json")).unwrap();
    assert!(rec.contains(r#""seven_day":{"resets_at":4102444800.0,"used_percent":6.0}"#), "{rec}");
    // their line: its output and exit code come back unchanged
    std::fs::write(home.join(".claude/settings.json"), r#"{"statusLine":{"type":"command","command":"printf 'mine'; exit 4"}}"#).unwrap();
    assert_eq!(run(&home, &["--statusline-relay", "work"], input), (b"mine".to_vec(), 4));
    // an account omher does not give: the line still runs and nothing is recorded under any name
    assert_eq!(run(&home, &["--statusline-relay", "../Bad"], input), (b"mine".to_vec(), 4));
    let mut names: Vec<String> = std::fs::read_dir(home.join(".omher/usage/claude")).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
    names.sort();
    assert_eq!(names, ["default.json", "work.json"]);
    let _ = std::fs::remove_dir_all(&home);
}

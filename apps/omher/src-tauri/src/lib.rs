mod accounts;
mod agent_chat;
mod bridge;
mod sessions;
mod setup;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use agent_chat::{ChatOut, ChatSessions};
use bridge::{Bridge, BridgeStatus, Os};
use sessions::{AgentInfo, Output, Sessions};
use setup::InstallEvent;
use tauri::ipc::{Channel, InvokeResponseBody};
use tauri::{Manager, RunEvent, State};

struct Shell {
    bridge: Arc<Bridge>,
    resource_dir: Option<PathBuf>,
    installing: Arc<AtomicBool>,
    logins: Arc<accounts::Logins>,
    sessions: Arc<Sessions>,
    chats: Arc<ChatSessions>,
}

/// `ws://127.0.0.1:<port>/?token=<token>` once the bridge is ready.
#[tauri::command]
async fn bridge_url(shell: State<'_, Shell>) -> Result<String, String> {
    shell.bridge.url(Duration::from_secs(2))
}

/// `{state: "ready" | "starting" | "failed", error?}`.
#[tauri::command]
async fn bridge_status(shell: State<'_, Shell>) -> Result<BridgeStatus, String> {
    Ok(shell.bridge.status())
}

/// Open a thread in its own app. Only Slack / Discord / Telegram links, and a plan node's GitHub pull request:
/// omher never opens arbitrary URLs.
/// The system opener (`open` on macOS, the shell's URL handler on Windows, `xdg-open` on Linux) hands the
/// link to the person's own Slack / Discord / browser.
#[tauri::command]
async fn open_external(url: String) -> Result<(), String> {
    if !allowed_external(&url) {
        return Err("not a Slack, Discord or Telegram link".into());
    }
    // A Discord web link opens the Discord app when it is installed, the browser otherwise.
    if let Some(app_url) = discord_app_url(&url) {
        if discord_app_installed() && tauri_plugin_opener::open_url(&app_url, None::<&str>).is_ok() {
            return Ok(());
        }
    }
    tauri_plugin_opener::open_url(&url, None::<&str>).map_err(|e| e.to_string())
}

/// `https://discord.com/channels/G/C` -> `discord://discord.com/channels/G/C` (the form the Discord app
/// routes to that exact channel or thread).
pub(crate) fn discord_app_url(url: &str) -> Option<String> {
    url.strip_prefix("https://discord.com/channels/")
        .map(|rest| format!("discord://discord.com/channels/{rest}"))
}

/// Whether the Discord desktop app is there to take `discord://`. macOS and Linux report a missing handler as
/// an open error (so the browser fallback runs); Windows would show an "find an app" dialog instead, so there
/// we look for the app first.
fn discord_app_installed() -> bool {
    #[cfg(windows)]
    {
        std::env::var_os("LOCALAPPDATA")
            .map(|d| {
                let d = PathBuf::from(d);
                ["Discord", "DiscordPTB", "DiscordCanary"].iter().any(|n| d.join(n).join("Update.exe").is_file())
            })
            .unwrap_or(false)
    }
    #[cfg(not(windows))]
    {
        true
    }
}

pub(crate) fn allowed_external(url: &str) -> bool {
    const PREFIXES: [&str; 5] = [
        "slack://channel?",
        "https://app.slack.com/",
        "https://discord.com/channels/",
        "discord://discord.com/channels/",
        "https://t.me/",
    ];
    !url.chars().any(|c| c.is_whitespace() || c.is_control())
        && (PREFIXES.iter().any(|p| url.starts_with(p)) || github_pr_url(url))
}

/// `https://github.com/<owner>/<repo>/pull/<n>` and nothing after it: the pull request a plan node opened (the
/// Plans graph's `#2746`), shown in the browser when the person clicks it.
pub(crate) fn github_pr_url(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("https://github.com/") else { return false };
    let parts: Vec<&str> = rest.split('/').collect();
    let name = |s: &str, first: bool| {
        !s.is_empty()
            && s.len() <= 100
            && s != "."
            && s != ".."
            && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || (!first && (c == '_' || c == '.')))
    };
    parts.len() == 4
        && name(parts[0], true)
        && name(parts[1], false)
        && parts[2] == "pull"
        && !parts[3].is_empty()
        && parts[3].len() <= 7
        && parts[3].bytes().all(|b| b.is_ascii_digit())
}

/// The line the first-run screen shows as what Install will run.
#[tauri::command]
async fn install_engine_command() -> Result<String, String> {
    Ok(setup::display_line(Os::current()).to_string())
}

/// Install Hermes and oh-my-hermes with OMH's fixed one-line installer (the first-run screen's Install
/// button), streaming its output to the screen, then start the bridge again. Takes nothing from the
/// page but the output channel; one run at a time.
#[tauri::command]
async fn install_engine(shell: State<'_, Shell>, on_event: Channel<InstallEvent>) -> Result<Option<i32>, String> {
    if shell.installing.swap(true, Ordering::SeqCst) {
        return Err("the installer is already running".into());
    }
    let installing = Arc::clone(&shell.installing);
    let result = tauri::async_runtime::spawn_blocking(move || {
        setup::run_install(setup::install_command(Os::current()), |e| {
            let _ = on_event.send(e);
        })
    })
    .await
    .map_err(|e| e.to_string());
    installing.store(false, Ordering::SeqCst);
    let code = result??;
    // An installer can exit 0 without leaving Hermes where omher looks; say so instead of showing the
    // setup screen again as if nothing had run.
    let found = code != Some(0) || bridge::discover_python(|k| std::env::var(k).ok(), |p| p.is_file()).is_ok();
    let code = setup::check_installed(code, found)?;
    if code == Some(0) {
        shell.bridge.start(shell.resource_dir.clone());
    }
    Ok(code)
}

fn user_home() -> Result<PathBuf, String> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| "no home folder".to_string())
}

/// The env a new session of `cli` starts with to use omher account `id` (`default` = the CLI's own home).
/// SESSIONS calls this when it starts an agent with the account picked for new sessions.
#[tauri::command]
async fn account_env(cli: String, id: String) -> Result<Vec<(String, String)>, String> {
    accounts::account_env(&user_home()?, &cli, &id)
}

/// Which coding CLIs are on this computer (PATH and the install folders a Dock-started app does not see).
#[tauri::command]
async fn account_clis() -> Result<Vec<(&'static str, bool)>, String> {
    tauri::async_runtime::spawn_blocking(accounts::clis_on_this_computer).await.map_err(|e| e.to_string())
}

/// The CLI's own login status for account `id`, through its fixed status command (Claude Code, Codex). Only
/// signed in / email / plan / method come back; `null` for CLIs that have no status command.
#[tauri::command]
async fn account_status(cli: String, id: String) -> Result<Option<accounts::LoginStatus>, String> {
    let home = user_home()?;
    tauri::async_runtime::spawn_blocking(move || accounts::status(&home, &cli, &id)).await.map_err(|e| e.to_string())?
}

/// Start the CLI's own sign-in (`claude auth login`, `codex login`) with omher account `id` as its home. The
/// browser part happens in the CLI; its plain output lines and then its exit arrive on `on_event`.
#[tauri::command]
async fn account_login_start(
    shell: State<'_, Shell>,
    cli: String,
    id: String,
    on_event: tauri::ipc::Channel<accounts::LoginEvent>,
) -> Result<u32, String> {
    shell.logins.start(&user_home()?, &cli, &id, move |ev| {
        let _ = on_event.send(ev);
    })
}

/// Cancel a sign-in started above. Its exit still arrives on its channel.
#[tauri::command]
async fn account_login_cancel(shell: State<'_, Shell>, login: u32) -> Result<(), String> {
    shell.logins.cancel(login);
    Ok(())
}

/// The allow-listed agent programs (claude, codex, omh, pi, omp, grok), how each opens and where each
/// was found, if anywhere.
#[tauri::command]
async fn sessions_agents() -> Result<Vec<AgentInfo>, String> {
    Ok(tauri::async_runtime::spawn_blocking(sessions::agents_on_this_machine).await.map_err(|e| e.to_string())?)
}

/// Start allow-listed agent `agent` in folder `cwd` in a new pseudo-terminal (its own terminal UI). Only an
/// agent id crosses from the UI: no program path, command line or argument; `resume` is a Claude Code
/// session id that the shell checks is one (so the terminal view continues a chat); `account` is the account a
/// session restarted after an app restart ran with (checked by `accounts::session_env_for`). Terminal output goes
/// to `on_data` as raw bytes, the exit code (null after a signal) once to `on_exit`.
#[tauri::command]
async fn session_start(
    shell: State<'_, Shell>,
    agent: String,
    cwd: String,
    resume: Option<String>,
    account: Option<String>,
    cols: u16,
    rows: u16,
    on_data: Channel<InvokeResponseBody>,
    on_exit: Channel<Option<u32>>,
) -> Result<u32, String> {
    let sessions = shell.sessions.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // The account Settings › Accounts picked for new sessions of this agent's CLI (or, for a session started
        // again after a restart, the one it ran with): its home variable, or nothing ("This computer").
        // chat_start passes the same.
        let account_env = user_home().map(|h| accounts::session_env_for(&h, &agent, account.as_deref())).unwrap_or_default();
        sessions.start_agent(&agent, std::path::Path::new(&cwd), resume.as_deref(), &account_env, cols, rows, move |ev| match ev {
            Output::Data(b) => {
                let _ = on_data.send(InvokeResponseBody::Raw(b));
            }
            Output::Exit(code) => {
                let _ = on_exit.send(code);
            }
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Keystrokes (and pastes) from the terminal view into session `id`.
#[tauri::command]
async fn session_write(shell: State<'_, Shell>, id: u32, data: String) -> Result<(), String> {
    shell.sessions.write(id, data.as_bytes())
}

#[tauri::command]
async fn session_resize(shell: State<'_, Shell>, id: u32, cols: u16, rows: u16) -> Result<(), String> {
    shell.sessions.resize(id, cols, rows)
}

/// Stop the session's program and forget the session.
#[tauri::command]
async fn session_close(shell: State<'_, Shell>, id: u32) -> Result<(), String> {
    shell.sessions.close(id);
    Ok(())
}

/// Stop every session. `main.tsx` calls this once per page load, before any UI renders, so a reloaded
/// window leaves nothing running unseen.
#[tauri::command]
async fn session_close_all(shell: State<'_, Shell>) -> Result<(), String> {
    let sessions = shell.sessions.clone();
    tauri::async_runtime::spawn_blocking(move || sessions.close_all()).await.map_err(|e| e.to_string())
}

/// Start allow-listed agent `agent` in folder `cwd` as a chat: its structured mode (the fixed arguments in
/// the allow-list), with events for the chat view on `on_event` and, once, `{event:"exit", code, error}`.
/// Only an agent id, a folder, optionally a Claude Code session id or Codex thread id, and optionally the account a
/// restarted session ran with cross from the UI.
#[tauri::command]
async fn chat_start(shell: State<'_, Shell>, agent: String, cwd: String, resume: Option<String>, account: Option<String>, on_event: Channel<serde_json::Value>) -> Result<u32, String> {
    let chats = shell.chats.clone();
    tauri::async_runtime::spawn_blocking(move || {
        // The same account as a terminal session of this agent: its home variable, or nothing ("This computer").
        let account_env = user_home().map(|h| accounts::session_env_for(&h, &agent, account.as_deref())).unwrap_or_default();
        chats.start_agent(&agent, std::path::Path::new(&cwd), resume.as_deref(), &account_env, move |out| {
            let _ = on_event.send(match out {
                ChatOut::Event(e) => e,
                ChatOut::Exit(code, error) => serde_json::json!({"event": "exit", "code": code, "error": error}),
            });
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

/// What the person did in chat `id`: `{kind:"send", text}`, `{kind:"interrupt"}`,
/// `{kind:"approve", request_id, choice}`, `{kind:"clarify", request_id, answer}`, `{kind:"model", model}`.
#[tauri::command]
async fn chat_input(shell: State<'_, Shell>, id: u32, input: agent_chat::Input) -> Result<(), String> {
    let chats = shell.chats.clone();
    tauri::async_runtime::spawn_blocking(move || chats.input(id, input)).await.map_err(|e| e.to_string())?
}

/// Stop the chat's program and forget the session.
#[tauri::command]
async fn chat_close(shell: State<'_, Shell>, id: u32) -> Result<(), String> {
    shell.chats.close(id);
    Ok(())
}

/// Stop every chat (the UI calls this when it loads, like `session_close_all`).
#[tauri::command]
async fn chat_close_all(shell: State<'_, Shell>) -> Result<(), String> {
    let chats = shell.chats.clone();
    tauri::async_runtime::spawn_blocking(move || chats.close_all()).await.map_err(|e| e.to_string())
}

/// Open a file the bot sent, with the system's default app, or show it in Finder / Explorer
/// (`reveal: true`). Only a file the bridge just served through `media.read` (the bot named it in a
/// `MEDIA:` line) may be opened; any other path is refused.
#[tauri::command]
async fn open_media(shell: State<'_, Shell>, path: String, reveal: Option<bool>) -> Result<(), String> {
    let path = media_target(&path, |p| shell.bridge.served_media(p))?;
    if reveal.unwrap_or(false) {
        tauri_plugin_opener::reveal_item_in_dir(&path).map_err(|e| e.to_string())
    } else {
        tauri_plugin_opener::open_path(&path, None::<&str>).map_err(|e| e.to_string())
    }
}

/// The path to open, when `served` knows it and it is still a plain file.
pub(crate) fn media_target<S: Fn(&str) -> bool>(path: &str, served: S) -> Result<PathBuf, String> {
    let p = PathBuf::from(path);
    if path.is_empty() || !p.is_absolute() || !served(path) || !p.is_file() {
        return Err("not a file this bot sent".into());
    }
    Ok(p)
}

/// Start the bridge again (the Retry button on the failed screen).
#[tauri::command]
async fn bridge_retry(shell: State<'_, Shell>) -> Result<(), String> {
    shell.bridge.start(shell.resource_dir.clone());
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        // In-app updates: the UI checks the fixed GitHub endpoint in tauri.conf.json and installs only a
        // build signed with the key whose public half is pinned there; process restarts into it.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            bridge_url,
            bridge_status,
            bridge_retry,
            open_external,
            install_engine,
            install_engine_command,
            account_env,
            account_clis,
            account_status,
            account_login_start,
            account_login_cancel,
            sessions_agents,
            session_start,
            session_write,
            session_resize,
            session_close,
            session_close_all,
            chat_start,
            chat_input,
            chat_close,
            chat_close_all,
            open_media
        ])
        .setup(|app| {
            let bridge = Bridge::new();
            let resource_dir = app.path().resource_dir().ok();
            bridge.start(resource_dir.clone());
            app.manage(Shell {
                bridge,
                resource_dir,
                installing: Arc::new(AtomicBool::new(false)),
                logins: accounts::Logins::new(),
                sessions: Sessions::new(),
                chats: ChatSessions::new(),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building omher");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(shell) = handle.try_state::<Shell>() {
                shell.sessions.close_all();
                shell.chats.close_all();
                shell.logins.cancel_all();
                shell.bridge.stop();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{allowed_external, media_target};

    #[test]
    fn opens_only_thread_links() {
        assert!(allowed_external("slack://channel?team=T1&id=C1&thread_ts=1.2"));
        assert!(allowed_external("https://discord.com/channels/1/2"));
        assert!(!allowed_external("https://evil.example/discord.com/channels/1"));
        assert!(!allowed_external("file:///etc/passwd"));
        assert!(!allowed_external("https://discord.com/channels/1 --args"));
        assert!(!allowed_external("javascript:alert(1)"));
    }

    #[test]
    fn opens_a_github_pull_request_and_nothing_else_on_github() {
        assert!(allowed_external("https://github.com/rlaope/oh-my-hermes/pull/2746"));
        assert!(allowed_external("https://github.com/o-1/r_e.po/pull/1"));
        for bad in [
            "https://github.com/rlaope/oh-my-hermes/pull/2746/files",
            "https://github.com/rlaope/oh-my-hermes/pull/2746?x=1",
            "https://github.com/rlaope/oh-my-hermes/issues/2746",
            "https://github.com/rlaope/oh-my-hermes/pull/",
            "https://github.com/rlaope/oh-my-hermes/pull/27x",
            "https://github.com/rlaope/../pull/1",
            "https://github.com/_x/r/pull/1",
            "https://github.com.evil.example/o/r/pull/1",
            "http://github.com/o/r/pull/1",
            "https://github.com/o/r/pull/1 --args",
            "https://github.com/settings/tokens",
        ] {
            assert!(!allowed_external(bad), "{bad}");
        }
    }

    #[test]
    fn discord_links_go_to_the_app_first() {
        use super::discord_app_url;
        assert_eq!(
            discord_app_url("https://discord.com/channels/1544/1568").as_deref(),
            Some("discord://discord.com/channels/1544/1568")
        );
        assert!(allowed_external(&discord_app_url("https://discord.com/channels/1/2").unwrap()));
        assert_eq!(discord_app_url("slack://channel?team=T1&id=C1"), None);
        assert_eq!(discord_app_url("https://t.me/x"), None);
    }

    #[test]
    fn open_media_refuses_paths_the_bridge_did_not_serve() {
        let dir = std::env::temp_dir().join(format!("omher-open-media-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("a.png");
        std::fs::write(&file, b"x").unwrap();
        let served = file.to_string_lossy().to_string();
        let known = |p: &str| p == served;
        assert_eq!(media_target(&served, known).unwrap(), file);
        let other = dir.join("b.png");
        std::fs::write(&other, b"x").unwrap();
        assert!(media_target(&other.to_string_lossy(), known).is_err(), "unknown file");
        assert!(media_target(&dir.to_string_lossy(), |_| true).is_err(), "a folder");
        assert!(media_target("a.png", |_| true).is_err(), "relative");
        assert!(media_target("", |_| true).is_err(), "empty");
        std::fs::remove_file(&file).unwrap();
        assert!(media_target(&served, known).is_err(), "gone since it was served");
        let _ = std::fs::remove_dir_all(&dir);
    }
}

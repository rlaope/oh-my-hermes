mod accounts;
mod bridge;
mod sessions;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use bridge::{Bridge, BridgeStatus};
use sessions::{AgentInfo, Output, Sessions};
use tauri::ipc::{Channel, InvokeResponseBody};
use tauri::{Manager, RunEvent, State};

struct Shell {
    bridge: Arc<Bridge>,
    resource_dir: Option<PathBuf>,
    logins: Arc<accounts::Logins>,
    sessions: Arc<Sessions>,
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

/// Open a thread in its own app. Only Slack / Discord / Telegram links: omher never opens arbitrary URLs.
/// The system opener (`open` on macOS, the shell's URL handler on Windows, `xdg-open` on Linux) hands the
/// link to the person's own Slack / Discord / browser.
#[tauri::command]
async fn open_external(url: String) -> Result<(), String> {
    if !allowed_external(&url) {
        return Err("not a Slack, Discord or Telegram link".into());
    }
    tauri_plugin_opener::open_url(&url, None::<&str>).map_err(|e| e.to_string())
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
        && PREFIXES.iter().any(|p| url.starts_with(p))
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

/// The allow-listed agent programs (claude, codex, omh, pi, omp) and where each was found, if anywhere.
#[tauri::command]
async fn sessions_agents() -> Result<Vec<AgentInfo>, String> {
    Ok(tauri::async_runtime::spawn_blocking(sessions::agents_on_this_machine).await.map_err(|e| e.to_string())?)
}

/// Start allow-listed agent `agent` in folder `cwd` in a new pseudo-terminal. Only an agent id crosses
/// from the UI: no program path, command line or argument. Terminal output goes to `on_data` as raw bytes,
/// the exit code (null after a signal) once to `on_exit`.
#[tauri::command]
async fn session_start(
    shell: State<'_, Shell>,
    agent: String,
    cwd: String,
    cols: u16,
    rows: u16,
    on_data: Channel<InvokeResponseBody>,
    on_exit: Channel<Option<u32>>,
) -> Result<u32, String> {
    let sessions = shell.sessions.clone();
    tauri::async_runtime::spawn_blocking(move || {
        sessions.start_agent(&agent, std::path::Path::new(&cwd), cols, rows, move |ev| match ev {
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
        .invoke_handler(tauri::generate_handler![
            bridge_url,
            bridge_status,
            bridge_retry,
            open_external,
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
            session_close_all
        ])
        .setup(|app| {
            let bridge = Bridge::new();
            let resource_dir = app.path().resource_dir().ok();
            bridge.start(resource_dir.clone());
            app.manage(Shell { bridge, resource_dir, logins: accounts::Logins::new(), sessions: Sessions::new() });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building omher");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(shell) = handle.try_state::<Shell>() {
                shell.sessions.close_all();
                shell.logins.cancel_all();
                shell.bridge.stop();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::allowed_external;

    #[test]
    fn opens_only_thread_links() {
        assert!(allowed_external("slack://channel?team=T1&id=C1&thread_ts=1.2"));
        assert!(allowed_external("https://discord.com/channels/1/2"));
        assert!(!allowed_external("https://evil.example/discord.com/channels/1"));
        assert!(!allowed_external("file:///etc/passwd"));
        assert!(!allowed_external("https://discord.com/channels/1 --args"));
        assert!(!allowed_external("javascript:alert(1)"));
    }
}

mod bridge;
mod sessions;
mod setup;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use bridge::{Bridge, BridgeStatus, Os};
use sessions::{AgentInfo, Output, Sessions};
use setup::InstallEvent;
use tauri::ipc::{Channel, InvokeResponseBody};
use tauri::{Manager, RunEvent, State};

struct Shell {
    bridge: Arc<Bridge>,
    resource_dir: Option<PathBuf>,
    installing: Arc<AtomicBool>,
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
        && PREFIXES.iter().any(|p| url.starts_with(p))
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
            install_engine,
            install_engine_command,
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
            app.manage(Shell {
                bridge,
                resource_dir,
                installing: Arc::new(AtomicBool::new(false)),
                sessions: Sessions::new(),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building omher");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(shell) = handle.try_state::<Shell>() {
                shell.sessions.close_all();
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
}

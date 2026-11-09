mod bridge;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use bridge::{Bridge, BridgeStatus};
use tauri::{Manager, RunEvent, State};

struct Shell {
    bridge: Arc<Bridge>,
    resource_dir: Option<PathBuf>,
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

/// Start the bridge again (the Retry button on the failed screen).
#[tauri::command]
async fn bridge_retry(shell: State<'_, Shell>) -> Result<(), String> {
    shell.bridge.start(shell.resource_dir.clone());
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![bridge_url, bridge_status, bridge_retry, open_external])
        .setup(|app| {
            let bridge = Bridge::new();
            let resource_dir = app.path().resource_dir().ok();
            bridge.start(resource_dir.clone());
            app.manage(Shell { bridge, resource_dir });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building omher");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(shell) = handle.try_state::<Shell>() {
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

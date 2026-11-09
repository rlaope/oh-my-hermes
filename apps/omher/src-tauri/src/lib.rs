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
        .invoke_handler(tauri::generate_handler![bridge_url, bridge_status, bridge_retry, open_external, open_media])
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

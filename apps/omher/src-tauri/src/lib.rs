mod accounts;
mod agent_chat;
mod appimage;
mod bridge;
mod dsh_chat;
mod git_branch;
mod hermes_auth;
mod session_files;
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

/// Open a link the person clicked: a thread in its own app (Slack / Discord / Telegram), a plan node's GitHub
/// pull request, or a message's http(s) link (a link chip) in the default browser. The system opener (`open`
/// on macOS, the shell's URL handler on Windows, `xdg-open` on Linux) hands it to the person's own Slack /
/// Discord / browser. Nothing else: no file, `javascript:` or other scheme, no address with a user name or
/// password in it.
#[tauri::command]
async fn open_external(url: String) -> Result<(), String> {
    if !allowed_external(&url) {
        return Err("not a thread or web link".into());
    }
    // A Discord web link opens the Discord app when it is installed, the browser otherwise.
    if let Some(app_url) = discord_app_url(&url) {
        if discord_app_installed() && system_open_url(&app_url).is_ok() {
            return Ok(());
        }
    }
    system_open_url(&url)
}

/// The system opener for an address. On Linux it goes through `appimage::open`, which hands a link to
/// `xdg-open` without the AppImage's bundled-library environment (a plain install is unaffected).
fn system_open_url(url: &str) -> Result<(), String> {
    #[cfg(target_os = "linux")]
    {
        appimage::open(url)
    }
    #[cfg(not(target_os = "linux"))]
    {
        tauri_plugin_opener::open_url(url, None::<&str>).map_err(|e| e.to_string())
    }
}

/// `https://discord.com/channels/G/C` -> `discord://discord.com/channels/G/C` (the form the Discord app
/// routes to that exact channel or thread).
pub(crate) fn discord_app_url(url: &str) -> Option<String> {
    url.strip_prefix("https://discord.com/channels/")
        .map(|rest| format!("discord://discord.com/channels/{rest}"))
}

/// Whether the Discord desktop app is there to take `discord://`. macOS and Linux report a missing handler as
/// an open error (`xdg-open` exits non-zero, so the browser fallback runs); Windows would show an "find an app" dialog instead, so there
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
        && (PREFIXES.iter().any(|p| url.starts_with(p)) || github_pr_url(url) || web_link(url))
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

/// An `http(s)://host/...` address with no user name or password before the host (`https://github.com@evil.io/`
/// reads as GitHub but goes to evil.io), as a link chip carries it.
pub(crate) fn web_link(url: &str) -> bool {
    let rest = match url.strip_prefix("https://").or_else(|| url.strip_prefix("http://")) {
        Some(r) => r,
        None => return false,
    };
    let host = rest.split(['/', '?', '#']).next().unwrap_or("");
    !host.is_empty() && !host.contains('@') && !host.contains('\\')
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

/// The allow-listed agent programs (claude, codex, omo, dsh, omh, pi, omp, grok), how each opens and where each
/// was found, if anywhere.
#[tauri::command]
async fn sessions_agents() -> Result<Vec<AgentInfo>, String> {
    Ok(tauri::async_runtime::spawn_blocking(sessions::agents_on_this_machine).await.map_err(|e| e.to_string())?)
}

/// Start allow-listed agent `agent` in folder `cwd` in a new pseudo-terminal (its own terminal UI). Only an
/// agent id crosses from the UI: no program path, command line or argument; `resume` is a Claude Code
/// session id or a DSH conversation id that the shell checks is a UUID (so the terminal continues it); `account` is the account a
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

/// What the person did in chat `id`: `{kind:"send", text, images, id}`, `{kind:"interrupt"}`,
/// `{kind:"approve", request_id, choice}`, `{kind:"clarify", request_id, answer}`, `{kind:"model", model}`,
/// `{kind:"mode", mode}` (one of `agent_chat::modes_for`), `{kind:"effort", effort}`.
#[tauri::command]
async fn chat_input(shell: State<'_, Shell>, id: u32, input: agent_chat::Input) -> Result<(), String> {
    let chats = shell.chats.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut input = input;
        // attached pictures: only files omher saved under its own session folder are read
        input.resolve(&user_home()?)?;
        chats.input(id, input)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Save one file the person attached in SESSIONS chat (or dropped on its terminal) `x-session` as
/// `~/.omher/session-files/<session>/<n>-<name>` and return that path. The body is the file's bytes; the name
/// comes percent-encoded in `x-name`. Nothing else is written.
#[tauri::command]
async fn session_file_save(request: tauri::ipc::Request<'_>) -> Result<String, String> {
    let header = |k: &str| request.headers().get(k).and_then(|v| v.to_str().ok()).map(str::to_string).unwrap_or_default();
    let (session, name) = (header("x-session"), session_files::percent_decode(&header("x-name")));
    let tauri::ipc::InvokeBody::Raw(data) = request.body() else { return Err("expected the file's bytes".into()) };
    let data = data.clone();
    let home = user_home()?;
    tauri::async_runtime::spawn_blocking(move || session_files::save(&home, &session, &name, &data).map(|p| p.to_string_lossy().into_owned()))
        .await
        .map_err(|e| e.to_string())?
}

/// The bytes of a file saved by `session_file_save` (a sent bubble's picture after omher restarted). Any other
/// path is refused.
#[tauri::command]
async fn session_file_read(path: String) -> Result<tauri::ipc::Response, String> {
    let home = user_home()?;
    let real = session_files::check(&home, &path)?;
    let bytes = tauri::async_runtime::spawn_blocking(move || std::fs::read(real)).await.map_err(|e| e.to_string())?.map_err(|e| e.to_string())?;
    Ok(tauri::ipc::Response::new(bytes))
}

/// The git branch of a session's folder, from its `.git/HEAD` only (no program runs); "" outside a repository.
#[tauri::command]
async fn session_branch(cwd: String) -> Result<String, String> {
    Ok(git_branch::branch(std::path::Path::new(&cwd)))
}

/// Remove session `session`'s saved files (it was closed).
#[tauri::command]
async fn session_files_remove(session: String) -> Result<(), String> {
    session_files::remove(&user_home()?, &session)
}

/// Remove the saved files of every session not in `keep` (omher started; the others are gone).
#[tauri::command]
async fn session_files_prune(keep: Vec<String>) -> Result<(), String> {
    session_files::prune(&user_home()?, &keep)
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
        #[cfg(target_os = "linux")]
        {
            appimage::open(&path.to_string_lossy())
        }
        #[cfg(not(target_os = "linux"))]
        {
            tauri_plugin_opener::open_path(&path, None::<&str>).map_err(|e| e.to_string())
        }
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

/// Settings › Providers "Add key": open the system terminal running exactly
/// `hermes auth add <provider> --type api-key` (rule 23). Hermes asks for the key there and stores it; omher
/// takes only the provider id, checked by `hermes_auth::valid_provider`, and never sees the key.
#[tauri::command]
async fn open_hermes_auth(provider: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || hermes_auth::open(&provider)).await.map_err(|e| e.to_string())?
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
            session_file_save,
            session_file_read,
            session_files_remove,
            session_files_prune,
            session_branch,
            chat_close_all,
            open_media,
            open_hermes_auth
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
    fn opens_thread_links_and_a_lookalike_only_as_a_web_page() {
        assert!(allowed_external("slack://channel?team=T1&id=C1&thread_ts=1.2"));
        assert!(allowed_external("https://discord.com/channels/1/2"));
        // a lookalike is an ordinary web link: it opens in the browser, never in the Discord app
        assert!(allowed_external("https://evil.example/discord.com/channels/1"));
        assert_eq!(super::discord_app_url("https://evil.example/discord.com/channels/1"), None);
        assert!(!allowed_external("slack://open?team=T1"));
        assert!(!allowed_external("discord://evil.example/channels/1"));
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
            assert!(!super::github_pr_url(bad), "{bad}");
        }
        // a plan node's PR page is also a web link, so a chip opens the same address
        assert!(allowed_external("https://github.com/rlaope/oh-my-hermes/pull/2746/files"));
    }

    #[test]
    fn opens_web_links_from_link_chips_and_nothing_else() {
        assert!(allowed_external("https://github.com/rlaope/oh-my-hermes/pull/2657"));
        assert!(allowed_external("https://sionicai.slack.com/archives/C0BLC924P1P/p1794195216893139"));
        assert!(allowed_external("http://example.com"));
        assert!(allowed_external("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=83s"));
        assert!(!allowed_external("https://github.com@evil.io/x"));
        assert!(!allowed_external("https://user:pw@example.com/"));
        assert!(!allowed_external("https:///etc/passwd"));
        assert!(!allowed_external("https://"));
        assert!(!allowed_external("ftp://example.com/x"));
        assert!(!allowed_external("vscode://file/etc/passwd"));
        assert!(!allowed_external("https://example.com/a b"));
        assert!(!allowed_external("https://example.com/\nx"));
        assert!(!allowed_external("HTTPS://example.com/"));
        assert!(!allowed_external("https:\\\\evil.io\\x"));
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

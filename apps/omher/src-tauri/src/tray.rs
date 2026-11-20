//! Closing the window keeps omher running (Settings › General "When the window closes", on by default): the close
//! (red button, Alt+F4, ⌘W reaching the window) hides the window instead, and a tray / menu bar icon offers
//! "Open omher" and "Quit omher". The TERMINALS ptys, the bridge and the bots go on while the window is hidden.
//! Real quits stay real: ⌘Q, the app menu's Quit, the tray's Quit and the updater's restart all go through the
//! normal exit (`RunEvent::Exit` in lib.rs), which stops the bridge and kills every pty. With the setting off, the
//! close quits as before.

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Emitter, Manager, Runtime, WindowEvent};

pub const OPEN_ID: &str = "omher-tray-open";
pub const QUIT_ID: &str = "omher-tray-quit";
/// The page hears this each time the close hid the window (it shows the one-time "still running" note).
pub const HIDDEN_EVENT: &str = "window-hidden";

/// Whether the window's close hides it (the page sends the setting at start and on each change).
pub struct TrayState {
    hide: AtomicBool,
}

impl Default for TrayState {
    fn default() -> Self {
        TrayState { hide: AtomicBool::new(true) }
    }
}

impl TrayState {
    pub fn hides(&self) -> bool {
        self.hide.load(Ordering::Relaxed)
    }
    pub fn set_hides(&self, on: bool) {
        self.hide.store(on, Ordering::Relaxed);
    }
}

/// What a close of the main window does.
#[derive(Debug, PartialEq, Eq)]
pub enum OnClose {
    Hide,
    Close,
}

pub fn on_close(label: &str, hides: bool) -> OnClose {
    if label == "main" && hides {
        OnClose::Hide
    } else {
        OnClose::Close
    }
}

/// What a tray menu item does.
#[derive(Debug, PartialEq, Eq)]
pub enum Item {
    Open,
    Quit,
    Other,
}

pub fn item(id: &str) -> Item {
    match id {
        OPEN_ID => Item::Open,
        QUIT_ID => Item::Quit,
        _ => Item::Other,
    }
}

/// Show and focus the main window (tray click, "Open omher", the Dock icon, a second launch).
pub fn show_main<R: Runtime>(app: &AppHandle<R>) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

/// The window's close: hide it when the setting says so (`CloseRequested` -> `prevent_close` + `hide`).
pub fn window_event<R: Runtime>(window: &tauri::Window<R>, event: &WindowEvent) {
    let WindowEvent::CloseRequested { api, .. } = event else { return };
    let hides = window.app_handle().try_state::<TrayState>().is_some_and(|s| s.hides());
    if on_close(window.label(), hides) == OnClose::Hide {
        api.prevent_close();
        let _ = window.hide();
        let _ = window.app_handle().emit(HIDDEN_EVENT, ());
    }
}

/// The tray icon and its menu (English until the page sends its labels).
pub fn build<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
    let open = MenuItem::with_id(app, OPEN_ID, "Open omher", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT_ID, "Quit omher", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &PredefinedMenuItem::separator(app)?, &quit])?;
    let mut b = TrayIconBuilder::with_id("omher-tray")
        .tooltip("omher")
        .menu(&menu)
        // macOS: a click opens the menu (the menu bar way); Windows and Linux: a click opens the window
        .show_menu_on_left_click(cfg!(target_os = "macos"))
        .on_menu_event(|app, ev| match item(ev.id().as_ref()) {
            Item::Open => show_main(app),
            Item::Quit => app.exit(0),
            Item::Other => {}
        })
        .on_tray_icon_event(|tray, ev| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = ev {
                if !cfg!(target_os = "macos") {
                    show_main(tray.app_handle());
                }
            }
        });
    if let Some(icon) = app.default_window_icon() {
        b = b.icon(icon.clone());
    }
    let tray = b.build(app)?;
    app.manage(TrayMenu { tray, open, quit });
    Ok(())
}

/// The built tray, kept so the page's setting and language can change it.
pub struct TrayMenu<R: Runtime> {
    tray: tauri::tray::TrayIcon<R>,
    open: tauri::menu::MenuItem<R>,
    quit: tauri::menu::MenuItem<R>,
}

impl<R: Runtime> TrayMenu<R> {
    /// The icon shows only while the close hides the window; the labels follow the page's language.
    pub fn apply(&self, hides: bool, open: &str, quit: &str) {
        let _ = self.tray.set_visible(hides);
        if !open.is_empty() {
            let _ = self.open.set_text(open);
        }
        if !quit.is_empty() {
            let _ = self.quit.set_text(quit);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_main_windows_close_hides_only_while_the_setting_is_on() {
        assert_eq!(on_close("main", true), OnClose::Hide);
        assert_eq!(on_close("main", false), OnClose::Close);
        assert_eq!(on_close("other", true), OnClose::Close);
        assert!(TrayState::default().hides(), "on by default");
        let s = TrayState::default();
        s.set_hides(false);
        assert!(!s.hides());
    }

    #[test]
    fn tray_items() {
        assert_eq!(item("omher-tray-open"), Item::Open);
        assert_eq!(item("omher-tray-quit"), Item::Quit);
        assert_eq!(item("omher-close"), Item::Other);
    }
}

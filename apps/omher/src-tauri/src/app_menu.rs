//! The macOS menu bar, as Tauri's default one, with one change: File › Close Window and Window › Close Window (⌘W)
//! are omher's own item instead of the system's. The system item closes the window at once; omher's asks the page
//! first (`menu-close`), which closes the focused split pane when a split has the keyboard (TERMINALS or the bottom
//! panel) and otherwise asks back to close the window (`window_close`). Other systems keep Tauri's default menu
//! (their Close is Alt+F4, which no split uses).

/// The id of omher's Close Window item.
pub const CLOSE_ID: &str = "omher-close";
/// The event the page hears when it is chosen (or ⌘W reaches the menu).
pub const CLOSE_EVENT: &str = "menu-close";

/// Whether a menu event is omher's Close Window.
pub fn is_close(id: &str) -> bool {
    id == CLOSE_ID
}

#[cfg(target_os = "macos")]
pub fn build<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<tauri::menu::Menu<R>> {
    use tauri::menu::{AboutMetadata, Menu, MenuItem, PredefinedMenuItem, Submenu, HELP_SUBMENU_ID, WINDOW_SUBMENU_ID};
    let pkg = app.package_info();
    let about = AboutMetadata { name: Some(pkg.name.clone()), version: Some(pkg.version.to_string()), ..Default::default() };
    let close = || MenuItem::with_id(app, CLOSE_ID, "Close Window", true, Some("CmdOrCtrl+W"));
    let window = Submenu::with_id_and_items(
        app,
        WINDOW_SUBMENU_ID,
        "Window",
        true,
        &[&PredefinedMenuItem::minimize(app, None)?, &PredefinedMenuItem::maximize(app, None)?, &PredefinedMenuItem::separator(app)?, &close()?],
    )?;
    let help = Submenu::with_id_and_items(app, HELP_SUBMENU_ID, "Help", true, &[])?;
    Menu::with_items(
        app,
        &[
            &Submenu::with_items(
                app,
                pkg.name.clone(),
                true,
                &[
                    &PredefinedMenuItem::about(app, None, Some(about))?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::services(app, None)?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::hide(app, None)?,
                    &PredefinedMenuItem::hide_others(app, None)?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::quit(app, None)?,
                ],
            )?,
            &Submenu::with_items(app, "File", true, &[&close()?])?,
            &Submenu::with_items(
                app,
                "Edit",
                true,
                &[
                    &PredefinedMenuItem::undo(app, None)?,
                    &PredefinedMenuItem::redo(app, None)?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::cut(app, None)?,
                    &PredefinedMenuItem::copy(app, None)?,
                    &PredefinedMenuItem::paste(app, None)?,
                    &PredefinedMenuItem::select_all(app, None)?,
                ],
            )?,
            &Submenu::with_items(app, "View", true, &[&PredefinedMenuItem::fullscreen(app, None)?])?,
            &window,
            &help,
        ],
    )
}

#[cfg(test)]
mod tests {
    #[test]
    fn only_omhers_close_item_counts() {
        assert!(super::is_close("omher-close"));
        assert!(!super::is_close("close"));
        assert!(!super::is_close(""));
        assert_eq!(super::CLOSE_EVENT, "menu-close");
    }
}

//! Voice (BOUNDARY rule 54): what the shell does so the page can record from the microphone. Linux only: WebKitGTK
//! keeps media capture off unless the webview's `enable-media-stream` setting is on, and with no permission handler
//! it refuses every capture request. macOS (WKWebView, where wry grants the page's request and macOS asks the person
//! through its own microphone dialog) and Windows (WebView2's own prompt) are left as they are: a permission handler
//! there would change how wry answers.

use tauri::webview::{PermissionKind, PermissionResponse};

/// The answer to a webview's permission request: Allow for the microphone, and the webview's own default for
/// everything else, which on WebKitGTK refuses (the camera, the screen, the location, notifications). A request for
/// the microphone and the camera together is refused too: wry 0.57.1 (`src/webkitgtk/mod.rs`) leaves such a request
/// unhandled when its camera half answers Default, and WebKitGTK's own default then refuses it.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub fn microphone_only(kind: PermissionKind) -> PermissionResponse {
    match kind {
        PermissionKind::Microphone => PermissionResponse::Allow,
        _ => PermissionResponse::Default,
    }
}

/// Turn on WebKitGTK's `enable-media-stream` for the main window's webview, the setting `getUserMedia` needs there
/// (wry leaves it off). Whether a recording then works still depends on the distribution's WebKitGTK build and its
/// GStreamer plugins; the page checks for the recording API itself and says so when it is missing.
#[cfg(target_os = "linux")]
pub fn enable_media_stream(window: &tauri::WebviewWindow) {
    let _ = window.with_webview(|webview| {
        use webkit2gtk::{SettingsExt, WebViewExt};
        if let Some(settings) = WebViewExt::settings(&webview.inner()) {
            settings.set_enable_media_stream(true);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_microphone_is_allowed() {
        assert_eq!(microphone_only(PermissionKind::Microphone), PermissionResponse::Allow);
        for kind in [
            PermissionKind::Camera,
            PermissionKind::DisplayCapture,
            PermissionKind::Geolocation,
            PermissionKind::Notifications,
            PermissionKind::ClipboardRead,
            PermissionKind::Other,
        ] {
            assert_eq!(microphone_only(kind), PermissionResponse::Default, "{kind:?}");
        }
    }

    // Not on Windows: a test binary that links the Wry builder imports common-controls entry points the test
    // executable has no manifest for, and Windows refuses to load it (STATUS_ENTRYPOINT_NOT_FOUND) before any test runs.
    #[cfg(not(windows))]
    #[test]
    fn the_builder_takes_the_answer() {
        // lib.rs's Linux-only line, type-checked here on macOS too: the builder is made and dropped, never run
        let _ = tauri::Builder::<tauri::Wry>::default().on_permission_request(|_webview, kind| microphone_only(kind));
    }
}

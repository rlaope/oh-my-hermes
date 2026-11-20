//! Settings › Terminal › Import from… (macOS): the colours and font of another terminal app's profiles, read once
//! when the person presses the button. Only two fixed files are ever opened, read-only, and never a symlink or a file
//! over 8 MB: iTerm2's `~/Library/Preferences/com.googlecode.iterm2.plist` and Apple Terminal's
//! `~/Library/Preferences/com.apple.Terminal.plist`. Only the parsed result goes back to the page (names, `#rrggbb`
//! colours, a font name and size; at most 64 profiles); the page keeps what the person picks as an omher theme and
//! nothing reads these files again until the button is pressed again. Nothing is ever written to them.
//!
//! iTerm2 keeps a profile's colours as dicts of `Red/Green/Blue Component` floats (taken as sRGB whatever their
//! `Color Space`) and its font as `"<PostScript name> <size>"`. Terminal.app keeps each colour and the font as an
//! NSKeyedArchiver blob (`NSColor`: `NSComponents` or `NSRGB` / `NSWhite` strings; `NSFont`: `NSName`, `NSSize`);
//! a profile with a blob that cannot be decoded comes back with `ok: false` and no colours.

use plist::{Dictionary, Value};
use serde::Serialize;
use std::fs::{File, OpenOptions};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};

/// The only two files this module opens, under the person's home folder.
const ITERM2_PLIST: &str = "Library/Preferences/com.googlecode.iterm2.plist";
const TERMINAL_PLIST: &str = "Library/Preferences/com.apple.Terminal.plist";
/// A prefs file larger than this is not read.
pub const MAX_BYTES: u64 = 8 * 1024 * 1024;
/// At most this many profiles go back to the page.
pub const MAX_PROFILES: usize = 64;
const MAX_NAME: usize = 80;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum App {
    Iterm2,
    Terminal,
}

impl App {
    pub fn parse(s: &str) -> Option<App> {
        match s {
            "iterm2" => Some(App::Iterm2),
            "terminal" => Some(App::Terminal),
            _ => None,
        }
    }
    fn id(self) -> &'static str {
        match self {
            App::Iterm2 => "iterm2",
            App::Terminal => "terminal",
        }
    }
    fn path(self, home: &Path) -> PathBuf {
        home.join(match self {
            App::Iterm2 => ITERM2_PLIST,
            App::Terminal => TERMINAL_PLIST,
        })
    }
}

#[derive(Serialize, Debug, Clone, PartialEq)]
pub struct Font {
    /// The PostScript name the app keeps (`Menlo-Regular`); the page finds the family it belongs to.
    pub name: String,
    pub size: f64,
}

#[derive(Serialize, Debug, Clone, PartialEq, Default)]
pub struct Colors {
    pub foreground: Option<String>,
    pub background: Option<String>,
    pub cursor: Option<String>,
    pub selection: Option<String>,
    /// ANSI 0..15: the eight normal colours, then the eight bright ones.
    pub ansi: Vec<Option<String>>,
}

#[derive(Serialize, Debug, Clone, PartialEq)]
pub struct Profile {
    pub name: String,
    /// The app's default profile (always first).
    pub default: bool,
    /// False: a colour or the font could not be decoded; the page lists it greyed out, without colours.
    pub ok: bool,
    pub font: Option<Font>,
    pub colors: Option<Colors>,
}

/// Which of the two apps have a prefs file that could be read (a regular file, not a symlink, within the size cap).
pub fn list(home: &Path) -> Vec<&'static str> {
    [App::Iterm2, App::Terminal]
        .into_iter()
        .filter(|a| std::fs::symlink_metadata(a.path(home)).map(|m| m.file_type().is_file() && m.len() <= MAX_BYTES).unwrap_or(false))
        .map(App::id)
        .collect()
}

/// `app`'s profiles, default first, at most 64.
pub fn read(home: &Path, app: App) -> Result<Vec<Profile>, String> {
    let bytes = read_capped(&app.path(home))?;
    let root = Value::from_reader(Cursor::new(bytes)).map_err(|_| "unreadable".to_string())?;
    let root = root.as_dictionary().ok_or("unreadable")?;
    let mut out = match app {
        App::Iterm2 => iterm2_profiles(root),
        App::Terminal => terminal_profiles(root),
    };
    out.truncate(MAX_PROFILES);
    Ok(out)
}

/// The file's bytes: refused when it is a symlink (checked by the open itself on unix), not a regular file, or over
/// the cap.
fn read_capped(path: &Path) -> Result<Vec<u8>, String> {
    let meta = std::fs::symlink_metadata(path).map_err(|_| "missing".to_string())?;
    if meta.file_type().is_symlink() {
        return Err("symlink".into());
    }
    if !meta.file_type().is_file() {
        return Err("unreadable".into());
    }
    let mut opts = OpenOptions::new();
    opts.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.custom_flags(libc::O_NOFOLLOW);
    }
    let f: File = opts.open(path).map_err(|_| "unreadable".to_string())?;
    let m = f.metadata().map_err(|_| "unreadable".to_string())?;
    if !m.is_file() {
        return Err("unreadable".into());
    }
    if m.len() > MAX_BYTES {
        return Err("too-large".into());
    }
    let mut buf = Vec::with_capacity(m.len() as usize);
    f.take(MAX_BYTES + 1).read_to_end(&mut buf).map_err(|_| "unreadable".to_string())?;
    if buf.len() as u64 > MAX_BYTES {
        return Err("too-large".into());
    }
    Ok(buf)
}

fn clean_name(s: &str) -> String {
    s.chars().filter(|c| !c.is_control()).take(MAX_NAME).collect::<String>().trim().to_string()
}

/// 0..1 components as `#rrggbb` (out-of-range values are clamped).
pub fn hex(r: f64, g: f64, b: f64) -> Option<String> {
    if !(r.is_finite() && g.is_finite() && b.is_finite()) {
        return None;
    }
    let c = |v: f64| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
    Some(format!("#{:02x}{:02x}{:02x}", c(r), c(g), c(b)))
}

/// `"Menlo-Regular 12"` -> the name and size.
fn font_of(spec: &str) -> Option<Font> {
    let (name, size) = spec.trim().rsplit_once(' ')?;
    let size: f64 = size.parse().ok()?;
    let name = clean_name(name);
    (size.is_finite() && size > 0.0 && !name.is_empty()).then_some(Font { name, size })
}

// ---- iTerm2 -------------------------------------------------------------------------------------------------------

/// One of iTerm2's colour dicts (`Red Component` …), or its `(Dark)` variant when the profile keeps separate colours
/// for light and dark mode.
fn iterm_color(p: &Dictionary, key: &str) -> Option<String> {
    let d = p.get(key).or_else(|| p.get(&format!("{key} (Dark)")))?.as_dictionary()?;
    let comp = |k: &str| d.get(k).and_then(|v| v.as_real().or_else(|| v.as_signed_integer().map(|i| i as f64)));
    // sRGB, Calibrated and P3 alike are taken as sRGB components
    hex(comp("Red Component")?, comp("Green Component")?, comp("Blue Component")?)
}

fn iterm2_profiles(root: &Dictionary) -> Vec<Profile> {
    let default = root.get("Default Bookmark Guid").and_then(Value::as_string).unwrap_or("");
    let Some(list) = root.get("New Bookmarks").and_then(Value::as_array) else { return vec![] };
    let mut out: Vec<Profile> = Vec::new();
    for v in list {
        let Some(p) = v.as_dictionary() else { continue };
        let name = clean_name(p.get("Name").and_then(Value::as_string).unwrap_or(""));
        if name.is_empty() {
            continue;
        }
        let is_default = !default.is_empty() && p.get("Guid").and_then(Value::as_string) == Some(default);
        let colors = Colors {
            foreground: iterm_color(p, "Foreground Color"),
            background: iterm_color(p, "Background Color"),
            cursor: iterm_color(p, "Cursor Color"),
            selection: iterm_color(p, "Selection Color"),
            ansi: (0..16).map(|i| iterm_color(p, &format!("Ansi {i} Color"))).collect(),
        };
        let font = p.get("Normal Font").and_then(Value::as_string).and_then(font_of);
        let prof = Profile { name, default: is_default, ok: true, font, colors: Some(colors) };
        if is_default {
            out.insert(0, prof);
        } else {
            out.push(prof);
        }
    }
    out
}

// ---- Terminal.app -------------------------------------------------------------------------------------------------

/// Terminal.app leaves a colour out of a profile while it is the app's own; these are those colours.
const TERMINAL_TEXT: &str = "#000000";
const TERMINAL_BACKGROUND: &str = "#ffffff";
const TERMINAL_CURSOR: &str = "#929292";
const TERMINAL_SELECTION: &str = "#a4cdff";
const TERMINAL_ANSI: [&str; 16] = [
    "#000000", "#990000", "#00a600", "#999900", "#0000b2", "#b200b2", "#00a6b2", "#bfbfbf", "#666666", "#e50000", "#00d900", "#e5e500", "#0000ff", "#e500e5",
    "#00e5e5", "#e5e5e5",
];
const TERMINAL_ANSI_KEYS: [&str; 16] = [
    "ANSIBlackColor",
    "ANSIRedColor",
    "ANSIGreenColor",
    "ANSIYellowColor",
    "ANSIBlueColor",
    "ANSIMagentaColor",
    "ANSICyanColor",
    "ANSIWhiteColor",
    "ANSIBrightBlackColor",
    "ANSIBrightRedColor",
    "ANSIBrightGreenColor",
    "ANSIBrightYellowColor",
    "ANSIBrightBlueColor",
    "ANSIBrightMagentaColor",
    "ANSIBrightCyanColor",
    "ANSIBrightWhiteColor",
];

/// An NSKeyedArchiver blob's objects and its root object.
fn unarchive(blob: &[u8]) -> Option<(Vec<Value>, Dictionary)> {
    let v = Value::from_reader(Cursor::new(blob)).ok()?;
    let d = v.as_dictionary()?;
    if d.get("$archiver").and_then(Value::as_string) != Some("NSKeyedArchiver") {
        return None;
    }
    let objects = d.get("$objects")?.as_array()?.clone();
    let root = d.get("$top")?.as_dictionary()?.get("root")?.as_uid()?.get() as usize;
    let root = objects.get(root)?.as_dictionary()?.clone();
    Some((objects, root))
}

/// A string kept as NUL-ended bytes (`NSRGB`, `NSComponents`, `NSWhite`) as numbers.
fn floats(v: Option<&Value>) -> Option<Vec<f64>> {
    let raw = v?.as_data()?;
    let s = std::str::from_utf8(raw).ok()?.trim_end_matches('\0');
    s.split_whitespace().map(|t| t.parse::<f64>().ok()).collect()
}

/// An archived `NSColor` as `#rrggbb`.
pub fn ns_color(blob: &[u8]) -> Option<String> {
    let (_, c) = unarchive(blob)?;
    // the components in the colour's own space (sRGB for an sRGB colour) beat NSRGB, which is converted
    if let Some(n) = floats(c.get("NSComponents")).filter(|n| n.len() == 3 || n.len() == 4) {
        return hex(n[0], n[1], n[2]);
    }
    if let Some(n) = floats(c.get("NSRGB")).filter(|n| n.len() >= 3) {
        return hex(n[0], n[1], n[2]);
    }
    if let Some(n) = floats(c.get("NSWhite")).filter(|n| !n.is_empty()) {
        return hex(n[0], n[0], n[0]);
    }
    None
}

/// An archived `NSFont`: its PostScript name and size.
pub fn ns_font(blob: &[u8]) -> Option<Font> {
    let (objects, f) = unarchive(blob)?;
    let name = match f.get("NSName")? {
        Value::Uid(u) => objects.get(u.get() as usize)?.as_string()?.to_string(),
        Value::String(s) => s.clone(),
        _ => return None,
    };
    let size = f.get("NSSize").and_then(|v| v.as_real().or_else(|| v.as_signed_integer().map(|i| i as f64)))?;
    let name = clean_name(&name);
    (size.is_finite() && size > 0.0 && !name.is_empty()).then_some(Font { name, size })
}

/// One Terminal.app profile. `Err(())`: a colour or the font is kept but cannot be decoded.
fn terminal_profile(p: &Dictionary) -> Result<(Colors, Option<Font>), ()> {
    let color = |key: &str, fallback: &str| -> Result<Option<String>, ()> {
        match p.get(key) {
            None => Ok(Some(fallback.to_string())),
            Some(v) => v.as_data().and_then(ns_color).map(Some).ok_or(()),
        }
    };
    let mut ansi = Vec::with_capacity(16);
    for (k, d) in TERMINAL_ANSI_KEYS.iter().zip(TERMINAL_ANSI) {
        ansi.push(color(k, d)?);
    }
    let colors = Colors {
        foreground: color("TextColor", TERMINAL_TEXT)?,
        background: color("BackgroundColor", TERMINAL_BACKGROUND)?,
        cursor: color("CursorColor", TERMINAL_CURSOR)?,
        selection: color("SelectionColor", TERMINAL_SELECTION)?,
        ansi,
    };
    let font = match p.get("Font") {
        None => None,
        Some(v) => Some(v.as_data().and_then(ns_font).ok_or(())?),
    };
    Ok((colors, font))
}

fn terminal_profiles(root: &Dictionary) -> Vec<Profile> {
    let default = root.get("Default Window Settings").and_then(Value::as_string).unwrap_or("");
    let Some(all) = root.get("Window Settings").and_then(Value::as_dictionary) else { return vec![] };
    let mut out: Vec<Profile> = Vec::new();
    for (key, v) in all {
        let Some(p) = v.as_dictionary() else { continue };
        let name = clean_name(p.get("name").and_then(Value::as_string).unwrap_or(key));
        if name.is_empty() {
            continue;
        }
        let is_default = key == default;
        let prof = match terminal_profile(p) {
            Ok((colors, font)) => Profile { name, default: is_default, ok: true, font, colors: Some(colors) },
            Err(()) => Profile { name, default: is_default, ok: false, font: None, colors: None },
        };
        if is_default {
            out.insert(0, prof);
        } else {
            out.push(prof);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn home(tag: &str) -> PathBuf {
        let h = std::env::temp_dir().join(format!("omher-term-import-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&h);
        fs::create_dir_all(h.join("Library/Preferences")).unwrap();
        h
    }

    fn rgb(r: f64, g: f64, b: f64, space: &str) -> Value {
        let mut d = Dictionary::new();
        d.insert("Red Component".into(), Value::Real(r));
        d.insert("Green Component".into(), Value::Real(g));
        d.insert("Blue Component".into(), Value::Real(b));
        d.insert("Alpha Component".into(), Value::Real(1.0));
        d.insert("Color Space".into(), Value::String(space.into()));
        Value::Dictionary(d)
    }

    fn iterm_fixture() -> Value {
        let mut a = Dictionary::new();
        a.insert("Name".into(), "Other".into());
        a.insert("Guid".into(), "AAA".into());
        a.insert("Normal Font".into(), "Monaco 10".into());
        a.insert("Foreground Color".into(), rgb(1.0, 1.0, 1.0, "sRGB"));
        let mut b = Dictionary::new();
        b.insert("Name".into(), "Main".into());
        b.insert("Guid".into(), "BBB".into());
        b.insert("Normal Font".into(), "JetBrainsMono-Regular 13.5".into());
        b.insert("Foreground Color".into(), rgb(0.8627, 0.8392, 0.8706, "sRGB"));
        b.insert("Background Color".into(), rgb(0.0431, 0.0353, 0.051, "Calibrated"));
        b.insert("Cursor Color".into(), rgb(0.95, 0.94, 0.96, "sRGB"));
        b.insert("Selection Color".into(), rgb(0.24, 0.21, 0.25, "sRGB"));
        for i in 0..16 {
            let key = if i == 3 { format!("Ansi {i} Color (Dark)") } else { format!("Ansi {i} Color") };
            b.insert(key, rgb(i as f64 / 15.0, 0.5, 1.0 - i as f64 / 15.0, "sRGB"));
        }
        let mut root = Dictionary::new();
        root.insert("Default Bookmark Guid".into(), "BBB".into());
        root.insert("New Bookmarks".into(), Value::Array(vec![Value::Dictionary(a), Value::Dictionary(b)]));
        Value::Dictionary(root)
    }

    fn put(h: &Path, app: App, v: &Value) {
        v.to_file_binary(app.path(h)).unwrap();
    }

    #[test]
    fn iterm2_profiles_default_first_with_colours_and_font() {
        let h = home("iterm");
        put(&h, App::Iterm2, &iterm_fixture());
        assert_eq!(list(&h), vec!["iterm2"]);
        let got = read(&h, App::Iterm2).unwrap();
        assert_eq!(got.len(), 2);
        let main = &got[0];
        assert_eq!(main.name, "Main");
        assert!(main.default && main.ok);
        assert_eq!(main.font, Some(Font { name: "JetBrainsMono-Regular".into(), size: 13.5 }));
        let c = main.colors.as_ref().unwrap();
        assert_eq!(c.foreground.as_deref(), Some("#dcd6de"));
        assert_eq!(c.background.as_deref(), Some("#0b090d"));
        assert_eq!(c.ansi.len(), 16);
        assert!(c.ansi.iter().all(Option::is_some), "the (Dark) variant fills slot 3");
        assert_eq!(c.ansi[0].as_deref(), Some("#0080ff"));
        assert_eq!(c.ansi[15].as_deref(), Some("#ff8000"));
        assert_eq!(got[1].name, "Other");
        assert!(!got[1].default);
        assert_eq!(got[1].colors.as_ref().unwrap().background, None);
        fs::remove_dir_all(&h).unwrap();
    }

    #[test]
    fn srgb_components_round_within_one_step() {
        for (v, want) in [(0.0, 0u8), (1.0, 255), (0.5, 128), (0.2, 51), (0.123456, 31), (0.999, 255), (-0.2, 0), (1.3, 255)] {
            let h = hex(v, v, v).unwrap();
            let got = u8::from_str_radix(&h[1..3], 16).unwrap();
            assert!((got as f64 / 255.0 - v.clamp(0.0, 1.0)).abs() <= 1.0 / 255.0, "{v} -> {h}");
            assert_eq!(got, want, "{v}");
        }
        assert_eq!(hex(f64::NAN, 0.0, 0.0), None);
    }

    #[test]
    fn terminal_app_archived_colours_and_font_decode() {
        let h = home("terminal");
        // a real Terminal.app-shaped prefs file: NSKeyedArchiver NSColor/NSFont blobs made by AppKit on macOS
        fs::copy(concat!(env!("CARGO_MANIFEST_DIR"), "/src/term_import_fixtures/terminal.plist"), App::Terminal.path(&h)).unwrap();
        assert_eq!(list(&h), vec!["terminal"]);
        let got = read(&h, App::Terminal).unwrap();
        let names: Vec<&str> = got.iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names[0], "Fixture Dark", "the default profile comes first");
        assert_eq!(got.len(), 3);
        let d = &got[0];
        assert!(d.default && d.ok);
        assert_eq!(d.font, Some(Font { name: "Menlo-Regular".into(), size: 12.0 }));
        let c = d.colors.as_ref().unwrap();
        // sRGB 0.2 0.4 0.6 (NSComponents), calibrated 0.1 0.1 0.12 / 0.9 0.1 0.3 (NSRGB), white 0.5 (NSWhite)
        assert_eq!(c.foreground.as_deref(), Some("#336699"));
        assert_eq!(c.background.as_deref(), Some("#1a1a1f"));
        assert_eq!(c.ansi[1].as_deref(), Some("#e61a4d"));
        assert_eq!(c.cursor.as_deref(), Some("#808080"));
        assert_eq!(c.selection.as_deref(), Some("#404d73"));
        // colours the profile leaves out are Terminal.app's own
        assert_eq!(c.ansi[0].as_deref(), Some("#000000"));
        let broken = got.iter().find(|p| p.name == "Broken").unwrap();
        assert!(!broken.ok && broken.colors.is_none() && broken.font.is_none());
        let basic = got.iter().find(|p| p.name == "Basic").unwrap();
        assert!(basic.ok);
        assert_eq!(basic.colors.as_ref().unwrap().background.as_deref(), Some("#ffffff"));
        assert_eq!(basic.font, None);
        fs::remove_dir_all(&h).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn a_symlinked_prefs_file_is_refused() {
        let h = home("symlink");
        let real = h.join("elsewhere.plist");
        iterm_fixture().to_file_binary(&real).unwrap();
        std::os::unix::fs::symlink(&real, App::Iterm2.path(&h)).unwrap();
        assert!(list(&h).is_empty());
        assert_eq!(read(&h, App::Iterm2), Err("symlink".to_string()));
        fs::remove_dir_all(&h).unwrap();
    }

    #[test]
    fn a_prefs_file_over_8_mb_is_refused() {
        let h = home("big");
        let f = File::create(App::Terminal.path(&h)).unwrap();
        f.set_len(MAX_BYTES + 1).unwrap();
        assert!(list(&h).is_empty());
        assert_eq!(read(&h, App::Terminal), Err("too-large".to_string()));
        assert_eq!(read(&h, App::Iterm2), Err("missing".to_string()));
        fs::remove_dir_all(&h).unwrap();
    }

    #[test]
    fn at_most_64_profiles_cross() {
        let h = home("many");
        let list: Vec<Value> = (0..100)
            .map(|i| {
                let mut d = Dictionary::new();
                d.insert("Name".into(), format!("P{i}").into());
                d.insert("Guid".into(), format!("G{i}").into());
                Value::Dictionary(d)
            })
            .collect();
        let mut root = Dictionary::new();
        root.insert("Default Bookmark Guid".into(), "G80".into());
        root.insert("New Bookmarks".into(), Value::Array(list));
        put(&h, App::Iterm2, &Value::Dictionary(root));
        let got = read(&h, App::Iterm2).unwrap();
        assert_eq!(got.len(), MAX_PROFILES);
        assert_eq!(got[0].name, "P80");
        fs::remove_dir_all(&h).unwrap();
    }

    #[test]
    fn the_only_files_opened_are_the_two_fixed_ones() {
        let h = Path::new("/h");
        assert_eq!(App::Iterm2.path(h), PathBuf::from("/h/Library/Preferences/com.googlecode.iterm2.plist"));
        assert_eq!(App::Terminal.path(h), PathBuf::from("/h/Library/Preferences/com.apple.Terminal.plist"));
        assert_eq!(App::parse("../x"), None);
        assert_eq!(App::parse("iterm2"), Some(App::Iterm2));
    }
}

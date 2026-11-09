//! Accounts: which home folder a new CLI session uses, the CLIProxyAPI management key, and the one kind of
//! request the app sends to a local CLIProxyAPI.
//!
//! * `account_env(cli, id)` gives the env a new session of `cli` starts with to use the omher account
//!   `~/.omher/accounts/<cli>/<id>/` (CLAUDE_CONFIG_DIR, CODEX_HOME, GROK_HOME, GEMINI_CLI_HOME). Logging in
//!   is the CLI's own (`claude` then /login, `codex login`…); omher never reads what it writes there.
//! * The CPA management key is typed once by the person and kept in the OS keychain (macOS Keychain,
//!   Windows Credential Manager). It is never written to a file and never handed back to the UI.
//! * `cpa_send` sends one management request (enable / disable / remove an auth file) to 127.0.0.1 only,
//!   with that key. Nothing else goes over the network from here.

use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Deserialize;

pub const KEYCHAIN_SERVICE: &str = "omher";
pub const KEYCHAIN_USER: &str = "cliproxyapi-management";
const CPA_TIMEOUT: Duration = Duration::from_secs(4);

/// The env var each CLI reads for its home folder (checked in each CLI's docs; Grok Build: GROK_HOME,
/// Gemini CLI: GEMINI_CLI_HOME, which gets a `.gemini` folder inside).
pub fn home_var(cli: &str) -> Option<&'static str> {
    match cli {
        "claude" => Some("CLAUDE_CONFIG_DIR"),
        "codex" => Some("CODEX_HOME"),
        "grok" => Some("GROK_HOME"),
        "gemini" => Some("GEMINI_CLI_HOME"),
        _ => None,
    }
}

/// Same rule as the bridge: lower-case letters, digits, `.`, `_`, `-`; up to 40; not `default`.
pub fn valid_account_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 40
        && id != "default"
        && b[0].is_ascii_alphanumeric()
        && !b[0].is_ascii_uppercase()
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, b'.' | b'_' | b'-'))
        && !id.contains("..")
}

/// `<home>/.omher/accounts/<cli>/<id>`.
pub fn account_dir(home: &Path, cli: &str, id: &str) -> Result<PathBuf, String> {
    home_var(cli).ok_or("unknown cli")?;
    if !valid_account_id(id) {
        return Err("bad account id".into());
    }
    Ok(home.join(".omher").join("accounts").join(cli).join(id))
}

/// The env a new session of `cli` starts with to use account `id`. `default` is the CLI's own home: no env.
pub fn account_env(home: &Path, cli: &str, id: &str) -> Result<Vec<(String, String)>, String> {
    let var = home_var(cli).ok_or("unknown cli")?;
    if id == "default" {
        return Ok(Vec::new());
    }
    let dir = account_dir(home, cli, id)?;
    Ok(vec![(var.to_string(), dir.to_string_lossy().into_owned())])
}

/// One CPA management request, as the bridge describes it (`accounts.cpa_action`).
#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct CpaRequest {
    pub port: u16,
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub body: Option<serde_json::Value>,
}

/// Only enable/disable (PATCH `/v0/management/auth-files/status`) and remove (DELETE
/// `/v0/management/auth-files?name=<file>`), with a plain file name.
pub fn allowed_cpa_request(r: &CpaRequest) -> bool {
    let plain = |s: &str| {
        !s.is_empty()
            && s.len() <= 124
            && s.ends_with(".json")
            && !s.starts_with('.')
            && s.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'@' | b'.' | b'_' | b'+' | b'-'))
    };
    match r.method.as_str() {
        "PATCH" => {
            r.path == "/v0/management/auth-files/status"
                && r.body.as_ref().is_some_and(|b| {
                    b.as_object().is_some_and(|o| {
                        o.len() == 2
                            && o.get("name").and_then(|v| v.as_str()).is_some_and(plain)
                            && o.get("disabled").is_some_and(|v| v.is_boolean())
                    })
                })
        }
        "DELETE" => r.body.is_none() && r.path.strip_prefix("/v0/management/auth-files?name=").is_some_and(plain),
        _ => false,
    }
}

/// The raw HTTP/1.1 request text for `r` with the management key as a Bearer token.
pub fn http_request(r: &CpaRequest, key: &str) -> String {
    let body = r.body.as_ref().map(|b| b.to_string()).unwrap_or_default();
    let mut out = format!(
        "{} {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAuthorization: Bearer {}\r\nConnection: close\r\n",
        r.method, r.path, r.port, key
    );
    if !body.is_empty() {
        out.push_str("Content-Type: application/json\r\n");
    }
    out.push_str(&format!("Content-Length: {}\r\n\r\n{}", body.len(), body));
    out
}

/// `HTTP/1.1 200 OK` -> 200.
pub fn status_code(response: &str) -> Option<u16> {
    let line = response.lines().next()?;
    let mut parts = line.split_whitespace();
    if !parts.next()?.starts_with("HTTP/") {
        return None;
    }
    parts.next()?.parse().ok()
}

/// What a CPA status means for the person (never the response body, which could echo anything).
pub fn status_text(code: u16) -> Result<(), String> {
    match code {
        200..=299 => Ok(()),
        401 | 403 => Err("CPA refused the management key".into()),
        404 => Err("CPA management is off".into()),
        _ => Err(format!("CPA answered {code}")),
    }
}

/// Send `r` to 127.0.0.1 only (never another host), with `key`.
pub fn send_local(r: &CpaRequest, key: &str) -> Result<(), String> {
    if !allowed_cpa_request(r) {
        return Err("not an allowed CPA request".into());
    }
    let addr = SocketAddrV4::new(Ipv4Addr::LOCALHOST, r.port);
    let mut s = TcpStream::connect_timeout(&addr.into(), CPA_TIMEOUT).map_err(|e| format!("CPA is not reachable: {e}"))?;
    s.set_read_timeout(Some(CPA_TIMEOUT)).ok();
    s.set_write_timeout(Some(CPA_TIMEOUT)).ok();
    s.write_all(http_request(r, key).as_bytes()).map_err(|e| e.to_string())?;
    let mut head = [0u8; 256];
    let n = s.read(&mut head).map_err(|e| e.to_string())?;
    let code = status_code(&String::from_utf8_lossy(&head[..n])).ok_or("CPA sent no HTTP status")?;
    status_text(code)
}

// ---------------------------------------------------------------------------------------------
// OS keychain (the only place the management key lives)
// ---------------------------------------------------------------------------------------------

fn entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYCHAIN_SERVICE, KEYCHAIN_USER).map_err(|e| e.to_string())
}

pub fn key_set(key: &str) -> Result<(), String> {
    let k = key.trim();
    if k.is_empty() || k.len() > 512 || k.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return Err("that does not look like a management key".into());
    }
    entry()?.set_password(k).map_err(|e| e.to_string())
}

pub fn key_present() -> bool {
    entry().and_then(|e| e.get_password().map_err(|e| e.to_string())).is_ok()
}

pub fn key_clear() -> Result<(), String> {
    match entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}

pub fn key_get() -> Result<String, String> {
    entry()?.get_password().map_err(|_| "no CPA management key saved".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn req(method: &str, path: &str, body: Option<serde_json::Value>) -> CpaRequest {
        CpaRequest { port: 8317, method: method.into(), path: path.into(), body }
    }

    #[test]
    fn env_per_cli_points_at_the_account_folder() {
        let home = Path::new("/h");
        let dir = |cli: &str| Path::new("/h/.omher/accounts").join(cli).join("work").to_string_lossy().into_owned();
        assert_eq!(account_env(home, "claude", "work").unwrap(), vec![("CLAUDE_CONFIG_DIR".to_string(), dir("claude"))]);
        assert_eq!(account_env(home, "codex", "work").unwrap(), vec![("CODEX_HOME".to_string(), dir("codex"))]);
        assert_eq!(account_env(home, "grok", "work").unwrap()[0].0, "GROK_HOME");
        assert_eq!(account_env(home, "gemini", "work").unwrap()[0].0, "GEMINI_CLI_HOME");
        assert_eq!(account_env(home, "claude", "default").unwrap(), vec![]);
    }

    #[test]
    fn env_refuses_other_paths_and_clis() {
        let home = Path::new("/h");
        for id in ["../x", "..", "a/b", "a\\b", "", "Work", "/tmp", "a..b", &"x".repeat(41)] {
            assert!(account_env(home, "claude", id).is_err(), "{id}");
        }
        assert!(account_env(home, "bash", "work").is_err());
        assert!(account_dir(home, "claude", "default").is_err());
        assert!(valid_account_id("account-2") && valid_account_id("a.b_c"));
    }

    #[test]
    fn only_status_and_delete_of_one_auth_file_are_allowed() {
        let ok = req("PATCH", "/v0/management/auth-files/status", Some(json!({"name": "claude-a@example.com.json", "disabled": true})));
        assert!(allowed_cpa_request(&ok));
        assert!(allowed_cpa_request(&req("DELETE", "/v0/management/auth-files?name=claude-a@example.com.json", None)));
        for bad in [
            req("GET", "/v0/management/auth-files", None),
            req("PUT", "/v0/management/config", Some(json!({}))),
            req("PATCH", "/v0/management/auth-files/status", Some(json!({"name": "../config.yaml", "disabled": true}))),
            req("PATCH", "/v0/management/auth-files/status", Some(json!({"name": "a.json", "disabled": "yes"}))),
            req("PATCH", "/v0/management/auth-files/status", Some(json!({"name": "a.json", "disabled": true, "x": 1}))),
            req("DELETE", "/v0/management/auth-files?name=a.json&all=1", None),
            req("DELETE", "/v0/management/auth-files?name=.a.json", None),
            req("PATCH", "/v0/management/auth-files/status\r\nX: y", Some(json!({"name": "a.json", "disabled": true}))),
        ] {
            assert!(!allowed_cpa_request(&bad), "{bad:?}");
        }
    }

    #[test]
    fn http_request_carries_the_key_only_in_the_header_and_goes_to_loopback() {
        let r = req("PATCH", "/v0/management/auth-files/status", Some(json!({"name": "a.json", "disabled": false})));
        let text = http_request(&r, "K3Y");
        assert!(text.starts_with("PATCH /v0/management/auth-files/status HTTP/1.1\r\nHost: 127.0.0.1:8317\r\n"));
        assert!(text.contains("\r\nAuthorization: Bearer K3Y\r\n"));
        assert_eq!(text.matches("K3Y").count(), 1);
        assert!(text.ends_with("\r\n\r\n{\"disabled\":false,\"name\":\"a.json\"}") || text.ends_with("\r\n\r\n{\"name\":\"a.json\",\"disabled\":false}"));
        let del = http_request(&req("DELETE", "/v0/management/auth-files?name=a.json", None), "K");
        assert!(del.ends_with("Content-Length: 0\r\n\r\n") && !del.contains("Content-Type"));
    }

    #[test]
    fn status_lines_map_to_plain_messages() {
        assert_eq!(status_code("HTTP/1.1 200 OK\r\n\r\n{}"), Some(200));
        assert_eq!(status_code("garbage"), None);
        assert!(status_text(204).is_ok());
        assert_eq!(status_text(404).unwrap_err(), "CPA management is off");
        assert_eq!(status_text(401).unwrap_err(), "CPA refused the management key");
    }

    #[test]
    fn send_local_refuses_a_disallowed_request_before_any_connect() {
        let r = CpaRequest { port: 1, method: "GET".into(), path: "/".into(), body: None };
        assert_eq!(send_local(&r, "k").unwrap_err(), "not an allowed CPA request");
    }

    #[test]
    fn send_local_talks_to_a_loopback_server_and_reads_the_status() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let srv = std::thread::spawn(move || {
            let (mut s, _) = listener.accept().unwrap();
            let mut buf = [0u8; 1024];
            let n = s.read(&mut buf).unwrap();
            s.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n").unwrap();
            String::from_utf8_lossy(&buf[..n]).into_owned()
        });
        let r = CpaRequest { port, method: "DELETE".into(), path: "/v0/management/auth-files?name=a.json".into(), body: None };
        assert_eq!(send_local(&r, "k").unwrap_err(), "CPA management is off");
        assert!(srv.join().unwrap().starts_with("DELETE /v0/management/auth-files?name=a.json HTTP/1.1"));
    }

    #[test]
    fn a_blank_or_multiline_key_is_refused_before_the_keychain() {
        assert!(key_set("").is_err());
        assert!(key_set("a b").is_err());
        assert!(key_set("a\nb").is_err());
    }
}

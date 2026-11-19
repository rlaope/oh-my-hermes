//! This computer's name, read from the system (no program is run). The page uses it only to accept a shell's
//! OSC 7 folder report (`file://<host>/<path>`) as coming from this computer; it is not kept or sent anywhere.

/// This computer's host name, or an empty string when the system gives none.
pub fn name() -> String {
    clean(raw())
}

/// The name as text: up to the first NUL, without surrounding spaces; empty when it is too long or holds a control
/// character.
fn clean(b: Vec<u8>) -> String {
    let end = b.iter().position(|&c| c == 0).unwrap_or(b.len());
    let s = String::from_utf8_lossy(&b[..end]).trim().to_string();
    if s.len() > 255 || s.chars().any(|c| c.is_control()) {
        return String::new();
    }
    s
}

#[cfg(unix)]
fn raw() -> Vec<u8> {
    let mut buf = vec![0u8; 256];
    // SAFETY: the buffer is writable for its whole length, and gethostname writes at most that many bytes.
    let rc = unsafe { libc::gethostname(buf.as_mut_ptr() as *mut libc::c_char, buf.len()) };
    if rc != 0 {
        return Vec::new();
    }
    buf
}

#[cfg(windows)]
fn raw() -> Vec<u8> {
    const DNS_HOSTNAME: i32 = 1; // ComputerNameDnsHostname
    #[link(name = "kernel32")]
    extern "system" {
        fn GetComputerNameExW(kind: i32, buffer: *mut u16, size: *mut u32) -> i32;
    }
    let mut buf = [0u16; 256];
    let mut size = buf.len() as u32;
    // SAFETY: `size` holds the buffer's length in UTF-16 units; on success it is the count written, without the NUL.
    let ok = unsafe { GetComputerNameExW(DNS_HOSTNAME, buf.as_mut_ptr(), &mut size) };
    if ok == 0 {
        return Vec::new();
    }
    String::from_utf16_lossy(&buf[..(size as usize).min(buf.len())]).into_bytes()
}

#[cfg(not(any(unix, windows)))]
fn raw() -> Vec<u8> {
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_a_name_without_nul_or_control_characters() {
        let n = name();
        assert!(!n.contains('\0'));
        assert!(!n.chars().any(|c| c.is_control()));
        assert_eq!(clean(b"mybox.local\0\0\0".to_vec()), "mybox.local");
        assert_eq!(clean(b"bad\nname".to_vec()), "");
        assert_eq!(clean(Vec::new()), "");
    }
}

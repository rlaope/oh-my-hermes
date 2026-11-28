#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
fn main() {
    // a TERMINALS Claude Code's status line runs this binary as a relay: handled before anything of the app starts
    let args: Vec<std::ffi::OsString> = std::env::args_os().collect();
    // a restored Shell row's program (Program Resume): started in place of this process, before anything of the app
    if let Some(code) = omher_lib::resume_exec(&args) {
        std::process::exit(code);
    }
    if let Some(code) = omher_lib::statusline_relay(&args) {
        std::process::exit(code);
    }
    omher_lib::run()
}

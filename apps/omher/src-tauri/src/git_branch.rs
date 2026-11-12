//! The git branch of a session's folder, for the line under its composer. Read from the repository's own `HEAD`
//! file only: no program runs (not even `git`), nothing is written, and nothing but `HEAD` (and the one-line
//! `.git` file of a worktree or submodule that points at its git folder) is opened.

use std::path::{Path, PathBuf};

/// The most bytes read from a `HEAD` or `.git` file (both are one short line).
const MAX: u64 = 4096;

fn read_small(p: &Path) -> Option<String> {
    use std::io::Read;
    let f = std::fs::File::open(p).ok()?;
    let mut s = String::new();
    f.take(MAX).read_to_string(&mut s).ok()?;
    Some(s)
}

/// The git folder of the repository `cwd` is in: `<dir>/.git` (a folder), or the folder a `.git` file names
/// (`gitdir: <path>`, a worktree or submodule), looking up from `cwd` to the filesystem root.
fn git_dir(cwd: &Path) -> Option<PathBuf> {
    let mut at = Some(cwd);
    while let Some(dir) = at {
        let dot = dir.join(".git");
        if dot.is_dir() {
            return Some(dot);
        }
        if dot.is_file() {
            let line = read_small(&dot)?;
            let target = line.trim().strip_prefix("gitdir:")?.trim().to_string();
            let p = PathBuf::from(&target);
            return Some(if p.is_absolute() { p } else { dir.join(p) });
        }
        at = dir.parent();
    }
    None
}

/// The branch checked out in the repository `cwd` is in: its name (`main`, `feat/x`), the first 7 characters of
/// the commit when detached, or "" when `cwd` is not in a repository (or is not an absolute folder).
pub fn branch(cwd: &Path) -> String {
    if !cwd.is_absolute() || !cwd.is_dir() {
        return String::new();
    }
    let Some(head) = git_dir(cwd).and_then(|d| read_small(&d.join("HEAD"))) else { return String::new() };
    let head = head.trim();
    if let Some(r) = head.strip_prefix("ref:") {
        let r = r.trim();
        return r.strip_prefix("refs/heads/").unwrap_or(r).chars().filter(|c| !c.is_control()).take(200).collect();
    }
    if head.len() >= 7 && head.chars().all(|c| c.is_ascii_hexdigit()) {
        return head[..7].to_string();
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("omher-branch-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d.canonicalize().unwrap()
    }

    #[test]
    fn reads_the_branch_from_head_in_the_folder_or_above_it() {
        let d = tmp("repo");
        std::fs::create_dir_all(d.join(".git")).unwrap();
        std::fs::write(d.join(".git/HEAD"), "ref: refs/heads/feat/session-controls\n").unwrap();
        std::fs::create_dir_all(d.join("src/deep")).unwrap();
        assert_eq!(branch(&d), "feat/session-controls");
        assert_eq!(branch(&d.join("src/deep")), "feat/session-controls");
        // detached: the short commit id
        std::fs::write(d.join(".git/HEAD"), "3e3f4c19e6bc9a5995f99b1a3689779ab98ad112\n").unwrap();
        assert_eq!(branch(&d), "3e3f4c1");
        let _ = std::fs::remove_dir_all(d);
    }

    #[test]
    fn a_worktree_follows_its_git_file() {
        let d = tmp("wt");
        let main = d.join("main/.git/worktrees/wt");
        std::fs::create_dir_all(&main).unwrap();
        std::fs::write(main.join("HEAD"), "ref: refs/heads/feat/omher-session-controls\n").unwrap();
        std::fs::create_dir_all(d.join("wt")).unwrap();
        std::fs::write(d.join("wt/.git"), format!("gitdir: {}\n", main.display())).unwrap();
        assert_eq!(branch(&d.join("wt")), "feat/omher-session-controls");
        // a relative gitdir is taken from the folder that holds the .git file
        std::fs::write(d.join("wt/.git"), "gitdir: ../main/.git/worktrees/wt\n").unwrap();
        assert_eq!(branch(&d.join("wt")), "feat/omher-session-controls");
        let _ = std::fs::remove_dir_all(d);
    }

    #[test]
    fn nothing_outside_a_repository_or_for_a_bad_path() {
        let d = tmp("plain");
        assert_eq!(branch(&d), "");
        assert_eq!(branch(Path::new("relative/dir")), "");
        assert_eq!(branch(&d.join("missing")), "");
        // a HEAD that is neither a ref nor a commit says nothing
        std::fs::create_dir_all(d.join(".git")).unwrap();
        std::fs::write(d.join(".git/HEAD"), "garbage").unwrap();
        assert_eq!(branch(&d), "");
        let _ = std::fs::remove_dir_all(d);
    }
}

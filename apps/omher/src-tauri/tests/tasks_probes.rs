// The verifier's probes (V1/V2 on PR #2908) kept as regression tests: production tasks.rs, included unchanged, with
// only its host-resolution dependencies stubbed. Unix only (the fake `gh` is a shell script).
#![cfg(unix)]
#![allow(dead_code)]
mod bridge { #[derive(Clone, Copy)] pub struct Os; impl Os { pub fn current() -> Self { Self } } pub(crate) fn no_console_window(_: &mut std::process::Command) {} }
mod accounts {
 use std::path::{Path,PathBuf};
 pub fn search_dirs<E: Fn(&str)->Option<String>>(env: &E, _: crate::bridge::Os) -> Vec<PathBuf> { std::env::split_paths(&env("PATH").unwrap_or_default()).collect() }
 pub fn resolve<X: Fn(&Path)->bool>(p: &str, dirs: &[PathBuf], ok: X, _:crate::bridge::Os) -> Option<PathBuf> { dirs.iter().map(|d|d.join(p)).find(|p|ok(p)) }
}
#[path="../src/git_branch.rs"] mod git_branch;
mod appimage { pub fn host_env(_: &mut std::process::Command) {} }
#[path="../src/tasks.rs"] mod tasks;
use tasks::*;
#[test]
fn independent_cli_status_without_credentials() {
 use std::os::unix::fs::PermissionsExt;
 let base=std::env::temp_dir().join(format!("verify7-gh-status-{}",std::process::id()));
 std::fs::create_dir_all(&base).unwrap();
 let old=std::env::var_os("PATH");
 std::env::set_var("PATH",&base);
 let absent=Tasks::default().status(Source::Github,true);
 assert!(!absent.installed && !absent.signed_in);
 let exe=base.join("gh");
 std::fs::write(&exe,"#!/bin/sh\nprintf 'fake credential must be discarded' >&2\nexit 1\n").unwrap();
 std::fs::set_permissions(&exe,std::fs::Permissions::from_mode(0o700)).unwrap();
 let signedout=Tasks::default().status(Source::Github,true);
 assert!(signedout.installed && !signedout.signed_in);
 println!("actual Tasks::status with isolated resolver: missing={absent:?}, signedout={signedout:?}; no auth text returned");
 match old {Some(v)=>std::env::set_var("PATH",v),None=>std::env::remove_var("PATH")};
 std::fs::remove_dir_all(base).unwrap();
}
#[test]
fn independent_reject_repo_attacks() {
 for source in [Source::Github,Source::Gitlab] { for repo in ["o/r;touch", "o/r space", "o/..", "../r", "o/r/../x"] { assert!(check_repo(source,repo).is_err(),"{repo}"); } }
 println!("semicolon, space, dot-dot segment attacks refused by actual check_repo");
}
#[test]
fn independent_500_items_paginate() {
 // gh answers newest first, at most --limit rows, only rows created at or before the search's `created:<=`
 let base=1_794_766_799i64;
 let all: Vec<_>=(1..=500).rev().map(|n:i64|serde_json::json!({"number":n,"title":format!("issue {n}"),"createdAt":iso(base-(500-n)/3)})).collect();
 let t=Tasks::default();
 let mut seen=Vec::new();
 for page in 0..30 {
  let mut limit=0;
  let result=t.list_with(Source::Github,Kind::Issues,"o/r",Filter::Open,page,|argv|{
   limit=argv.iter().position(|a|a=="--limit").map(|i|argv[i+1].parse::<usize>().unwrap()).unwrap();
   let search=argv.iter().position(|a|a=="--search").map(|i|argv[i+1].clone()).unwrap();
   let bound=search.split(' ').find_map(|w|w.strip_prefix("created:<=")).map(epoch);
   let rows:Vec<_>=all.iter().filter(|r|bound.is_none_or(|b|epoch(r["createdAt"].as_str().unwrap())<=b)).take(limit).collect();
   Ok(serde_json::to_string(&rows).unwrap())
  }).unwrap();
  println!("page={page} limit={limit} rows={} more={}",result.items.len(),result.more);
  assert!(limit<=PAGE+4,"page {page}: one call asked for {limit} rows");
  seen.extend(result.items.iter().map(|i|i.number)); if !result.more {break;}
 }
 println!("seen={} requested=500",seen.len()); assert_eq!(seen.len(),500,"all 500 items must remain reachable");
 assert_eq!(seen,(1..=500).rev().collect::<Vec<i64>>().iter().map(|n|*n as u64).collect::<Vec<u64>>());
}
#[test]
fn independent_token_body_not_exposed() {
 let fake=format!("ghp_{}","X".repeat(36));
 let json=serde_json::json!({"number":1,"title":"test","body":format!("example credential {fake}")}).to_string();
 let d=parse_view(Source::Github,Kind::Issues,&json).unwrap();
 let exposed=d.body.contains(&fake); println!("fake token retained in detail payload: {exposed}");
 assert!(!exposed,"token-like issue content must not be shown");
}
#[test]
fn independent_error_token_punctuation() {
 let fake=format!("ghp_{}","X".repeat(36));
 let exposed=error_line(&format!("failure credential={fake}")).contains(&fake);
 println!("fake token retained in error_line with credential= prefix: {exposed}");
 assert!(!exposed,"token-like error content must not be shown");
}

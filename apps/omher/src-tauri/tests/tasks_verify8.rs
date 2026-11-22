// Independent acceptance neighbours, production module unchanged.
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
fn v8_1001_pagination() {
 for kind in [Kind::Issues,Kind::Changes] {
  let all: Vec<_>=(1..=1001).rev().map(|n:i64|serde_json::json!({"number":n,"title":format!("row {n}"),"createdAt":iso(1794766799-(1001-n)/7)})).collect();
  let t=Tasks::default(); let mut seen=Vec::new(); let mut max_limit=0;
  for page in 0..50 {
   let result=t.list_with(Source::Github,kind,"o/r",Filter::Open,page,"",|argv| {
    let limit=argv[argv.iter().position(|a|a=="--limit").unwrap()+1].parse::<usize>().unwrap();
    max_limit=max_limit.max(limit);
    let search=&argv[argv.iter().position(|a|a=="--search").unwrap()+1];
    let bound=search.split_whitespace().find_map(|w|w.strip_prefix("created:<=")).map(epoch);
    let rows:Vec<_>=all.iter().filter(|r|bound.is_none_or(|b|epoch(r["createdAt"].as_str().unwrap())<=b)).take(limit).collect();
    Ok(serde_json::to_string(&rows).unwrap())
   }).unwrap();
   seen.extend(result.items.iter().map(|r|r.number));
   if !result.more {break;}
  }
  println!("V8 {kind:?}: seen={} unique={} max_limit={max_limit}",seen.len(),seen.iter().collect::<std::collections::HashSet<_>>().len());
  assert_eq!(seen,(1u64..=1001).rev().collect::<Vec<_>>()); assert!(max_limit<=33);
 }
}
#[test]
fn v8_code_link_and_surroundings() {
 let fake=format!("ghp_{}","X".repeat(36));
 let body=format!("before\n```sh\n{fake}\n```\n[docs](https://example.org/?token={fake})\nafter");
 let raw=serde_json::json!({"number":1,"title":"safe","body":body,"comments":[{"body":fake,"author":{"login":"tester"}}]}).to_string();
 let d=parse_view(Source::Github,Kind::Issues,&raw).unwrap();
 assert!(!d.body.contains(&fake)); assert!(d.body.contains("before")&&d.body.contains("after")&&d.body.contains("••••"));
 assert!(!serde_json::to_string(&d).unwrap().contains(&fake)); println!("V8 code, URL, comment masked; before/after retained");
}
#[test]
fn v8_split_line_token() {
 let split=format!("ghp_XXXX\n{}","X".repeat(32));
 let raw=serde_json::json!({"number":1,"title":"safe","body":format!("before {split} after")}).to_string();
 let d=parse_view(Source::Github,Kind::Issues,&raw).unwrap();
 let retained=d.body.replace('\n',"").contains(&format!("ghp_{}","X".repeat(36)));
 println!("V8 split-line token retained after newline removal={retained}");
 assert!(!retained,"split-line synthetic token exposed by parse_view");
}

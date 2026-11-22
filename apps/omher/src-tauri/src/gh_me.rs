//! Tasks' "나" (Me) scope and Settings › Accounts' GitHub accounts (BOUNDARY rules 18 and 33): the open pull requests
//! that ask for my review, my own open pull requests, the open issues assigned to me and the last week's mentions of
//! me, across every repository, for each GitHub account the person chose in omher. Read-only, through the person's
//! own GitHub CLI (`gh`), with the same runner as tasks.rs (`tasks::run_env`: no shell, nothing on stdin, at most 20
//! seconds).
//!
//! What crosses from the page is only an account id (`<login>@<host>`, checked and then looked up among the accounts
//! `gh auth status --json hosts` lists), a section word and a page number. Every argv is built here from fixed words.
//!
//! The token exception (BOUNDARY rules 5, 10 and 18). gh signs in one account per host at a time (the active one),
//! and which one that is can change under omher at any moment (a `gh auth switch` or `gh auth login` in any shell).
//! So every call as a chosen account, active or not, is pinned to that account: it first asks gh for that account's
//! own token (`gh auth token --hostname <host> --user <login>`) and passes it only as `GH_TOKEN`
//! (`GH_ENTERPRISE_TOKEN` for a GitHub Enterprise Server host) with `GH_HOST` in the environment of that one `gh`
//! child, and the status query must then name that account as its viewer. The token is read fresh for each call and
//! never cached: the copy omher keeps for the call lives in a `Zeroizing` string that is wiped when the call ends, and
//! it is never put in an argv, a log line, an error, the cache or anything the page gets. A few short-lived copies
//! inside the runner and std's `Command` (the pipe's bytes before they become that string, the child's environment)
//! are freed without being wiped. Every child here also drops any `GH_TOKEN` / `GITHUB_TOKEN` / `GH_ENTERPRISE_TOKEN`
//! / `GITHUB_ENTERPRISE_TOKEN` omher inherited (so `gh auth status` lists gh's own logins and a call reads the account
//! named) and gh's debug and pager variables. omher never runs `gh auth switch`; only gh's own sign-in (`gh auth
//! login`, run by the person in a terminal tab) makes the account it signs in gh's active one, as gh always does.
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use zeroize::Zeroizing;

use crate::tasks::{check_repo, epoch, error_line, find, gh_author, gh_labels, iso, one_line, run_full, text, web_url, Detail, Filter, Kind, Label, Page, Ran, Source, Tasks, KEEP};

/// The last page of a section (gh search has no page flag: page `n` asks for `(n + 1) * base` rows).
pub const MAX_ME_PAGE: u32 = 3;
/// ⟳ reads again only an answer older than this (the minute's cache stands otherwise).
const MIN_GAP: Duration = Duration::from_secs(15);
/// GitHub allows 30 searches a minute per user; omher stops a little below that and says "try again soon".
const SEARCHES_PER_MINUTE: usize = 27;

// ---- accounts -----------------------------------------------------------------------------------

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct GhAccount {
    pub host: String,
    pub login: String,
    /// gh's active account on this host (its calls need no token)
    pub active: bool,
    /// gh's own word: `success` when the login works; anything else (`error`, `timeout`) means sign in again
    pub state: String,
    pub scopes: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct GhAccounts {
    /// gh was found
    pub installed: bool,
    pub accounts: Vec<GhAccount>,
}

/// One account row of `gh auth status --json hosts`: only these five fields are read. Any other field the CLI prints
/// (a token, should a gh version print one) is skipped by the parser and never becomes a value in omher.
#[derive(Deserialize)]
struct StatusRow {
    #[serde(default)]
    host: String,
    #[serde(default)]
    login: String,
    #[serde(default)]
    active: bool,
    #[serde(default)]
    state: String,
    #[serde(default)]
    scopes: Option<Value>,
}

#[derive(Deserialize)]
struct StatusDoc {
    #[serde(default)]
    hosts: BTreeMap<String, Vec<StatusRow>>,
}

/// A GitHub host name: lowercase DNS labels, at least two, no port, no leading `-`.
pub fn host_ok(h: &str) -> bool {
    h.len() <= 253
        && h.split('.').count() >= 2
        && h.split('.').all(|p| !p.is_empty() && p.len() <= 63 && !p.starts_with('-') && !p.ends_with('-') && p.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-'))
}

/// A GitHub login (and an Enterprise managed user's `name_short`): letters, digits, `-` and `_`, not starting with
/// `-` or `_`, at most 64.
pub fn login_ok(l: &str) -> bool {
    !l.is_empty() && l.len() <= 64 && !l.starts_with('-') && !l.starts_with('_') && l.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

/// `<login>@<host>` as its two checked parts.
pub fn parse_account_id(id: &str) -> Result<(String, String), String> {
    let (login, host) = id.split_once('@').ok_or_else(|| "not a GitHub account".to_string())?;
    if !login_ok(login) || !host_ok(host) {
        return Err("not a GitHub account".into());
    }
    Ok((login.to_string(), host.to_string()))
}

impl GhAccount {
    pub fn id(&self) -> String {
        format!("{}@{}", self.login, self.host)
    }
}

/// The argv (after `gh`) that lists the signed-in accounts. Never `--show-token`.
pub fn status_argv() -> Vec<String> {
    vec!["auth".into(), "status".into(), "--json".into(), "hosts".into()]
}

/// The accounts of a `gh auth status --json hosts` answer: host, login, active, state and scopes, nothing else.
/// A row whose host or login is not well formed is left out.
pub fn parse_auth_status(out: &str) -> Result<Vec<GhAccount>, String> {
    let doc: StatusDoc = serde_json::from_str(out.trim()).map_err(|_| "gh answered something that is not its account list".to_string())?;
    let mut all = Vec::new();
    for (key, rows) in doc.hosts {
        for r in rows {
            let host = if r.host.is_empty() { key.to_ascii_lowercase() } else { r.host.to_ascii_lowercase() };
            if !host_ok(&host) || !login_ok(&r.login) {
                continue;
            }
            let scopes = match r.scopes {
                Some(Value::String(s)) => s.split(',').map(|x| x.trim().trim_matches('\'').to_string()).filter(|x| !x.is_empty()).collect(),
                Some(Value::Array(a)) => a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect(),
                _ => vec![],
            };
            let scopes = scopes.into_iter().filter(|s: &String| s.len() <= 40 && s.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, ':' | '_' | '-'))).take(30).collect();
            let state = if r.state.chars().all(|c| c.is_ascii_lowercase()) && r.state.len() <= 16 { r.state } else { "error".into() };
            all.push(GhAccount { host, login: r.login, active: r.active, state, scopes });
        }
    }
    Ok(all)
}

/// The argv (after `gh`) that prints account `login`'s token on `host`. Its answer goes only into the environment of
/// the one call it was read for (`account_env`).
pub fn token_argv(host: &str, login: &str) -> Result<Vec<String>, String> {
    if !host_ok(host) || !login_ok(login) {
        return Err("not a GitHub account".into());
    }
    Ok(vec!["auth".into(), "token".into(), "--hostname".into(), host.into(), "--user".into(), login.into()])
}

/// gh's own sign-in for one more account (after `gh`): `auth login`, or `auth login --hostname <host>` for a GitHub
/// Enterprise host. Run in a terminal-panel tab (sessions.rs `start_gh_login`); never `auth switch`.
pub fn login_argv(host: Option<&str>) -> Result<Vec<String>, String> {
    let mut a = vec!["auth".to_string(), "login".to_string()];
    if let Some(h) = host.filter(|h| !h.is_empty()) {
        if !host_ok(h) {
            return Err("not a GitHub host".into());
        }
        a.extend(["--hostname".to_string(), h.to_string()]);
    }
    Ok(a)
}

/// The variable gh reads a token from for `host`: `GH_TOKEN` for github.com and GHE.com, `GH_ENTERPRISE_TOKEN` for a
/// GitHub Enterprise Server host.
pub fn token_var(host: &str) -> &'static str {
    if host == "github.com" || host.ends_with(".ghe.com") {
        "GH_TOKEN"
    } else {
        "GH_ENTERPRISE_TOKEN"
    }
}

/// What every child here takes out of the environment omher inherited: the tokens above, and gh's debug output and
/// pager (a debug log can print request headers; a pager would wait on a terminal there is none of).
pub const SCRUB: [&str; 8] = ["GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_DEBUG", "DEBUG", "GH_PAGER", "PAGER"];

/// The REST search requests one search argv costs: gh pages a search 100 rows at a time.
pub fn search_cost(argv: &[String]) -> usize {
    let limit = argv.iter().position(|a| a == "--limit").and_then(|i| argv.get(i + 1)).and_then(|n| n.parse::<usize>().ok()).unwrap_or(1);
    limit.max(1).div_ceil(100)
}

/// An account list with each `<login>@<host>` once (the first gh lists).
pub fn dedupe(accounts: Vec<GhAccount>) -> Vec<GhAccount> {
    let mut seen = std::collections::HashSet::new();
    accounts.into_iter().filter(|a| seen.insert(a.id().to_ascii_lowercase())).collect()
}

/// "이 저장소" reads a github.com repository (tasks.rs reads remotes on github.com only), so a chosen account it reads
/// as must be a github.com one: a GitHub Enterprise account would read another host's repository of that name.
pub fn repo_account_ok(id: &str) -> Result<(), String> {
    match parse_account_id(id)? {
        (_, host) if host == "github.com" => Ok(()),
        _ => Err("this repository is on github.com; pick a github.com account".into()),
    }
}

/// The environment one call as an account adds: its host and that account's own token. Nothing else.
pub fn account_env<'a>(host: &'a str, token: &'a str) -> Vec<(&'static str, &'a str)> {
    vec![("GH_HOST", host), (token_var(host), token)]
}

// ---- the sections -------------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Section {
    /// open pull requests that ask for my review
    Review,
    /// my own open pull requests
    Authored,
    /// open issues assigned to me
    Assigned,
    /// issues and pull requests that mention me, updated in the last 7 days
    Mentions,
}

impl Section {
    pub fn parse(s: &str) -> Result<Section, String> {
        match s {
            "review" => Ok(Section::Review),
            "authored" => Ok(Section::Authored),
            "assigned" => Ok(Section::Assigned),
            "mentions" => Ok(Section::Mentions),
            _ => Err(format!("unknown section {s:?}")),
        }
    }
    /// Rows a page holds.
    pub fn base(self) -> usize {
        if self == Section::Mentions {
            30
        } else {
            50
        }
    }
}

/// The fields read from a pull request search and an issue search (`gh search issues` has no `isDraft`).
const PR_FIELDS: &str = "number,title,url,repository,isDraft,isPullRequest,state,createdAt,updatedAt,author,labels";
const ISSUE_FIELDS: &str = "number,title,url,repository,isPullRequest,state,createdAt,updatedAt,author,labels";

/// The search argv (after `gh`) for one page of `section`. `now`: seconds since the epoch (the mentions' 7 days).
pub fn search_argv(section: Section, page: u32, now: i64) -> Result<Vec<String>, String> {
    if page > MAX_ME_PAGE {
        return Err(format!("page {} is past the last one", page.saturating_add(1)));
    }
    let s = |v: &str| v.to_string();
    let mut a = match section {
        Section::Review => vec![s("search"), s("prs"), s("--review-requested=@me"), s("--state=open")],
        Section::Authored => vec![s("search"), s("prs"), s("--author=@me"), s("--state=open")],
        Section::Assigned => vec![s("search"), s("issues"), s("--assignee=@me"), s("--state=open")],
        Section::Mentions => vec![s("search"), s("issues"), s("--mentions=@me"), s("--include-prs"), format!("--updated=>={}", &iso(now - 7 * 86_400)[..10])],
    };
    let limit = section.base() * (page as usize + 1);
    let fields = if a[1] == "prs" { PR_FIELDS } else { ISSUE_FIELDS };
    // a fixed order, so page n + 1 continues page n (gh's default, best match, can reorder between calls)
    a.extend([s("--sort=updated"), s("--order=desc"), s("--json"), s(fields), s("--limit"), limit.to_string()]);
    Ok(a)
}

/// The one GraphQL query: CI, review decision and mergeability of my open pull requests and of the open pull requests
/// that ask for my review, and when my review was asked for. Fixed text; the page never sends a query.
pub const STATUS_QUERY: &str = "query { viewer { login pullRequests(states: OPEN, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) { nodes { ...pr } } } \
search(query: \"is:open is:pr review-requested:@me archived:false\", type: ISSUE, first: 50) { nodes { ...pr ... on PullRequest { timelineItems(itemTypes: [REVIEW_REQUESTED_EVENT], last: 10) { nodes { ... on ReviewRequestedEvent { createdAt requestedReviewer { ... on User { login } } } } } } } } } \
fragment pr on PullRequest { number isDraft reviewDecision mergeable repository { nameWithOwner } commits(last: 1) { nodes { commit { statusCheckRollup { state } } } } }";

/// The argv (after `gh`) of the status query.
pub fn graphql_argv() -> Vec<String> {
    vec!["api".into(), "graphql".into(), "-f".into(), format!("query={STATUS_QUERY}")]
}

// ---- what the page gets -------------------------------------------------------------------------

#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct MeItem {
    /// `owner/repo`
    pub repo: String,
    pub number: u64,
    pub title: String,
    pub url: String,
    /// a pull request (else an issue)
    pub pr: bool,
    pub draft: bool,
    /// `open`, `closed`, `merged` or `draft`
    pub state: String,
    pub author: String,
    pub labels: Vec<Label>,
    /// seconds since the epoch (0: unknown)
    pub created: i64,
    pub updated: i64,
    /// my review is asked for (the review section)
    pub asked: bool,
    /// `passed`, `failed`, `pending`, or "" (no checks, or not read)
    pub ci: String,
    /// `approved`, `changes`, `required`, or ""
    pub review: String,
    /// GitHub says it has a merge conflict
    pub conflict: bool,
    /// when my review was asked for (0: unknown)
    pub requested: i64,
}

#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct MePage {
    pub items: Vec<MeItem>,
    /// another page may follow
    pub more: bool,
}

/// A failed call: `rate` (GitHub's rate limit: "try again soon", not a failure), `auth` (the account must sign in
/// again) or `other`. `line` is masked and short.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct MeError {
    pub kind: &'static str,
    pub line: String,
}

impl MeError {
    pub fn new(kind: &'static str, line: impl Into<String>) -> MeError {
        MeError { kind, line: line.into() }
    }
}

/// The kind of a gh error line (already masked).
pub fn classify(line: &str) -> MeError {
    let l = line.to_ascii_lowercase();
    let kind = if l.contains("rate limit") || l.contains("abuse detection") {
        "rate"
    } else if l.contains("401") || l.contains("bad credentials") || l.contains("not logged in") || l.contains("gh auth login") || l.contains("no oauth token") || l.contains("authentication") {
        "auth"
    } else {
        "other"
    };
    MeError::new(kind, if line.is_empty() { "gh failed".to_string() } else { line.to_string() })
}

fn up(v: &Value, k: &str) -> String {
    text(v, k).to_ascii_uppercase()
}

/// A search answer as items. `section` marks the review section's rows as asking for me.
pub fn parse_search(section: Section, out: &str) -> Result<Vec<MeItem>, String> {
    let v: Value = serde_json::from_str(out.trim()).map_err(|_| "gh answered something that is not JSON".to_string())?;
    let rows = v.as_array().ok_or_else(|| "gh did not answer a list".to_string())?;
    let mut items = Vec::new();
    for r in rows {
        let number = r.get("number").and_then(Value::as_u64).unwrap_or(0);
        let Some(repo) = r.get("repository").map(|x| text(x, "nameWithOwner")).and_then(|n| check_repo(Source::Github, &n).ok()) else { continue };
        if number == 0 {
            continue;
        }
        let pr = r.get("isPullRequest").and_then(Value::as_bool).unwrap_or(matches!(section, Section::Review | Section::Authored));
        let draft = r.get("isDraft").and_then(Value::as_bool).unwrap_or(false);
        let state = match up(r, "state").as_str() {
            "MERGED" => "merged",
            "CLOSED" => "closed",
            _ if draft => "draft",
            _ => "open",
        };
        items.push(MeItem {
            repo,
            number,
            title: one_line(text(r, "title"), 300),
            url: web_url(&text(r, "url")),
            pr,
            draft,
            state: state.into(),
            author: gh_author(r),
            labels: gh_labels(r),
            created: epoch(&text(r, "createdAt")),
            updated: epoch(&text(r, "updatedAt")),
            asked: section == Section::Review,
            ..Default::default()
        });
    }
    Ok(items)
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrState {
    pub ci: String,
    pub review: String,
    pub conflict: bool,
    pub draft: bool,
    pub requested: i64,
}

fn pr_state(n: &Value, me: &str) -> Option<((String, u64), PrState)> {
    let number = n.get("number").and_then(Value::as_u64)?;
    let repo = check_repo(Source::Github, &text(n.get("repository")?, "nameWithOwner")).ok()?;
    let rollup = n.pointer("/commits/nodes/0/commit/statusCheckRollup").filter(|x| x.is_object());
    let ci = match rollup.map(|r| up(r, "state")).as_deref() {
        Some("SUCCESS") => "passed",
        Some("FAILURE") | Some("ERROR") => "failed",
        Some("PENDING") | Some("EXPECTED") => "pending",
        _ => "",
    };
    let review = match up(n, "reviewDecision").as_str() {
        "APPROVED" => "approved",
        "CHANGES_REQUESTED" => "changes",
        "REVIEW_REQUIRED" => "required",
        _ => "",
    };
    // the latest request naming me, else the latest request (a team's)
    let events: Vec<&Value> = n.pointer("/timelineItems/nodes").and_then(Value::as_array).map(|a| a.iter().collect()).unwrap_or_default();
    let mine = events.iter().rev().find(|e| e.pointer("/requestedReviewer/login").and_then(Value::as_str).is_some_and(|l| l.eq_ignore_ascii_case(me)));
    let requested = mine.or(events.last()).map(|e| epoch(&text(e, "createdAt"))).unwrap_or(0);
    Some((
        (repo, number),
        PrState { ci: ci.into(), review: review.into(), conflict: up(n, "mergeable") == "CONFLICTING", draft: n.get("isDraft").and_then(Value::as_bool).unwrap_or(false), requested },
    ))
}

/// The status query's answer, by (`owner/repo`, number).
pub fn parse_status(out: &str) -> Result<HashMap<(String, u64), PrState>, String> {
    let v: Value = serde_json::from_str(out.trim()).map_err(|_| "gh answered something that is not JSON".to_string())?;
    let data = v.get("data").filter(|d| d.is_object()).ok_or_else(|| {
        let first = v.pointer("/errors/0/message").and_then(Value::as_str).unwrap_or("the status query failed");
        error_line(first)
    })?;
    let me = data.pointer("/viewer/login").and_then(Value::as_str).unwrap_or("");
    let mut all = HashMap::new();
    for path in ["/viewer/pullRequests/nodes", "/search/nodes"] {
        for n in data.pointer(path).and_then(Value::as_array).into_iter().flatten() {
            if let Some((k, st)) = pr_state(n, me) {
                all.insert(k, st);
            }
        }
    }
    Ok(all)
}

/// A GraphQL answer with a `data` object (possibly beside `errors`).
pub fn has_data(out: &str) -> bool {
    serde_json::from_str::<Value>(out.trim()).ok().is_some_and(|v| v.get("data").is_some_and(Value::is_object))
}

/// The login the status query ran as (`viewer.login`).
pub fn viewer_login(out: &str) -> Option<String> {
    let v: Value = serde_json::from_str(out.trim()).ok()?;
    v.pointer("/data/viewer/login").and_then(Value::as_str).filter(|l| login_ok(l)).map(str::to_string)
}

/// Fill each pull request's CI, review, conflict and request time from the status query.
pub fn merge_status(items: &mut [MeItem], status: &HashMap<(String, u64), PrState>) {
    for i in items.iter_mut().filter(|i| i.pr) {
        if let Some(st) = status.get(&(i.repo.clone(), i.number)) {
            i.ci = st.ci.clone();
            i.review = st.review.clone();
            i.conflict = st.conflict;
            i.draft = i.draft || st.draft;
            i.requested = st.requested;
        }
    }
}

/// How much an item needs me now: 0 its CI failed, 1 changes were requested, 2 it has a merge conflict, 3 my review is
/// asked for, 4 the rest. (src/tasks/me.ts `attention` is the same order.)
pub fn attention(i: &MeItem) -> u8 {
    if i.ci == "failed" {
        0
    } else if i.review == "changes" {
        1
    } else if i.conflict {
        2
    } else if i.asked {
        3
    } else {
        4
    }
}

/// Items needing action first; review requests oldest first (waited longest); the rest newest first.
pub fn sort_items(items: &mut [MeItem]) {
    items.sort_by(|a, b| {
        let (x, y) = (attention(a), attention(b));
        x.cmp(&y).then_with(|| if x == 3 { waited(a).cmp(&waited(b)) } else { b.updated.cmp(&a.updated) }).then_with(|| a.repo.cmp(&b.repo)).then_with(|| a.number.cmp(&b.number))
    })
}

fn waited(i: &MeItem) -> i64 {
    if i.requested > 0 {
        i.requested
    } else {
        i.created
    }
}

// ---- running ------------------------------------------------------------------------------------

/// The accounts gh lists, the answers of the last minute by (account, argv), and the searches of the last minute by
/// account. No token is ever kept here.
#[derive(Default)]
pub struct Me {
    accounts: Mutex<Option<(Instant, GhAccounts)>>,
    cache: Mutex<HashMap<String, (Instant, String)>>,
    searches: Mutex<HashMap<String, Vec<Instant>>>,
    /// tests: a stand-in `gh` (None: the one found on this computer)
    gh: Option<PathBuf>,
    /// tests: variables standing for ones omher itself was started with (none: only the real environment)
    inherited: Vec<(String, String)>,
}

fn now_secs() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

impl Me {
    /// Run one gh child (tasks.rs's runner: no shell, nothing on stdin, at most 20 seconds), every one without `SCRUB`.
    fn run(&self, exe: &Path, argv: &[String], env: &[(&str, &str)]) -> Result<Ran, String> {
        let inherited: Vec<(&str, &str)> = self.inherited.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        run_full(exe, argv, true, &inherited, env, &SCRUB)
    }

    /// Account `a`'s token, read from gh for one call. Wiped when dropped. Never in an error: a failure names only
    /// gh's own (masked) line.
    fn read_token(&self, exe: &Path, a: &GhAccount) -> Result<Zeroizing<String>, MeError> {
        let argv = token_argv(&a.host, &a.login).map_err(|e| MeError::new("other", e))?;
        let ran = self.run(exe, &argv, &[]).map_err(|e| MeError::new("other", error_line(&e)))?;
        let out = Zeroizing::new(ran.out);
        if ran.code != Some(0) {
            let mut e = classify(&error_line(&ran.err));
            e.kind = "auth";
            return Err(e);
        }
        let t = out.trim();
        if t.is_empty() || t.chars().any(|c| c.is_whitespace() || c.is_control()) {
            return Err(MeError::new("auth", "gh has no login for this account"));
        }
        Ok(Zeroizing::new(t.to_string()))
    }

    /// The GitHub accounts gh is signed in to (kept 60 seconds; `fresh` asks again). gh missing: none, `installed`
    /// false.
    pub fn accounts(&self, fresh: bool) -> GhAccounts {
        self.detect(fresh).unwrap_or_else(|| GhAccounts { installed: self.exe().is_some(), accounts: vec![] })
    }

    fn exe(&self) -> Option<PathBuf> {
        self.gh.clone().or_else(|| find("gh"))
    }

    /// gh's accounts, or None when gh did not answer them (not installed: an empty list). A failed answer (a timeout,
    /// output that is not the list) is not kept, so a passing hiccup never reads as a sign-out for a minute.
    fn detect(&self, fresh: bool) -> Option<GhAccounts> {
        if !fresh {
            if let Some((at, a)) = self.accounts.lock().ok().and_then(|g| g.clone()) {
                if at.elapsed() < KEEP {
                    return Some(a);
                }
            }
        }
        let got = match self.exe() {
            None => GhAccounts { installed: false, accounts: vec![] },
            Some(exe) => {
                // an inherited token would make gh list its owner as active and gh's own logins as not
                let ran = self.run(&exe, &status_argv(), &[]).ok()?;
                let out = Zeroizing::new(ran.out);
                GhAccounts { installed: true, accounts: dedupe(parse_auth_status(&out).ok()?) }
            }
        };
        if let Ok(mut g) = self.accounts.lock() {
            // an account that changed (became active or not, or failed) or went: drop what was read as it
            let before = g.as_ref().map(|(_, a)| a.accounts.clone()).unwrap_or_default();
            let changed: Vec<String> = before.iter().filter(|b| !got.accounts.contains(b)).map(GhAccount::id).collect();
            if !changed.is_empty() {
                self.forget(&changed);
            }
            *g = Some((Instant::now(), got.clone()));
        }
        Some(got)
    }

    /// The signed-in account `id` names; an error when gh does not list it (or it must sign in again).
    fn account(&self, id: &str) -> Result<GhAccount, MeError> {
        let (login, host) = parse_account_id(id).map_err(|e| MeError::new("other", e))?;
        let all = self.detect(false).ok_or_else(|| MeError::new("other", "gh did not list its accounts"))?;
        let a = all.accounts.into_iter().find(|a| a.host == host && a.login.eq_ignore_ascii_case(&login)).ok_or_else(|| MeError::new("auth", format!("gh is not signed in as {login} on {host}")))?;
        if a.state != "success" {
            return Err(MeError::new("auth", format!("{login} on {host} must sign in again")));
        }
        Ok(a)
    }

    /// Drop every answer read as these accounts.
    fn forget(&self, ids: &[String]) {
        if let Ok(mut c) = self.cache.lock() {
            c.retain(|k, _| !ids.iter().any(|id| k.starts_with(&format!("{id}\0"))));
        }
    }

    fn cached(&self, key: &str, fresh: bool) -> Option<String> {
        let c = self.cache.lock().ok()?;
        let gap = if fresh { MIN_GAP } else { KEEP };
        c.get(key).filter(|(at, _)| at.elapsed() < gap).map(|(_, v)| v.clone())
    }

    fn keep(&self, key: String, v: String) {
        if let Ok(mut c) = self.cache.lock() {
            c.retain(|_, (at, _)| at.elapsed() < KEEP);
            c.insert(key, (Instant::now(), v));
        }
    }

    /// Count `n` search requests for `id`; false when they would pass the minute's limit.
    fn search_slot(&self, id: &str, n: usize) -> bool {
        let Ok(mut m) = self.searches.lock() else { return true };
        let list = m.entry(id.to_string()).or_default();
        list.retain(|t| t.elapsed() < Duration::from_secs(60));
        if list.len() + n > SEARCHES_PER_MINUTE {
            return false;
        }
        list.extend(std::iter::repeat_n(Instant::now(), n));
        true
    }

    /// Run `argv` (built by this module or tasks.rs, never by the page) as account `id`, active or not, with its own
    /// token in this one child's environment. The answer is kept 60 seconds per (account, argv). The status query
    /// runs first (its answer kept the same minute) and must name that account as its viewer: a token gh keeps for
    /// one login that signs in as another is refused ("sign in again"), so one account's rows never show under
    /// another's name.
    pub fn run_as(&self, id: &str, argv: Vec<String>, fresh: bool) -> Result<String, MeError> {
        let a = self.account(id)?;
        let who = viewer_login(&self.call(&a, graphql_argv(), false)?);
        if !who.is_some_and(|w| w.eq_ignore_ascii_case(&a.login)) {
            return Err(MeError::new("auth", format!("gh's login for {} on {} signs in as another account", a.login, a.host)));
        }
        self.call(&a, argv, fresh)
    }

    /// One call as account `a` (cached, counted against the search limit, with that account's own token).
    fn call(&self, a: &GhAccount, argv: Vec<String>, fresh: bool) -> Result<String, MeError> {
        let key = format!("{}\0{}", a.id(), argv.join("\0"));
        if let Some(v) = self.cached(&key, fresh) {
            return Ok(v);
        }
        if argv.first().map(String::as_str) == Some("search") && !self.search_slot(&a.id(), search_cost(&argv)) {
            return Err(MeError::new("rate", "GitHub's search limit for this minute is used up"));
        }
        let exe = self.exe().ok_or_else(|| MeError::new("other", "gh is not installed"))?;
        // pinned to this account whichever one gh has active now
        let token = self.read_token(&exe, a)?;
        let env = account_env(&a.host, token.as_str());
        let ran = self.run(&exe, &argv, &env);
        drop(env);
        drop(token);
        let ran = ran.map_err(|e| MeError::new("other", error_line(&e)))?;
        // `gh api graphql` exits 1 when the answer carries `errors` beside its `data` (a repository behind an
        // organisation's SSO, say): the data it has is still the answer
        if ran.code != Some(0) && !(argv.first().map(String::as_str) == Some("api") && has_data(&ran.out)) {
            return Err(classify(&error_line(&ran.err)));
        }
        self.keep(key, ran.out.clone());
        Ok(ran.out)
    }

    /// "이 저장소": one page of `repo` (on github.com, where tasks.rs reads remotes) as chosen account `id`, which must
    /// be a github.com account: a GitHub Enterprise account would read another host's repository of that name.
    pub fn repo_list(&self, t: &Tasks, kind: Kind, repo: &str, filter: Filter, page: u32, id: &str) -> Result<Page, String> {
        repo_account_ok(id)?;
        t.list_with(Source::Github, kind, repo, filter, page, id, |argv| self.run_as(id, argv, false).map_err(|e| e.line))
    }

    /// The drawer of one item read as chosen account `id`: "이 저장소"'s (a github.com account, as its list) or a "나"
    /// row's, which lives on whichever host that account is on (a GitHub Enterprise row is read on its own host).
    pub fn view(&self, t: &Tasks, kind: Kind, repo: &str, number: u64, id: &str) -> Result<Detail, String> {
        t.view_with(Source::Github, kind, repo, number, |argv| self.run_as(id, argv, false).map_err(|e| e.line))
    }

    /// One page of `section` for account `id`, the pull requests with their CI, review and conflict state, sorted by
    /// what needs action first. The status query is best effort: when it fails, the rows show without that state.
    pub fn list(&self, id: &str, section: Section, page: u32, fresh: bool) -> Result<MePage, MeError> {
        let argv = search_argv(section, page, now_secs()).map_err(|e| MeError::new("other", e))?;
        let base = section.base();
        let out = self.run_as(id, argv, fresh)?;
        let all = parse_search(section, &out).map_err(|e| MeError::new("other", e))?;
        let more = all.len() >= base * (page as usize + 1) && page < MAX_ME_PAGE;
        let mut items: Vec<MeItem> = all.into_iter().skip(base * page as usize).take(base).collect();
        if matches!(section, Section::Review | Section::Authored) {
            if let Ok(st) = self.run_as(id, graphql_argv(), fresh).and_then(|o| parse_status(&o).map_err(|e| MeError::new("other", e))) {
                merge_status(&mut items, &st);
            }
        }
        sort_items(&mut items);
        Ok(MePage { items, more })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const AUTH: &str = include_str!("tasks_fixtures/gh-auth-status.json");
    const SEARCH: &str = include_str!("tasks_fixtures/gh-search-prs.json");
    const STATUS: &str = include_str!("tasks_fixtures/gh-graphql-status.json");

    #[test]
    fn account_ids_hosts_and_logins_are_checked() {
        let ok = [("octo@github.com", ("octo", "github.com")), ("a-b_c@ghe.example.co.kr", ("a-b_c", "ghe.example.co.kr")), ("x1@acme.ghe.com", ("x1", "acme.ghe.com"))];
        for (id, (l, h)) in ok {
            assert_eq!(parse_account_id(id).unwrap(), (l.to_string(), h.to_string()), "{id}");
        }
        for bad in [
            "", "octo", "@github.com", "octo@", "-x@github.com", "_x@github.com", "octo@--hostname", "octo@github.com;rm -rf", "octo@github.com:8080", "o cto@github.com", "octo@../etc",
            "octo@localhost", "octo@GITHUB.COM", "octo@-bad.com", "octo@github.com\n", "a@b@github.com", "octo@github..com", "octo@github.com/x", "$(id)@github.com",
        ] {
            assert!(parse_account_id(bad).is_err(), "{bad:?}");
        }
        assert!(!login_ok(&"a".repeat(65)));
        assert!(!host_ok(&format!("{}.com", "a".repeat(64))));
    }

    #[test]
    fn argv_builders_are_fixed_reads() {
        let now = 1_794_766_799; // 2026-11-15
        let j = |a: Vec<String>| a.join(" ");
        assert_eq!(j(status_argv()), "auth status --json hosts");
        assert_eq!(j(search_argv(Section::Review, 0, now).unwrap()), format!("search prs --review-requested=@me --state=open --sort=updated --order=desc --json {PR_FIELDS} --limit 50"));
        assert_eq!(j(search_argv(Section::Authored, 1, now).unwrap()), format!("search prs --author=@me --state=open --sort=updated --order=desc --json {PR_FIELDS} --limit 100"));
        assert_eq!(j(search_argv(Section::Assigned, 0, now).unwrap()), format!("search issues --assignee=@me --state=open --sort=updated --order=desc --json {ISSUE_FIELDS} --limit 50"));
        assert_eq!(j(search_argv(Section::Mentions, 0, now).unwrap()), format!("search issues --mentions=@me --include-prs --updated=>=2026-11-08 --sort=updated --order=desc --json {ISSUE_FIELDS} --limit 30"));
        assert!(search_argv(Section::Review, MAX_ME_PAGE + 1, now).is_err());
        assert!(search_argv(Section::Review, u32::MAX, now).is_err());
        let g = graphql_argv();
        assert_eq!(&g[..3], &["api", "graphql", "-f"]);
        assert_eq!(g[3], format!("query={STATUS_QUERY}"));
        assert!(!STATUS_QUERY.contains("mutation"));
        assert_eq!(j(token_argv("github.com", "octo").unwrap()), "auth token --hostname github.com --user octo");
        assert!(token_argv("github.com", "--show-token").is_err());
        assert!(token_argv("--hostname", "octo").is_err());
        assert_eq!(j(login_argv(None).unwrap()), "auth login");
        assert_eq!(j(login_argv(Some("")).unwrap()), "auth login");
        assert_eq!(j(login_argv(Some("ghe.example.com")).unwrap()), "auth login --hostname ghe.example.com");
        for bad in ["--with-token", "ghe.example.com --web", "ghe.example.com;id", "localhost", "-x.com"] {
            assert!(login_argv(Some(bad)).is_err(), "{bad}");
        }
        assert!(Section::parse("review").is_ok());
        for bad in ["", "Review", "all", "review;", "../x"] {
            assert!(Section::parse(bad).is_err(), "{bad}");
        }
        // every argv is a read: search, api graphql (a query), auth status / token; never a write verb or a switch
        let mut all = vec![status_argv(), graphql_argv(), token_argv("github.com", "o").unwrap()];
        for s in [Section::Review, Section::Authored, Section::Assigned, Section::Mentions] {
            all.push(search_argv(s, 0, now).unwrap());
        }
        for a in all {
            for w in ["switch", "logout", "login", "create", "close", "edit", "comment", "merge", "delete", "review", "-X", "--method", "--show-token", "--input"] {
                assert!(!a.iter().any(|x| x == w), "{a:?} has {w}");
            }
        }
    }

    #[test]
    fn auth_status_keeps_five_fields_and_never_the_token() {
        let fake = "gho_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE";
        assert!(AUTH.contains(fake), "the fixture carries a token field");
        let got = parse_auth_status(AUTH).unwrap();
        assert_eq!(got.len(), 3);
        assert_eq!(got[0], GhAccount { host: "ghe.example.com".into(), login: "octo-corp".into(), active: true, state: "error".into(), scopes: vec![] });
        assert_eq!(got[1].login, "octo");
        assert!(got[1].active);
        assert_eq!(got[1].scopes, vec!["gist", "read:org", "repo", "workflow"]);
        assert_eq!((got[2].login.as_str(), got[2].active, got[2].state.as_str()), ("octo-work", false, "success"));
        let dump = format!("{got:?}{}", serde_json::to_string(&got).unwrap());
        assert!(!dump.contains(fake) && !dump.contains("gho_") && !dump.contains("token"), "{dump}");
        // a row with a hostile login is left out; junk is an error, not a panic
        let hostile = r#"{"hosts":{"github.com":[{"login":"--show-token","host":"github.com","active":false,"state":"success"}]}}"#;
        assert!(parse_auth_status(hostile).unwrap().is_empty());
        assert!(parse_auth_status("not json").is_err());
        assert!(parse_auth_status("{}").unwrap().is_empty());
    }

    #[test]
    fn an_accounts_token_goes_only_into_the_env() {
        let fake = "gho_TESTTESTTESTTESTTESTTESTTESTTESTTEST";
        let env = account_env("github.com", fake);
        assert_eq!(env, vec![("GH_HOST", "github.com"), ("GH_TOKEN", fake)]);
        assert_eq!(account_env("ghe.example.com", fake)[1].0, "GH_ENTERPRISE_TOKEN");
        assert_eq!(account_env("acme.ghe.com", fake)[1].0, "GH_TOKEN");
        // no argv this module builds carries a token
        let now = 1_794_766_799;
        for s in [Section::Review, Section::Authored, Section::Assigned, Section::Mentions] {
            assert!(!search_argv(s, 0, now).unwrap().iter().any(|a| a.contains("gho_") || a.contains("TOKEN")));
        }
        assert!(!graphql_argv().iter().any(|a| a.contains("gho_")));
        // a token-like string in a gh error line is masked before it can reach the page
        assert_eq!(classify(&error_line(&format!("HTTP 401: Bad credentials {fake}"))), MeError { kind: "auth", line: "HTTP 401: Bad credentials ••••".into() });
    }

    #[test]
    fn errors_are_classified() {
        assert_eq!(classify("API rate limit exceeded for user ID 1.").kind, "rate");
        assert_eq!(classify("You have exceeded a secondary rate limit").kind, "rate");
        assert_eq!(classify("HTTP 401: Bad credentials (https://api.github.com/graphql)").kind, "auth");
        assert_eq!(classify("To get started with GitHub CLI, please run:  gh auth login").kind, "auth");
        assert_eq!(classify("could not resolve host").kind, "other");
        assert_eq!(classify("").line, "gh failed");
    }

    #[test]
    fn parses_search_and_status_and_merges_them() {
        let mut items = parse_search(Section::Authored, SEARCH).unwrap();
        // the row with a bad repository and the row with no number are dropped; an http link is dropped
        assert_eq!(items.len(), 4);
        assert!(items.iter().all(|i| i.pr && !i.asked && i.repo.contains('/')));
        assert_eq!(items[0].repo, "octo/app");
        assert_eq!(items[0].title, "Fix the login ••••");
        assert_eq!(items[2].url, "");
        assert_eq!(items[3].state, "draft");
        let st = parse_status(STATUS).unwrap();
        assert_eq!(st.len(), 4);
        merge_status(&mut items, &st);
        let by = |n: u64| items.iter().find(|i| i.number == n).unwrap().clone();
        assert_eq!((by(11).ci.as_str(), by(11).review.as_str(), by(11).conflict), ("failed", "", false));
        assert_eq!((by(12).ci.as_str(), by(12).review.as_str()), ("passed", "changes"));
        assert!(by(13).conflict);
        assert_eq!(by(14).ci, "pending");
        assert_eq!(viewer_login(STATUS).as_deref(), Some("octo"));
        assert_eq!(viewer_login("{}"), None);
        // a partial answer (data beside errors) still counts; errors alone do not
        assert!(has_data(r#"{"data":{"viewer":{"login":"octo"}},"errors":[{"message":"SAML"}]}"#));
        assert!(!has_data(r#"{"errors":[{"message":"x"}]}"#));
        assert!(!has_data("not json"));
        let review = parse_search(Section::Review, SEARCH).unwrap();
        assert!(review.iter().all(|i| i.asked));
        // the request time is the latest request naming me (octo), not the later team request
        assert_eq!(st.get(&("other/lib".to_string(), 13)).unwrap().requested, epoch("2026-11-10T00:00:00Z"));
        // junk answers are errors, not panics
        for bad in ["", "nope", "{}", "[1", "null"] {
            assert!(parse_search(Section::Review, bad).is_err(), "{bad}");
        }
        assert!(parse_status("{\"errors\":[{\"message\":\"Something went wrong\"}]}").is_err());
        assert!(parse_status("[]").is_err());
    }

    fn item(n: u64, f: impl FnOnce(&mut MeItem)) -> MeItem {
        let mut i = MeItem { repo: "o/r".into(), number: n, pr: true, updated: 1000 + n as i64, created: 100, ..Default::default() };
        f(&mut i);
        i
    }

    #[test]
    fn sorts_by_what_needs_action() {
        let mut v = vec![
            item(1, |_| {}),
            item(2, |i| i.asked = true),
            item(3, |i| {
                i.asked = true;
                i.requested = 50;
            }),
            item(4, |i| i.conflict = true),
            item(5, |i| i.review = "changes".into()),
            item(6, |i| i.ci = "failed".into()),
            item(7, |i| {
                i.ci = "failed".into();
                i.review = "changes".into();
            }),
            item(8, |_| {}),
        ];
        sort_items(&mut v);
        let order: Vec<u64> = v.iter().map(|i| i.number).collect();
        // CI failed (newest first), changes requested, conflict, review requests oldest first, then the rest newest first
        assert_eq!(order, vec![7, 6, 5, 4, 3, 2, 8, 1]);
        assert_eq!(attention(&v[0]), 0);
        assert_eq!(attention(&v[7]), 4);
    }

    #[test]
    fn rate_cost_dedupe_and_the_repository_account() {
        let now = 1_794_766_799;
        assert_eq!(search_cost(&search_argv(Section::Review, 0, now).unwrap()), 1);
        assert_eq!(search_cost(&search_argv(Section::Review, 2, now).unwrap()), 2); // --limit 150
        assert_eq!(search_cost(&search_argv(Section::Authored, MAX_ME_PAGE, now).unwrap()), 2); // --limit 200
        assert_eq!(search_cost(&search_argv(Section::Mentions, MAX_ME_PAGE, now).unwrap()), 2); // --limit 120
        let me = Me::default();
        assert!(me.search_slot("a@github.com", 26));
        assert!(!me.search_slot("a@github.com", 2), "26 + 2 passes 27");
        assert!(me.search_slot("a@github.com", 1));
        assert!(me.search_slot("b@github.com", 2), "each account has its own minute");
        let acc = |l: &str, active: bool| GhAccount { host: "github.com".into(), login: l.into(), active, state: "success".into(), scopes: vec![] };
        assert_eq!(dedupe(vec![acc("octo", true), acc("Octo", false), acc("work", false)]).iter().map(|a| a.login.as_str()).collect::<Vec<_>>(), vec!["octo", "work"]);
        assert!(repo_account_ok("octo@github.com").is_ok());
        assert!(repo_account_ok("octo@ghe.example.com").is_err());
        assert!(repo_account_ok("--x@github.com").is_err());
    }


    /// A stand-in `gh` in a folder of its own: `auth status` answers `status.json` (or, when a token is in its
    /// environment, `status-env.json`, as gh does: the token's owner active, gh's own logins not); `auth token
    /// --user <l>` answers `tok-<l>`; a search or the status query answers as the token's owner, else as the login in
    /// `active.txt` (gh's active account). Every call is logged with the variables it got.
    #[cfg(unix)]
    fn stub_gh(tag: &str) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let d = std::env::temp_dir().join(format!("omher-gh-stub-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        let script = r#"#!/bin/sh
dir="$(dirname "$0")"
tok="${GH_TOKEN:-$GH_ENTERPRISE_TOKEN}"
echo "token=$tok|host=$GH_HOST|debug=$GH_DEBUG|pager=$PAGER|$*" >> "$dir/calls.log"
if [ -n "$tok" ]; then who="${tok#tok-}"; else who="$(cat "$dir/active.txt")"; fi
case "$1 $2" in
  "auth status") if [ -n "$GH_TOKEN" ]; then cat "$dir/status-env.json"; else cat "$dir/status.json"; fi ;;
  "auth token") echo "tok-$6" ;;
  "api graphql") printf '{"data":{"viewer":{"login":"%s","pullRequests":{"nodes":[]}},"search":{"nodes":[]}}}' "$who" ;;
  "pr list"|"issue list") echo "[]" ;;
  "pr view"|"issue view") printf '{"number":%s,"title":"t","state":"OPEN","url":"https://%s/x/y/pull/%s","body":"read as %s","comments":[]}' "$3" "$GH_HOST" "$3" "$who" ;;
  "search prs"|"search issues") printf '[{"number":1,"title":"read as %s","url":"https://github.com/o/r/pull/1","repository":{"nameWithOwner":"o/r"},"isPullRequest":true,"state":"open"}]' "$who" ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"#;
        std::fs::write(d.join("gh"), script).unwrap();
        std::fs::set_permissions(d.join("gh"), std::fs::Permissions::from_mode(0o755)).unwrap();
        d
    }

    #[cfg(unix)]
    fn status(active: &str) -> String {
        let row = |l: &str| format!(r#"{{"host":"github.com","login":"{l}","active":{},"state":"success","scopes":"repo"}}"#, l == active);
        format!(r#"{{"hosts":{{"github.com":[{},{}]}}}}"#, row("octo"), row("octo-work"))
    }

    #[cfg(unix)]
    #[test]
    fn a_call_reads_the_account_named_even_when_gh_switched_meanwhile() {
        let d = stub_gh("switch");
        std::fs::write(d.join("status.json"), status("octo")).unwrap();
        std::fs::write(d.join("active.txt"), "octo").unwrap();
        let me = Me { gh: Some(d.join("gh")), ..Default::default() };
        assert_eq!(me.accounts(true).accounts.iter().filter(|a| a.active).map(|a| a.login.as_str()).collect::<Vec<_>>(), vec!["octo"]);
        // within the minute the account list is kept, someone runs `gh auth switch` in a shell
        std::fs::write(d.join("active.txt"), "octo-work").unwrap();
        let p = me.list("octo@github.com", Section::Review, 0, false).unwrap();
        assert_eq!(p.items[0].title, "read as octo");
        let p = me.list("octo-work@github.com", Section::Review, 0, false).unwrap();
        assert_eq!(p.items[0].title, "read as octo-work");
        // every search and status query carried the named account's own token and host
        let log = std::fs::read_to_string(d.join("calls.log")).unwrap();
        for l in log.lines().filter(|l| l.contains("|search ") || l.contains("|api graphql")) {
            assert!(l.starts_with("token=tok-octo|host=github.com|") || l.starts_with("token=tok-octo-work|host=github.com|"), "{l}");
        }
        assert!(!log.contains("auth switch"));
        // gh now lists octo-work as active: what was read as either account is read again
        std::fs::write(d.join("status.json"), status("octo-work")).unwrap();
        let searches = |log: &str| log.lines().filter(|l| l.contains("|search ")).count();
        let before = searches(&std::fs::read_to_string(d.join("calls.log")).unwrap());
        me.accounts(true);
        me.list("octo@github.com", Section::Review, 0, false).unwrap();
        assert_eq!(searches(&std::fs::read_to_string(d.join("calls.log")).unwrap()), before + 1);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[cfg(unix)]
    #[test]
    fn an_inherited_token_is_taken_out_of_every_gh_child() {
        let d = stub_gh("inherit");
        std::fs::write(d.join("status.json"), status("octo")).unwrap();
        // what gh 2.97 lists with GH_TOKEN set: the token's owner active, gh's own logins not (one of them twice)
        let row = |l: &str, a: bool| format!(r#"{{"host":"github.com","login":"{l}","active":{a},"state":"success"}}"#);
        std::fs::write(d.join("status-env.json"), format!(r#"{{"hosts":{{"github.com":[{},{},{}]}}}}"#, row("intruder", true), row("octo", false), row("octo", false))).unwrap();
        std::fs::write(d.join("active.txt"), "octo").unwrap();
        // omher as if started from a shell that set these (injected: this process's environment is left alone)
        let inherited = [("GH_TOKEN", "tok-intruder"), ("GITHUB_TOKEN", "tok-intruder"), ("GH_DEBUG", "api"), ("DEBUG", "1"), ("PAGER", "less"), ("GH_PAGER", "less")];
        let me = Me { gh: Some(d.join("gh")), inherited: inherited.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect(), ..Default::default() };
        let got = me.accounts(true);
        assert_eq!(got.accounts.iter().map(|a| (a.login.as_str(), a.active)).collect::<Vec<_>>(), vec![("octo", true), ("octo-work", false)]);
        let p = me.list("octo@github.com", Section::Review, 0, false).unwrap();
        assert_eq!(p.items[0].title, "read as octo");
        // the doubled row of the token's view shows once
        let env_view = dedupe(parse_auth_status(&std::fs::read_to_string(d.join("status-env.json")).unwrap()).unwrap());
        assert_eq!(env_view.iter().map(|a| a.id()).collect::<Vec<_>>(), vec!["intruder@github.com", "octo@github.com"]);
        let log = std::fs::read_to_string(d.join("calls.log")).unwrap();
        assert!(log.lines().count() >= 4, "{log}");
        assert!(log.lines().all(|l| l.contains("debug=|pager=|") && !l.contains("intruder")), "{log}");
        // the seam is real: without the scrub the stub would have seen the injected token
        let raw = run_full(&d.join("gh"), &status_argv(), true, &[("GH_TOKEN", "tok-intruder")], &[], &[]).unwrap();
        assert!(raw.out.contains("intruder"));
        let _ = std::fs::remove_dir_all(&d);
    }

    #[cfg(unix)]
    #[test]
    fn a_rows_drawer_reads_on_its_accounts_own_host_and_this_repository_only_on_github_com() {
        let d = stub_gh("ghe");
        let row = |h: &str, l: &str| format!(r#"{{"host":"{h}","login":"{l}","active":true,"state":"success"}}"#);
        std::fs::write(d.join("status.json"), format!(r#"{{"hosts":{{"github.com":[{}],"ghe.example.com":[{}]}}}}"#, row("github.com", "octo"), row("ghe.example.com", "octo-corp"))).unwrap();
        std::fs::write(d.join("active.txt"), "octo").unwrap();
        let me = Me { gh: Some(d.join("gh")), ..Default::default() };
        let t = Tasks::default();
        // a "나" row read as the GitHub Enterprise account opens its drawer, on that host, with its own token
        let det = me.view(&t, Kind::Changes, "corp/app", 7, "octo-corp@ghe.example.com").unwrap();
        assert_eq!(det.item.number, 7);
        assert_eq!(det.body, "read as octo-corp");
        let log = std::fs::read_to_string(d.join("calls.log")).unwrap();
        assert!(log.lines().any(|l| l.starts_with("token=tok-octo-corp|host=ghe.example.com|") && l.contains("|pr view 7 --repo corp/app")), "{log}");
        // "이 저장소" (a github.com repository) never reads as it, and reads as a github.com account
        assert!(me.repo_list(&t, Kind::Issues, "corp/app", Filter::Open, 0, "octo-corp@ghe.example.com").unwrap_err().contains("github.com"));
        assert!(me.repo_list(&t, Kind::Issues, "o/r", Filter::Open, 0, "octo@github.com").is_ok());
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn the_sign_in_tab_drops_an_inherited_token_and_gh_debug() {
        // scrub_gh_env is what gh_login_command runs on the command it builds (injected: no process env touched)
        let mut cmd = portable_pty::CommandBuilder::new("gh");
        for k in SCRUB {
            cmd.env(k, "x");
        }
        cmd.env("HOME", "/home/you");
        crate::sessions::scrub_gh_env(&mut cmd);
        for k in SCRUB {
            assert!(cmd.get_env(k).is_none(), "{k}");
        }
        assert!(cmd.get_env("HOME").is_some());
        let cmd = crate::sessions::gh_login_command(Path::new("/usr/local/bin/gh"), login_argv(Some("ghe.example.com")).unwrap(), &std::env::temp_dir());
        for k in SCRUB {
            assert!(cmd.get_env(k).is_none(), "{k}");
        }
        assert_eq!(cmd.get_argv().iter().skip(1).map(|a| a.to_string_lossy().into_owned()).collect::<Vec<_>>(), vec!["auth", "login", "--hostname", "ghe.example.com"]);
    }

    /// The real smoke on this computer: `cargo test gh_me::tests::real_accounts -- --ignored --nocapture`. Prints
    /// counts only (never a title or a token).
    #[test]
    #[ignore]
    fn real_accounts() {
        let me = Me::default();
        let acc = me.accounts(true);
        println!("gh installed={} accounts={}", acc.installed, acc.accounts.len());
        for a in &acc.accounts {
            let mut line = format!("account #{} active={} state={}:", acc.accounts.iter().position(|x| x == a).unwrap() + 1, a.active, a.state);
            for s in [Section::Review, Section::Authored, Section::Assigned, Section::Mentions] {
                match me.list(&a.id(), s, 0, false) {
                    Ok(p) => {
                        let ci = p.items.iter().filter(|i| !i.ci.is_empty()).count();
                        line += &format!(" {s:?}={} (with CI state {ci}, more={})", p.items.len(), p.more);
                    }
                    Err(e) => line += &format!(" {s:?}=error:{}", e.kind),
                }
            }
            println!("{line}");
        }
    }
}

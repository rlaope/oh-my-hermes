//! Tasks › GitHub, the dashboard (BOUNDARY rule 51): for one repository the person pinned, its open pull requests
//! (and which of them ask for my review), its recent workflow runs, its releases, its default branch's CI and how many
//! commits that branch has since the latest release. Read-only, through the person's own GitHub CLI (`gh`), as a
//! GitHub account chosen in Settings › Accounts, through gh_me.rs's `Me::run_as`: tasks.rs's one runner (no shell,
//! nothing on stdin, at most 20 seconds), that account's own token in that one child's environment only, every
//! answer kept 60 seconds per (account, argv), ⟳ reading again only an answer older than 15 seconds.
//!
//! What crosses from the page is only an account id (`<login>@<host>`, a github.com one) and a repository
//! (`owner/repo`, checked by tasks.rs's `check_repo`). Every argv is built here from fixed words and a fixed `--json`
//! field list; the GraphQL query is a constant and takes the repository's two checked parts as variables; the tag and
//! branch of the compare read come from GitHub's own answers and are checked (`ref_ok`) before they are used. Every
//! text passes tasks.rs's `text`, so a token-like string in a title, a label, a workflow or a release is masked.
use serde::Serialize;
use serde_json::Value;

use crate::gh_me::{repo_account_ok, Me, MeError, MeItem};
use crate::tasks::{check_repo, epoch, gh_author, gh_checks, gh_labels, one_line, text, web_url, Source};

/// The most open pull requests read per repository.
pub const PR_LIMIT: usize = 50;
/// The most workflow runs read per repository.
pub const RUN_LIMIT: usize = 15;
/// The most releases read per repository.
pub const RELEASE_LIMIT: usize = 5;

const PR_FIELDS: &str = "number,title,url,labels,author,createdAt,updatedAt,isDraft,statusCheckRollup,reviewDecision,mergeable";
const RUN_FIELDS: &str = "databaseId,workflowName,displayTitle,headBranch,event,status,conclusion,createdAt,startedAt,updatedAt,url";
const RELEASE_FIELDS: &str = "tagName,name,isLatest,isPrerelease,publishedAt,createdAt";

/// The one repository query: the default branch's name and its head commit's CI state. Fixed text; the owner and
/// the name go in as GraphQL variables.
pub const REPO_QUERY: &str = "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { defaultBranchRef { name target { ... on Commit { statusCheckRollup { state } } } } } }";

fn s(v: &str) -> String {
    v.to_string()
}

/// The open pull requests (after `gh`).
pub fn prs_argv(repo: &str) -> Result<Vec<String>, String> {
    let repo = check_repo(Source::Github, repo)?;
    Ok(vec![s("pr"), s("list"), s("--repo"), repo, s("--state"), s("open"), s("--json"), s(PR_FIELDS), s("--limit"), PR_LIMIT.to_string()])
}

/// The numbers of the open pull requests that ask for my review (mine or a team's I am in).
pub fn asked_argv(repo: &str) -> Result<Vec<String>, String> {
    let repo = check_repo(Source::Github, repo)?;
    Ok(vec![s("pr"), s("list"), s("--repo"), repo, s("--state"), s("open"), s("--search"), s("review-requested:@me"), s("--json"), s("number"), s("--limit"), PR_LIMIT.to_string()])
}

/// The recent workflow runs.
pub fn runs_argv(repo: &str) -> Result<Vec<String>, String> {
    let repo = check_repo(Source::Github, repo)?;
    Ok(vec![s("run"), s("list"), s("--repo"), repo, s("--json"), s(RUN_FIELDS), s("--limit"), RUN_LIMIT.to_string()])
}

/// The latest published releases.
pub fn releases_argv(repo: &str) -> Result<Vec<String>, String> {
    let repo = check_repo(Source::Github, repo)?;
    Ok(vec![s("release"), s("list"), s("--repo"), repo, s("--exclude-drafts"), s("--json"), s(RELEASE_FIELDS), s("--limit"), RELEASE_LIMIT.to_string()])
}

/// The default branch and its CI (the fixed query, the repository's two parts as variables).
pub fn repo_argv(repo: &str) -> Result<Vec<String>, String> {
    let repo = check_repo(Source::Github, repo)?;
    let (owner, name) = repo.split_once('/').ok_or_else(|| format!("not a repository: {repo:?}"))?;
    Ok(vec![s("api"), s("graphql"), s("-f"), format!("query={REPO_QUERY}"), s("-f"), format!("owner={owner}"), s("-f"), format!("name={name}")])
}

/// A tag or branch name the compare read may carry: letters, digits, `.`, `_`, `-` and `/`, at most 100, not
/// starting with `-`, `.` or `/`, not ending with `.` or `/`, and no `..` or `//` (so it never reads as an option, a
/// path step or the compare's own `...`).
pub fn ref_ok(r: &str) -> bool {
    !r.is_empty()
        && r.len() <= 100
        && !r.starts_with(['-', '.', '/'])
        && !r.ends_with(['.', '/'])
        && !r.contains("..")
        && !r.contains("//")
        && r.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-' | '/'))
}

/// How many commits `branch` has since `tag` (a GET of the compare endpoint; only `ahead_by` is printed).
pub fn compare_argv(repo: &str, tag: &str, branch: &str) -> Result<Vec<String>, String> {
    let repo = check_repo(Source::Github, repo)?;
    if !ref_ok(tag) || !ref_ok(branch) {
        return Err("not a tag or branch name".into());
    }
    Ok(vec![s("api"), format!("repos/{repo}/compare/{tag}...{branch}"), s("--jq"), s(".ahead_by")])
}

// ---- what the page gets -------------------------------------------------------------------------

#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct DashRun {
    pub id: u64,
    pub workflow: String,
    pub title: String,
    pub branch: String,
    pub event: String,
    /// `passed`, `failed`, `pending`, `cancelled` or `skipped`
    pub state: String,
    /// seconds since the epoch (0: unknown)
    pub created: i64,
    pub started: i64,
    pub updated: i64,
    pub url: String,
}

#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct DashRelease {
    pub tag: String,
    pub name: String,
    /// GitHub's Latest release
    pub latest: bool,
    pub prerelease: bool,
    /// seconds since the epoch (0: unknown)
    pub published: i64,
    pub url: String,
}

#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct DashRepo {
    /// `owner/repo`
    pub repo: String,
    /// the default branch ("" when it could not be read)
    pub branch: String,
    /// the default branch's CI: `passed`, `failed`, `pending` or ""
    pub ci: String,
    /// the open pull requests, newest update first; `asked` marks the ones that ask for my review
    pub prs: Vec<MeItem>,
    pub runs: Vec<DashRun>,
    pub releases: Vec<DashRelease>,
    /// commits the default branch has since the latest release (None: no release, or not read)
    pub ahead: Option<u64>,
    /// GitHub's rate limit stopped one of the reads: what is here is shown, with "try again soon"
    pub rate: bool,
}

// ---- parsing ------------------------------------------------------------------------------------

fn json(out: &str) -> Result<Value, String> {
    serde_json::from_str(out.trim()).map_err(|_| "gh answered something that is not JSON".to_string())
}

fn rows(out: &str) -> Result<Vec<Value>, String> {
    match json(out)? {
        Value::Array(a) => Ok(a),
        _ => Err("gh did not answer a list".into()),
    }
}

/// The open pull requests of `repo`, newest update first.
pub fn parse_prs(repo: &str, out: &str) -> Result<Vec<MeItem>, String> {
    let mut items = Vec::new();
    for r in rows(out)? {
        let number = r.get("number").and_then(Value::as_u64).unwrap_or(0);
        if number == 0 {
            continue;
        }
        let draft = r.get("isDraft").and_then(Value::as_bool).unwrap_or(false);
        let ci = match gh_checks(&r).map(|c| c.0) {
            Some(c) if c.failed > 0 => "failed",
            Some(c) if c.pending > 0 => "pending",
            Some(c) if c.total > 0 => "passed",
            _ => "",
        };
        let review = match text(&r, "reviewDecision").to_ascii_uppercase().as_str() {
            "APPROVED" => "approved",
            "CHANGES_REQUESTED" => "changes",
            "REVIEW_REQUIRED" => "required",
            _ => "",
        };
        items.push(MeItem {
            repo: repo.to_string(),
            number,
            title: one_line(text(&r, "title"), 300),
            url: web_url(&text(&r, "url")),
            pr: true,
            draft,
            state: if draft { "draft".into() } else { "open".into() },
            author: gh_author(&r),
            labels: gh_labels(&r),
            created: epoch(&text(&r, "createdAt")),
            updated: epoch(&text(&r, "updatedAt")),
            ci: ci.into(),
            review: review.into(),
            conflict: text(&r, "mergeable").eq_ignore_ascii_case("CONFLICTING"),
            ..Default::default()
        });
    }
    items.sort_by(|a, b| b.updated.cmp(&a.updated).then_with(|| b.number.cmp(&a.number)));
    Ok(items)
}

/// The numbers of a `--json number` list.
pub fn parse_numbers(out: &str) -> Result<Vec<u64>, String> {
    Ok(rows(out)?.iter().filter_map(|r| r.get("number").and_then(Value::as_u64)).filter(|n| *n > 0).collect())
}

/// A workflow run's state: `pending` until it completes, then by its conclusion.
fn run_state(status: &str, conclusion: &str) -> &'static str {
    if !status.eq_ignore_ascii_case("completed") {
        return "pending";
    }
    match conclusion.to_ascii_lowercase().as_str() {
        "success" => "passed",
        "cancelled" => "cancelled",
        "skipped" | "neutral" | "stale" => "skipped",
        "" => "pending",
        _ => "failed",
    }
}

pub fn parse_runs(out: &str) -> Result<Vec<DashRun>, String> {
    Ok(rows(out)?
        .iter()
        .map(|r| DashRun {
            id: r.get("databaseId").and_then(Value::as_u64).unwrap_or(0),
            workflow: one_line(text(r, "workflowName"), 120),
            title: one_line(text(r, "displayTitle"), 200),
            branch: one_line(text(r, "headBranch"), 120),
            event: one_line(text(r, "event"), 40),
            state: run_state(&text(r, "status"), &text(r, "conclusion")).into(),
            created: epoch(&text(r, "createdAt")),
            started: epoch(&text(r, "startedAt")),
            updated: epoch(&text(r, "updatedAt")),
            url: web_url(&text(r, "url")),
        })
        .filter(|r| r.id > 0)
        .collect())
}

pub fn parse_releases(repo: &str, out: &str) -> Result<Vec<DashRelease>, String> {
    Ok(rows(out)?
        .iter()
        .filter_map(|r| {
            let tag = text(r, "tagName");
            if tag.is_empty() || tag.chars().any(|c| c.is_whitespace() || c.is_control()) {
                return None;
            }
            let published = epoch(&text(r, "publishedAt"));
            Some(DashRelease {
                url: if ref_ok(&tag) { format!("https://github.com/{repo}/releases/tag/{tag}") } else { String::new() },
                name: one_line(text(r, "name"), 200),
                latest: r.get("isLatest").and_then(Value::as_bool).unwrap_or(false),
                prerelease: r.get("isPrerelease").and_then(Value::as_bool).unwrap_or(false),
                published: if published > 0 { published } else { epoch(&text(r, "createdAt")) },
                tag: one_line(tag, 100),
            })
        })
        .collect())
}

/// The default branch and its CI from the repository query (an answer with `data` beside `errors` counts).
pub fn parse_repo(out: &str) -> Result<(String, String), String> {
    let v = json(out)?;
    let r = v.pointer("/data/repository/defaultBranchRef").filter(|x| x.is_object()).ok_or_else(|| "the repository has no default branch".to_string())?;
    let branch = text(r, "name");
    let state = r.pointer("/target/statusCheckRollup").filter(|x| x.is_object()).map(|x| text(x, "state").to_ascii_uppercase()).unwrap_or_default();
    let ci = match state.as_str() {
        "SUCCESS" => "passed",
        "FAILURE" | "ERROR" => "failed",
        "PENDING" | "EXPECTED" => "pending",
        _ => "",
    };
    Ok((if ref_ok(&branch) { branch } else { String::new() }, ci.into()))
}

/// `ahead_by`, as `--jq` prints it.
pub fn parse_ahead(out: &str) -> Option<u64> {
    out.trim().parse::<u64>().ok()
}

/// The release the commits are counted from: GitHub's Latest, else the newest that is not a pre-release, else the
/// newest.
pub fn base_release(releases: &[DashRelease]) -> Option<&DashRelease> {
    releases.iter().find(|r| r.latest).or_else(|| releases.iter().find(|r| !r.prerelease)).or_else(|| releases.first())
}

// ---- reading ------------------------------------------------------------------------------------

/// One repository's dashboard as chosen account `id` (a github.com account). The open pull requests must read; every
/// other part is best effort (a repository without Actions or releases shows none), and GitHub's rate limit on any of
/// them sets `rate`. `fresh` (⟳, window focus): read again past a 15-second gap instead of the minute's answer.
pub fn read(me: &Me, id: &str, repo: &str, fresh: bool) -> Result<DashRepo, MeError> {
    let other = |e: String| MeError::new("other", e);
    repo_account_ok(id).map_err(other)?;
    let repo = check_repo(Source::Github, repo).map_err(other)?;
    let ask = |argv: Result<Vec<String>, String>| argv.map_err(other).and_then(|a| me.run_as(id, a, fresh));
    // the independent reads side by side: each is one gh child, at most 20 seconds
    let (prs, asked, runs, releases, info) = std::thread::scope(|sc| {
        let asked = sc.spawn(|| ask(asked_argv(&repo)));
        let runs = sc.spawn(|| ask(runs_argv(&repo)));
        let releases = sc.spawn(|| ask(releases_argv(&repo)));
        let info = sc.spawn(|| ask(repo_argv(&repo)));
        let prs = ask(prs_argv(&repo));
        let join = |h: std::thread::ScopedJoinHandle<'_, Result<String, MeError>>| h.join().unwrap_or_else(|_| Err(MeError::new("other", "a read stopped")));
        (prs, join(asked), join(runs), join(releases), join(info))
    });
    let mut prs = parse_prs(&repo, &prs?).map_err(other)?;
    let mut rate = false;
    let mut soft = |r: Result<String, MeError>| match r {
        Ok(o) => Some(o),
        Err(e) => {
            rate |= e.kind == "rate";
            None
        }
    };
    if let Some(nums) = soft(asked).and_then(|o| parse_numbers(&o).ok()) {
        for p in prs.iter_mut() {
            p.asked = nums.contains(&p.number);
        }
    }
    let runs = soft(runs).and_then(|o| parse_runs(&o).ok()).unwrap_or_default();
    let releases = soft(releases).and_then(|o| parse_releases(&repo, &o).ok()).unwrap_or_default();
    let (branch, ci) = soft(info).and_then(|o| parse_repo(&o).ok()).unwrap_or_default();
    let ahead = match base_release(&releases) {
        Some(r) if !branch.is_empty() => compare_argv(&repo, &r.tag, &branch).ok().and_then(|a| soft(me.run_as(id, a, fresh))).and_then(|o| parse_ahead(&o)),
        _ => None,
    };
    Ok(DashRepo { repo, branch, ci, prs, runs, releases, ahead, rate })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn argv_builders_are_fixed_reads() {
        let j = |a: Vec<String>| a.join(" ");
        assert_eq!(j(prs_argv("example/web-console").unwrap()), format!("pr list --repo example/web-console --state open --json {PR_FIELDS} --limit 50"));
        assert_eq!(j(asked_argv("example/web-console").unwrap()), "pr list --repo example/web-console --state open --search review-requested:@me --json number --limit 50");
        assert_eq!(j(runs_argv("example/web-console").unwrap()), format!("run list --repo example/web-console --json {RUN_FIELDS} --limit 15"));
        assert_eq!(j(releases_argv("example/web-console").unwrap()), format!("release list --repo example/web-console --exclude-drafts --json {RELEASE_FIELDS} --limit 5"));
        let r = repo_argv("example/web-console").unwrap();
        assert_eq!(r, vec!["api", "graphql", "-f", &format!("query={REPO_QUERY}"), "-f", "owner=example", "-f", "name=web-console"]);
        assert!(!REPO_QUERY.contains("mutation"));
        assert_eq!(j(compare_argv("example/web-console", "v1.2.0", "main").unwrap()), "api repos/example/web-console/compare/v1.2.0...main --jq .ahead_by");
        assert_eq!(j(compare_argv("example/web-console", "omher-v1.2.4", "release/2026").unwrap()), "api repos/example/web-console/compare/omher-v1.2.4...release/2026 --jq .ahead_by");
        // the repository is checked before any argv is built
        for bad in ["", "web-console", "-x/y", "a/b/c", "a/../b", ".x/y", "a/b;id", "a b/c", "a/b --method POST"] {
            assert!(prs_argv(bad).is_err(), "{bad}");
            assert!(asked_argv(bad).is_err(), "{bad}");
            assert!(runs_argv(bad).is_err(), "{bad}");
            assert!(releases_argv(bad).is_err(), "{bad}");
            assert!(repo_argv(bad).is_err(), "{bad}");
            assert!(compare_argv(bad, "v1", "main").is_err(), "{bad}");
        }
        // a tag or branch that could be an option, a path step or a second `...` is refused
        for bad in ["", "-X", "--method", ".hidden", "/abs", "v1..v2", "a//b", "v1.", "dir/", "v1 POST", "v1?x=1", "v1#a", "a@{1}", "v1;id", "ü", &"v".repeat(101)] {
            assert!(!ref_ok(bad), "{bad:?}");
            assert!(compare_argv("example/web-console", bad, "main").is_err(), "{bad:?}");
            assert!(compare_argv("example/web-console", "v1", bad).is_err(), "{bad:?}");
        }
        for ok in ["v1.2.4", "omher-v1.2.4", "main", "release/2026", "trunk_2", "1.0.0-rc.1"] {
            assert!(ref_ok(ok), "{ok}");
        }
        // every argv is a read: list verbs, a GraphQL query and a GET; never a write verb, a method or a body field
        let all = [prs_argv("o/r"), asked_argv("o/r"), runs_argv("o/r"), releases_argv("o/r"), compare_argv("o/r", "v1", "main")];
        for a in all.into_iter().map(Result::unwrap) {
            for w in ["create", "close", "edit", "comment", "merge", "delete", "review", "rerun", "cancel", "watch", "upload", "-X", "--method", "--input", "-f", "-F", "--field", "--raw-field"] {
                assert!(!a.iter().any(|x| x == w), "{a:?} has {w}");
            }
        }
        for w in ["-X", "--method", "--input", "-F", "--field"] {
            assert!(!r.iter().any(|x| x == w), "{r:?} has {w}");
        }
    }

    const PRS: &str = r#"[
      {"number":212,"title":"fix: login loop after the session ends","url":"https://github.com/example/web-console/pull/212","labels":[{"name":"bug","color":"d73a4a"}],"author":{"login":"contributor-a"},"createdAt":"2026-11-20T10:00:00Z","updatedAt":"2026-11-27T10:00:00Z","isDraft":false,"reviewDecision":"APPROVED","mergeable":"MERGEABLE","statusCheckRollup":[{"__typename":"CheckRun","name":"test","status":"COMPLETED","conclusion":"SUCCESS"}]},
      {"number":209,"title":"feat: audit log export token=ghp_abcdefghijklmnopqrstuvwxyz0123456789","url":"https://github.com/example/web-console/pull/209","labels":[],"author":{"login":"contributor-b"},"createdAt":"2026-11-19T10:00:00Z","updatedAt":"2026-11-28T09:00:00Z","isDraft":false,"reviewDecision":"CHANGES_REQUESTED","mergeable":"CONFLICTING","statusCheckRollup":[{"__typename":"CheckRun","name":"test","status":"COMPLETED","conclusion":"FAILURE"},{"__typename":"CheckRun","name":"lint","status":"IN_PROGRESS","conclusion":""}]},
      {"number":205,"title":"chore: draft","url":"javascript:alert(1)","labels":[],"author":{"login":"contributor-c"},"createdAt":"2026-11-10T10:00:00Z","updatedAt":"2026-11-11T10:00:00Z","isDraft":true,"reviewDecision":"","mergeable":"UNKNOWN","statusCheckRollup":[]},
      {"number":0,"title":"broken"}
    ]"#;

    #[test]
    fn parses_pull_requests_newest_first_with_ci_review_and_conflict() {
        let p = parse_prs("example/web-console", PRS).unwrap();
        assert_eq!(p.iter().map(|i| i.number).collect::<Vec<_>>(), vec![209, 212, 205]);
        let (a, b, c) = (&p[0], &p[1], &p[2]);
        assert_eq!((a.ci.as_str(), a.review.as_str(), a.conflict), ("failed", "changes", true));
        assert!(a.title.contains("••••") && !a.title.contains("ghp_"), "{}", a.title);
        assert_eq!((b.ci.as_str(), b.review.as_str(), b.conflict, b.state.as_str()), ("passed", "approved", false, "open"));
        assert_eq!(b.labels[0].name, "bug");
        assert_eq!(b.labels[0].color, "d73a4a");
        assert_eq!(b.author, "contributor-a");
        assert_eq!(b.repo, "example/web-console");
        assert!(b.pr && !b.asked);
        assert_eq!((c.ci.as_str(), c.state.as_str(), c.draft), ("", "draft", true));
        assert_eq!(c.url, "", "only https links reach the page");
        assert!(parse_prs("o/r", "{}").is_err());
        assert!(parse_prs("o/r", "not json").is_err());
        assert_eq!(parse_numbers(r#"[{"number":209},{"number":0},{}]"#).unwrap(), vec![209]);
    }

    #[test]
    fn parses_runs_releases_the_repository_and_the_count() {
        let runs = parse_runs(r#"[
          {"databaseId":11,"workflowName":"CI","displayTitle":"fix: login loop","headBranch":"fix/login","event":"pull_request","status":"completed","conclusion":"failure","createdAt":"2026-11-28T09:00:00Z","startedAt":"2026-11-28T09:00:05Z","updatedAt":"2026-11-28T09:08:19Z","url":"https://github.com/example/web-console/actions/runs/11"},
          {"databaseId":12,"workflowName":"e2e","displayTitle":"x","headBranch":"main","event":"push","status":"in_progress","conclusion":"","createdAt":"2026-11-28T09:10:00Z","startedAt":"2026-11-28T09:10:00Z","updatedAt":"2026-11-28T09:11:00Z","url":"https://github.com/example/web-console/actions/runs/12"},
          {"databaseId":13,"workflowName":"docs","status":"completed","conclusion":"success"},
          {"databaseId":14,"workflowName":"nightly","status":"completed","conclusion":"cancelled"},
          {"databaseId":15,"workflowName":"label","status":"completed","conclusion":"skipped"},
          {"databaseId":16,"workflowName":"deploy","status":"completed","conclusion":"timed_out"},
          {"workflowName":"no id"}
        ]"#)
        .unwrap();
        assert_eq!(runs.iter().map(|r| r.state.as_str()).collect::<Vec<_>>(), vec!["failed", "pending", "passed", "cancelled", "skipped", "failed"]);
        assert_eq!((runs[0].workflow.as_str(), runs[0].branch.as_str(), runs[0].updated - runs[0].started), ("CI", "fix/login", 494));
        let rel = parse_releases("example/web-console", r#"[
          {"tagName":"v2.0.0-rc.1","name":"v2.0.0-rc.1","isLatest":false,"isPrerelease":true,"publishedAt":"2026-11-27T00:00:00Z"},
          {"tagName":"v1.4.0","name":"v1.4.0","isLatest":true,"isPrerelease":false,"publishedAt":"2026-11-20T00:00:00Z"},
          {"tagName":"bad tag","name":"x"}
        ]"#)
        .unwrap();
        assert_eq!(rel.len(), 2);
        assert_eq!(rel[1].url, "https://github.com/example/web-console/releases/tag/v1.4.0");
        assert_eq!(base_release(&rel).unwrap().tag, "v1.4.0");
        // no Latest: the newest that is not a pre-release, else the newest
        let mut no_latest = rel.clone();
        no_latest[1].latest = false;
        assert_eq!(base_release(&no_latest).unwrap().tag, "v1.4.0");
        assert_eq!(base_release(&no_latest[..1]).unwrap().tag, "v2.0.0-rc.1");
        assert!(base_release(&[]).is_none());
        let (branch, ci) = parse_repo(r#"{"data":{"repository":{"defaultBranchRef":{"name":"main","target":{"statusCheckRollup":{"state":"FAILURE"}}}}}}"#).unwrap();
        assert_eq!((branch.as_str(), ci.as_str()), ("main", "failed"));
        assert_eq!(parse_repo(r#"{"data":{"repository":{"defaultBranchRef":{"name":"main","target":{"statusCheckRollup":null}}}}}"#).unwrap().1, "");
        assert_eq!(parse_repo(r#"{"data":{"repository":{"defaultBranchRef":{"name":"--evil","target":{}}}}}"#).unwrap().0, "");
        assert!(parse_repo(r#"{"data":{"repository":{"defaultBranchRef":null}}}"#).is_err());
        assert_eq!(parse_ahead("12\n"), Some(12));
        assert_eq!(parse_ahead("null"), None);
    }

    /// A stand-in `gh` that answers each dashboard read for `example/web-console` (and logs every argv with the token
    /// it got); `rate.txt` makes the release list answer GitHub's rate limit.
    #[cfg(unix)]
    fn stub_gh(tag: &str) -> std::path::PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let d = std::env::temp_dir().join(format!("omher-dash-stub-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        let script = r#"#!/bin/sh
dir="$(dirname "$0")"
echo "token=$GH_TOKEN|$*" >> "$dir/calls.log"
case "$1 $2" in
  "auth status") echo '{"hosts":{"github.com":[{"host":"github.com","login":"octo","active":true,"state":"success","scopes":"repo"}]}}' ;;
  "auth token") echo "tok-$6" ;;
  "api graphql")
    case "$*" in
      *owner=*) echo '{"data":{"repository":{"defaultBranchRef":{"name":"main","target":{"statusCheckRollup":{"state":"SUCCESS"}}}}}}' ;;
      *) echo '{"data":{"viewer":{"login":"octo","pullRequests":{"nodes":[]}},"search":{"nodes":[]}}}' ;;
    esac ;;
  "pr list")
    case "$*" in
      *review-requested*) echo '[{"number":209}]' ;;
      *) echo '[{"number":212,"title":"a","url":"https://github.com/example/web-console/pull/212","updatedAt":"2026-11-27T10:00:00Z"},{"number":209,"title":"b","url":"https://github.com/example/web-console/pull/209","updatedAt":"2026-11-26T10:00:00Z"}]' ;;
    esac ;;
  "run list") echo '[{"databaseId":11,"workflowName":"CI","status":"completed","conclusion":"success"}]' ;;
  "release list")
    if [ -f "$dir/rate.txt" ]; then echo "API rate limit exceeded" >&2; exit 1; fi
    echo '[{"tagName":"v1.4.0","name":"v1.4.0","isLatest":true}]' ;;
  "api repos/example/web-console/compare/v1.4.0...main") echo 7 ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"#;
        std::fs::write(d.join("gh"), script).unwrap();
        std::fs::set_permissions(d.join("gh"), std::fs::Permissions::from_mode(0o755)).unwrap();
        d
    }

    #[cfg(unix)]
    #[test]
    fn reads_one_repository_as_the_account_named() {
        let d = stub_gh("read");
        let me = Me::with_gh(d.join("gh"));
        let got = read(&me, "octo@github.com", "example/web-console", false).unwrap();
        assert_eq!(got.prs.iter().map(|p| (p.number, p.asked)).collect::<Vec<_>>(), vec![(212, false), (209, true)]);
        assert_eq!((got.branch.as_str(), got.ci.as_str(), got.ahead, got.rate), ("main", "passed", Some(7), false));
        assert_eq!(got.runs[0].state, "passed");
        assert_eq!(got.releases[0].tag, "v1.4.0");
        let log = std::fs::read_to_string(d.join("calls.log")).unwrap();
        // every read but `auth status` / `auth token` carried that account's own token
        for l in log.lines().filter(|l| !l.contains("|auth ")) {
            assert!(l.starts_with("token=tok-octo|"), "{l}");
        }
        // within the minute nothing is read again
        let n = log.lines().count();
        read(&me, "octo@github.com", "example/web-console", false).unwrap();
        assert_eq!(std::fs::read_to_string(d.join("calls.log")).unwrap().lines().count(), n);
        // GitHub's rate limit on one part shows the rest, marked
        std::fs::write(d.join("rate.txt"), "1").unwrap();
        let me = Me::with_gh(d.join("gh"));
        let got = read(&me, "octo@github.com", "example/web-console", false).unwrap();
        assert!(got.rate);
        assert!(got.releases.is_empty() && got.ahead.is_none());
        assert_eq!(got.prs.len(), 2);
        // only a github.com account, only a checked repository, only an account gh lists
        assert!(read(&me, "octo@ghe.example.com", "example/web-console", false).is_err());
        assert!(read(&me, "octo@github.com", "example/web-console --method", false).is_err());
        assert_eq!(read(&me, "someone@github.com", "example/web-console", false).unwrap_err().kind, "auth");
        let _ = std::fs::remove_dir_all(&d);
    }
}

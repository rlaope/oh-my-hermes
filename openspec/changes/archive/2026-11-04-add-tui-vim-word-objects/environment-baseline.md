# Environment Baseline

Package: OpenSpec CLI 1.3.1 (`openspec --version`).
Schema: agent-harness user override; schema format 3, description version 2.0.0; `openspec schema validate agent-harness` passed.
Captured at: 2026-11-04T21:39:18Z (`date -u '+%Y-%m-%dT%H:%M:%SZ'`).
Owner: word-object planning author; this is the source baseline, not an implementation candidate.
Tools: Python 3.15.2 (`/opt/homebrew/bin/python3 --version`), OpenSpec 1.3.1. Git source commit from `git rev-parse HEAD`: fcd2abcb11e323ccba4c26a3b340e7d377c0daa8; `git status --porcelain=v1` empty at baseline.
Platform: Darwin arm64 (`uname -sm`), macOS 26.5.2 (`sw_vers -productVersion`).
Roots:
- planning: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning`
- package: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning/openspec/changes/add-tui-vim-word-objects`
- source: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix` (read-only)
- future implementation materialization: not created, not authorized; Human must name a separate worktree before apply.
Known noise: command duration/output timing excluded; no bytecode output (`PYTHONDONTWRITEBYTECODE=1`, `-B`).
Normalization: Python `json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False)` encoded UTF-8 without newline; exactly the following object, excluding capture timestamp and roots so the digest reflects runtime/source identity rather than checkout location:
```json
{"arch":"arm64","files":{"src/tui/composer.py":"8f651b0fd549f6cee6ed619b0c7654a2b73d3bfb0029d04a9e1d6d7f3fffd455","src/tui/keys.py":"96ec9fb7ae293c8740ed7116d5f92299921d47952346d927838af2f1df7b7e9c","tests/test_tui_composer.py":"a5a6f633590a931ad31488c5901f7c591a270b5088f6aaa9e8fa3849ac786cc5","tests/test_tui_shortcuts.py":"81abcfb68bec933d42c75ee1627366c3fb3bb95cd8b8982d9ba28374ed796ff4"},"openspec":"1.3.1","os":"Darwin","os_version":"26.5.2","python":"3.15.2","schema":"agent-harness","schema_format":3,"source_commit":"fcd2abcb11e323ccba4c26a3b340e7d377c0daa8"}
```
Digest: `726337ff1a3e44bbe061e63726d7019e484f474c0ef2495ba37eeca672b18ca2` (computed by hashlib.sha256 on normalized JSON).
Reproduce: discover runtime/OS/CLI versions with commands above, hash each listed relative file with Python `hashlib.sha256(Path(path).read_bytes()).hexdigest()`, populate the same keys from live values, serialize as specified and hash. Do not hardcode old values into the implementation candidate identity.
Freshness: snapshot valid only while all normalized values and source commit/diff remain identical; no fabricated wall-clock TTL. Rebaseline at apply, after source/runtime/schema/tool or acceptance revision changes, and after materializing the future candidate. Candidate must additionally bind its diff and accepted plan revisions; this baseline alone is insufficient acceptance evidence.
Observed checks: `diw` baseline has unchanged text/caret 11/pending false; leader tests 25 OK. New object acceptance is unexecuted.

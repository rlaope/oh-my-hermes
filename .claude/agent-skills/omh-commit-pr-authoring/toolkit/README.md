# Commit & PR Authoring Offline Merge-Danger Scanner (`merge_danger_scan.py`)

Offline Python 3.11+ standard-library companion script for `omh-commit-pr-authoring`.
It inspects a unified diff (from a saved patch file or piped stdin from `git diff`) and flags high-risk
merge hazards so the drafted commit message or PR Risk/Compatibility section never
misses migrations, lockfile/dependency drift, workflow/security edits, public API
deletions, bulk deletions, or accidentally added secret prefixes.

## Safety Boundary

- **Read-only, zero subprocess spawning**: never runs `git`, never spawns child processes, and makes no network calls.
- **Counts-only on secret hits**: reports the file path and count of added secret-like
  lines without echoing the added secret value.

## Usage

```sh
python3 toolkit/scripts/merge_danger_scan.py --diff-file /tmp/change.patch --json
git diff origin/main..HEAD | python3 toolkit/scripts/merge_danger_scan.py --diff-file - --json
```

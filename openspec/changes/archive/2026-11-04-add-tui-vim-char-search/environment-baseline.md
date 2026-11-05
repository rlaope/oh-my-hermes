# Environment Baseline

Package: agent-harness 2.0.0 (schema description); OpenSpec CLI 1.3.1.
Schema format: 3 (schema YAML version 3).
Captured at: 2026-11-04T22:04:06Z (read-only source identity recaptured; probes earlier this run).
Owner: draft-char-search planning agent.
Tools:
- Python 3.15.2: `/opt/homebrew/bin/python3 --version`.
- OpenSpec 1.3.1: `openspec --version`.
- Source identity: `git rev-parse HEAD`; cleanliness: `git status --porcelain` (empty).
- Platform: `uname -s`, `uname -m`, `sw_vers -productVersion`: Darwin, arm64, 26.5.2.
- Timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ`.
Platform: {os: Darwin 26.5.2, arch: arm64, runtime: /opt/homebrew/bin/python3 3.15.2}.
Roots:
- project/read-only source: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix`.
- planning workspace: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning`.
- package: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning/openspec/changes/add-tui-vim-char-search`.
- materialization: N/A, no feature candidate exists or is authorized.
- schema: `/Users/danrio/.local/share/openspec/schemas/agent-harness/schema.yaml`.
Known noise: [test duration, timestamp, transient CLI spinner]; excluded from semantic identity.
Normalization: exact UTF-8 JSON below, keys sorted, compact separators, no trailing newline. Digest uses `hashlib.sha256(encoded.encode('utf-8')).hexdigest()`. Hash inputs are source bytes and user schema bytes read with pathlib.Path.read_bytes; tool command outputs normalized to the recorded versions. Path, timestamp and test durations are contextual, not digest fields.
```json
{"arch":"arm64","files":{"src/tui/composer.py":"8f651b0fd549f6cee6ed619b0c7654a2b73d3bfb0029d04a9e1d6d7f3fffd455","src/tui/keys.py":"96ec9fb7ae293c8740ed7116d5f92299921d47952346d927838af2f1df7b7e9c","tests/test_tui_composer.py":"a5a6f633590a931ad31488c5901f7c591a270b5088f6aaa9e8fa3849ac786cc5","tests/test_tui_shortcuts.py":"81abcfb68bec933d42c75ee1627366c3fb3bb95cd8b8982d9ba28374ed796ff4"},"openspec":"1.3.1","os":"Darwin","os_version":"26.5.2","python":"3.15.2","schema":"agent-harness","schema_format":3,"schema_sha256":"afb5ead42a50b36ad50d9a290c95b80f278e1ba155378f835908fb8977a7fea3","source_commit":"fcd2abcb11e323ccba4c26a3b340e7d377c0daa8"}
```
Digest: `6f4d139762e4be02b95929e86cc9ba9fb1fe9a808e336774c1e0c7b9c4eb41ec`.
Freshness: {stale_after: 2026-11-05T22:04:06Z, rebaseline_trigger: any source/accepted slice-1 materialization/runtime/schema/config/tool identity change or later application}.

Pinned interpreter for every Composer/test execution:
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B
```
Run from exact recorded source/candidate root. Do not silently substitute system Python or allow __pycache__ writes. This baseline describes the pre-word-object source; future slice-2 feature evidence MUST bind the accepted word-object parent and recomputed digest, never reuse this pre-feature digest as candidate proof. Timestamp expiry is a planning freshness cutoff, not a substitute for content equality.

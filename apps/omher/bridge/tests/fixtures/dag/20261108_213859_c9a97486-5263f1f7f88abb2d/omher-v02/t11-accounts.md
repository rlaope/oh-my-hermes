# T11 handoff: Accounts (lane acct, wt v02-acct, branch feat/omher-v02-acct)

Status: DONE. Every VERIFY passes. The commit is signed off and not pushed.

## Commit
- `3d21d5bc7` feat(omher): accounts - stacked logins, one-click switch, auto-switch (on top of T7/T10 `fe8398d6f`)

## What was built

### Entry
- The sidebar user row ("You") is now a button that opens Settings › Accounts.
- Settings nav has a new "You" section with Accounts as the first item.
- The row turns gray while Accounts is open. The Settings nav item is not highlighted then.

### Bridge (`bridge/omher_bridge.py`, new "accounts" section)
- `read_accounts()` groups accounts per CLI. A CLI is listed only when it is on PATH or has accounts.

**Backend A: CPA.** Used when `~/.cli-proxy-api/config.yaml` exists and a bare TCP connect to `10.0.0.1:<port>` succeeds.
- `read_cpa_file` keeps only `email, disabled, expired, last_refresh, type`. It clears the parsed dict at once.
- States: ready, disabled, or expired.
- The group carries `{port, management, strategy}`.
- `management` is only whether `secret-key` is non-empty. The key itself is never returned.

**Backend B: omher.** Accounts live in `~/.omher/accounts/<cli>/<id>/`.
- A "default" row (the CLI's own home) is listed first.
- State is `login` until the CLI's login file exists. This is a stat only; the file is never opened.
- For Claude, the email comes from `.claude.json` `oauthAccount.emailAddress`.
- Each account gets its own usage record, through `_claude_usage` / `_codex_usage`. Their new `root=` parameter is the only change to T10 code.
- A limited usage record makes the account `limited` with `resets_at`.
- The active account is stored per CLI in `active.json`.

**Ops**
- `accounts.list`, `accounts.add` (label → slug, mkdir 0700 + `account.json`), `accounts.set_active`, `accounts.remove`, `accounts.cpa_action`.
- add, set_active and remove emit an `accounts.update` event.
- remove deletes only `~/.omher/accounts/<cli>/<id>`. It refuses `..`, slashes, `default`, symlinks, and unknown CLIs.

**Decision: ops take `account`, not `id`.** `id` is the frame's own request id, so an `id` param was silently overwritten. I found this in e2e; the protocol comment now says so.

**Decision: the bridge makes no HTTP call.** `test_bridge_has_no_http_or_llm_client` and rule 5 stay true. `accounts.cpa_action` only validates the request and returns `{port, method, path, body}`. The app sends it.

### Rust (`src-tauri/src/accounts.rs`, commands in `lib.rs`)
- `account_env(home, cli, id) -> Vec<(String,String)>`:
  - claude → `CLAUDE_CONFIG_DIR`
  - codex → `CODEX_HOME`
  - grok → `GROK_HOME`
  - gemini → `GEMINI_CLI_HOME`
  - `default` gives no env. Bad ids are refused.
  - Grok and Gemini env names were checked against their docs (Grok Build `GROK_HOME`; Gemini CLI `GEMINI_CLI_HOME`, which makes `.gemini` inside).
- Keychain via the `keyring` 3 crate: apple-native on macOS, windows-native on Windows, linux-native kernel keyring on Linux (no system lib needed for the CI ubuntu matrix).
  - Commands: `cpa_key_set`, `cpa_key_present`, `cpa_key_clear`.
  - The key is never returned to the UI and never written to a file.
- `cpa_send(request)`:
  - It accepts only PATCH `/v0/management/auth-files/status` with exactly `{name, disabled:bool}`, or DELETE `/v0/management/auth-files?name=<plain .json>`.
  - It connects to `10.0.0.1` only, sends the Bearer key, and maps the status to a plain message. The response body is never shown.
- Tauri commands: `account_env`, `cpa_key_set`, `cpa_key_present`, `cpa_key_clear`, `cpa_send`.
- `accounts_add` is the bridge op, which creates the dir and returns `{id, dir}`. The env comes from `account_env`. The PTY stays with the SESSIONS PR.

### UI
- `src/settings/accounts/AccountsPage.tsx` + `accounts.css`.
  - Groups have an AgentIcon, a name and a source tag (CLIProxyAPI / omher).
  - Each row shows: the T10 usage ring (`Ring` is now exported from `sidebar/Usage.tsx`), the masked email (`k***@domain`, full email on hover via `title`), the plan, a state chip (Active / Ready / Limited until hh:mm / Expired / Disabled / Log in) and a ⋯ menu.
  - **CPA group:**
    - "Auto-switch: CPA fill-first" (CPA's own strategy).
    - With management off: the exact hint text and no ⋯ menu (read-only).
    - With management on: a keychain key field (desktop only), then a Disable/Enable/Remove menu.
    - "+ Add account" shows `cliproxyapi -claude-login` etc.
  - **omher group:**
    - On/Off auto-switch control (gray `Seg`, default on, saved in localStorage `omher.autoswitch`).
    - ⋯ menu: Make active, Re-login, Remove…. Remove has an inline confirm that names the folder; the default login has no Remove.
    - "+ Add account" asks for a name, then shows the stub "Run login in a new session: `CODEX_HOME=<dir> codex login`".
  - Disabled/expired rows are dimmed; their chips are outlined.
- `src/settings/accounts/rules.ts`:
  - `nextAccount(accounts, usage, activeId)`: fill-first. Limited or expired active → first Ready that isn't limited, in list order.
  - Also `maskEmail`, `stateChip`, `switchNote`, `autoSwitchOn`.
  - Tests in `rules.test.ts` (8 vitest cases).
- `useAccounts.ts`:
  - A shared copy, plus an `AccountsWatcher` mounted in the sidebar. It refreshes every 60 s and on `accounts.update`.
  - When an omher group's active account is limited and auto-switch is on, it calls `accounts.set_active` and adds a toast inside that group.
- **owner addition: system line in the bot chat.**
  - New `SystemItem` (`kind: "system"`) in the store, added via the `systemNote` action. It is never sent to the bot.
  - Rendered by Timeline as a centered quiet line with hairlines, e.g. "Switched to Codex #2 Work (limit on #1 Default, resets Tue 00:05)".
  - Ids and names in the line are labels or masked emails only, never tokens.

### Mock + e2e
- `e2e/mock-bridge.mjs`:
  - Claude: 5 CPA rows with management off, one of them Disabled.
  - Codex: an omher stack with Default (active) and Work.
  - add / set_active / remove, and `cpa_action` → `cpa_management_off`.
  - Test op `mock.accounts {limit}` marks an account limited.
- `e2e/accounts.spec.ts` has 7 tests:
  1. The user row opens Accounts, listed first.
  2. 5 CPA rows are read-only, with the hint and the strategy; emails masked, full on hover; no token in the DOM; no cpa_action call.
  3. Add → the row appears in the "Log in" state, with the login hint; Make active moves the chip.
  4. Remove asks first; Cancel keeps the row and Confirm deletes only that account; default has no Remove.
  5. Auto-switch: limit → Work becomes Active, a toast appears in the Codex group, one system line shows in the Kami chat, and no chat.send is made.
  6. With auto-switch off, nothing moves.
  7. Screenshots.

### BOUNDARY
- New rule 12 in `docs/OMHER-BOUNDARY.md`: accounts are the one exception to 4/5/11. It covers the five CPA fields, writes only under `~/.omher/accounts/`, the loopback-only single CPA request, the key kept in the keychain, no tokens, and that a switch never stops a session.
- `tests/test_omher_boundary.py`:
  - pins 5 sentences of the rule;
  - adds `AccountsNeverCarryAToken`: 25 fuzz rounds of fake CPA files and omher folders holding `access_token/refresh_token/id_token/api_key/OPENAI_API_KEY`, with wrong types and nested tokens. It asserts no key or secret appears in `read_accounts` (CPA up and down) or in `cpa_request`.
  - The cap stays ≤12 (rule 12 fills it; the comment notes this).
- Bridge test class `Accounts` has 9 tests: the five-field reader, the fuzz, management off/on request building with bad names refused, the add/activate/remove lifecycle, remove refusing every other path (incl. symlink), Claude email + limited from its own folder, CPA down → omher fallback, and that the accounts code has no subprocess, http, keyring or environ writes.

## Real data on this Mac
- `read_accounts()` gives Claude: cpa, 5 rows, `management: false`, `strategy: fill-first`, no token keys in the JSON (checked).
- Codex is listed as omher/default with its 21% weekly usage. Codex is not on PATH, but a usage record exists.
- The real UI will therefore show 5 read-only Claude rows + the hint, as the brief predicted.

## VERIFY (literal tails, final run on the committed tree; log ~/.hermes/profiles/kami/cache/scratch/omher-v02/t11-verify.log)
```
== typecheck+test
 Test Files  6 passed (6)
      Tests  51 passed (51)
rc=0
== bridge
Ran 68 tests in 0.882s
OK
rc=0
== e2e   (OMHER_PORT=5433 OMHER_MOCK_PORT=5434 lockf … playwright test e2e/accounts.spec.ts e2e/usage.spec.ts)
  12 passed (12.5s)
rc=0
== boundary   (repo root: PYTHONPATH=tests … unittest tests.test_omher_boundary)
Ran 9 tests in 3.395s
OK
rc=0
== diff-check   (git diff --check)
rc=0
```
cargo test (lockf; log t11-cargo.log), rc=0:
```
test accounts::tests::send_local_talks_to_a_loopback_server_and_reads_the_status ... ok
test result: ok. 27 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.13s
```
Windows `cargo check --target x86_64-pc-windows-msvc` (fakerc, CARGO_TARGET_DIR=…/omher-wincheck-t11; log t11-win.log), rc=0:
```
    Checking webview2-com v0.39.1
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 42.99s
```
Extra regression check (not required): settings, bots, shell, usability and mock specs on 5433/5434 gave `36 passed`. The sidebar and settings-nav edits did not break them.

## Screenshots (~/.hermes/profiles/kami/cache/scratch/omher-v02/)
- T11-accounts-dark.png / -light.png: the full page, with 5 CPA rows + hint and the Codex stack.
- T11-menu-dark.png / -light.png: the ⋯ menu open on Work.
- T11-switch-dark.png / -light.png: after auto-switch (vision 7/10). The toast is in the Codex group, Work is Active, and Default reads "Limited until …".
- T11-chatline-dark.png (7/10) / -light.png (8/10): the quiet system line in the Kami chat. Hairlines were added after the first review, because without them the line read like a time divider.

## Fixed after vision review
- The toast was at the top of the page; it now sits inside the group it describes.
- Light-theme amber chip contrast was raised (#94600f).
- Disabled/expired rows are now dimmed with outlined chips.
- Removed the empty ring placeholder.
- The system line now has hairlines.

## Open / not done
- **PTY login.** "Run login in a new session" is a stub that shows the env + command. Wiring the SESSIONS PTY (spawn with `account_env`) belongs to the SESSIONS PR. Likewise, new sessions do not yet use `active.json`; the SESSIONS spawn should call `account_env(cli, active)`.
- **Grok/Gemini login.** For omher stacks, the login-file markers are best guesses (`auth.json` / `user-settings.json`; `.gemini/oauth_creds.json`) because neither CLI is installed here. The `LOGIN_CMD` for grok (`grok login`) is unverified.
- **CPA writes.** The CPA write path (keychain + `cpa_send`) is unit-tested in Rust against a loopback fake server, but not exercised end-to-end against a real CPA, because management is off on this Mac. It is untested in e2e because the browser has no Tauri.
- **Re-login.** For CPA rows there is no Re-login; the "+ Add account" hint covers CPA's own login flags.
- **Model auto-switch line.** Only account switches emit a system line. The same `systemNote` action is available for a model auto-switch, but nothing emits one yet.
- **Vision nitpicks left alone.**
  - The CPA group shows a text strategy where the omher group has an On/Off control. This is by design: CPA does its own switching.
  - The Claude rows reserve an empty ⋯ column.
  - Chips are 11px, like the existing `st-tag`/Soon badges.
- **Outside apps/omher.** `docs/OMHER-BOUNDARY.md` and `tests/test_omher_boundary.py` were edited, as the brief requires (BOUNDARY rule + boundary test).

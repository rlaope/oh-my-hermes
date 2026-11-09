# Own-runtime spike: a TUI-only Hermes home beside the bots' gateway

Verdict: **go**. Measured 2026-11-08 22:23 KST on the owner's machine, Hermes 0.23.0
(`code_sha 2bd378ed`), with the root gateway (`~/.hermes`, pid 72122, serving `default` and
`kami`, feishu and kami:discord connected) running the whole time and never signalled.

Scripts: `build_sandbox.py` (run on Hermes' interpreter) builds the home; `run_spike.py` (run from
the checkout) opens a session on it through the OMH TUI's own client and attach child, exactly as
`omh` would with `HERMES_HOME` pointing there. Raw record: `spike-result-2026-11-08.json`.

## What was built

A home outside `profiles/` (profile kind `custom`): `config.yaml` carrying the root's `model`,
`providers`, `agent`, `display`, `memory` (provider omh, `omh_home` pointed at a sandbox OMH home),
`skills` (external_dirs = OMH's current skills) and `plugins` (omh only), with `platforms: {}` and
`gateway.unmanaged_idle_exit_seconds: 30`; `.env` = the root's minus messaging token names (the root
`.env` holds none; kami's Slack and Discord tokens live in kami's own `.env` and were never read);
`auth.json` copied; `SOUL.md` symlinked; `skills/` = per-skill symlinks, root ∪ kami, root wins on
the 20 shared names (kami-only `sionic-onprem-gpu` added; 25 names); `plugins/omh` symlinked to the
root's; a fresh `git init` cwd.

## What was measured

| Claim | Measured | Where |
| --- | --- | --- |
| A second gateway starts for the custom home while the root gateway runs | yes: sandbox `gateway_state.json` pid 78011, state `running`, `hermes_home` = sandbox; root pid 72122 unchanged before, during and after | `sandbox_record`, `root_before/during/after` |
| It connects no messaging adapter | `platforms: {}`; sandbox `gateway.log`: "No messaging platforms enabled." Root adapters unchanged (feishu, kami:discord connected) | `sandbox_platforms`, `root_platforms_*` |
| The OMH TUI's client opens a session there | `gateway.ready` at 26.2 s (first launch: Hermes verified its dependency generation for the new data root, "preparing dependencies for this data root"; no new environment directory was created under `~/.hermes/installs`), `session.create` answered in 0.7 s: profile `default`, model `claude-opus-5-5`, a shared-gateway subscription | `steps`, `session_create` |
| Skills: the union is visible, no ambiguity | 250 skill entries in the create answer's `info.skills`; zero `Ambiguous skill name` lines in the sandbox `gateway.error.log` | `skills_seen_by_session`, `ambiguous_skill_warnings` |
| `session.list` works on the own store | 1 session (the new one) | `session_list_count` |
| The root home is not written by the TUI gateway | every file newer than the marker under `~/.hermes` is the root gateway's own (kami's skill curator, cron ticker, heartbeat, `cache/*`), and Hermes' cache path is `get_hermes_home()/cache`, which for the sandbox is the sandbox's own `cache/` (present after the run) | `root_writes_total`; `hermes_cli/model_catalog.py:122` |
| Idle exit | client closed at 45.0 s; record `draining` at 87.1 s, `stopped` at 89.1 s, pid gone; log: "Exiting: auto-started gateway idle for 30s … the next client starts a fresh gateway"; teardown 1.6 s | `idle_exit`, `sandbox_gateway_log_tail` |
| No lasting launchd job | the macOS transient job `com.nousresearch.hermes.runtime.<12hex>` is bootstrapped from a plist Hermes deletes right after; after the exit `launchctl list` still shows the label with no pid (launchd keeps finished transient labels until bootout or logout). Hermes' own behaviour for every auto-started gateway, not the TUI home's | `launchd_before/during/after` |
| Hermes resolves `--profile default` to the custom home, not `~/.hermes` | `spawn_unmanaged_gateway` passes `--profile default` for a non-`profiles/` home; `resolve_profile_env("default")` returns `profile_root_for_env_home(HERMES_HOME)`, which is the custom home itself | `hermes_cli/gateway_runtime_start.py:43-60`; `hermes_cli/profiles.py:2367-2391` |

Not measured: a prompt round trip (`--prompt` flag exists; skipped to spend no tokens on the owner's
keys), and the drain independence under a real root restart (argued from per-home ownership:
`gateway/runtime_ownership.py` reserves per home path; the root's drain refuses admission on the
root's session authority only; the sandbox session never touched the root's control socket).

## Costs seen

- First launch on a fresh home: ~26 s to `gateway.ready` (dependency verification for the data root
  plus gateway start). A later launch is Hermes' usual start.
- The TUI home grows Hermes' usual per-home files (`state.db`, `kanban.db`, `cache/`, `installs/`
  state, `memories/`, `sessions/`): own, disposable, rebuilt by Hermes.
- One finished transient launchd label per auto-started gateway (Hermes' own).

## Consequences for PR 2

- Build the TUI home exactly as `build_sandbox.py` does; keep the token scrub list and the
  per-skill symlink union (root wins) — `skills.external_dirs` cannot carry two roots with 20
  shared names without `Ambiguous skill name` refusals.
- Expect `gateway.ready` to take longer the first time; the launch wait already covers it and says
  what it waits for.
- `/gateway restart` on the own runtime is a plain stop of an idle-exit gateway: the next launch
  starts a fresh one on the new OMH generation.

## Profile spike (2026-11-09): the TUI home as a standalone named profile

Verdict: **go**, and the shape the TUI runtime ships with. Measured 2026-11-09 14:56 KST on the owner's
machine, Hermes 0.23.0 (`code_sha 2bd378ed`), root gateway pid 72122 serving `default` and `kami`, never
signalled. Script: `run_profile_spike.py` (run from the checkout). Record: `profile-spike-result-2026-11-09.json`
(provider names, token values and bot paths left out).

Why: the custom home beside the root (above) could not share the login. Hermes reads `auth.json` only from
the home and, for a named profile, from the root as a fallback (`_load_provider_state_with_source`), writing a
rotated OAuth chain back to the store it came from under both locks. A home inside the root but outside
`profiles/` is the default profile to Hermes and gets no gateway of its own (section 10 of the plan). A named
profile with `gateway.standalone: true` is the one shape Hermes gives both: the host multiplexer never serves
it (`profiles_to_serve` skips it) and its client starts an unmanaged gateway for it without `--force`.

| Claim | Measured |
| --- | --- |
| The host leaves the profile alone | `served_profiles` `[default, kami]` before placing the profile, 3 s after, during the session, after |
| A gateway of its own | pid 68447 beside 72122; `hermes_home` the profile; `platforms: {}` |
| The login is shared with no copy | no `auth.json` in the profile before or after; `prompt.submit` answered `ok` on the root's OAuth provider; root `auth.json` mtime and provider set unchanged |
| Skills | 273 in the create answer; no `Ambiguous skill name` |
| Start | `gateway.ready` 7.6 s, `session.create` 0.8 s, prompt round trip 2.7 s |
| Idle exit | NOT within 90 s: the gateway logged `Cron scheduler will tick 3 profile(s): ['default', 'kami', 'omh-tui']`; `_cron_tick_profile_homes` is `profiles_to_serve(True)` plus the launch profile for any gateway under the root, and `_cron_busy` counts kami's 5 scheduled jobs as work. It stands down per tick for a home another gateway owns (`_cron_profile_gate`). Hermes' fleet semantics; no config knob (`cron.provider` is a scheduler, not a switch). |
| Root writes | the root ticker's own heartbeat/lock files; nothing under `~/.hermes` outside the profile and the root gateway's housekeeping |

Consequences shipped: the builder targets `<root>/profiles/omh-tui`, sets `standalone: true` in the copied
config's `gateway:` block, copies no `auth.json`, writes Hermes' `.no-bundled-skills` marker, stages a new
profile under a dot name and renames it, removes the legacy `<omh_home>/tui-home`; `own` is the default; every
OMH listing of Hermes profiles skips `omh-tui`. Known cost: on a host whose bots have scheduled cron jobs the
TUI gateway stays up between sessions.

### Shipped builder, live (2026-11-09 15:27 KST)

`run_live_build.py`: this branch's `build_tui_home` against the real root, then a session the way `omh` opens
one, then `remove_tui_home`. Record: `live-build-result-2026-11-09.json`. Built in 0.07 s (120 skills: 97 root +
23 kami-only; 89 kami duplicates of root names recorded as clashes; nothing scrubbed, the root `.env` holds no
messaging token; no `auth.json`; `.no-bundled-skills` present; the copied config's `gateway:` block carries
`standalone: true`); a second build refreshed nothing; `gateway.ready` 4.0 s; session on profile `omh-tui`,
273 skills, prompt answered `ok`; host `served_profiles` `[default, kami]` throughout; profile removed, only
`kami` left under `profiles/`.

Pitfall met on the way (the first spike script removed the profile while its gateway still ran): the dying
gateway re-created the directory with `state.db` and no config, the host saw a marker-bearing profile without
the standalone key and started serving it (`cron/`, `skills/`, `plugins/` appeared). `remove_tui_home` refuses
while the record is live, and the staged build never shows the host a directory without its config; the ghost
was cleared with the `unserve-profile` control verb plus removal, never a signal to the host.

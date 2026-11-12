# Agent Skills projection

OMH can project its reviewed workflow catalog into the open Agent Skills
`SKILL.md` format for Claude Code, Codex, Cursor, opencode, OpenClaw, and pi.
This is a guidance projection, not a port of the Hermes runtime, plugin, or
wrapper. The existing managed Hermes skills and their installation are unchanged.

## Clone-and-run host installers (no Python or omh required)

Clone once, then run the chosen adapter **from the target project's root
directory** (it need not be a git repository). The script locates the canonical
`agent-skills/` source beside itself, not in your current directory:

```sh
git clone https://github.com/rlaope/oh-my-hermes.git "$HOME/oh-my-hermes"
cd /path/to/your/project
sh "$HOME/oh-my-hermes/.cursor/install.sh"
# User scope instead of this project:
sh "$HOME/oh-my-hermes/.cursor/install.sh" --user
```

Replace `.cursor` with `.claude`, `.codex`, `.opencode`, `.openclaw`, or `.pi`.
Each directory contains generated `install.sh`, `install.ps1`, and
`manifest.json`; there are no handwritten host skill copies. POSIX installation
uses ordinary shell utilities plus `sha256sum` or `shasum` (automatic fallback),
with no Python, omh, package manager, network access, or git subprocess.

Windows-native PowerShell (5.1 or 7):

```powershell
git clone https://github.com/rlaope/oh-my-hermes.git "$HOME/oh-my-hermes"
Set-Location C:/path/to/your/project
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME/oh-my-hermes/.cursor/install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME/oh-my-hermes/.cursor/install.ps1" -User
```

Windows 10 and 11 ship with the `Restricted` execution policy, which refuses
to run any `.ps1` file, so calling the script directly
(`& ".../install.ps1"`) fails there. `-ExecutionPolicy Bypass` applies to that
one process only and changes no machine or user policy. With PowerShell 7, run
the same line with `pwsh` in place of `powershell`.

Claude installs only `.claude/skills/`, from its own generated copy of the
pack in `.claude/agent-skills/` (see
[Claude Code skill listing](#claude-code-skill-listing)); the other five
adapters install `agent-skills/` into `.agents/skills/` only. User scope places the same relative path under the user's
home. These paths come from the recorded [host matrix](#host-support-matrix),
not invented vendor-specific directories. In particular, `.openclaw/` and
`.pi/` contain installers, **not** new host skill scan paths. OpenClaw's custom
`OPENCLAW_STATE_DIR` caveat below still applies; no alternative path is guessed.

Both installers read their pack's one inventory,
`agent-skills/.omh-agent-skills-manifest.json` (Claude:
`.claude/agent-skills/.omh-agent-skills-manifest.json`), verify the complete source file
list and SHA256s against it before writing, copy only listed files, verify the
installed bytes, copy that inventory verbatim as the receipt, and print the
installed skill names. Re-running is idempotent. A reinstall replaces edited
`SKILL.md` and reference files, so review/back up local edits first. It never
replaces an edited **toolkit** file (`<skill>/toolkit/...`): it stops before
writing anything with `Foreign/edited support preserved: <path> (move it aside,
then rerun)`, and keeps stopping on every run until that file is gone. To
recover, back up the file, move it out of the skills directory, and run the
installer again; it then writes the pack's copy. Other files and skills
(including existing `.claude/skills/triage-sweep`, `review-sweep`, and
`model-onboarding`) are preserved. Symlink/reparse-point destinations are
refused. Interrupted copies report failure; rerun after resolving the cause.
Clone scripts do not track or delete retired files from older packs.

If omh is already installed, the same catalog manifest selects the destination:

```sh
# Host-selected repo scope defaults to the CURRENT project directory, like the scripts.
omh install --target agents --host cursor
omh install --target agents --host claude --scope user
omh install --target agents --host cursor --status --json
```

The CLI and both clone scripts write the same skill bytes and
`.omh-agent-skills-manifest.json` receipt. With a matching package version/checkout,
fresh installed trees are byte-identical, including the receipt, in either scope.
Single-target receipts use `target_dirs: ["."]` relative to the receipt directory,
not install-time absolute paths; CLI status still reports the actual absolute
destination. The CLI retains its collision checks and manifest-owned retired
file cleanup; the clone scripts deliberately copy only the committed pack.
Neither path installs the Hermes-native `skills/` projection, registers the
Hermes plugin, adds host rules/plugins/MCP tools, or proves host execution.
**Installing** needs no Python; **using** workflows marked `requires-omh-cli`
still needs that optional CLI. Phase 1 is copy-only, not a runtime port.

## Install through omh without a host selector (agents and operators)

Install the `oh-my-hermes` Python package so `omh` is on PATH, then choose one
scope explicitly:

```sh
# From anywhere inside the target git repository; writes at the git root.
omh install --target agents --scope repo

# User-wide: two independent copies, not symlinks.
omh install --target agents --scope user

# Read-only inspection (add --json for machine-readable output).
omh install --target agents --scope repo --status
omh install --target agents --scope user --status --json
```

Repo scope generates `.agents/skills/<name>/SKILL.md` and a `.claude/skills/`
copy at the git root, and fails closed outside a repository. Two copies mean
Cursor and opencode load every skill twice (see
[Duplicate copies](#duplicate-copies)), and the command prints a warning saying
so; use `--host` when you use one host. Claude Code
2.1.270 discovered the repo `.claude/skills/` copy but not `.agents/skills/`
in observed parent QA (2026-09-13; details below).
User scope likewise generates both `~/.agents/skills/` and `~/.claude/skills/`,
because Claude Code does not document `~/.agents/skills/` as a user scan path. References
are copied alongside each skill. Generation works from an installed package;
it does not read this repository's committed projection tree.

`--dry-run` reports current status without writing. Source import, Hermes
profiles, and release-selection options do not apply to this target. No Hermes
configuration is registered, and no vendor configuration is written. Existing
symlink destinations and conflicting files OMH never installed are refused;
unrelated skills are preserved. Repo-wide Hermes source imports exclude only
manifest-owned files in the Claude mirror, not neighboring custom Claude skills.
An explicit import rooted at the mirror still imports the selected source.

### Manifest and refresh

`.omh-agent-skills-manifest.json` uses `schema_version:
omh_agent_skills_projection/v1`, a content-addressed `catalog_revision`,
`target_dirs`, and a `files` mapping from projection-relative path to SHA256.
Without a host selector, both scopes retain absolute `target_dirs` and write a
manifest at each of their two roots with the **same `target_dirs`**; each lists
the digests of its own root's files, because the `.claude/skills` copy carries
the [Claude listing change](#claude-code-skill-listing) and the
`.agents/skills` copy does not. A mirror written before that change reports
stale (clean drift) until the install is rerun or `omh update` refreshes it.
Host-selected single-target installs instead use the portable `["."]`
receipt described above. Older absolute single-target receipts report stale
(clean drift) until an explicit reinstall refreshes them. Manifest paths never
choose the write destinations.

Status separates `projection` (`fresh`, `stale`, `missing`) from `drift`
(`clean`, `locally_modified`, `unknown`), and includes `locally_modified` and
`next_action`. Human output spells the drift state `locally-modified`. A missing
or edited mirror is not a fresh install in either scope. `mirror:` prefixes identify mirror
file drift. An interrupted install stays missing/stale until every copy agrees.

Inspect and back up local edits before repeating the install command. An
explicit reinstall replaces managed local edits to `SKILL.md` and reference
files, refreshes both chosen-scope copies, and removes retired manifest-owned
files; it does not import those edits into the catalog. Like the clone scripts,
it refuses an edited toolkit file (`Agent Skills refuses edited support`), and
status then says to move that file aside before rerunning. There is no automatic update, host reload, or background sync.

## Claude Code skill listing

Claude Code puts a listing of skill names and descriptions into every turn,
inside a budget. Its [skills documentation](https://code.claude.com/docs/en/skills#skill-descriptions-are-cut-short)
says: "The listing always contains every skill name, but if you have many
skills, Claude Code drops some descriptions to fit the listing's character
budget, which removes the keywords Claude needs to match your request. The
budget scales at 1% of the model's context window."

The whole portable pack did not fit. So the Claude copy, generated into
`.claude/agent-skills/` and installed by `.claude/install.sh`, `.ps1` and the
CLI's `.claude/skills` root, changes one thing: each `SKILL.md`'s frontmatter
`description:` is cut to its lead (the text before the generated ` Use when the
user says:` trigger list) and, if that is still longer than
`CLAUDE_DESCRIPTION_CAP` (160 characters, `src/install/agent_skills_projection.py`),
to the last clause boundary under the cap, else the last word, never ending on
a function word, closed with a full stop. The leading `[omh] ` stays. All 123
skills stay listed and model-invocable; no flag and no extra skill is added.
The trigger phrases remain in the portable pack and in the skill bodies.
Bodies, references and toolkit files are byte-identical to `agent-skills/`,
and `.agents/skills` and the Hermes `skills/` tree do not change. The built
descriptions run from 61 to 160 characters (mean 134).

Measured on 2026-11-13 with Claude Code 2.1.322 and `claude-opus-5-5` (1M
context), in a fresh git project after `.claude/install.sh`, with an empty
`CLAUDE_CONFIG_DIR`:

| Pack | Skills listing | OMH rows | With a description | Name-only (`< 20`) |
| --- | --- | --- | --- | --- |
| before this change | 9.9k | 123 | 61 | 62 |
| this pack (cap 160) | 8.5k | 123 | 123 | 0 |

The same pack in user scope (`install.sh --user`, scratch `HOME`) lists 123 of
123 with a description. Before this change, the rows that lost their
description were everything from `omh-localization-review` on, `omh-plan` and
all eight `ulw-*` among them. A `< 20` row can also be a description of about
45 characters or less; the shortest description here is 61, so `< 20` means
dropped.

**What a model picks is a different measurement.** In four task prompts, one
run each (`claude -p --setting-sources project --tools "Read,Skill" --max-turns 4`,
same version and model, 2026-11-13), the model loaded the fitting skill in 4 of
4 runs on this pack; on the pack before this change it did in 3 of 4
(2026-11-12). Four prompts are too few to give a rate.

**Tried and rejected.** The first design flagged 113 skills
`disable-model-invocation: true` and listed them in one generated `omh-index`
skill. It listed 11 skills (3.2k), but in the same four prompts the model
loaded the fitting skill in 0 of 4 runs and never opened the index. The
index idea came from `yetone/magpie` (MIT, commit
`5e933e153a87c4017a19502e1d2e87aa714572b9`); concept only, reimplemented and
then dropped.

To measure your own setup, run `/context` in the project and count the rows:

```sh
claude -p "/context" > context.md
uv run python tools/claude_context_skills.py context.md
```

The script prints, per source, how many skills are listed, how many have a
description, and how many are name-only. It reads the saved file and does not
run `claude`.

**When your own listing is already full.** The shorter descriptions do not
create budget. With the owner's real home on 2026-11-13 (55 user skills, 124
plugin skills, listing 9.9k), an empty project kept 35 of 55 user
descriptions; with the pack before this change the user skills kept 25 of 55
and the project 5 of 123 OMH descriptions; with this pack, 28 of 55 and 6 of
123. A full listing is not fixed by this change. Claude Code documents these
settings for it:

- `skillListingBudgetFraction` raises the share of the context window the
  listing may use (default `0.01`; "Raise this key to keep more descriptions
  visible at the cost of more context per turn",
  [settings reference](https://code.claude.com/docs/en/settings-reference#skilllistingbudgetfraction)).
  The skills page also names the `SLASH_COMMAND_TOOL_CHAR_BUDGET` environment
  variable "to a fixed character count".
- `skillOverrides` sets a skill to `"name-only"` ("Claude sees the skill by
  name without its description") or `"user-invocable-only"` ("Claude doesn't
  see the skill, but you can still type `/name`") without editing its
  `SKILL.md` ([settings reference](https://code.claude.com/docs/en/settings-reference#skilloverrides)).
  Use it to free budget from skills you rarely want Claude to choose.
- `/skill-doctor` "see[s] what each of your skills costs and how often it gets
  used" ([Find unused skills](https://code.claude.com/docs/en/skills#find-unused-skills)).

## Duplicate copies

Every installer writes one of two directories: `.agents/skills/` (Codex,
Cursor, opencode, OpenClaw, pi) or `.claude/skills/` (Claude Code). Some hosts
read both. Per each vendor's skills documentation, read on 2026-10-25:

| Host | Reads `.agents/skills/` | Reads `.claude/skills/` | With the same name in both |
| --- | --- | --- | --- |
| Claude Code | no | yes | n/a |
| Codex | yes | no | n/a |
| Cursor | yes | yes ("for compatibility", repo and user) | loads both; resolution not documented |
| opencode | yes | yes (Claude-compatible, repo and global) | loads both; its docs ask for names unique across all locations |
| OpenClaw | yes | no | n/a |
| pi | yes | not documented | first discovered wins, with a warning |

Sources: [Claude Code](https://code.claude.com/docs/en/skills),
[Codex](https://learn.chatgpt.com/docs/build-skills),
[Cursor](https://cursor.com/docs/context/skills),
[opencode](https://opencode.ai/docs/skills/),
[OpenClaw](https://docs.openclaw.ai/tools/skills), and
[pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/skills.md).

Two ways create both copies under one root:

- `omh install --target agents` without `--host`, in either scope. That mode
  writes both on purpose, because it cannot know which host you use.
- `.claude/install.sh` (or `.ps1`) plus any of the other five installers.

Both paths warn instead of refusing, since a person who uses Claude Code and a
`.agents/skills/` host needs both copies. The CLI adds the warning to
`warnings` in `--json` output and prints it in human output, on install and on
`--status`. The clone scripts print it to stderr after installing. If you use
only one host, keep the copy that host reads and remove the other one, as
described in [Removal](#removal). After removing a copy that an install
without `--host` made, rerun the install with `--host <host>`. That rewrites
the remaining receipt as a single-target one, so `--status` reports `fresh`.

A pack in a repo directory and another in the same host's user directory is
also a duplicate for Cursor and opencode. The installers check only the root
they write to, so they do not warn about that case.

## Removal

`omh uninstall` does not touch Agent Skills trees. To remove a pack, delete
the skill directories its receipt lists, then the receipt. Do not delete the
whole `skills/` directory, because it can hold your own skills. Change into the
skills directory first: `.claude/skills` or `.agents/skills` under the project
root, or under your home directory for a user-scope install.

```sh
cd .agents/skills
sed -n 's|^    "\([A-Za-z0-9_-][A-Za-z0-9._-]*\)/.*|\1|p' .omh-agent-skills-manifest.json |
    LC_ALL=C sort -u | while IFS= read -r skill; do rm -rf -- "./$skill"; done
rm -f .omh-agent-skills-manifest.json
```

```powershell
Set-Location .agents/skills
(Get-Content -Raw -LiteralPath .omh-agent-skills-manifest.json | ConvertFrom-Json).files.PSObject.Properties.Name |
    ForEach-Object { $_.Split('/')[0] } | Sort-Object -Unique |
    ForEach-Object { Remove-Item -Recurse -Force -LiteralPath (Join-Path . $_) }
Remove-Item -LiteralPath .omh-agent-skills-manifest.json
```

This removes each listed skill's whole directory, including files you added
inside one, so back those up first. Skills the receipt does not list are kept.

## Portability classes

The single reviewed table in `src/skills/catalog_portable.py` classifies catalog
**definition fields**, not generated-file keywords. Unknown/new entries are
`hermes-only` until reviewed.

- **portable**: the workflow needs only the host's ordinary reasoning, files,
  tools, or explicitly authorized tasks. Artifact schema names describe output
  contracts; they do not conjure RPC tools or enforce a prompt's policy.
- **requires-omh-cli**: the workflow also uses local deterministic OMH commands
  or records. Its frontmatter declares `Requires the omh CLI on PATH (pip
  install oh-my-hermes).` For example, `omh-frontend` uses offline design data,
  and `omh-codebase-uml` generates its model through the CLI. `omh-docs` answers
  read-only product questions from official sources and bounded local CLI or
  metadata; it routes requested mutations elsewhere rather than requiring a
  Hermes runtime.
- **hermes-only**: the workflow requires Hermes runtime, registration, native
  plugin tools, or wrapper semantics. It is absent from this projection.

The ULW projection includes `ulw-work`, `ulw-plan`, `ulw-loop`, `ulw-qa`,
`ulw-research`, `ulw-perf`, `ulw-context`, and `ulw-interview`. Portable overrides
replace native delegation with the host's actual subagent/task mechanism and
native plan-recording commands with an explicitly chosen durable file/ledger.
Sequential lanes or a named unavailable capability replace missing delegation,
never fabricated participants. Domain contracts and portable references are
shared with the catalog; Hermes-coupled references are not shipped. Progressive
specialist contracts are inlined, retaining their portable procedure references.

### Adaptation quality preservation

`ulw-plan`, `ulw-work`, and `omh-verification-gate` conditionally load the one
[adaptation-quality procedure](../agent-skills/omh-verification-gate/references/adaptation-quality.md).
Their sibling-relative pointers resolve from the loaded skill directory; the
native DAG workflow uses the same procedure but its runtime is not ported.
The procedure preserves requested executable capability and craft through
component mapping, explicit user-agreed losses, reuse-first decisions, early
and final same-task comparisons, and distinct technical/output-quality verdicts.
A methods-only adaptation must declare that narrower outcome; neither a working
substitute nor structural checks prove retained capability or output quality.
Unobserved execution/review stays unobserved. It grants no provider, dependency,
credential or spending authority, and unrelated tasks need no upstream run.

### Code-review return compatibility

Both distributions ship optional finding-validation, architecture-delta, and
risk-selection references. Load them for candidate confirmation, changed
contracts/dependencies or extraction proposals, and risk-based inspection depth;
selection is not dispatch authority or evidence a check ran. The extraction
rubric is also reachable from the existing structure lens and smell baseline.

The review return now requires `spec_axis`, `could_not_assess`, and
`verification_gaps`. The spec object is either `assessed` with non-empty
claim/requirements/verdict/evidence rows, or `not_assessed` with a reason.
The two arrays may be empty. Gap rows carry `path`, `line_range`, and `evidence`
without `priority`, `confidence`, or `severity`; ordinary findings retain their
ranked contract. A `ship` still requires non-empty checked-clean coverage. Consumers
of old optional fields or string spec results must update before using the
stricter contract; useful extra annotations remain allowed.

Schema checks reject blank evidence and malformed positive line syntax, not
invented files, inverted/out-of-bounds ranges, unread code, or false claims.
Native same-turn schema records and later completion-message manual checks
remain distinct. These instructions and shape fixtures do not measure live
Hermes/host compliance, semantic accuracy, detection rates, false positives, or
review cost; no runtime validator, new tool, dependency, or automatic execution
was added.

### When a replaced catalog section moves

A definition's `portable_overrides` entry **replaces** that catalog section in
the portable body; the catalog's own lines for that section are never
consulted. That is deliberate — a Hermes-shaped line cannot be filtered down,
it has to be rewritten by someone who knows what the host can do — and it means
a line added to the section is absent from the portable body with every drift
gate still green. `docs agent-skills --check` compares the shipped bytes
against a projection that already applied the override, so it agrees with the
override by construction.

The override sits in the same `SkillDefinition` literal as the section it
replaces (`src/skills/catalog_definitions.py`, or the
`_feature_surface_skill(...)` call in `src/skills/catalog_feature_surfaces.py`),
so the edit that moves a section is made beside the replacement that shadows
it. Beside it, `portable_override_shadows` records the sha256 of the JSON form
of each replaced section as it read when the override was last reviewed. When
the section moves, `tests/test_agent_skills_projection.py` fails naming
`<skill>::<section>: shadowed section changed` and prints the new digest. Re-read
the override against the new section, edit it if the line belongs in the
portable body, then update the digest in the same literal. Updating the digest
without editing the override is a valid outcome and records the choice not to
mirror the line.

`tests/test_agent_skills_projection.py` fails, naming `<skill>::<section>`,
when an override key is not a `SkillDefinition` field (a renamed section) or
when a replacement line is absent from the rendered portable body. The second
check is a floor, not a proof: an override whose lines the body already
carries without it (a no-op override, or lines shared with the catalog
section) passes it, so the field-name check is what catches a mis-targeted
section.

### Loop boundary

`ulw-loop` is `requires-omh-cli`. `src/commands/loop.py` calls local loop-ledger
functions in `src/workflows/goal_loop.py`: start/status do not require a running
Hermes process or an existing Hermes home. They create/inspect metadata only.

The default `hermes_goal` driver label is **prepared metadata**, not evidence
that another host has native `/goal` controls. This projection does not port
native goal activation, native gates, or contiguous Hermes-session turn
observations. An external resumable-goal driver requires an explicitly chosen
coding owner and a session-bound `host_observed` capability snapshot; it is
never assumed. Otherwise the host executes authorized work and keeps its own
continuation/evidence ledger. Missing native evidence remains unavailable;
queued ticks never establish execution or goal completion. Linked OMH goal
completion retains its existing evidence gate.

### Hermes-only boundary

A workflow in `skills/` that is absent from `agent-skills/` is Hermes-only: it
needs the Hermes runtime, registration, native plugin tools, or wrapper
semantics. `skill_portability()` in `src/skills/catalog_portable.py` decides
it. Each reviewed row of its table carries its reason as the comment above it,
and a skill the table does not list fails closed as `hermes-only`. To see the
current set, compare the two directories; this page does not list the names,
because such a list goes stale whenever a Hermes-only skill is added.
`tests/test_agent_skills_projection.py` checks that the two trees and that
function agree.

Retired/reference-only ULW surfaces (`ulw-ralph`, `ulw-goal`, `ulw-team`, and
`ulw-process`) and `omh-quality-evidence-loop` remain non-installable here too. A skill mentioned
as a possible next workflow but absent from the installed pack is unavailable,
not authorization to imitate its host-specific behavior.

## Host support matrix

Except for the explicitly observed Claude Code discovery result below, this
is a documentation/source compatibility assessment, not observed skill
selection or execution in six running hosts. The evidence-class column says
what the [host evidence matrix](#host-evidence-matrix) can observe for each
row; it is not an observation on any machine.

**Observed correction, 2026-09-13 (parent Phase B QA):** Claude Code 2.1.270,
launched in a temporary repository with
`claude -p "list ulw-/omh- skills" --model haiku`, returned `NONE` in two
isolated runs with only `.agents/skills/` installed. After adding the
`.claude/skills/` copy, the same prompt discovered `ulw-context`,
`ulw-interview`, `ulw-loop`, and `omh-plan`. This supersedes the earlier
standard-facts assumption that Claude Code scans repo `.agents/skills/`.
It establishes discovery for the reported version and runs, not execution of
every workflow or a guarantee about other versions.

| Host | Repo scan path | User installation | Discovery and caveats | Evidence class |
| --- | --- | --- | --- | --- |
| Claude Code | `.claude/skills/` mirror (observed 2.1.270) | `~/.claude/skills/` mirror | Repo `.agents/skills/` not discovered in two isolated runs; `.claude/skills/` discovery observed | `installed` read by OMH; later stages `probe_unsupported` (a model session lists them; no verified credential-free command) |
| Codex | `.agents/skills/` | `~/.agents/skills/` | Model-selected progressive disclosure; standard-path contract | `installed` read by OMH; later stages `probe_unsupported` (a model session lists them; no verified credential-free command) |
| Cursor | `.agents/skills/` | `~/.agents/skills/` | Standard-path support; user-scope scanning not independently verified | `installed` read by OMH; later stages `probe_unsupported` (no verified credential-free command) |
| opencode | `.agents/skills/` | `~/.agents/skills/` | Permission-gated `skill` tool, implicit nomination; description must be 1-1024 characters | `installed` read by OMH; later stages `probe_unsupported` (a model session lists them; no verified credential-free command) |
| OpenClaw | `.agents/skills/` | `~/.agents/skills/` with default state root | Implicit and `/skill <name>`/`$name`; workspace `skills/` can outrank this pack | `installed` read by OMH; later stages `probe_unsupported` (no verified credential-free command) |
| pi | `.agents/skills/` | `~/.agents/skills/` | Trusted projects only; implicit and `/skill:name`; first duplicate name wins | `installed` read by OMH; later stages `probe_unsupported` (no verified credential-free command) |

OpenClaw **skips `~/.agents/skills/` when `OPENCLAW_STATE_DIR` points elsewhere**.
No extra OpenClaw target is installed in v1. Its injected discovery summary is
shorter than the full description; frontmatter and loaded body remain separate
surfaces. Resolve reference paths from the loaded skill's base directory
(`{baseDir}` where supplied), not a hardcoded home. Host precedence and existing
same-name skills can affect nomination; installation does not settle it.

The renderer enforces 1-1024-character descriptions. If the catalog description
plus its optional trigger/alias tail exceeds that budget, this target drops the
tail; an over-budget base description fails generation. Hermes bytes are pinned
and unchanged.

## Host evidence matrix

Maintainer and operator command, not a normal user step:

```sh
omh quality-evidence agent-skills [--scope repo|user] [--project-root DIR] [--user-home DIR] [--json]
omh quality-evidence agent-skills --receipts earlier-evidence.json [--scope repo|user] [--json]
```

It reports five evidence stages for every row of the host support matrix in
both scopes: `installed`, `discovered`, `nominated`, `loaded`, and `executed`.
No stage is inferred from another. OMH starts no host session and makes no
model call; the only host process the command runs is the version probe
described below.

- **installed** is observed by OMH itself. It reads the host's scan path, repo
  scope under `--project-root` and user scope under `--user-home` (default:
  your home), and compares every file's bytes with its host's pack inventory,
  `agent-skills/.omh-agent-skills-manifest.json` (Claude Code:
  `.claude/agent-skills/.omh-agent-skills-manifest.json`). The read writes nothing and
  runs no host process. `--project-root` defaults to the current directory, as the
  host-selected installers use; an install made without `--host` writes at
  the repository root, so pass that root when running from a subdirectory.
  The outcome carries a closed `reason`: `observed` / `match` when every pack
  file is present and byte-identical, `not_observed` / `absent` when the pack
  is not there, and `hold` with `partial` (files missing), `modified` (files
  differ), `symlink` (a symlink in the scan path, which the installers refuse
  to write through), or `unreadable`. Files beside the pack, including ones a
  newer pack retired, are not checked.
- **discovered, nominated, loaded, executed** stay `not_observed` for every
  host, with that host's `probe_unsupported` reason. OMH has verified no
  credential-free, non-interactive host command that lists the skills a host
  discovered. Claude Code, Codex, and opencode can list them in a model
  session (`claude -p`, `codex exec`, `opencode run`), which needs provider
  credentials, and OMH makes no model call. `probe_unsupported` is not a claim
  that a host cannot discover Agent Skills, nor that no such command exists.
  The 2026-09-13 Claude Code observation above was a manual model-session run,
  not a receipt of this layer.
- **Host version** comes only from the readiness module's approved
  `<cli> --version` probe, for a CLI in that probe's set
  (`version_probed_agent_clis()` in `src/coding/executor_readiness.py`). The
  set is unchanged, but the trigger is wider: this command runs the probe for
  every such CLI on PATH, where readiness ran the runtime-family host CLI only
  for that profile and `opencode` only when no runtime-family host CLI was on
  PATH. Only the version
  token is kept. Any other host is recorded as `no_approved_probe`,
  and a missing binary as `executable_missing`. What a `--version` child writes
  for itself is neither prevented nor observed.

Each `omh_agent_skills_discovery/v1` receipt records the host, scope, operating
system, scan path relative to its root, adapter schema version, transform, the
pack inventory's `source_digest`, the pack `catalog_revision`, the host version
and its status, the version command, `credential_required` (OMH's conservative
assumption that discovery would need credentials, `true` for every host),
`probe_unsupported`, observation timestamps, cleanup (`nothing_created`: OMH
creates nothing), and exactly the five stages in order, each with an outcome,
a reason, and a detail. A receipt this command produces carries no absolute
path and no host output beyond the version token. The parser rejects unknown
or missing fields, values outside each enumeration, a `credential_required`
that is not a JSON boolean, a host version that disagrees with its status, a
version probe for a CLI outside the approved set, missing or reordered stages,
a reason that does not fit its outcome, any stage after `installed` that is
not `not_observed`, and credential-like text. The command builds every receipt
through that parser. The parser does not compare free-text details with the
disk or the descriptor table, so a hand-edited receipt can still claim what no
run observed.

The matrix has one row per host and scope, sorted by host and then scope. A
row's `evidence_class` is `observed_through_<stage>`, `hold`, `not_observed`,
or `no_receipt` (a receipts file without that host and scope). `freshness` is
`current` only when the receipt's `source_digest`, `catalog_revision`, scan
path, operating system, and host version all match now; any mismatch is
`stale`, and a host version not observed on either side is
`version_unverified`. Freshness compares the operating system but does not
identify the machine. With `--receipts`, the command reads no scan path: it
validates an earlier `--json` payload (UTF-8, UTF-16, or UTF-32, as a shell
redirect wrote it) and compares its receipts with the current pack and the
host versions observed now. A receipt that fails validation is an error, never
a row.

Exit status: 0 when every scan path the run had to read was read, whatever it
found; 3 when a scan path could not be read (`unread_scan_paths` names it, and
the matrix is still printed); 2 for an error, such as a `--project-root` or
`--user-home` that is not a directory (refused rather than reported as an
absent pack) or a receipts file that fails validation.

No receipt corpus is checked in. A receipt describes one machine's
installation and host versions at one time, and does not hold for a later host
version or pack.

## Non-portable capabilities

- **`omh_*` RPC tools** such as todo, delegation-route, and run-summary tools
  are not skills. An MCP adapter is feasible for Claude Code, Codex, Cursor,
  opencode, and OpenClaw; pi needs a TypeScript extension (`registerTool`).
  This install implements neither adapter and registers no tools.
- **File-backed memory provider**: Claude Code, Codex, and OpenClaw already
  have native memory, so another provider is largely redundant there. Cursor,
  opencode, and pi have a provider gap. Model-invoked memory tools and
  session-start context injection have different semantics; neither follows
  from installing a memory-related workflow document.
- **TUI/HUD widgets** are genuinely host-specific. Claude Code status-line
  scripts and pi custom UI could support different adapters; Codex's fixed
  status items, opencode's theme/keybind TUI, and Cursor's extension UI are
  not interchangeable widget APIs. No widget is ported here.
- **Chat-wrapper routing** is Hermes-specific. OpenClaw has analogous gateway
  channel routing; other hosts' subagents/tasks do not implement OMH wrapper
  continuity. A portable workflow does not port that control plane.

## Prepared versus observed

`prepared_not_observed` remains the boundary. A plan, skill copy, manifest,
validation pass, or fresh status proves no host selection, tool invocation,
review, CI, or merge. Report execution only from actual host/tool observations.
Host accounting is reported only when observed; otherwise say unavailable.

## Maintainer byte gate

```sh
omh docs agent-skills
omh docs agent-skills --check
# The external validator accepts ONE skill directory, not a collection root.
npx skills-ref validate agent-skills/ulw-work
```

The committed `agent-skills/` tree is generated from the packaged catalog. The
same command regenerates every host adapter file beside it; `--check` checks
every adapter's exact bytes while leaving existing host skill/configuration
files alone. `--output /tmp/stage/agent-skills` stages the tree and its sibling
adapter directories without modifying the checkout.

The gate detects missing, stale, and extra canonical files, including
references and the inventory, missing/stale adapter files, and missing, stale
and extra files in Claude Code's own pack, `.claude/agent-skills/` (with its
own inventory). Catalog host rows
live in `src/skills/host_adapters.py`; `host_adapter_render.py` produces both
scripts and each host's `manifest.json` from those rows alone, with
`transform: copy-only`. No adapter file carries a file digest or path list:
the per-file SHA256s live once per pack, in `agent-skills/.omh-agent-skills-manifest.json`
and, for Claude Code, `.claude/agent-skills/.omh-agent-skills-manifest.json`
(the exact receipts the CLI writes, named by each host manifest's `inventory`
field), so a skill body edit moves that body and its inventory in each pack and
no installer or host `manifest.json`. The installers run from the same checkout as
that inventory, so embedding the hashes in the scripts would verify nothing the
committed, byte-gated inventory does not. Both scripts accept only the exact
layout the producer emits: every line of the `files` block is one
`"<path>": "<sha256>"` row, no row appears anywhere else, and the rows are
sorted and unique. So the rows a script reads are exactly the files the copied
receipt owns for any JSON reader, including `omh install --target agents`, which
deletes owned files a newer pack retired. The scripts refuse a `.` or `..`
segment, a path outside `[A-Za-z0-9._-]` segments and a case-variant duplicate,
and compare the source tree with the listed paths as a set, never by count.
The producer refuses the same paths before writing the inventory. `source_digest`
(recorded by discovery receipts) is SHA256 of the UTF-8, LF-terminated
inventory sorted by relative POSIX path, one `<file-sha256>  <path>` per line,
computed from that inventory's `files`. `.gitattributes` forces LF for
generated Markdown, shell, PowerShell, and JSON, including the inventory, so
Windows `core.autocrlf` cannot invalidate checksums or byte comparisons.

Edit catalog/portable overrides or the appropriate producer, regenerate, and
commit source plus projection together. Never hand-edit adapter outputs,
`skills/*`, or `docs/WORKFLOWS.md` to implement this target.

See [Documentation](README.md), [Direction](DIRECTION.md), and
[Workflow Reference](WORKFLOWS.md) for the original Hermes boundaries.

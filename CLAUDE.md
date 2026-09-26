# CLAUDE.md

Practical Claude Code guidance for this repo. Product direction, delivery
grain, PR report style, evidence boundaries, and commit trailers are defined in
`AGENTS.md` and `docs/DIRECTION.md` — read those first; this file does not
repeat them. `CONTEXT.md` is the glossary for the OMH ↔ Hermes Agent boundary
(which product owns which surface, state root, and TUI); use its terms before
reasoning about anything that touches Hermes Agent.

## What This Repo Is

oh-my-hermes (OMH) is a Hermes-native wrapper orchestration layer: a
deterministic skill catalog, router, and prepared-handoff generator installed
next to Hermes Agent. Core `omh` code makes no LLM, API, or network calls and
never patches Hermes. Pure Python 3.11+, zero runtime dependencies. Two scoped
exceptions. `omh coding fanout dispatch` (explicit opt-in) spawns local agent
CLIs as subprocesses — those CLIs make their own network calls; omh itself
makes none there, and nothing executes without that explicit command. The
`omh_jev_ask` plugin tool is the one place OMH itself opens a connection: it
POSTs typed questions to Jev (TypeSafe, or OpenRouter only with the operator
setting in `<omh_home>/jev/settings.json`) with the user's own key, only when
the user named Jev in that turn and a key resolves. Stdlib only, HTTPS only, a
fixed two-host route table, redirects refused;
`src/plugin_bundle/omh/jev_ask_client.py` is the only network client in
`src/`, pinned by INVARIANT 2's `NETWORK_CLIENT_BRIDGES`. Third-party Jev
plugins are still never called.

## Build & Test

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v   # full suite
PYTHONPATH=tests uv run python -m unittest tests/test_cli.py -v   # one file
uv run python -m compileall -q src tests                          # syntax gate
uv run python -m omh.cli docs workflows --check                   # byte gate
uv run python -m omh.cli docs roles --check                       # byte gate
uv run python -m omh.cli docs claims --check --json               # selected claims
uv run python -m omh.cli docs chain-table --check                 # byte gate
uv run python -m omh.cli docs navigation --check                  # docs structure gate
uv run python -m omh.cli docs skill-shortlist --check             # byte gate
uv run python -m omh.cli docs skill-sources --check               # watch-closure gate
uv run --group lint ruff check src tests                          # static-analysis gate
git diff --check
```

- Always set `PYTHONPATH=tests` for unittest; test helpers live at tests root.
- Run the smallest test that proves your claim, then broaden if the touched
  surface is shared. Full suite before claiming done.
- `uv run --group lint ruff check src tests` installs the pinned Ruff version
  from the `lint` dependency group (declared in `pyproject.toml`) into the
  project's `uv`-managed environment — no globally installed `ruff` needed.
  CI runs the identical command as its own step. The initial rule set is
  Pyflakes (`F`) only, scoped narrow to stay actionable on a ~135k LOC repo;
  see the `[tool.ruff]` block in `pyproject.toml` for the per-file re-export
  exclusions and the deliberately-not-yet-enforced broad-exception
  (`BLE001`) policy, owned by issue #652.
- That broad-exception policy is a gate, not a comment.
  `tests/test_broad_exception_policy.py` re-derives every broad `except` site
  in `src/` from source and fails when one is not classified as either
  intentional (the failure is classified and surfaced) or needing the #637
  treatment (the failure is relabeled as a normal result). Add the verdict in
  that file when you add a broad `except`; do not record hit counts or line
  numbers in prose, they drift.

## Generated Artifacts Map

Source of truth → generated file → regen command → drift gate:

| Source | Generated | Regenerate | Gate |
| --- | --- | --- | --- |
| `src/skills/catalog.py` + `src/skills/render.py` via `builtin_skill_templates()` / `builtin_skill_reference_templates()` | `skills/*/SKILL.md`, `skills/*/references/*.md` | write template `.content` back to `skills/` (short Python loop; no dedicated CLI writer) | tap-skills staleness inside `docs workflows --check` (missing/stale/extra); `tests/test_router_content.py` |
| Same catalog data | `docs/WORKFLOWS.md` | `uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md` | `uv run python -m omh.cli docs workflows --check` |
| Same catalog data | `docs/ROLES.md` | `uv run python -m omh.cli docs roles --output docs/ROLES.md` | `uv run python -m omh.cli docs roles --check` |
| Demo case engine | `examples/use-cases/g1-g10-demo-cards.json` | `uv run python -m omh.cli cases demo --all --json` output | parse-equality in `tests/test_application_cases.py` |
| `capability_family_projection()` in `src/capabilities/families.py` | `src/plugin_bundle/omh/tools/capability_families.json` | `uv run python -m omh.cli docs capability-families` | `uv run python -m omh.cli docs capability-families --check`; dict-parity in `tests/test_plugin_capabilities.py` |
| `src/routing/lexical_shortlist.py` index via `standalone_skill_shortlist_json()` in `src/routing/skill_shortlist_sidecar.py` | `src/plugin_bundle/omh/tools/skill_shortlist.json` | `uv run python -m omh.cli docs skill-shortlist` | `uv run python -m omh.cli docs skill-shortlist --check`; ranking parity in `tests/test_skill_shortlist_sidecar.py` |
| `ulw_inventory_payload()` in `src/skills/catalog.py` via `src/catalogs/ulw_surfaces.py` | marked ULW region of `README.md` | `uv run python -m omh.cli docs ulw-inventory` | `uv run python -m omh.cli docs ulw-inventory --check`; `tests/test_ulw_inventory.py` |
| Same producer | marked ULW region of `site/index.html` | `uv run python -m omh.cli docs ulw-site` | `uv run python -m omh.cli docs ulw-site --check`; i18n parity in `tests/test_ulw_inventory.py` |
| `SHIPPED_MODEL_RECOMMENDATIONS` in `src/coding/model_recommendations.py` via `src/catalogs/model_chain_table.py` | marked chain-table region of `docs/INSTALLATION.md` | `uv run python -m omh.cli docs chain-table` | `uv run python -m omh.cli docs chain-table --check`; round-trip equality in `tests/test_model_chain_table.py` |
| `src/skills/catalog_portable.py` + catalog/render via `agent_skill_templates()` / `agent_skill_reference_templates()` | `agent-skills/*/SKILL.md`, `agent-skills/*/references/*.md` | `uv run python -m omh.cli docs agent-skills` | `uv run python -m omh.cli docs agent-skills --check` |

Rules:

- Never hand-edit `agent-skills/*/SKILL.md` or its references; regenerate the portable target without changing the Hermes projection.
- Never hand-edit `skills/*/SKILL.md`, `docs/WORKFLOWS.md`, `docs/ROLES.md`, the
  demo-cards JSON, or a marked region (ULW in `README.md` / `site/index.html`,
  the shipped chain table in `docs/INSTALLATION.md`). Edit the catalog/render
  source, regenerate, commit both.
- A model generation that leaves or joins a shipped chain needs
  `docs chain-table` rerun; a NEW mixture category also needs a
  `CHAIN_SURFACE_PURPOSES` entry in `src/catalogs/model_chain_table.py`, and a
  new model alias a `MODEL_DISPLAY_LABELS` entry. Both raise with the key to
  add — the public table cannot stay silent about a shipped chain.
- After any catalog or render change, rerun every `--check` gate before commit.
- The gates are byte-exact comparisons. A one-character drift fails CI.

## Code Conventions

- Small explicit Python functions and data structures. No clever string
  parsing. No new dependencies without explicit user approval.
- Routing lives in `src/routing/` (`chat.py` is the main router). Match on
  normalized phrases or token sets via the existing helpers
  (`normalized_phrase`, `routing_tokens`, `contains_cue_phrase`) — do not add
  raw substring checks. Phrase triggers for multi-word intents; token triggers
  only when a single token is unambiguous.
- A multi-word trigger is also scored as its separate tokens, so a phrase
  built from everyday words widens the skill far beyond the phrase. Before
  shipping one, route a sentence that contains the generic word in an
  unrelated sense and compare the score against `origin/main`; if it moved a
  clarify into a dispatch, hold the word back in
  `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` (`src/routing/recommend.py`) so only the
  complete phrase scores, and pin it with a negative case.
- Guard patterns: routing and policy changes ship with negative cases
  alongside positive cases. Adding a trigger without a negative case is
  incomplete. Both corpora live in `src/quality/routing_precision.py` and each
  has a name worth searching for: `ROUTING_PRECISION_CASES` is the
  negative-control corpus and its failure metric is `overroute_count`;
  `ROUTING_INTERVENTION_CASES` is the positive-intervention corpus and its
  failure metric is `missed_intervention_count`. Grepping for "underroute"
  finds nothing — the guard exists under the intervention name.
- Tests are contracts. Many fixtures assert exact counts. When you add a
  routing case, skill, or demo card, update the exact-count assertions in the
  same commit — they are the point, not noise. To find them, grep the current
  value read off `tests/test_routing_precision.py` (or the drift registry in
  `src/maintenance/drift.py`), not a number quoted here; per the rule above,
  counts written into prose drift and then send you looking for a string that
  no longer exists.
- English for code, docs, commits, and PR text — and for all user-facing CLI
  output by default. Localized output (ko/ja/zh) is explicit opt-in via
  `--language` or `OMH_LANG` only; never auto-detect the OS locale. Korean-only
  surfaces shrink the audience to Korean users.

## Workflow Rules

- A report that something is broken is not yet repo work. Measure which fault
  domain owns it first — see Fault domains in `CONTEXT.md` for the four domains
  and the command that proves each. Only one of them produces a PR.
- One user goal → one PR. Do not frame partial slices; see Delivery Grain in
  `AGENTS.md` for the only valid split reasons.
- Branch before the first edit, named by the kind of change, never by the
  executor: `feature/<topic>` for a capability, `fix/<topic>` for a defect,
  `omh/<topic>` for everything else (docs, release, maintenance). See Git And
  Commits in `AGENTS.md`.
- Every commit needs DCO `Signed-off-by:` plus the Lore-style trailers listed
  in `AGENTS.md` (Constraint / Rejected / Confidence / Scope-risk / Directive /
  Tested / Not-tested).
- PR bodies follow the repo template: capability, motivation, boundary-level
  implementation, observed verification, risks. Never a one-line changelog.
- Report only observed evidence. `prepared_not_observed` is never execution,
  review, CI, or merge evidence.
- Never revert or clean up unrelated dirty files; report them instead.
- Reflecting merged changes onto a live machine goes through `omh update`
  (plus a TUI restart), never by hand-copying files into `~/.hermes/plugins/`
  or `~/.hermes/tui-widgets/`. Hand-copied artifacts drift from the install
  manifests and make later updates refuse or require `--force`.

## Common Pitfalls

- Adding a new installable skill involves more than `catalog.py` — awareness
  lane + context card, ack/label/card coverage, and the generated
  capability-family sidecar. Follow `docs/ADDING-A-SKILL.md`; the coverage
  gates fail with paste-ready instructions when a surface is missed.
- Hand-editing a generated `skills/*/SKILL.md` — the change is silently lost on
  regeneration and fails the byte gates. Edit `src/skills/catalog.py` /
  `render.py` instead.
- Expecting a `docs ... --check` gate to notice a skill BODY change. Those are
  drift gates: they compare a producer against its generated file, and a real
  body edit moves both, so all ten stay green. The pinned sha256 per body in
  `tests/fixtures/agent_skills_hermes_digests.json` is what fires, through
  `test_hermes_projection_byte_stable`, and its failure names the bodies that
  moved. Re-derive that fixture in the same commit as the edit, sorted-key,
  and check the named list is the set you meant to change.
- Adding a routing fixture or skill without updating exact-count assertions —
  breaks `tests/test_routing_precision.py`, `tests/test_cli.py`,
  `tests/test_hermes_ux_quality.py`, and `tests/test_release_smoke.py`, plus
  the expected values in `src/maintenance/drift.py`. Grep those five for the
  old count when totals change, and remember each test file pins the totals
  twice: once in the payload assertions and once in the rendered CLI strings
  (`NNN/NNN negative-control cases`, `Interventions: NNN/NNN ...`).
- Resolving a routing-count rebase conflict by picking a side. Those same five
  files conflict whenever main added a case while your branch was open, and
  neither side is right: upstream's baseline moved and your delta still has to
  land on top of it. Keep whichever side carries your reason comments, then
  re-derive every number from the producer rather than doing the arithmetic by
  hand:

  ```py
  from omh.quality.routing_precision import build_routing_precision_demo, routing_precision_errors
  payload = build_routing_precision_demo(source="discord")
  print(payload["summary"])          # case_count, intervention_case_count, total_case_count
  print(routing_precision_errors(payload))  # must be []
  ```

  Confirm with `drift_report()["ok"]` before continuing the rebase. Adjacent
  budgets can fire in the same change and are raised the same way, with the
  reason written at the entry: the per-skill Hangul freeze in
  `tests/test_routing_language_policy.py` and the zero-slack ratchets in
  `src/maintenance/release.py` (the per-request index, schema, and
  `pre_llm_call` limits). `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` and
  `FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT` are ceilings with headroom,
  not ratchets: re-derive them from the producer by the policy written beside
  them, and only when a test says to.
- Advancing `reviewed_ref` in `docs/SKILL-SOURCES.md` without appending the
  closure receipt, or landing the skill change and leaving the row behind.
  `docs skill-sources --check` fails either half by name
  (`closure_receipt_missing`, `closure_checkpoint_missing`) because a row that
  did not move makes the next tracker run re-evaluate a range already reviewed.
  The receipt schema, the reason codes, and the baseline enrolment for rows
  that predate the contract are in the Closure receipts section of
  `docs/SKILL-SOURCES.md`.
- Adding a page under `docs/` and stopping there. `docs navigation --check`
  requires every top-level `docs/*.md` to be reachable from a declared root or
  classified in `src/catalogs/documentation_navigation.py` with a reason and an
  owner; a page that is neither fails, which is the whole point — an accidental
  orphan must not pass as an intentional one. Link it from a page a reader
  actually reaches before reaching for the classification list, and delete the
  classification entry when a page later becomes reachable (a reachable page
  still marked exempt is its own failure).
- Adding a module-level `omh.*` import to a file under `src/plugin_bundle/omh/`.
  Hermes loads that directory with its own interpreter, which has no reason to
  have the `omh` package on its path; its memory-provider loader also execs
  every top-level file eagerly and keeps the half-initialized module in
  `sys.modules` when one raises. The next lazy import of that module then fails
  on the NAME, with an `ImportError` carrying the bundle's own dotted path
  rather than `omh`, so a guard written for `ModuleNotFoundError` with an
  `omh`-prefixed name check re-raises it — on every tool call (#1623). Either
  vendor what the module needs into the bundle, or guard the import and report
  the absence at the feature's own entry point.
  `tests/test_plugin_bundle_standalone.py` imports every module in that
  directory with `omh` blocked and derives its subject from the directory, so a
  new module joins the gate without anyone listing it.
- Grepping the repo and matching stale strings under `build/lib/` — it is a
  gitignored copy of old sources. Scope searches to `src/`, `tests/`, `docs/`,
  `skills/`.
- Letting an exit code report success over work that failed. On 2026-09-11
  every unit of a dispatch failed on a provider session limit and
  `omh coding fanout dispatch` exited `0`, so a wrapper reading only the status
  was told the batch succeeded. The mapper had a case for a refusal, with a
  docstring saying a shell that only checks the status must not read "nothing
  was dispatched" as success — the sentence was right and had been applied to
  only one of the ways work fails to happen.
  `tests/test_exit_code_truthfulness_policy.py` now re-derives every
  `*_exit_code` mapper under `src/commands/` and fails when one maps a summary
  carrying a failure signal to `0`. It says nothing about which code to return,
  so a new command keeps its own vocabulary and its own recoverable lane; it
  only may not call failure success.
- Matching a provider's refusal by wording alone. The limit-shape patterns in
  `src/coding/fanout_dispatch.py` are how a failure becomes recoverable rather
  than terminal, and the same day the exit code lied, `You've hit your session
  limit` matched none of the twelve patterns and classified as `crash` — a
  condition that clears at a stated time, recorded as a permanent fault. When a
  provider adds a phrasing, add the pattern and a verbatim regression case; when
  you add a pattern, check it against ordinary narration in the same commit, the
  way the existing anchors are deliberately multi-word.
- Trusting a red run before clearing `build/`. A `ModuleNotFoundError` whose
  traceback names a `build/__editable__…` path is the gitignored editable
  install, not the tree you are editing: your venv's copy predates a module the
  branch now has. It is not a real failure and it is not the other branch's
  regression. Clear it before you diagnose anything:

  ```sh
  rm -rf build && find src tests -name __pycache__ -prune -exec rm -rf {} + \
    && uv sync --reinstall-package oh-my-hermes
  ```

  This is worth its own entry because of how it lies. Bisecting across the
  commit that adds the module produces green-then-red — the exact shape of a
  genuine regression — since before that commit the stale copy is adequate and
  after it the import fails. It cost several agents hours in one afternoon and
  produced one false attribution of a defect to another contributor's branch.
  If a checkout ever aborts with "local changes would be overwritten", stop:
  every run after that measured the same dirty tree. `git reset --hard &&
  git clean -fdx` first, then re-measure.

  Why it is always a *missing module* and never a stale edit: `pyproject.toml`
  sets `[tool.uv] config-settings = { editable_mode = "strict" }`, so **uv**
  builds the editable install as a tree of per-file symlinks under `build/`
  (hard links where the filesystem has no symlinks). Every file that existed at
  build time has a link and resolves live, so edits in place are seen; a file
  ADDED afterward has no link and does not exist for the install at all. The
  granularity that matters: a new module inside an existing package is
  invisible, because `build/.../omh/<pkg>/` is a real directory of per-file
  links. A new top-level directory under `src/` can still resolve, because
  `build/.../omh/__init__.py` appends `src/` to `__path__`.

  It does not heal on its own. uv does not revalidate on ordinary `uv run` or
  `uv sync` — the missing-link state persists until
  `uv sync --reinstall-package oh-my-hermes`, or until something invalidates
  uv's build cache, such as a change to `pyproject.toml`'s mtime. So the
  ordering that produces the false red is resyncing *before* writing the
  branch's new source files rather than after: resync last, after the final new
  file exists. Short of the two triggers above, nothing else heals it at all.

  This is a property of the uv-managed dev environment, not of the project. The
  three test-bearing jobs (`plan`, `test`, `test-windows`)
  install with `python -m pip install -e .`, which ignores `[tool.uv]` and uses
  setuptools' default path-hook editable mode — no `build/` tree. Where a job
  does call `uv run` (the ruff gate in `test`, the packaging steps in
  `distribution`) the strict tree is built, but each job checks out fresh and
  installs after checking out (`aggregate` installs nothing at all), so no tree
  in CI is ever older than its source. CI cannot reach the stale state and so
  cannot warn you about it.

  What makes it read as a real regression is who resolves what. A `-P` spawn —
  or any run launched from outside the checkout, including the `omh` console
  script — reads the installed generation, while `uv run python -m omh.cli docs
  … --check` from inside the checkout resolves through the repo-root `omh/`
  shim to your working tree and passes at the same moment. So every gate is
  green and exactly one test is red. The canary is
  `tests/test_agent_board_kanban` — case K7 in `tests/five_issue_cases/kanban.py`
  spawns three docs gates through `-P -m omh.cli` with `UV_NO_SYNC=1` in the
  child's environment, so it cannot self-heal and reads whatever sits in
  `build/` at that moment. Run that one file before reporting any isolated
  failure as pre-existing or as another branch's; if it is red, clear, resync,
  and re-measure, because the earlier run is not evidence. It is a strong
  heuristic and not a proof: importing `omh.cli` pulls in most of `src/` but
  not all of it, so a new module nothing on the docs path imports will not fire
  it.

  Clear `__pycache__` in the same breath, as the command above does. A cached
  entry is validated by source mtime at one-second granularity plus size, so an
  edit that is length-identical AND lands in the same second as the last
  compile is not detected; a later edit is. It costs nothing and removes the
  question.
- Concluding a platform fact settles a call site. Windows and POSIX differ in
  ways this repo keeps rediscovering — `Path.write_text` without `newline=`
  emits CRLF; a child process's stdout arrives CRLF-terminated; CR is a control
  character to a text guard; and Windows will not unlink a file another thread
  still holds open, so a leaked worker turns a test failure into a failure plus
  a cleanup error. Each of those is true, and none of them is a conclusion on
  its own. One prediction here reasoned correctly that `os.open` without
  `O_BINARY` returns a text-mode descriptor, and missed that the next line's
  `os.fdopen(fd, 'rb')` re-sets the descriptor to binary before a byte is read.
  Trace the composition to the end, or say the claim is untested.
- Letting a best-effort `except OSError` decide what a failure was. The swallow
  in `append_sidecar_line` is deliberate — the sidecar is the record of last
  resort and must not raise — but it covers every step under it, and
  `FileLockTimeout` is a `TimeoutError`, hence an `OSError` too. So "the write
  failed", "the lock timed out" and "Windows denied the chmod while another
  waiter held the file open" all leave one trace: a line missing and nothing
  raised. The barrier test above it then reports `13 != 16`, which is exactly
  what a lock that failed to hold would report, and the Windows run that
  produced it is over. Two rules follow. A swallow is only as good as what
  still records the failure, so widen the *report*, not the `except`. And when
  a guard can fail two ways, put the discriminator in the assertion message —
  here, whether any surviving line failed to parse, since only an interleave
  splices one. A count is not a diagnosis.
- Regenerating docs but forgetting the demo cards (or vice versa) when catalog
  data changes — the parse-equality test catches it late; regenerate all four
  artifact families together.
- Dropping `PYTHONPATH=tests` — imports of `_cli_harness` and friends fail with
  confusing errors.
- Spawning `python -m omh.cli` (or `-c "import omh.cli"`) without `-P` — the
  repo root ships a top-level `omh/` shim, so a run launched from inside a
  checkout imports the checkout instead of the installed generation.
  `tests/test_interpreter_spawn_policy.py` re-derives every such spawn from
  `src/` and fails on one that lacks `-P`; route new spawns through
  `_omh_cli()` in `src/install/self_update.py` or add `-P` yourself.
- Making Codex the implicit default owner in wording, schemas, or reports —
  keep Codex, Claude Code, Hermes runtime, and generic executors
  executor-neutral (`AGENTS.md`, Implementation Boundaries).
- Reading Maestro/handoff surfaces (`src/coding/maestro/`, executor capability
  snapshots, prompting contracts, throughput overlays) as the default coding
  path — they activate only after an explicit coding-owner choice. The default
  and normal path is the Hermes harness; `CONTEXT.md` (Coding delegation) and
  `src/coding/orchestration_vocabulary.py` pin the two lanes.

## Working Style

- State assumptions before editing; if the contract is unclear, ask.
- Minimum code that solves the goal. No speculative options, flags, or hooks.
- Touch only what the goal requires; match surrounding style exactly.
- Define the verifying command before coding; loop until it passes, then run
  the byte gates and full suite as the final proof.

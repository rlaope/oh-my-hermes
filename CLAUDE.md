# CLAUDE.md

The engineering manual for this repo: commands, gates, generated artifacts,
and the pitfalls that have cost real time. It applies to every executor
(Codex, Claude Code, Hermes handoffs, generic profiles), not only Claude Code.
`AGENTS.md` is the operating contract (product boundaries, delivery grain, PR
reports, commit trailers); read it first. `CONTEXT.md` is the glossary for the
OMH ↔ Hermes Agent boundary; use its terms before reasoning about anything
that touches Hermes. `docs/DIRECTION.md` is product direction.

## What This Repo Is

oh-my-hermes (OMH) is a Hermes-native wrapper orchestration layer: a
deterministic skill catalog, router, and prepared-handoff generator installed
next to Hermes Agent. Pure Python 3.11+, zero runtime dependencies. Core `omh`
makes no LLM, API, or network call and never patches Hermes. The scoped
exceptions, stated in full under Implementation Boundaries in `AGENTS.md` and
held by the invariants in `tests/test_handoff_safety_contract_enforcement.py`:

- `omh coding fanout dispatch` (and its `omh coding run` entry): explicit
  opt-in; spawns local agent CLIs, which make their own network calls. Nothing
  runs without that command.
- `omh_jev_ask`: POSTs typed questions to Jev with the user's own key, only
  when the user named Jev in that turn and a key resolves (TypeSafe, or
  OpenRouter only with the operator setting in `<omh_home>/jev/settings.json`).
  Stdlib, HTTPS only, a fixed two-host route table, redirects refused.
  `src/plugin_bundle/omh/jev_ask_client.py` is the only in-process network
  client in `src/`, pinned by INVARIANT 2's `NETWORK_CLIENT_BRIDGES`.
  Third-party Jev plugins are never called.
- The `show-reel` toolkit scripts `toolkit/scripts/eleven.py`, `narrate.py`
  (ElevenLabs, by spawning `curl` with the key on stdin) and
  `codex_ref_image.sh` (the user's codex CLI): package data the user runs with
  their own `ELEVENLABS_API_KEY` or codex login. OMH never imports or runs
  them; without the credential they exit 2. `eleven.py` is in INVARIANT 1's
  `PROCESS_SPAWN_ALLOWLIST`.
- The OMH TUI's gateway child, `src/tui/attach/gateway_attach.py`: not core.
  It runs only on Hermes' interpreter, spawned by path, imported by nothing in
  `src/`, and reaches the person's own gateway over loopback as Hermes' Ink TUI
  does. INVARIANT 2's `HERMES_INTERPRETER_SCRIPTS` holds it to a closed allow
  list of imports, names and name flows measured from the script. It is not a
  sandbox: an allowed Hermes function called with other arguments, and where
  the grant's url points, are beyond it.

## Build & Test

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v   # full suite
PYTHONPATH=tests uv run python -m unittest tests/test_cli.py -v   # one file
uv run python -m compileall -q src tests                          # syntax gate
uv run python -m omh.cli docs workflows --check                   # byte gate
uv run python -m omh.cli docs roles --check                       # byte gate
uv run python -m omh.cli docs agent-skills --check                # byte gate
uv run python -m omh.cli docs capability-families --check         # byte gate
uv run python -m omh.cli docs skill-shortlist --check             # byte gate
uv run python -m omh.cli docs ulw-inventory --check               # byte gate
uv run python -m omh.cli docs ulw-site --check                    # byte gate
uv run python -m omh.cli docs chain-table --check                 # byte gate
uv run python -m omh.cli docs navigation --check                  # docs structure gate
uv run python -m omh.cli docs skill-sources --check               # watch-closure gate
uv run python -m omh.cli docs claims --check --json               # selected claims (local only)
uv run python tools/render_skill_pack.py --check                  # tap pack (unit tests in CI)
uv run --group lint ruff check src tests tools packaging          # static analysis, as CI runs it
git diff --check origin/main...HEAD                               # whitespace, as CI runs it
```

- Always set `PYTHONPATH=tests` for unittest; shared helpers (`_cli_harness`
  and friends) live at the tests root and fail to import with confusing
  errors without it.
- Run the smallest test that proves the claim, broaden when the touched
  surface is shared, and run the full suite before claiming done.
- Ruff installs from the `lint` group in `pyproject.toml`; no global `ruff`.
  The rule set is Pyflakes (`F`) only; `[tool.ruff]` holds the per-file
  re-export exclusions.
- The broad-exception (`BLE001`) policy is a gate, not a comment, owned by
  issue #652. `tests/test_broad_exception_policy.py` re-derives every broad
  `except` in `src/` and fails when one is not classified as intentional (the
  failure is classified and surfaced) or as needing the #637 treatment (the
  failure is relabeled as a normal result). Add the verdict there when you add
  a broad `except`.

## Generated Artifacts Map

Never hand-edit a generated file or marked region. Edit the source,
regenerate, and commit source and output together. Every gate is byte-exact:
one character of drift fails CI. After any catalog or render change, rerun
every gate above, and regenerate every family in this table that reads the
changed source.

| Source | Generated | Regenerate | Gate |
| --- | --- | --- | --- |
| `src/skills/skill_record.py` (`SkillRecord` over the catalog/render producers) plus the closed `builtin_skill_support_templates()` inventory and canonical toolkit resources | `skills/*/SKILL.md`, `skills/*/references/*.md`, declared `skills/omh-*/toolkit/**` | `uv run python tools/render_skill_pack.py --write` | `tools/render_skill_pack.py --check`; tap-skills byte gate in `docs workflows --check` |
| Canonical show-reel toolkit resources + `provenance_manifest()` | `src/skills/show_reel_toolkit/upstream-manifest.json` (self-hash excluded) | `uv run python tools/render_skill_pack.py --write --refresh-provenance` (show-reel only; the domain toolkits' provenance is producer-validated) | producer digest validation and the support/distribution tests |
| Same catalog data | `docs/WORKFLOWS.md` | `uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md` | `docs workflows --check` |
| `roles_reference_markdown()` in `src/catalogs/roles.py` | `docs/ROLES.md` | `uv run python -m omh.cli docs roles --output docs/ROLES.md` | `docs roles --check` |
| `agent_skill_files()` / `agent_skills_manifest()` over the catalog, portable and reviewed support producers | `agent-skills/**`, `agent-skills/.omh-agent-skills-manifest.json`, the host adapters (`manifest.json` and installers under `.claude/`, `.codex/`, `.cursor/` and the other host directories) | `uv run python -m omh.cli docs agent-skills` | `docs agent-skills --check`; never copy digest maps into an adapter |
| Demo case engine | `examples/use-cases/g1-g10-demo-cards.json` | `uv run python -m omh.cli cases demo --all --json` output | parse-equality in `tests/test_application_cases.py` |
| `capability_family_projection()` in `src/capabilities/families.py` | `src/plugin_bundle/omh/tools/capability_families.json` | `uv run python -m omh.cli docs capability-families` | `docs capability-families --check`; dict parity in `tests/test_plugin_capabilities.py` |
| `src/routing/lexical_shortlist.py` via `standalone_skill_shortlist_json()` in `src/routing/skill_shortlist_sidecar.py` | `src/plugin_bundle/omh/tools/skill_shortlist.json` | `uv run python -m omh.cli docs skill-shortlist` | `docs skill-shortlist --check`; ranking parity in `tests/test_skill_shortlist_sidecar.py` |
| `ulw_inventory_payload()` in `src/skills/catalog.py` via `src/catalogs/ulw_surfaces.py` | marked ULW region of `README.md` | `uv run python -m omh.cli docs ulw-inventory` | `docs ulw-inventory --check`; `tests/test_ulw_inventory.py` |
| Same producer | marked ULW region of `site/index.html` | `uv run python -m omh.cli docs ulw-site` | `docs ulw-site --check`; i18n parity in `tests/test_ulw_inventory.py` |
| `SHIPPED_MODEL_RECOMMENDATIONS` in `src/coding/model_recommendations.py` via `src/catalogs/model_chain_table.py` | marked chain-table region of `docs/INSTALLATION.md` (the public chain table; the READMEs link to it) | `uv run python -m omh.cli docs chain-table` | `docs chain-table --check`; round-trip equality in `tests/test_model_chain_table.py` |

- A skill's read path is `skill_record(name)`; new per-skill metadata is a
  field on the record, not a new module.
- A model that joins or leaves a shipped chain needs `docs chain-table`
  rerun. A new mixture category also needs a `CHAIN_SURFACE_PURPOSES` entry
  in `src/catalogs/model_chain_table.py`, and a new alias a
  `MODEL_DISPLAY_LABELS` entry; the renderer raises with the key to add. The
  hand-maintained chain rows in `site/index.html` and
  `site/docs/model-routing/index.html` move too (`docs/MODEL-ONBOARDING.md`,
  `/model-onboarding`).
- The drift gates do not notice a skill BODY change: a real edit moves the
  producer and its output together, so every gate stays green. What fires is
  the pinned sha256 per body in
  `tests/fixtures/agent_skills_hermes_digests.json`, through
  `test_hermes_projection_byte_stable`, which names the bodies that moved.
  Re-derive that fixture in the same commit, sorted-key, and check the named
  list is the set you meant to change.

## Code Conventions

- Small explicit Python functions and data structures. No clever string
  parsing. No new dependency without the user's explicit approval.
- Routing lives in `src/routing/` (`chat.py` is the main router). Match on
  normalized phrases or token sets through `normalized_phrase`,
  `routing_tokens` and `contains_cue_phrase`, never raw substring checks.
  Phrase triggers for multi-word intents; a token trigger only when the token
  alone is unambiguous.
- A multi-word trigger is also scored as its separate tokens, so a phrase
  built from everyday words widens the skill far beyond the phrase. Before
  shipping one, route a sentence that uses the generic word in an unrelated
  sense and compare the score against `origin/main`. If it moved a clarify
  into a dispatch, hold the word in `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS`
  (`src/routing/recommend.py`) and pin it with a negative case.
- Routing and policy changes ship negative cases beside positive ones; a
  trigger without a negative case is incomplete. Both corpora live in
  `src/quality/routing_precision.py`: `ROUTING_PRECISION_CASES` (negative
  controls, failure metric `overroute_count`) and `ROUTING_INTERVENTION_CASES`
  (positive interventions, failure metric `missed_intervention_count`).
  Searching for "underroute" finds nothing.
- Tests are contracts. The routing corpus totals have reviewed pins in two
  places only, updated in the commit that adds a case: the two `expected=`
  values in `src/maintenance/drift.py` (each with its reason history) and the
  `case_count` / `intervention_case_count` literals at the top of
  `tests/test_routing_precision.py`. `omh release drift` names the pins that
  moved. Every other test compares against `build_routing_precision_demo()`
  and needs no edit. The literal counts `count_metrics()` in
  `src/maintenance/drift.py` registers list every site that hardcodes each
  one; a new skill moves those. Never quote a count, line number or hit count
  in prose: it drifts and sends the next reader after a string that no
  longer exists.

## Workflow Rules

Delivery grain, branch names, commit trailers, PR bodies and evidence
language are in `AGENTS.md`. Two rules live here:

- A report that something is broken is not yet repo work. Measure which fault
  domain owns it first (Fault domains in `CONTEXT.md` names the four and the
  command that proves each); only the OMH product fault produces a PR.
- Merged changes reach a live machine only through `omh update` (plus a TUI
  restart), never by hand-copying into `~/.hermes/plugins/` or other host
  roots. Hand-copied files drift from the install manifests and make later
  updates refuse or need `--force`.

## Common Pitfalls

- **A new skill is more than `catalog.py`**: awareness lane and context card,
  ack/label/card coverage, and the capability-family sidecar. Follow
  `docs/ADDING-A-SKILL.md`; the coverage gates fail with paste-ready
  instructions when a surface is missed.
- **A routing-count rebase conflict is never resolved by picking a side.**
  Upstream's baseline moved and your delta lands on top of it. Keep the side
  carrying your reason comments, then re-derive every number from the
  producer:

  ```py
  from omh.quality.routing_precision import build_routing_precision_demo, routing_precision_errors
  payload = build_routing_precision_demo(source="discord")
  print(payload["summary"])          # case_count, intervention_case_count, total_case_count
  print(routing_precision_errors(payload))  # must be []
  ```

  Confirm `drift_report()["ok"]` before continuing. Adjacent budgets fire the
  same way and are raised with the reason written at the entry: the per-skill
  Hangul freeze in `tests/test_routing_language_policy.py` and the zero-slack
  ratchets in `src/maintenance/release.py` (per-request index, schema,
  `pre_llm_call`). `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` and
  `FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT` are ceilings with headroom,
  not ratchets: re-derive them by the policy written beside them, only when a
  test says to.
- **`reviewed_ref` in `docs/SKILL-SOURCES.md` moves with its closure
  receipt.** `docs skill-sources --check` fails either half by name
  (`closure_receipt_missing`, `closure_checkpoint_missing`), because a row
  that did not move makes the next tracker run re-review the same range. The
  schema and reason codes are in its Closure receipts section.
- **A new `docs/*.md` page must be reachable.** `docs navigation --check`
  requires every top-level page to be linked from a declared root or
  classified in `src/catalogs/documentation_navigation.py` with a reason and
  an owner. Link it from a page readers reach first; delete the
  classification when a page becomes reachable (reachable and exempt is its
  own failure).
- **No module-level `omh.*` import under `src/plugin_bundle/omh/`.** Hermes
  loads that directory on its own interpreter, where `omh` may be absent, and
  its memory-provider loader execs every top-level file and keeps a
  half-initialized module in `sys.modules`. The next import then fails on the
  NAME, with an `ImportError` carrying the bundle's dotted path, which a
  `ModuleNotFoundError` guard checking for an `omh` prefix re-raises on every
  tool call (#1623). Vendor what the module needs, or guard the import and
  report the absence at the feature's entry point.
  `tests/test_plugin_bundle_standalone.py` imports every module there with
  `omh` blocked.
- **Spawn `python -m omh.cli` (or `-c "import omh.cli"`) with `-P`.** The repo
  root ships an `omh/` shim, so a spawn from inside a checkout imports the
  checkout instead of the installed generation.
  `tests/test_interpreter_spawn_policy.py` fails on a spawn in `src/` without
  it; route new spawns through `_omh_cli()` in `src/install/self_update.py`.
- **An exit code may not call failure success.** A dispatch whose every unit
  failed on a provider limit once exited `0`.
  `tests/test_exit_code_truthfulness_policy.py` re-derives every
  `*_exit_code` mapper under `src/commands/` and fails when one maps a summary
  carrying a failure signal to `0`. Which nonzero code is the command's own
  choice.
- **A provider refusal is matched by shape, checked against narration.** The
  limit patterns in `src/coding/fanout_dispatch.py` decide whether a failure
  is recoverable or a permanent `crash`; a new phrasing (`You've hit your
  session limit`) once fell through to `crash`. Add the pattern with a
  verbatim regression case, and check it against ordinary narration in the
  same commit; the anchors are deliberately multi-word.
- **Clear `build/` before trusting a red run.** A `ModuleNotFoundError` whose
  traceback names `build/__editable__…` is the gitignored editable install,
  not your tree, and not another branch's regression:

  ```sh
  rm -rf build && find src tests -name __pycache__ -prune -exec rm -rf {} + \
    && uv sync --reinstall-package oh-my-hermes
  ```

  Why it lies: `pyproject.toml` sets `[tool.uv] config-settings = {
  editable_mode = "strict" }`, so uv builds the install as per-file links
  under `build/`. Edits to existing files resolve live; a module ADDED after
  the build has no link and does not exist for the install (a new top-level
  directory under `src/` can still resolve through `__path__`). It never heals
  on ordinary `uv run` / `uv sync`, so resync after the branch's last new file
  exists, not before. Bisecting across the commit that adds a module then
  shows green-then-red, the exact shape of a real regression. CI cannot reach
  this state (its test jobs `pip install -e .` on a fresh checkout), so it
  cannot warn you. A `-P` spawn or the `omh` console script reads the
  installed generation while in-checkout `uv run … docs --check` reads your
  tree, so every gate is green and one test is red. The canary is
  `tests/test_agent_board_kanban` (case K7 spawns docs gates through `-P`
  with `UV_NO_SYNC=1`): run it before calling any isolated failure
  pre-existing or someone else's, and if it is red, clear, resync and
  re-measure. It is a heuristic, not a proof: a module nothing on the docs
  path imports will not fire it. Clear `__pycache__` too: a cached entry is
  validated by mtime at one-second granularity plus size. If a checkout ever
  aborts with "local changes would be overwritten", stop: `git reset --hard
  && git clean -fdx`, then re-measure, because every run since measured the
  same dirty tree.
- **`build/lib/` is a gitignored copy of old sources.** Scope searches to
  `src/`, `tests/`, `docs/`, `skills/`.
- **A platform fact does not settle a call site.** Windows and POSIX differ in
  ways this repo keeps rediscovering: `Path.write_text` without `newline=`
  emits CRLF; a child's stdout arrives CRLF-terminated; CR is a control
  character to a text guard; Windows will not unlink a file another thread
  holds open, so a leaked worker turns one failure into a failure plus a
  cleanup error; Windows reports `0o666` for a file chmod'ed `0o600`. Trace
  the composition to the end (`os.open` without `O_BINARY` is text mode, and
  the next line's `os.fdopen(fd, 'rb')` makes it binary again), or say the
  claim is untested.
- **A best-effort `except OSError` hides which failure it swallowed.**
  `append_sidecar_line` must not raise, but its swallow covers every step,
  and `FileLockTimeout` is a `TimeoutError`, hence an `OSError`: a failed
  write, a lock timeout and a Windows chmod denial all leave one trace, a
  missing line. Widen the report, not the `except`. When a guard can fail two
  ways, put the discriminator in the assertion message (here, whether a
  surviving line failed to parse, which only an interleave produces). A count
  is not a diagnosis.
- **Coding ownership stays executor-neutral.** Never make Codex the implicit
  default owner in wording, schemas or reports (`AGENTS.md`, Implementation
  Boundaries). Maestro and handoff surfaces (`src/coding/maestro/`, executor
  capability snapshots, prompting contracts, throughput overlays) activate
  only after an explicit coding-owner choice; the default coding path is the
  Hermes harness (`CONTEXT.md`, Coding delegation;
  `src/coding/orchestration_vocabulary.py`).

## Working Style

- State assumptions before editing; if the contract is unclear, ask.
- Minimum code that solves the goal; touch only what it requires and match
  the surrounding style.
- Define the verifying command before coding, loop until it passes, then run
  the gates and the full suite as the final proof.

# CLAUDE.md

This file is the engineering manual for every executor on this repo (Codex,
Claude Code, Hermes handoffs, generic profiles): commands, gates, the
generated-artifact map, and one line per costly pitfall. `AGENTS.md` holds the
operating contract (product boundaries, delivery grain, PR reports, commit
trailers); read it first. `CONTEXT.md` is the glossary for the OMH ↔ Hermes
Agent boundary. Long forms: `docs/ENGINEERING-PITFALLS.md`,
`docs/IMPLEMENTATION-BOUNDARIES.md`.

## What This Repo Is

oh-my-hermes (OMH) is a Hermes-native wrapper orchestration layer: a
deterministic skill catalog, router, and prepared-handoff generator installed
next to Hermes Agent. Pure Python 3.11+, zero runtime dependencies. Core `omh`
makes no LLM, API, or network call and never patches Hermes. Every scoped
exception (fanout dispatch, `omh_jev_ask`, the TUI update notice and gateway
child, the local proofreader, the show-reel and channel-watch scripts, omher)
is stated in `docs/IMPLEMENTATION-BOUNDARIES.md`, summarized in `AGENTS.md`,
and held by the invariants in `tests/test_handoff_safety_contract_enforcement.py`.
omher (`apps/omher/`) has its own toolchain, CI and rules: `apps/omher/README.md`
(Develop, Release, Repository rules); a PR touching both runs both checks.

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
- A broad `except` in `src/` needs its verdict in
  `tests/test_broad_exception_policy.py` (policy owned by issue #652).

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
| `skills/*/SKILL.md` (minus `ulw-*` and `dag-ulw`) via `tools/render_site_skills.py` | `site/docs/skills/index.html` (the public skill guide; Pages re-renders it on every deploy) | `uv run python tools/render_site_skills.py --write` | `tools/render_site_skills.py --check`; `tests/test_site_skills_guide.py` |
| `src/coding/model_recommendations.py` (three categories) via `tools/render_site_guide.py` | `site/guide/index.html` region `omh:guide-chains` (the Start Guide's model lists; Pages re-renders it on every deploy) | `uv run python tools/render_site_guide.py --write` | `tools/render_site_guide.py --check`; `tests/test_site_guide.py` |
| `SHIPPED_MODEL_RECOMMENDATIONS` in `src/coding/model_recommendations.py` via `src/catalogs/model_chain_table.py` | marked chain-table region of `docs/INSTALLATION.md` (the public chain table; the READMEs link to it) | `uv run python -m omh.cli docs chain-table` | `docs chain-table --check`; round-trip equality in `tests/test_model_chain_table.py` |

- A skill's read path is `skill_record(name)`; new per-skill metadata is a
  field on the record, not a new module.
- The drift gates do not notice a skill BODY change; the pinned sha256 per
  body in `tests/fixtures/agent_skills_hermes_digests.json` does
  (`test_hermes_projection_byte_stable`). Re-derive it in the same commit.

## Code Conventions

- Small explicit Python functions and data structures. No clever string
  parsing.
- Routing lives in `src/routing/` (`chat.py` is the main router). Match on
  normalized phrases or token sets through `normalized_phrase`,
  `routing_tokens` and `contains_cue_phrase`, never raw substring checks.
- Routing and policy changes ship negative cases beside positive ones, in
  `src/quality/routing_precision.py` (`ROUTING_PRECISION_CASES`,
  `ROUTING_INTERVENTION_CASES`), and move the reviewed count pins in the same
  commit (`src/maintenance/drift.py`, `tests/test_routing_precision.py`;
  `omh release drift` names them). Never quote a count or line number in prose.

## Workflow Rules

- A report that something is broken is not yet repo work. Measure which fault
  domain owns it first (Fault domains in `CONTEXT.md`); only the OMH product
  fault produces a PR.
- Merged changes reach a live machine only through `omh update` (plus a TUI
  restart), never by hand-copying into `~/.hermes/plugins/` or other host
  roots.

## Common Pitfalls

Each has a long form in `docs/ENGINEERING-PITFALLS.md`; read it before working
around the gate named here.

- A new skill touches more than `catalog.py`: follow `docs/ADDING-A-SKILL.md`.
- A routing-count rebase conflict is re-derived from the producer, never
  resolved by picking a side.
- A new `docs/*.md` page must be reachable (`docs navigation --check`).
- No module-level `omh.*` import under `src/plugin_bundle/omh/`
  (`tests/test_plugin_bundle_standalone.py`).
- Spawn `python -m omh.cli` with `-P` (`tests/test_interpreter_spawn_policy.py`).
- A red run naming `build/__editable__…` is a stale editable install: clear
  `build/` and `__pycache__`, then `uv sync --reinstall-package oh-my-hermes`;
  `tests/test_agent_board_kanban` is the canary. `build/lib/` is old sources.
- Windows and POSIX differ (CRLF, chmod modes, open-file unlink); trace the
  composition or say the claim is untested.
- Coding ownership stays executor-neutral: never make Codex the implicit
  default owner.

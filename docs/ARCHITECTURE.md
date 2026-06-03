# Architecture

## Goals

oh-my-hermes-agent should feel like a native Hermes workflow layer, not a pile
of copied prompt files.

The architecture favors:

- a small command interface
- reversible local installation
- generated skill text from testable catalog data
- explicit compatibility contracts
- conservative routing behavior

## Package Layout

```text
src/
  cli.py
  config_adapter.py
  converter.py
  doctor.py
  installer.py
  manifest.py
  paths.py
  snippet.py
  skill_pack.py
  core/
  skills/
```

## Main Modules

`cli.py` owns command parsing and user-facing JSON output.

`installer.py` owns managed skill writes, manifest updates, update behavior, and
uninstall behavior.

`config_adapter.py` owns the Hermes config edit boundary. It should remain
small, heavily tested, and conservative.

`skills/catalog.py` owns workflow names, descriptions, trigger phrases, and
use-when rules as data.

`skills/render.py` owns generated `SKILL.md` content. It should render from the
catalog rather than becoming a second source of truth.

`skill_pack.py` is a compatibility facade so older imports keep working while
the package grows internally.

## Routing

Routing is prompt-level guidance. The router skill gives Hermes a structured map
of workflow names and strong trigger phrases, but it does not override Hermes
core behavior.

Future routing work should deepen the catalog first, then render richer skill
metadata from it.

## Safety Model

- Managed files are tracked by manifest hashes.
- Local modifications block updates unless `--force` is supplied.
- Config registration is isolated to `skills.external_dirs`.
- Workspace guidance is printed by `omh snippet`; it is not applied by default.

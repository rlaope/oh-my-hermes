# oh-my-hermes-agent

`oh-my-hermes-agent` installs Hermes-compatible adaptations of OMX / oh-my-codex skills.

The `omh` command does not patch Hermes Agent by default. It writes an adapted skill pack to `~/.omh/skills` and adds that directory to Hermes' `skills.external_dirs` setting, so Hermes can discover the skills through its existing `/skills`, `skills_list`, and `skill_view` surfaces.

## Install

From this repository:

```sh
python -m pip install -e .
omh install
omh apply
omh doctor
```

Useful commands:

```sh
omh install --dry-run
omh install --from-codex ~/.codex/skills
omh update --from-codex ~/.codex/skills
omh apply --dry-run
omh list
omh snippet --dry-run
omh uninstall
```

## What Gets Installed

The built-in pack includes:

- `oh-my-hermes`
- `ralph`
- `ultragoal`
- `deep-interview`
- `team`
- `ultraqa`
- `plan`
- `ralplan`
- `code-review`
- `ai-slop-cleaner`
- `best-practice-research`
- `autoresearch-goal`
- `performance-goal`
- utility skills such as `wiki`, `ask`, `cancel`, `skill`, and `doctor`

Each workflow skill includes a Hermes Compatibility Contract. Codex-only mechanisms such as native Codex goal tools, tmux `omx question`, and Codex role prompts are translated to Hermes-native fallbacks instead of being required unconditionally.

## Routing Contract

The router skill is best-effort prompt guidance. It does not override Hermes core behavior and it does not guarantee exact OMX runtime parity.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in `oh-my-hermes` and ask one concise clarification question.

Recovery:

- Use `/oh-my-hermes` to load the router skill explicitly.
- Use `/skills`, `skills_list`, or `skill_view` if Hermes does not automatically load the intended skill.
- Use `omh snippet --dry-run` to print optional workspace guidance. `omh apply` does not write `AGENTS.md` or other repo-local prompt files by default.

## Local Development

```sh
python -m unittest discover -s tests
python -m omh.cli --help
```

The tests use temporary homes and do not mutate the real `~/.hermes`.


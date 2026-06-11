# Contributing

Thanks for helping improve oh-my-hermes.

## Development Setup

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests
```

## Contribution Rules

- Keep Hermes as the runtime boundary.
- Keep installer behavior reversible and inspectable.
- Do not write workspace guidance files by default.
- Do not overwrite locally modified managed skills unless the caller passes
  `--force`.
- Add or update tests for routing, config edits, manifest behavior, and command
  output when those contracts change.
- Keep generated skill text conservative. It may guide routing, but it must not
  claim hidden control over Hermes core behavior.

## Pull Request Checklist

- The change is scoped and explained.
- Tests pass locally.
- Public docs were updated when behavior changed.
- Generated docs were refreshed or `python -m omh.cli docs workflows --check`
  was run when catalog data changed.
- Release-channel impact was considered for installer, update, or packaging
  changes.
- Runtime or native capability claims are backed by artifact evidence, wrapper
  evidence, or explicit "not observed" language.
- The PR description includes risk, validation, and known gaps.
- New public strings avoid coupling the project to another agent runtime.

## Commit Messages

Use concise decision-oriented messages. Mention why the change exists, not just
what files changed.

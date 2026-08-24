# OMH Structural Code Search

Optional playbook for the `ast-grep` structural search tool. The fallback comes
first: if `ast-grep` is not on PATH, use grep/ripgrep exactly as today — every
rule below assumes the binary is already present, and none of them is a reason
to install anything. OMH detects presence only (`omh doctor` / `omh probe`); it
never executes ast-grep, and a prepared command from this playbook is not
execution evidence until an observed result records it.

Figures were measured against ast-grep 0.45.1 on the oh-my-hermes repository's
`src/` tree; reproduce each with the command printed beside it.

## When To Reach For It

- The target is a syntactic shape — a call form, a signature, an assertion
  arity — rather than a string. A structural call pattern answers "where is it
  called"; grep answers "where is it mentioned".
- The repository is not Python. `omh codegraph` is stdlib-`ast` and
  Python-only by construction; ast-grep 0.45.1 lists 28 languages
  (`ast-grep run -h | grep -A2 'Supported languages'`) — roughly 23
  programming languages plus 5 markup/data formats (Css, Html, Json, Markdown,
  Yaml). For TypeScript, Go, or Rust work this is structural search existing
  at all, not an optimization.

## Never Body-Capture In A Search

A `$$$BODY` metavariable makes search output catastrophically larger, not
smaller. Measured: `def $NAME($$$A) -> dict[str, object]: $$$BODY` over `src/`
returned 870 matches totalling 1,436,267 bytes of match text, where the
equivalent grep question cost 141 lines / 14,039 bytes. ast-grep is not
automatically cheaper; capture the smallest node that answers the question.

## Locate First, Read Second

Start with paths only:

```sh
ast-grep run -l python -p '<pattern>' --files-with-matches src/
```

The saving is in avoided follow-up reads, not in the search output itself
(measured: grep sent one call-site query to 11 files, the structural pattern
to 10; the file lists differed by only ~30 bytes). Open only the files that
matter.

## Ignore-File Semantics

ast-grep honors `.gitignore` by default; `grep -rn` does not. Measured in an
isolated probe repo: with `build/` gitignored, the default scan returned only
`real.py` while `--no-ignore vcs` also returned `build/stale.py`. Grepping a
repo with a gitignored stale build tree produces hits the default ast-grep
scan never produces — and each stale hit is a wasted follow-up read.

## Precision, Qualified

Measured on `src/`: `grep -rn 'shutil\.which'` found 16 hits;
`ast-grep run -l python -p 'shutil.which($$$A)' src/` found 12. The four
differences are not all noise: three were comments/docstrings, one was a
genuine function-object reference rather than a call. Both "where is it
called" and "where is it mentioned" are legitimate questions; pick the pattern
that matches yours, and do not treat the delta as pure false-positive
elimination.

## Pattern And Flag Footguns

- Prefer `$$$REST` over fixed arity: `self.assertEqual(len($A), $B)` silently
  misses the three-argument message form.
- `-r` collides across subcommands on 0.45.1: it means `--rewrite <FIX>` under
  `ast-grep run` but `--rule <RULE_FILE>` under `ast-grep scan`. Spell the
  long flags.
- Only `-U`/`--update-all` writes; `--rewrite` without it prints a read-only
  diff preview.
- Always spell `ast-grep`, never `sg`: some installs alias `sg` to ast-grep,
  but on many Linux distributions `sg` is util-linux's newgrp-family group switch. The
  collision is conditional, so the long name is the only safe spelling.

## Version Scope

Measured against ast-grep 0.45.1. Pattern syntax (`$VAR`, `$$$MULTI`) is
stable; the CLI flag surface has moved across minor versions. If a documented
flag is missing, check `ast-grep --version` before assuming this guidance is
wrong. OMH pins no executor CLI version and never requires one.

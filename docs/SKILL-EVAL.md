# Skill host-fit check (`omh skill-eval`)

`omh skill-eval` reads a skill folder, or a folder of skills, and reports for
each agent host whether it loads the skill, loads it degraded, never sees it, or
cannot be judged from the facts on record (`unverified`).
It reads files only: no model call, no network, no key. The `omh-skill-eval`
skill runs it for you; the command also works on its own and in CI.

```sh
omh skill-eval ./my-skills/pdf-tables --install-root .claude/skills
omh skill-eval agent-skills --catalog --install-root .agents/skills --json report.json
omh skill-eval ~/.hermes/skills/my-skill --host hermes,claude-code --strict
```

| Option | Meaning |
| --- | --- |
| `PATH` | A folder with `SKILL.md`, or a folder of skill folders, category folders included (read as a catalog automatically) |
| `--catalog` | Read `PATH` as a folder of skills even when it has its own `SKILL.md` |
| `--host H1,H2` | Hosts to check: `hermes`, `claude-code`, `codex`, `openclaw`, `opencode`, `copilot-cli`. Left out, all six are checked; given but naming none (`--host ,`), the command exits 2 |
| `--install-root ROOT` | Where the folder is installed (`.agents/skills`, `.claude/skills`, `~/.hermes/skills`). Otherwise read off the path as given: a dotted root, a root under `~`, a Hermes profile's `skills/` (`$HERMES_HOME/skills`, `~/.hermes/profiles/*/skills`) or a `skills.external_dirs` folder of the active Hermes home; failing that, each host's root reads `not_checked` |
| `--context-tokens N` | The model's context window; 0 uses each host's unknown-context budget |
| `--json FILE` | Also write the `omh_skill_eval/v1` payload |
| `--strict` | Exit 1 when any host row is `not_loaded` or `degraded` |

Output is one line per host (`✅ loads`, `❔ unverified`, `⚠️ degraded`,
`❌ not_loaded`, with the first finding), the catalog size, overlap groups,
static findings, and a count line. A catalog run prints only the skills with a
flagged row. Exit 0 is the default, because the check is advisory. `--strict`
turns flagged rows (unverified included) into exit 1, and a missing folder, an
unknown host or a `--host` naming none exits 2.

How the path is read:

- The install root comes from the path as you typed it, without following
  links, so a skill folder linked into `~/.hermes/skills` from elsewhere counts
  as installed there. A link target matters only where a host has a link rule:
  OpenClaw does not load a skill folder linked from outside its root
  (`OPENCLAW_DIR_LINK_ESCAPE`); Codex and the others follow it.
- A catalog is every `SKILL.md` below the folder, walked the way Hermes walks a
  skills root: category folders are entered, links followed, a skill's own
  `references/`, `templates/`, `assets/` and `scripts/` and cache or VCS
  folders skipped. Hosts that read only the root's own folders (Claude Code) or
  a few levels (Codex 5, Copilot CLI 3) get a `*_GROUPING` finding for a deeper
  skill, and their list budgets count only the skills they see.
- Frontmatter is read as the YAML subset skills use. An unquoted number,
  boolean or date is a typed value, not a string (`*_DESC_TYPE`); a list or a
  mapping is `*_DESC_LIST` / `*_DESC_MAP`; a tab-indented line is
  `*_TAB_INDENT`; quoted keys are keys. Each host takes the effect its recorded
  facts give, and where no fact covers a case the row is `unverified`, never
  `loads`. YAML outside the subset (anchors, tags, a bare `: ` in a plain
  value, an unclosed quote) is `*_YAML_UNSUPPORTED`, `unverified` on every host.
- A `$ARGUMENTS`-style token inside a code span is documentation, also when the
  span runs across a line break (CommonMark pairs backtick runs of equal
  length). Line numbers in findings are `SKILL.md` lines.
- OpenCode's skill tool cuts the body it delivers at 2,000 lines or 51,200
  bytes (`OPENCODE_BODY_CAP`), separate from its 2,000-character line cut on
  other files. Codex's shell-read cut depends on how the skill is invoked and on
  the provider, so it is not evaluated.

In the `omh_skill_eval/v1` payload a host row's `status` is `loads`,
`unverified`, `degraded` or `not_loaded` (worst finding wins, in that order); a
finding's `effect` is `advisory`, `unverified`, `degraded` or `not_loaded`;
`summary` counts `not_loaded`, `degraded` and `unverified` rows; and `catalog`
carries `grouped`, the skills that sit in a category folder.

A host verdict says whether the host loads and lists the skill. It does not say
whether the skill improves answers. Measure that with the skill's
`references/with-without-eval.md`: run the same tasks with and without the
skill on your own model. The host facts and their sources are listed in
[Skill Upstream Sources](SKILL-SOURCES.md) (`skill-eval`).

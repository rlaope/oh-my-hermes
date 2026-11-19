# Skill host-fit check (`omh skill-eval`)

`omh skill-eval` reads a skill folder, or a folder of skills, and reports for
each agent host whether it loads the skill, loads it degraded, or never sees it.
It reads files only: no model call, no network, no key. The `omh-skill-eval`
skill runs it for you; the command also works on its own and in CI.

```sh
omh skill-eval ./my-skills/pdf-tables --install-root .claude/skills
omh skill-eval agent-skills --catalog --install-root .agents/skills --json report.json
omh skill-eval ~/.hermes/skills/my-skill --host hermes,claude-code --strict
```

| Option | Meaning |
| --- | --- |
| `PATH` | A folder with `SKILL.md`, or a folder of skill folders (read as a catalog automatically) |
| `--catalog` | Read `PATH` as a folder of skills even when it has its own `SKILL.md` |
| `--host H1,H2` | Hosts to check: `hermes`, `claude-code`, `codex`, `openclaw`, `opencode`, `copilot-cli` (default: all) |
| `--install-root ROOT` | Where the folder is installed (`.agents/skills`, `.claude/skills`, `~/.hermes/skills`). A dotted path or a path under `~` is inferred; otherwise each host's root reads `not_checked` |
| `--context-tokens N` | The model's context window; 0 uses each host's unknown-context budget |
| `--json FILE` | Also write the `omh_skill_eval/v1` payload |
| `--strict` | Exit 1 when any host row is `not_loaded` or `degraded` |

Output is one line per host (`✅ loads`, `⚠️ degraded`, `❌ not_loaded`, with the
first finding), the catalog size, overlap groups, static findings, and a count
line. A catalog run prints only the skills with a flagged row. Exit 0 is the
default, because the check is advisory. `--strict` turns flagged rows into
exit 1, and a missing folder or an unknown host exits 2.

A host verdict says whether the host loads and lists the skill. It does not say
whether the skill improves answers. Measure that with the skill's
`references/with-without-eval.md`: run the same tasks with and without the
skill on your own model. The host facts and their sources are listed in
[Skill Upstream Sources](SKILL-SOURCES.md) (`skill-eval`).

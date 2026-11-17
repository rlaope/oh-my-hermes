# Telling harnesses apart in omher

omher shows who did a piece of work: Hermes itself, or another harness that Hermes handed the work to (Claude Code,
Codex and others, over ACP or through an OMH fanout export). It shows each one with that harness's official mark.
This page lists which recorded fields identify what, where each field lives, and what omher cannot know.

All marks come from one registry, `apps/omher/src/harness/registry.ts` (`HARNESSES`, `harnessOf`). It is the only
code that names files in `src/assets/agents/`, through `src/harness/assets.ts`. A unit test (`registry.test.ts`)
checks that no other file reads that folder. To add a harness, add one registry row and one asset file.

## The decision order (`harnessOf(facts)`)

`facts` is `{executor?, acpCommand?, provider?, model?, kind?}`.

1. **An explicit executor or fanout owner.** Sources are a dag node's `executor`, the `owner` of a fanout unit, a
   CLI run's agent, or the `kind` that the bridge's `runs.node_session` returns. Names are matched without regard to
   case, and aliases also match (`claude-code` → claude, `codex`, `omp`, `gemini-cli` …).
2. **The ACP command's basename.** `claude-agent-acp` and `claude-code-acp` → claude, `codex-acp` → codex. `gemini`,
   `opencode`, `kimi`, `qwen`, `copilot`, `cline` and `goose` are matched with their `--acp`/`acp` argument. The path
   and a Windows `.exe` suffix are ignored. An ACP command that no row knows → `generic`.
3. **A plain Hermes child.** If only a provider or model is known, the work ran inside Hermes, so the harness is
   `hermes`. The model maker's mark (Claude, OpenAI, Gemini, DeepSeek, xAI, Z.ai …) is a second, smaller fact
   (`modelMark`). A Hermes child that runs a Claude model is shown as Hermes with a Claude model mark, never as Claude
   Code.
4. **Nothing known** → `generic`, a neutral outline mark. omher never shows another company's logo as a guess.

## Evidence (read-only, kami profile and `~/.omh`, 2026-11-15)

| What | Where it is recorded | Identifies |
| --- | --- | --- |
| Hermes subagent session | `<profile>/state.db` `sessions` rows with `source='subagent'` (449 on kami), `parent_session_id`, `model`, `billing_provider`, `started_at`/`ended_at` | It is a Hermes child, and which model it ran on: `claude-proxy`/custom → claude-*, `openai-codex` → gpt-*, `og` → glm/grok/kimi … |
| What it did | `messages` rows of that session: `role`, `content`, `tool_calls` (JSON), `tool_name`, `tool_call_id` (70–195 messages and 33–94 tool calls each) | Prompt = first user message. Steps = assistant `tool_calls`, paired by id with the `tool` messages. Answer = the last assistant text. Later user messages are the parent's steers. |
| Which dag node it is | The first user message carries `[dag:<run>/<node>]` (210 of 449 on kami) | The node a child belongs to |
| Live subagent events | Gateway `subagent.*` events: `subagent_id`, `parent_id`, `depth`, `model`, `goal` (bridge `subagent_fields`) | Model and goal only. They carry no ACP command. |
| Delegation manifest | `<profile>/cache/delegation/live/deleg_*/manifest.json` `{model, provider, tasks[{goal, log}]}` | Model and provider of a fan-out's tasks |
| Fanout export | `<omh>/runtime/dag/<sid>/<run>/fanout-<hash>-units.json` `{units: [{unit_id, owner, title, file_scope}]}` | The agent CLI (`owner`) a node was handed to |
| Fanout binding | `<omh>/runtime/runs/fanout-<hash>-<unit>/executor_progress/binding.json` `executor`, `correlation_aliases[{kind: "worktree", value}]`, `created_at` | The worktree and start time of the CLI session that ran the unit |
| Claude Code session | `<CLAUDE_CONFIG_DIR or ~/.claude>/projects/<cwd slug>/<id>.jsonl`, subagents in `<id>/subagents/agent-<id>.{jsonl,meta.json}` | Claude Code. `message.model` gives the model. |
| Codex session | `<CODEX_HOME or ~/.codex>/sessions/YYYY/MM/DD/rollout-*.jsonl`. The first line `session_meta` holds `cwd`, and `source.subagent.thread_spawn.parent_thread_id` for spawned children. | Codex. `turn_context.model` gives the model. |

## The gap: the ACP command

When Hermes runs a child over ACP (`delegate_task` with `acp_command`/`acp_args`, or a provider whose
`auth_type: external_process` carries a `command`), the command is hidden from the model. It is not written to
`subagent.*` events or to `state.db`. omher therefore takes `acpCommand` only from a record that names it:

- the dag record or the fanout units file (`owner`), when OMH exported the node to a CLI;
- the delegation manifest, if a future Hermes version writes the command there.

When no record names it, the child is identified by its model family only (step 3 above), so it shows as Hermes plus
the model mark. That is honest: omher shows what the records prove. No ACP adapter is installed on this Mac
(`claude-agent-acp` and `codex-acp` are absent), so ACP identification is covered by unit tests and was not run live.

## The node session view (`runs.node_session`)

`runs.node_session {bot, run, node}`, `{bot, ref}` (a child named by an earlier read) or `{bot, goal, since}` (a
subagent card in the chat). The op is read-only and returns:

```
{session: {kind: "hermes"|"claude"|"codex", prompt, steps: [{tool, input, result, ok}], answer,
           children: [{ref, kind, goal, state, summary, model}], items: [...in order...], model, provider,
           parent}, why?, executor?}
```

- **Hermes child.** It is found by its `[dag:run/node]` mark, or for a delegate fan-out by its goal and start time.
  It is read from the bot's own `state.db` through a read-only URI. Only `role, content, tool_calls, tool_name,
  tool_call_id, timestamp` are selected. The reasoning columns are never read.
- **Claude Code / Codex.** The fanout units file gives the binding, and the binding's worktree gives the session.
  That is the Claude transcript in exactly that folder's slug, or the Codex rollout whose `session_meta.cwd` is that
  folder, started at or after the binding's `created_at`. The bridge reads only plain files whose real path is inside
  the CLI home. Symlinks are refused, and a session from another folder is never picked. `thinking` parts and
  `reasoning` items are skipped.
- **Every input and result** is clipped to 4 KB. Token-like strings
  (`sk-…`, `gh[pousr]_…`, `github_pat_…`, `glpat-…`, `xox[abprs]-…`, `AKIA…`, and the value of `token=`,
  `credential=`, `password=`, `secret=`, `api_key=`) are replaced by `••••`, by omher's one masker
  (`apps/omher/src/lib/secrets.json`, shared with the desktop shell and the page).

The UI (`src/harness/AgentChat.tsx`) draws the session as a chat between agents, reusing the main chat's components:

- The parent's prompt and steers are right bubbles labelled with the parent's name.
- The child's words are left bubbles, with its harness mark as the face. A Hermes child also wears its model mark.
- Tool calls are our step rows. Each one opens to its full input and result.
- Its own children are our subagent rows. Clicking one opens that child's chat in place, under a breadcrumb.
- The answer is the last left bubble.

## API for other lanes

- `harnessOf(facts) → {harness, modelMark, by}` and `HARNESSES`: `src/harness/registry.ts`.
- `<HarnessMark id size/>`, `<HarnessFace facts size/>` and `<HarnessStack items max={3}/>` ("+N"):
  `src/harness/HarnessMark.tsx`.
- `<AgentChat bot target title facts running/>`: `src/harness/AgentChat.tsx`.

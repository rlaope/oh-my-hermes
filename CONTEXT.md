# oh-my-hermes

The glossary for oh-my-hermes: which product, record or surface owns each
term, so agents stop blurring OMH and Hermes Agent. Each entry is the term's
single definition; `_Avoid_` lists the names it gets confused with. Product
direction is `docs/DIRECTION.md`, the operating contract `AGENTS.md`, and
commands and pitfalls `CLAUDE.md`.

## Language

### Products

**OMH (oh-my-hermes)**:
This repo — a deterministic wrapper orchestration layer installed next to
Hermes Agent: skill catalog, router, prepared-handoff generator, and
metadata-only status surfaces. Makes no LLM, API, or network calls outside
the scoped exceptions `CLAUDE.md` lists under What This Repo Is.
_Avoid_: Hermes plugin (that is one distribution surface, not the product),
coding executor, Hermes patch

**Hermes Agent**:
Nous Research's agent product that OMH integrates with — a separate codebase
installed on the user's machine (typically under `~/.hermes/hermes-agent`).
OMH never modifies its code and does not vendor it.
_Avoid_: Hermes runtime (that names an OMH executor path), our agent

### State roots

**Hermes home**:
`$HERMES_HOME`, default `~/.hermes` — Hermes Agent's own state root. OMH only
adds managed, explicitly installed artifacts under it (`plugins/omh` and skill
registration in `config.yaml`). Earlier versions also installed a status
widget under `tui-widgets/` and skin files under `skins/`; setup and update
remove the ones OMH can prove it wrote.
_Avoid_: using it for OMH runtime state

**OMH home**:
`$OMH_HOME`, default `~/.omh` — OMH's state root; managed skills and the
runtime metadata the HUD reads live here. Exactly one home is active per
invocation: the user-scope default, `OMH_HOME`, `--omh-home`, or
`--scope project`, which resolves to the repository's own `./.omh`.
_Avoid_: probing several guessed homes, Hermes home

### Skills and routing

**Managed skill**:
A generated workflow document (`skills/*/SKILL.md`) OMH installs under the OMH
home and registers into Hermes' `skills.external_dirs` so Hermes can invoke it
in chat. Generated from the skill catalog; never hand-edited.
_Avoid_: slash command, prompt template, OMC skill (that is a different
product's concept)

**Hermes skill category**:
The dashboard group Hermes shows a skill under in its startup banner and skills
list. Hermes derives it from the SKILL.md's DIRECTORY, not from frontmatter, and
only when the path relative to a registered skills dir has three or more parts —
so managed skills install at `<skills_dir>/<category>/<label>/SKILL.md`.
`hermes_skill_category()` in `src/skills/catalog.py` owns the mapping: the
skill's Hermes role, with the ULW engines carved out as `ultrawork`. The repo's
own `skills/` tap tree stays flat, because Hermes' tap lister reads only one
directory level below a tap path.
_Avoid_: `SkillDefinition.category` (the catalog's fine-grained phase field,
which Hermes never reads), capability family

**Agent Skills projection**:
A separately generated, portability-reviewed view of the catalog under
`agent-skills/`. Hosts discover installed copies in `.agents/skills/`;
both repo and user scopes also copy them into `.claude/skills/` under the same
scope root for Claude Code. This is not a
managed Hermes skill, a plugin, an RPC tool, or a runtime port. A fresh copy is
not evidence that a host loaded or executed it. See [Agent Skills](docs/AGENT-SKILLS.md).
_Avoid_: managed skill, Hermes plugin, execution adapter

**Skill catalog**:
The source of truth for every skill and its metadata (`src/skills/catalog.py`
plus render code). Skills, `docs/WORKFLOWS.md`, `docs/ROLES.md`, and the demo
cards are byte-exact projections of it.
_Avoid_: editing any generated projection directly

**Skill record**:
One record per skill (`src/skills/skill_record.py`) assembling its definition,
harness, routing policy, portability, body and reference renderers, and
next-action label from the catalog tables, behind `project(skill, target)`. It
reads the tables and moves no data; boundary fields stay as each table states
them.
_Avoid_: reading a skill's fields from the tables directly in a new writer;
deriving one boundary field from another; `install/manifest.SkillRecord`, an
installed file's name/path/sha256, which shares the name and nothing else

**Router**:
OMH's deterministic chat-intake classifier that maps a natural-language
request to a workflow, skill, or intervention using normalized phrase and
token matching. Not a model and not an LLM dispatcher.
_Avoid_: LLM router, model routing (that names executor model selection)

**Route hint**:
A non-binding recommendation of the nearest OMH workflow for a message, as
returned by `omh_recommend` or `omh recommend`. It records nothing and
authorizes nothing.
_Avoid_: dispatch, delegation, decision

**Routing query**:
The prepared stages of one message (`RoutingQuery` in
`src/routing/query.py`: executable, scrubbed, routing text, normalized,
tokens), built once and taken as input by every router reader that needs the
full prep chain.
_Avoid_: re-deriving the prep chain at a call site; passing a half-prepared
string into the scorer

### Runtime evidence

**Run**:
One recorded unit of coding work under `$OMH_HOME/runtime/runs/<id>` — the
place prepared handoffs, observations, and effect receipts about that work
accumulate.
_Avoid_: session (wrapper sessions are a different record), task

**Run record**:
An on-disk run, dispatch, or receipt file (`run.json`, `events.jsonl`,
`dispatch_summary.json`, `external_effect_receipts.jsonl`, …) that the
control-plane writers produce and the Hermes-side readers in the plugin bundle
consume. Its file names, schema versions, and closed vocabularies are owned
once, by `src/plugin_bundle/omh/run_records.py`; the writers import them.
_Avoid_: a second definition of a file name or schema version, a parity test as
the owner

**Delegation ledger**:
`delegation_ledger/v1` at `$OMH_HOME/runtime/delegation/<key>.json`, one per
conversation: what Hermes' own `subagent_start`, `post_tool_call` (for
`delegate_task`) and `subagent_stop` hooks said about delegated children.
Session and subagent ids, parent, turn, task index, delegation id, times,
status words, and the route OMH had recorded for the session when a child
started, and, for a child whose goal carries `[dag:<run>/<node>]`, those
two ids (**Dag-ulw run**). No goal, summary, prompt or tool history. It is the
only record that ties a child session to the call and task that made it;
`state.db`, the delegation manifests and the live logs do not.
_Avoid_: evidence that a lane succeeded (a stop status is Hermes' report),
reading a goal from it

**Prepared handoff**:
OMH's output contract for coding work — a payload a coding owner may execute
later. Preparing one is not dispatch, execution, review, CI, or merge
evidence; its status is `prepared_not_observed`.
_Avoid_: run, execution, delegation result

**Observed evidence**:
A recorded observation that something actually happened (dispatch, execution,
verification, review, CI, merge), as opposed to something being prepared or
claimed. The only basis for completion claims in reports and status surfaces.
_Avoid_: treating a prepared artifact, a declaration, or an executor's
self-report as evidence

**Claim boundary**:
The sentence attached to a record stating what that record is *not* evidence
of. Every metadata artifact OMH writes carries one.
_Avoid_: disclaimer (it is a validated contract field, not prose)

**Executor progress binding**:
The metadata record that links a run or wrapper session to a live executor so
its progress events can be projected as HUD activity rows. Bindings age from
active to stale to expired; they never prove results.
_Avoid_: process handle, job

**Plan todo**:
The declared checklist the HUD surfaces render above the prompt input.
Items are plan declarations; a done mark never upgrades into observed
evidence. One record per declaring session: a plan stamped with `session_ref`
lives at `$OMH_HOME/runtime/todos/<session key>.json` and renders only for
the session that owns it — the OMH TUI names the session it shows, the
Desktop pane its focused session, the plugin tool and hooks the session that
invoked them — so a plan declared from Slack, Discord, or a second TUI is
neither shown in nor overwritten by another session. An unstamped record
(`omh runtime todo set` without `--session`) keeps the home-wide
`$OMH_HOME/runtime/todo.json`, scoped by write time against the reading
session's start; a reader with no live TUI row to date it against (a gateway
session), or a host that cannot say which session is reading, keeps the
age-only behavior. A TUI session reference (`tui_session_ref`, which the
Desktop pane passes) that names no live TUI row is first offered to the
host's active-session lease registry, which pairs a created
session's transport id with its durable key; an unpaired reference stays its
own identity and reads no other session's record.

Two tools write this one record, and only one of them holds a given plan's
steps. Where Hermes' native `todo_list` is present (see Native tool
presence), it does: the plugin's `post_tool_call` projects each successful
`todo_list` write into the session's own record with `source: todo_list`
(`src/plugin_bundle/omh/native_todo.py`) — `completed` as `done`, judged
against recorded commands like any done mark, and `cancelled` as `done` with
a `blocked_reason` — and `omh_todo` is called only for what `todo_list`
cannot say: `plan_stage`, the completion dossier, an item's `blocked_reason`
and the plan's `deferred_reason`. On a `todo_list`-held plan `todo_list`
alone sets item states (an `omh_todo` advance there keeps the state and the
`source`), and a recorded reason is carried across later native writes by
item text while the item stays where it was or is paused back to pending.
Where it is absent, `omh_todo` is the only writer. Every
reader — the HUD, the OMH TUI, the Desktop pane, the plan-stage gate, the
stall finding and the continuation drive — reads the record through
`read_omh_todo` and never asks which tool wrote it. A native write never
replaces a plan only `omh_todo` can express: one awaiting acceptance or a
template plan while it is open, or an accepted plan — the one `omh_team`
binds — until it goes stale; `omh_todo action=clear` is how a session leaves
one, and a recorded `deferred_reason` only pauses it (the hold never reads
it). Only a whole-list write re-declares a record's `source`: an `omh_todo`
set, or a mirrored `todo_list` write (replacing the plan, or adopting an
identical one). Where Hermes draws
its own todo list — Hermes Desktop — the OMH pane leaves a `todo_list`-held
plan's items to it and shows only what it cannot: a reason `omh_todo`
recorded on an open item and the stall finding. The OMH TUI's plan panel
draws the items whichever tool holds them.

One field on this record refuses work rather than describing it, which is why
it is named here: a planning run stamps `plan_stage: awaiting_acceptance` when
it declares the checklist, and while that holds, a `write_file` or `patch` in
the owning session is escalated to the host's human-approval gate so the
person is asked before the run implements. `accepted` is their recorded
go-ahead and ends it; the field's ABSENCE is unknown rather than "not
accepted", so every plan that is not a planning run — a delivery checklist, a
CLI write, a record predating the field — is ungated. Still a declaration and
still never evidence: the stamp says what the run claims about the person's
answer, never that a plan was reviewed or that anything was implemented.
_Avoid_: task list as evidence, TodoWrite (that is another product's tool
name), reading an absent `plan_stage` as an unaccepted plan, a second
checklist (the same steps written to both `todo_list` and `omh_todo`)

**Completion dossier**:
The record a verification verdict, a review finding set, or a QA result
survives its session in: `native_completion/v1` at
`$OMH_HOME/runtime/completion/records.json`, written by OMH from an
`omh_todo action=record` declaration under a scope checkpoint, read back with
`omh_todo action=recall` inside a session or `omh runtime verdict show` from
the command line. Every row keeps `standing: model_declaration` and
`observed: false` whatever `claimed_evidence_state` (`prepared_not_observed`
or `observed`) its writer claimed, so a stored PASS is evidence that a PASS
was claimed, exactly as a done mark on the plan todo is. The read adds
`freshness` — `current` or `stale` against a stated revision and environment,
`unbound` when none is stated — and a source state per kind (`absent`,
`stale`, `declared_no_findings`, `declared_findings`), so a missing record
and a record that declared nothing found never read alike. A verdict is bound
to the revision it was declared for and goes stale when that revision moves,
not on a clock; the 30-day cap only bounds a dossier nobody moves.
_Avoid_: reading a stored PASS as verification, reading an absent dossier as a
clean run, review transcript (the store holds summaries and evidence ids,
never transcripts or raw output)

### Coding delegation

**Default coding lane (Hermes harness)**:
Absent an explicit coding-owner choice, coding work runs inside the Hermes
harness and no external coding CLI is selected. This is the default and the
normal path — most coding work in chat is this lane, and none of the
Maestro/handoff machinery below participates in it. The vocabulary contract in
`src/coding/orchestration_vocabulary.py` pins this wording.
_Avoid_: coding handoff (that is the Maestro lane), assuming an external
executor by default, reading handoff modules as the main coding path

**Coding owner**:
The executor selected to perform coding work for a run: Codex, Claude Code, a
Hermes runtime/handoff path, or a generic executor profile. OMH language,
schemas, and reports stay neutral across all of them.
_Avoid_: defaulting to Codex in wording, the agent

**Maestro**:
The operator lane by which an external coding CLI becomes the coding owner
after an explicit user choice — `src/coding/maestro/` prepares a handoff for
the chosen CLI and never runs it. Its facade rejects the `hermes` profile
(`HermesNativeSelectionError`), so the default lane and Maestro never blur in
code; keep them separate in prose too. Prepared handoffs, executor capability
snapshots, executor prompting contracts, throughput overlays, and the handoff
sections of `wrapper-routing.md` all belong to this lane, not to the default
lane. The lane's skill-facing surface is the `ulw-maestro` engine (canonical
`maestro`), whose explicit-owner precondition is the same gate stated here.
_Avoid_: treating Maestro surfaces as the default coding path, legacy (it is
current, just not default), "coding delegation" as a synonym for all coding
work

**Fanout dispatch**:
The explicit, operator-invoked `omh coding fanout dispatch` (multi-unit) or
its `omh coding run` single-run entry (one unit, same engine, one call) that
spawns local agent CLIs as subprocesses. Its one sibling is the Hermes-native
child boundary (`omh coding hermes-child dispatch`, which `paired-run` and
`--final-review` reuse): one confirmed, isolated local Hermes process.
Nothing else in OMH executes work: the OMH TUI below starts Hermes' own
gateway for a terminal the person opened, and every model call, tool run and
`!` shell command the person types there is Hermes' to run.
_Avoid_: implicit execution, background dispatch, counting the OMH TUI as an
execution surface

**Programmatic tool calling (`execute_code`)**:
Hermes Agent's own tool: the model writes a Python script that calls a
sandboxed subset of Hermes tools over RPC, collapsing a multi-step tool chain
into one inference turn; only the script's stdout returns to context. Part of
the default coding lane and owned entirely by Hermes — OMH neither implements
nor wraps it and may only describe it in awareness guidance.
_Avoid_: fanout dispatch (OMH's separate opt-in surface), an OMH execution
surface, code-mode batching (a Maestro-lane handoff instruction, currently
inert)

**Wrapper session**:
The metadata record of a chat-surface interaction (Discord, Slack, hosted
chat) driving OMH through the chat contract. A wrapper session is
conversation state, not coding evidence.
_Avoid_: run, transcript

### OMH surfaces inside Hermes

**OMH plugin**:
The Python bundle OMH distributes into `$HERMES_HOME/plugins/omh` — Hermes
tools (`omh_*`), lifecycle hooks, the memory provider, and the runtime reader.
A managed copy of `src/plugin_bundle/omh`, never a symlink, and enabled via
Hermes' `plugins.enabled` list.
_Avoid_: equating it with OMH itself

**Plugin tool**:
One of the `omh_*` tools the plugin registers with Hermes (for example
`omh_recommend`, `omh_hud`, `omh_todo`). Tools are metadata-only; the ones
that write touch only OMH-owned artifacts in the configured OMH home.
_Avoid_: MCP tool (the MCP bridge is a separate, allowlisted surface), shell
command

**Awareness**:
The bounded guidance the plugin's hooks inject into Hermes context so Hermes
knows which OMH tools and workflows exist and when to use them. Awareness is
instruction, never state and never evidence.
_Avoid_: system prompt, memory

**Memory provider**:
OMH's deterministic file-backed memory implementation that Hermes loads only
when `memory.provider: omh` is selected in Hermes config. Hermes runs at most
one external provider, so the key is a slot, not a list.
_Avoid_: claiming the slot when another product holds it

**Memory admission**:
The one path from a stated fact to a replay-ready record: capture, the
confinement-scoped duplicate check, the candidate write, auto-safe approval,
and the receipt. Owned by the plugin bundle (`memory_admission`), called
in-process by the `omh_memory` tool and through adapters by the `omh memory`
CLI.
_Avoid_: a second write path, a subprocess from the plugin into the CLI

**Delegation view**:
A conversation's delegated work drawn as a graph (`delegation_graph/v1`:
nodes, edges, layers): frontiers of boxes (title,
category and model, status, parents), one connector per frontier gap, the
recorded edges listed exactly under `Dependencies`, and a `Node details` card
per running or stuck node and for `/dag`'s highlighted one; or a compact tree
when no box fits or the edges loop; the tree nests a node a dag-ulw run added
(a repair or an extend) under where it came from. The
OMH TUI draws it in the agent view under the info line: a dag run as a
folding tree (a header row per node, under an open one its child's latest
call and latest line, running and failed nodes open, layers set apart by
blank rows, folded to fit the view's cap before a count row cuts it; Down
gives it the keys, and Enter, `x` and `s` act on a node's child as in the
agent list), any other graph as its tree. `/dag` opens the boxes full screen, live and keyboard-driven (highlight, fold,
details), sending nothing anywhere; `omh hud --graph` prints the boxes. A
chat reply never carries the boxes: on Slack, Discord, Telegram, Mattermost
and Matrix,
`transform_llm_output` appends to the reply Hermes is sending a run's start
block once, a count line on a turn its counts changed, and its end block once
(**Delegated run**). A box draws no `?`: it leaves a field with no record out
(a blank line where neither category nor model is recorded) and draws an
unknown state as `◇`. In the tree a model not recorded yet is blank, and `?`
stands in the category column where neither is recorded; nothing in it reads
current config. Colour is the TUI theme's (a box by its node's state, the
tree's edges by `dag_edges`), never part of the text: a chat post is plain.
_Avoid_: a message OMH sends (Hermes delivers the reply), a plan (it shows
dispatched work and the nodes a dag-ulw run declared, never a plan it
inferred), reading a wave as a dependency

**Delegated run**:
The lanes of a conversation's delegation graph that no chat end post has
closed yet. It starts on the first reply that finds one of them not settled,
and ends on the first reply after all of them have settled (done, failed,
interrupted, or `unknown`) and, for a dag-ulw run, nothing in it is out or
ready (done, cancelled, out of repair cycles, or waiting on a repair the reply
did not make), or after nothing has been in
flight or changed for 15 minutes (`stalled`; the parts not moving stay
open). The ledger's `posted` record keeps its phase, its last counts, the
keys of the lanes earlier runs closed, and the keys of the lanes a post has
shown. A later wave's lanes form the next run, except nodes a dag-ulw run
adds after its end post: they reopen that run, with a count line naming
them, not a second start block.
_Avoid_: a single `delegate_task` call (a run can span several waves), a
Hermes session

**Dag-ulw run**:
`omh_dag/v1` at `$OMH_HOME/runtime/dag/<session key>/<run>.json`: the plan a
parent agent declared for one dag-ulw run (node ids, labels, categories,
prompts, `depends_on`, write scopes) and the outcome it settled for each
attempt. It holds each node's prompt, the instructions the parent wrote for
that child (at most 3,000 characters a node and 256 KiB a record, created
mode 0600), so `ready` can hand a node out after the parent's own context
was compacted. That is the one difference from the **Delegation ledger**,
which holds no goal text: the run record keeps what the parent planned, never
what a child returned (no output, summary or tool history). The `omh_dag`
tool is its only writer, and a session keeps at most 16 runs (a new one
drops the oldest finished one); the delegation graph reads it under every
segment of the conversation, so a compacted parent still finds its run.
Hermes runs every node as the parent's own `delegate_task` child; the child
of a node is the one whose goal carries `[dag:<run>/<node>]`. Node and
run states are derived on every read. `accepted` is the parent's judgement
after it read the node's handoff file, refused while that file is missing
or Hermes reported the child failed; a failed or blocked node blocks only
its dependents. Repair nodes stand in for a failed producer once all are
accepted, and the nodes after it read the repair's handoff files; a failed
verification node runs again instead, and only its own accepted re-run
satisfies it; at most two repair cycles a node. When every node passed but
the goal check finds work missing, `extend` adds a round of nodes to the
same run (at most two rounds a run), under the same refusals as the first
plan. Each node records where it came from: `define`, `repair:<root>` or
`extend:<round>`. With a coding owner the person chose (the router's
explicit-choice record, read exactly as the router reads it, and no older
than a day: an external CLI spends the person's money and quota, so a stale
choice starts nothing), the ready coding nodes go to that owner's fanout
(`export`) and never to `delegate_task`; verification and review nodes stay
native. Hermes chat records no such choice; `omh chat` and `omh coding` do.
Graph topology is decided once, in `plugin_bundle/omh/dag_core.py`, which
`omh_team` and the fanout contract share.
_Avoid_: reading `accepted` as verification, a child's `completed` as
acceptance, a second graph engine

**HUD payload**:
The metadata-only JSON projection built by `read_omh_hud()` from OMH home and
Hermes home — plugin readiness, activity rows, the plan todo, display lines.
Status narration, never execution, review, CI, merge, or token-usage evidence.
_Avoid_: runtime state (the payload is a read-only projection of it)

### Hermes terminal surfaces

**Classic TUI**:
Hermes Agent's Python prompt_toolkit terminal UI — what `hermes` runs when
`display.interface` selects the classic REPL, which is the default bare
`hermes` opens. It does not load user widget files; its extension point is
wrapper-CLI method hooks.
_Avoid_: treating it as an OMH surface

**Modern TUI**:
Hermes Agent's TypeScript terminal UI — what `hermes --tui` runs, and what
bare `hermes` runs when the person sets `display.interface: tui` (OMH no
longer sets it). Loads user widget apps from `$HERMES_HOME/tui-widgets/*.mjs`;
OMH installs none. Its launcher runs `<HERMES_TUI_DIR>/dist/entry.js` instead
of the Ink app when that variable is set, which is how the OMH TUI takes its
place.
_Avoid_: ui-tui (internal directory name), dashboard TUI, OMH TUI

**OMH TUI**:
The terminal frontend bare `omh` opens (`src/tui/`, installed as `omh.tui`).
`omh` runs the person's own `hermes --tui` with `HERMES_TUI_DIR` pointing at
the packaged shim `omh/tui/frontend/dist/entry.js`, so Hermes' launcher still
resolves the profile, the resume target, the working directory and session
ownership, then starts the shim in place of its Ink app. The shim hands the
terminal to `omh.tui.app.main` on OMH's interpreter, started `-E -P` so the
launcher's `PYTHONPATH` and the working directory stay off its import path,
with the directory `omh` imported its own package from (`OMH_TUI_SITE`) put
first on that path when the interpreter does not already import `omh` from
there, as under the npm and Bun launcher, whose cache is on the path only
inside its own process;
the TUI spawns its gateway child, one at a time, with the interpreter and
import path the launcher provided and speaks `tui_gateway`'s stdio JSON-RPC to
it. The child (`omh/tui/attach/gateway_attach.py`, run by path on Hermes'
interpreter) attaches to the profile's shared gateway as Hermes' Ink TUI does
on a Hermes that has that API, starting it with idle exit when none runs, and
otherwise runs Hermes' stdio entry, which since Hermes 9595c3f345 refuses a
home a running gateway owns; when that
child exits on its own with a failure, it spawns it again the same way and
resumes the open session, at most 3 times in 60 s (an open question closes
unanswered, a running turn is reported lost and never re-sent), and past that
it exits as before; Ctrl+Z stops its process group, the gateway child with it, as
Hermes' own CLI's Ctrl+Z does. Layout, input, rendering and
the OMH panels are OMH's; every model call, tool run and approval decision is
the gateway's. Shift+Tab may turn on Hermes' per-session yolo, so Hermes stops
asking for approvals in that one session (a `config.set` naming the session,
never `approvals.mode`), and the TUI sends that session an explicit off before
it leaves it. Every deny the person gives an approval also interrupts the
running turn, except its last row's, which denies and sends what the person
then types into the running turn as a steer; its `always` row, there only when
Hermes offers it, sends Hermes' own permanent allow, which Hermes saves. It writes no
transcript or server-request frame, and prompt
text only to Hermes' own input history (`$HERMES_HOME/.hermes_history`, which
`hermes --tui` shares: each line the person sends is appended in its format,
never an answer to a question Hermes asked); its other writes are metadata
(the launcher's active-session file, what OMH's HUD reader and model-chain
picker write under the OMH home, and a fallback marker at the path `omh`
named, holding what the TUI printed about why it did not start, which `omh`
prints again after Hermes' own terminal closes and then removes). Finished
transcript lines go to the terminal's own scrollback; only a region drawn
right under them (the streaming tail, one slot for the plan or a prompt
Hermes asked, the composer, the info line under it, and under that the agent
view, always expanded while there are agents) repaints; the
composer sits right under the output until the screen fills, then stays on
the bottom rows, and a slot closing there does not move it. When it cannot start
(an OMH that cannot import itself, gateway unavailable, protocol drift at
startup) it creates the sentinel file `omh` named for that launch and exits
75; that exit, and a blocker found before anything starts, has `omh` say why
in one line on stderr and open Hermes' own TUI (`hermes --tui`, with none of
the OMH TUI's environment) when the reason is the OMH TUI's own and Node is
found, or plain `hermes` (`TERM=dumb`, `OMH_NO_TUI=1`, no Node), which follows
`display.interface`. A 75 without that file (Hermes
exits 75 on paths of its own) ends the launch like any other code. Bare
`hermes` is stock Hermes: OMH writes none of its display keys and draws
nothing in its terminal, while the OMH plugin (tools, hooks, memory, skills)
stays loaded there. The theme it opens with is the one saved under the OMH
home (`omh theme use`), else an OMH palette `display.skin` names, else sky
(`skin_pack.effective_theme`); `/theme` changes the open session only.
_Avoid_: Modern TUI (Hermes' Ink app), OMH status widget (the retired
extension of Hermes' TUI), a Hermes patch or fork, an execution surface

**Hermes gateway protocol**:
Hermes' `tui_gateway` newline JSON-RPC over stdio, which the OMH TUI speaks as
a client. Attached to a shared gateway, its child translates that wire to and
from the gateway's canonical session wire (`hermes-gateway-v1`) in the closed
set of places `gateway_attach.Adapter` names, after Hermes' own
`canonicalGateway.ts`, and passes the rest unchanged. The slice the TUI relies on (the methods it calls with the only
keys it sends, how it answers each server-to-client request, and the subagent
and notification events and the `session.info`, `subagent.tail` and
`session.steer` fields and values it keys on) is declared once in
`src/tui/gateway_contract.py`, against a named Hermes commit, with every event type split into handled and unread;
an event type it does not handle is ignored, never an error, and a submitted
turn that brings no event the TUI shows, only undeclared types, gets one
notice pointing at `omh doctor`, which prints the installed Hermes commit next
to the declared one. The gateway rejects
unknown keys (code 4000) and unknown methods (-32601); the TUI reads either as
drift, falls back at startup, and leaves mid-session with the command to
reopen the session in `hermes`, except on the two calls a session does
without (reading the command list, the `/reload-skills` rescan), where it
says so and the session goes on. This is a read and write coupling to
a Hermes-private shape, the same class as the lease registry below, and
testing OMH against a new Hermes release includes it; `requires_hermes` stays
a floor for the plugin and is not raised for the TUI, whose compatibility is
judged at launch.
_Avoid_: reading the generated OpenRPC file at runtime (Hermes' wheel does not
ship it), a published API

**OMH status widget**:
Retired. `omh-status.mjs`, the Modern-TUI widget file earlier versions
installed into `$HERMES_HOME/tui-widgets/` so bare `hermes` drew the plan
checklist and the status HUD, and registered `/omh-model` there. Setup and
update remove it where its manifest proves OMH wrote it
(`omh/tui_widget_pack.py`); the OMH TUI's panels draw that HUD, and its own
`/omh-model` opens the picker.
_Avoid_: describing it as installed, statusline (that is a different,
host-owned surface)

**Hermes Desktop**:
Hermes Agent's Electron app (`hermes desktop`). It loads no `tui-widgets/`
file; its extension point is a desktop plugin, one uncompiled ESM file that
default-exports a `HermesPlugin`. OMH's desktop half is `desktop/plugin.js`
plus `dashboard/manifest.json` and `dashboard/plugin_api.py` inside the
installed bundle (`$HERMES_HOME/plugins/omh/`). By its loader source, the app
copies `desktop/` to `$HERMES_HOME/desktop-plugins/omh/` beside a
`.hermes-package.json` marker, and the `hermes serve` process it spawns mounts
the backend's `router` at `/api/plugins/omh/` while `omh` is in the host's
`plugins.enabled` (the registration `omh setup` and `omh update` write, and
`omh doctor` reports as `plugin_enabled`); `plugin.js` polls
`GET /api/plugins/omh/hud` and draws the structured payload in a right-hand
`omh` pane -- the plan checklist with its phases, glyphs and progress, the
agent rows with their route identity (`category:name(model:effort)`) and
metrics, the fanout DAG while one is active -- plus a compact agent and plan
count in the status bar, in the app's own visual language (theme tokens, the
bundled panes' typography); the same HUD payload the OMH TUI's panels draw,
with formatters ported from the same retired widget, and the main session's
model from the app's own state, which the payload carries only per subagent
row. The route reads the
launch profile's home: the `profile` query the app appends when it routes a
non-primary profile through a shared backend is not honoured, as the host's
own bundled plugin backends do not honour it (a local non-primary profile has
its own backend and is unaffected). The half ships OFF: the marker forces it
disabled until the user switches it on under Capabilities -> Plugins, and that
decision lives in the app's renderer storage, which OMH neither reads nor
writes. The browser dashboard (`hermes dashboard`) reads the same
`dashboard/manifest.json` and registers a tab for every manifest; OMH marks
it `tab.hidden`, so that dashboard gets no `omh` tab (it still requests the
manifest's default entry script and logs its absence at console level).
_Avoid_: reading `desktop-plugins/` as install truth (it is the app's copy;
the bundle under `plugins/omh/` is what `omh update` refreshes), claiming the
half is enabled (not observable from OMH), claiming the app's own copy step
was observed (the pane and the status-bar item were observed from a
hand-placed standalone copy in an isolated home; the copy step is read from
the app's source), OMH TUI (that is the terminal surface)

### Host surfaces OMH reads

**Native tool presence**:
Whether a Hermes tool is available to a session: its name is in the
session's tool list OR in the tool_search catalog. A deferred tool is
reachable through the `tool_call` bridge and is present, and Hermes peels the
bridge before plugin hooks run, so its calls reach `post_tool_call` under its
own name. Stated once, by `native_tool_presence_clause` in
`src/plugin_bundle/omh/native_tools.py`, as text the model evaluates —
plugin hooks are handed no tool list, the model sees its own. Every surface
that relies on a native tool uses that clause and says what happens when the
tool is absent.
_Avoid_: gating on a Hermes version number (a version says what shipped, not
what this session was given), reading a deferred tool as missing

**Live TUI session row**:
A row in `$HERMES_HOME/state.db` `sessions`, scoped to `source='tui'`, not
ended, archived, or hidden, not a delegation child, ordered by the host's own
`last_activity_at`. Keyed on the durable session key
(`20260917_132533_8da9b8`), which is what the plan-todo records are keyed on
too. Read by `live_tui_session_rows` for the approval-bypass projection and
the plan-todo scope.
_Avoid_: treating an empty result as a negative answer (it means the question
is unanswerable here)

**Active-session lease registry**:
`$HERMES_HOME/runtime/active_sessions.json`, the host's own record of open
chat surfaces. One entry per lease, carrying the durable session key as
`session_id` and the gateway transport id as `metadata.live_session_id`,
alongside `surface`. It is the only place the two names for one TUI session
meet — the transport id appears in no `state.db` column — so it is how a
TUI session reference resolves to the session that owns a plan. Written by `_claim_active_session_slot`
(`tui_gateway/session_lifecycle.py`) on a session's first real turn, not at
creation, so a TUI nobody has prompted in is named by no entry.

This is a read-only coupling to a Hermes-private file shape, and part of the
plugin's compatibility surface alongside the hooks and tools:
`requires_hermes` in `src/plugin_bundle/omh/plugin.yaml` is a floor only (so a
new Hermes minor does not delist the plugin), and testing OMH against a new Hermes release includes checking that
the file, both field names, and the `surface` value still hold. If the shape
moves, the read must go quiet and the reference stay its own identity — never
fall back to guessing which session is reading.
_Avoid_: writing to it, treating it as a published API, reading a non-`tui`
lease as a TUI identity

**Hermes child usage ledger**:
The `sessions` rows of the disposable `HERMES_HOME/state.db` that
`omh coding hermes-child dispatch` hands its child, read once after the child
exits and before that home is removed (`src/coding/_hermes_child_usage.py`).
Hermes writes its `--usage-file` report for `-z/--oneshot` alone, and that mode
cannot read a prompt from stdin, so on the `chat --query-file -` transport the
ledger is the only record of the turn's spend: every API call queues
`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`,
`reasoning_tokens`, `api_call_count`, `estimated_cost_usd`, `cost_status`,
`cost_source`, `model`, and `billing_provider` into the row
(`agent/turn_usage.py` → `SessionDB.queue_token_counts`), drained at turn
finalize and again when the quiet CLI exits. The home belongs to that child
alone, so every row in the file is its spend and the rows are summed; the
result is the `-z` report's vocabulary, which the observation builder already
reads. The child runs with `--toolsets file --safe-mode`, so no delegate
subagent opens a row of its own and a context-compression rotation is the only
source of a second row. The sum equals the `-z` counters only because of that
restriction: a delegate child writes its own `sessions` row, and the `-z`
main-loop keys exclude subagent tokens while its cost includes them, so a
later `--toolsets` widening that admits delegation has to revisit this read.
The columns have been in the table since Hermes 2026-04, before the
`requires_hermes` floor.

This is a read-only coupling to a Hermes-private file shape, the same class as
the lease registry above: widening `requires_hermes` includes checking that
the table and these column names still hold. If the shape moves, the read goes
quiet and `usage` stays empty — never zero, never estimated.
_Avoid_: writing to it, reading it before the child has exited, reading any
`state.db` other than the disposable one the dispatcher created, treating an
empty result as a measured zero, treating a `timed_out` or `cancelled`
result's usage as complete (the child was killed, deltas still in Hermes'
daemon token-writer queue are lost, and the read is a lower bound with no
marker of its own)

**Stored prompt identity**:
The `Model:` line of the identity trailer Hermes ends every system prompt
with (`agent/system_prompt._timestamp_line`), as stored for a delegation
child in `state.db`: `system_prompts.prompt` by `sessions.system_prompt_hash`,
or inline `sessions.system_prompt` on older rows. Hermes builds the prompt
from the model the child was built with and creates the row with it before
the child's first model call. A fallback during a turn rewrites only the
in-memory copy (`rewrite_prompt_model_identity`), and the first accounted call
can rewrite `sessions.model` to the model that answered
(`first_accounted_route`). The stored prompt is rewritten from the RUNNING
model, which after a fallback is the fallback, in two places: an in-place
compaction (`compression.in_place`, on by default) archives the compacted
rows (`messages.active = 0`) and then stores a rebuilt prompt in the same row,
and a later turn whose stored identity differs from the running model stores
a rebuilt prompt at its start (a child's output-schema retry is a second
turn). So the line is read as the child's request, the requested side of a
HUD row's `model_attestation` (`src/plugin_bundle/omh/hermes_delegation.py`),
only on a first segment (`parent_session_id` is the delegating session) with
no archived message and at most one user message. Any other first segment
with a stored prompt is marked as possibly rebuilt. A compression continuation
names the previous segment and rebuilds its prompt, so it attests nothing. Not
covered: a row Hermes creates late (a retry after the create at turn start
failed transiently, or a re-create after the row disappeared mid-run) carries
the in-memory prompt, and nothing in the row marks it. The read takes the end
of the stored prompt, drops the runtime block at its last heading, and reads
the last paragraph only when every line in it is one `_timestamp_line` writes.

Without an attested request no agreement is reported. These cases read
`unknown`, and the basis says which:
- `requested_model_not_attested`: no stored first prompt names a model (none
  is stored, the row is a compression continuation, the schema lacks the
  columns, the read failed, or the trailer has no `Model:` line), and
  `sessions.model` agrees with the answering model;
- `requested_model_prompt_may_be_rebuilt`: a first segment's stored prompt was
  withheld (an archived message, or more than one user message), and
  `sessions.model` agrees with the answering model;
- `no_requested_model`: neither an attested stored prompt nor `sessions.model`
  names a model.

In the first two cases, a `sessions.model` that disagrees with the sole model
the usage rows name reads `disagreement`. The answering side is judged before
any of the three: no usage row (`no_usage_observation`) or more than one usage
model (`multiple_usage_models`) also reads `unknown`. It reads only the
child's own calls. Hermes records an auxiliary call (compression, vision, web
extraction, ...) in the same table under a non-empty `task`, on the aux
route's model. Such a row counts toward the child's tokens and cost, and
prices a child whose only calls were auxiliary, but it never names the
answering model.

This is a read-only coupling to a Hermes-private shape, the same class as
the lease registry above: widening `requires_hermes` includes checking the
trailer lines, the runtime-block markers, the two storage columns,
`messages.active` and `session_model_usage.task`. If the prompt shape moves,
the read goes quiet, unless the new last paragraph is itself made only of
trailer lines, in which case it is read as the trailer, as Hermes' own
`identity_line_value` would read it. A quiet read attests no request, so the
cases above apply. A missing `task` does not go quiet: the answering side
then counts every usage row, as it did before OMH read the column, so an
auxiliary row on another model reads `multiple_usage_models`.
_Avoid_: reading `sessions.model` or the current `delegation.model` as a past
request, reading a `Model:` line outside the trailer, reading the prompt of a
continuation, of a compacted row or of a later turn as the child's request

**Originating session stamp**:
`origin_session_id` on a fanout unit (and on the dispatch summary, for that
run's recovery attempts), copied by `omh coding fanout dispatch` from the
`HERMES_SESSION_ID` Hermes injects into every terminal command's environment
(`tools/environments/local._inject_session_context_env`) — the session-db id
of the spawning conversation, the same value `processes.json` records as
`parent_session_id`. It is the only link from a fanout unit to the
conversation that asked for it, and the cost receipt reads nothing else to
attribute a unit.
_Avoid_: attributing a unit by timing or by todo text, stamping a value that
is not id-shaped, reading an absent stamp as "belongs to no one" rather than
"not attributable"

**Detached fork**:
A turn Hermes runs on a copy of the live agent, built by
`build_cache_parity_fork` (`agent/background_review.py`): the background
memory and skill review after a turn, and the `/btw` side question during
one. The fork keeps the parent's `session_id`, mints its own task id and turn
id, and is marked `_persist_disabled`. It is the host's internal work, not
the person's turn, but every hook it reaches is called with the parent's
session id. Hermes 0.21.2 (tag `v2026.9.11`) and later skip
`on_session_start`, `pre_llm_call`, `post_llm_call` and `on_session_end` for
it. On every release its whitelisted tool calls still reach `pre_tool_call`,
`post_tool_call` and `transform_tool_result`. A review fork's whitelist is the
skill tools, the memory tools when memory is on, `read_file`, `search_files`,
and any tool `auxiliary.background_review.extra_tools` names. OMH counts a
review fork's `read_file` and `search_files` calls as direct reads of the
parent's session, so a fork could carry one of that session's delegation
nudges (at most two per session) on its own tool result; that is unmeasured.
Its final text still reaches `transform_llm_output`, where OMH's handler is
gated on the latch recorded under the turn id it is handed.

The plugin floor, Hermes 0.21.1 (tag `v2026.9.7`), has none of those skips.
OMH covers `pre_llm_call` itself: it returns nothing when a non-empty
`parent_session_id` equals `session_id` (#2112). That check misses a fork
built while the parent's session id rotates, because Hermes reads the two ids
at different moments: a `/btw` fork during a turn, and possibly a review fork
whose build, on its own thread, meets a compression in the person's next turn.
`on_session_start` reaches only a fork routed to another model, and OMH's
handler there restores only a route whose writer session is no longer live.
The `on_session_end` call itself carries no `parent_session_id`. Telling a
fork's turn end apart is still possible: 0.21.1 hands `pre_llm_call` and
`on_session_end` the same `turn_id`, so the turn id `pre_llm_call` saw for a
fork could be recorded and skipped at the turn end, with the same rotation gap
as #2112. That correlation is not built, so the fork runs the whole handler as
a turn end of the parent's session. Calling OMH's hooks with the arguments a
0.21.1 fork sends (read from Hermes source) shows what the fork's turn end
does:

- The delegation-route restore is scoped to the task that wrote the route,
  and the fork's task id is its own. A route written during a Hermes turn,
  whose tool call the host hands that turn's `task_id`, stays in place
  (`not_last_writer`). A route recorded with no task id is matched on the
  session alone: if it was recorded under the person's session id, the fork's
  turn end puts the person's baseline back, and if it names no session it
  stays (`not_last_writer`). A `/btw` fork can end inside the person's turn,
  so that restore can land before the dispatch the route was written for.
- Where OMH runtime state exists, the fork rewrites the metadata-only
  `runtime/plugin-session-end.json`. The file names no session, but
  `omh_status` reports it as `plugin_session_end`, so its `observed_at` can
  be the fork's turn end rather than the person's.
- Before Hermes 0.21.4 (tag `v2026.9.21`) `transform_llm_output` is passed no
  `turn_id`, and OMH's handler returns nothing for an unkeyed turn, whether
  it is a fork's or the person's.

What a person sees in the common case: their delegation route is untouched,
and at most the `plugin_session_end` time in `omh_status` belongs to the
fork. The route case needs a route recorded under the person's session id
without a task id, which a tool call inside a Hermes turn never produces;
whether another 0.21.1 dispatch path does was not checked. None of this was
observed on a live 0.21.1 host, so its impact is unmeasured. Upgrading Hermes
to 0.21.2 or later removes the turn-end part. Raising `requires_hermes` to
`">=0.21.2"` would remove it too, and was rejected: the bundle's `register()`
refuses a host below the floor, so the plugin would stop loading on every
0.21.1 host over a residual with no observed effect, and
`HERMES_COMPAT_MATRIX` (`src/install/plugin_compat.py`) holds real-host
admission evidence for 0.21.1 only.
_Avoid_: reading a hook call that carries the person's session id as the
person's turn, raising the floor to close this residual

### Fault domains

**OMH install fault**:
A managed artifact under a host root is missing, stale, or was never refreshed
on this machine; the repo itself is fine. `omh doctor` proves it — it reports
plugin and managed-skill state — and `omh setup` or `omh update` fixes it. Measure the domain before assuming one: this and the Hermes
user-config fault are cheap reads and come first, an OMH product fault needs a
clean-tree reproduction, and a Hermes-side fault comes last and only with both
of its proofs in hand.
_Avoid_: opening a PR for it, reaching for `hermes update`

**Hermes user-config fault**:
A user-owned key is set inconsistently with what the reporter expects —
`model.default`, `model.provider`, `model.base_url`, or a display key. Reading
the key proves it. OMH reports the inconsistency and stops there. Every
display key (`display.interface`, `display.skin`, `display.sections`) is the
person's: OMH writes none. Earlier versions wrote all three, so setup and
update run a one-shot release per config (`release_managed_display`): a
value OMH's record says it wrote and that still reads that way goes, or goes
back to the value consent replaced; an `omh*` skin goes with or without a
record, its theme saved under the OMH home first; a value the person changed
since, an unrecorded `display.interface` or section, and every noncanonical
YAML shape stay byte-for-byte. The record then carries
`display_released_at`, and from that pass on no display value in that config
is read as OMH's. Dry-run previews the release and never persists it. Check
this fault alongside the install fault, before reproducing anything.
_Avoid_: writing a display key, re-running the release on a config whose
record says it ran, filing it as a product fault

**OMH product fault**:
The behaviour reproduces from a clean install and on the repo dev tree,
independent of the reporter's machine — prove it by running
`uv run python -m omh.cli …` in a clean checkout. The fix is a repo change
with tests, which makes this the only fault domain that produces a PR.
_Avoid_: claiming it before a clean-tree reproduction

**Hermes-side fault**:
Hermes Agent's own code or built assets are genuinely behind, which is what
makes `hermes update` the answer. Two proofs are required together, never
either one alone: `git -C "$HERMES_HOME/hermes-agent" rev-parse HEAD` behind
that repo's `origin/main`, and the built Modern-TUI bundle older than its
TypeScript sources. A visual symptom that reads as "an old TUI" is almost
always an OMH product fault or a Hermes user-config fault instead (a current,
freshly built Hermes has shown exactly that symptom over an OMH product gap).
OMH never patches Hermes either way.
_Avoid_: prescribing `hermes update` from a visual symptom alone, treating one
of the two proofs as sufficient

### Repo guard vocabulary

**Byte gate**:
A CI check that compares a generated artifact byte-for-byte against its
regeneration from source (`omh docs … --check`). A one-character drift fails;
the fix is always to edit the source and regenerate, never the artifact.
_Avoid_: lint (byte gates prove provenance, not style)

**Routing corpora**:
The two named guard corpora for router changes: `ROUTING_PRECISION_CASES`
(negative controls; failure metric `overroute_count`) and
`ROUTING_INTERVENTION_CASES` (positive interventions; failure metric
`missed_intervention_count`). Every trigger change ships cases in both.
_Avoid_: underroute (that name matches nothing in the code)

**Budget ledger**:
The one module (`src/maintenance/drift.py`) that measures every per-turn and
footprint number, holds its limit and kind (`ratchet` | `ceiling`), and renders
the verdict (`drift_report()`, also `verdict`). `skill_content_smoke` and
`omh release drift` read their budget verdicts from it.
_Avoid_: a second comparer, a count or headroom formula restated in a test

**Managed artifact**:
A file OMH installs and refreshes under a host-owned root and may safely
overwrite on setup/update — the plugin bundle, managed skills, and the config
keys OMH inserted. The status widget and the skin files earlier versions
installed are managed artifacts in one direction only: setup, update and
uninstall remove them where a manifest (or, for a skin, the shipped bytes)
proves OMH wrote them, and keep and name any the person edited. OMH writes no
display key; `--no-omh-tui` is accepted and does nothing. Everything else
under a host root is user-owned and preserved.
_Avoid_: overwriting anything OMH did not write without explicit consent,
writing a display key

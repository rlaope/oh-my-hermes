# OMH TUI Boundary

What the OMH TUI (the frontend bare `omh` opens) and its gateway child send,
answer, write, and may import. `AGENTS.md` (Implementation Boundaries) states
the boundary in brief and points here; this page is its full statement.
Tests under `tests/test_tui_*.py` pin these sentences against the code, so a
behaviour change moves the code, this page and its test together. Glossary
terms (OMH TUI, Hermes gateway protocol, Modern TUI) are in `CONTEXT.md`;
what a user sees is in [Installation](INSTALLATION.md).

## Launch and the gateway child

The OMH TUI is the frontend bare `omh` opens. `omh` runs the user's own `hermes
--tui` with `HERMES_TUI_DIR` pointing at OMH's packaged frontend, so Hermes'
launcher still resolves the profile, resume target, working directory and
session ownership, then starts OMH's frontend in place of its own. A session
the person closes there exits with OMH's own code (`CLOSED_EXIT`) instead of
0, which Hermes' launcher prints no exit summary for (it prints one, naming
`hermes --tui --resume`, only for 0 and 130); `omh` then prints its exit
card, with only the `omh` way back, and returns 0. That
frontend spawns one child at a time, with the interpreter, import path and
environment the launcher handed it, and speaks the stdio JSON-RPC of Hermes'
`tui_gateway` to it. The child is `src/tui/attach/gateway_attach.py`, run by
path on Hermes' interpreter and imported by nothing in OMH. On a Hermes that
has the shared-gateway attach API (Hermes 9595c3f345 and later refuse the stdio
entry beside a running gateway) it reaches the profile's gateway as Hermes' own
Ink TUI does, whether or not one was running: Hermes' `ensure_gateway_runtime`
finds it or starts it (an unmanaged gateway daemon with idle exit, or the
gateway service the person installed, which Hermes starts through launchctl or
systemd), a session ticket comes from the home's private control socket, and
`websockets.asyncio.client.connect` dials the loopback socket Hermes names. It
translates between the stdio wire and the gateway's canonical one only where
they differ (the launch policy riding `session.create`, a detach for a close, a
rewind as Hermes' revision-fenced `session.mutate`, a steer or a stop carrying
the execution generation of the turn it acts on, images staged through
Hermes' `image.attach_bytes`, approvals and clarify questions the gateway asks
as events, and a command the person typed that the gateway's `slash.exec`
refuses but runs through a call of its own, `/compress` and `/undo` among
them, sent as that call, as Ink sends it), and passes everything else as it
is. On any other Hermes it runs
Hermes' stdio entry in its own process, as before. Which one is decided by what
imports in that Hermes, never by an error's wording. When that child exits on
its own with a failure (never after a normal exit, after the person quits, or
for a gateway another runtime owns), it spawns it again the same way and
resumes the session that was open (`session.resume`), at most 3 times in 60 s,
as Hermes' own TUI does: the open question and those waiting behind it close
unanswered, a turn that was running is reported lost and never sent again, and
past that limit it exits as it would without recovery, naming `omh --resume
<id>` (with `-p` for a named profile) when `omh` launched it, and `hermes --tui`
otherwise. A reply that shows the gateway no longer speaks the declared
contract ends the session the same way. The attach refusal still names Hermes'
own terminal: the OMH TUI cannot open a session another runtime's gateway owns.

## What it sends and answers

It relays only what the person types; on its own it reads Hermes' settings and
command catalog as a session opens and, at a fresh start, `session.list` to
name the last session under the banner, reads the config file's mtime
(`config.get mtime`) and Hermes' configured default model (`model.options`
naming no session) at the launch, the mtime again at each turn's end and
before each prompt that starts a turn, and the default again when the mtime
moved, and, beyond opening and closing
sessions (`client.capabilities`, `session.create`, `session.resume`,
`session.close`), sends only what this bullet names below, plus
`session.history` again when Hermes refuses a rewind; when no turn runs, a
steer Hermes refused as an ordinary prompt; and, at once, the decline frame for
a request it cannot show (a vault unlock or save-login prompt, a terminal,
preview or window read, a preview action, a tour, a display sudo install, a
clarify with no question in it, or a method it does not know). It never answers
an approval, clarify, sudo, or secret request on its own, apart from declining
at once a request it cannot show (listed above): Esc or Ctrl+C declines, an
approval decline is an explicit deny and then interrupts the running turn
(`session.interrupt`, only while a turn runs; every deny the person gives an
approval does, `d`, `n` and Enter on deny too, except the tell row's below),
allowing a command takes the arrows and then Enter, and a request the gateway
withdraws (its own timeout, an interrupt) closes without an answer. Hermes'
`always` choice is offered only when the request lists it and is sent, like any
allow, only on the person's arrows and then Enter; saving it as a permanent
allow (`command_allowlist`) is Hermes' doing, and like allow this session for
one session it stops Hermes asking about commands that match. An approval's
last row, "no, and tell Hermes what to do instead", sends the explicit deny at
once, interrupts nothing, and then opens the composer for what the person tells
Hermes instead; Esc there sends nothing more.

## Leaving a session, approvals and session settings

Leaving a session (`/new`, a switch) declines that session's open requests and
says so in the new transcript. Shift+Tab is the one key that changes what
Hermes asks; the approval answers above change it only for the commands they
match. Shift+Tab may turn on Hermes' per-session yolo, the switch it sets in
Hermes' own TUI, which stops Hermes from sending approval requests for that
session; the TUI still answers none, because Hermes then sends none. It does
this only on the person's keypress, with a `config.set` that names the session
and an explicit value and never a `scope`, so it never writes the global
`approvals.mode` and never sets the switch for the gateway process. Leaving a
session it turned yolo on for, or whose yolo call is still unanswered (`/new`,
a switch, `/quit`, any exit), it first sends that session an explicit off,
since Hermes keeps yolo through `session.close` for a session a messaging
gateway started. The mode is shown on the info line under the composer (which
stays while a list the person picks from hides the composer) only once Hermes
confirms it for that session; when turning it on, an answer that confirms
anything else is a failure, followed by an explicit off, and accept is shown
again if Hermes does not confirm that off either; and `session.info` corrects
what is shown, so yolo that Hermes reports for its own reasons is shown too,
except that one saying approvals are on within 2 seconds of a confirmed on is
held until the next, keeping accept shown. Ctrl+T and `/effort` set that
session's reasoning effort through the same session-scoped call. A pick in the
`/model` picker (bare `/model`, listed from `model.options`, or `/model
--refresh`, listed from `model.options` with `refresh`), and a typed `/model
<name>` with at most `--provider <slug>`, is sent as `config.set model` naming
the session with the value `<name> --provider <slug> --session`, as Hermes'
own TUI sends it (attached to a shared gateway, the gateway child sends it as
the owner's `session.mutate model`), so it switches that session only; a typed
`/model <name>` carries `--session` only when the person typed it, so on
Hermes' stdio entry Hermes' own rule (`model.persist_switch_by_default`)
decides whether it also persists, as for Hermes' typed `/model`; a name
or slug that could read as a flag is left out of the list and is never sent,
and a `/model` with any other flag goes to Hermes' `/model` as typed. The one
switch the TUI makes on its own is this one: when Hermes' configured default
model moved since it was last read (the person or the agent edited Hermes'
config), it switches the session to the new default at the next turn boundary,
never during a turn: at a turn's end, or before the prompt that starts the next
turn, which waits for that check (an edit made while no turn ran then reaches
the very next turn). It says so in one line; a refusal leaves the session as it was
and says why. A target Hermes asks to confirm (cost, data policy, a large
context), from a pick or from this switch, is a question the TUI asks in the
slot, keeping the session's model first and selected; only the person's
"switch anyway" sends it again with `confirm_expensive_model`, and Esc keeps
the model; a prompt waiting on that check goes once the person answered, on
the model they chose. It never switches because
the session runs a model other than the default, so one picked with `/model`
stays until the default itself moves (owner, 2026-10-25). `/cost` and
`/permissions` run Hermes' `/usage` and
`/approvals`; the latter shows or sets Hermes' persistent approval mode, as
typed. Plan mode is the frontend's own flag, also turned on with Shift+Tab:
while it is on, a prompt the person types goes to Hermes as `/plan <text>`.
While Hermes has approvals off on its own (an off it confirmed did not end
them, or they were off without the TUI turning them on), Shift+Tab sends
nothing and turns only plan mode on and off.

## Steers

A steer (Ctrl+Enter, `/steer`, or what the person sends from the composer the
tell row opened) sends into the running turn only text the person typed and
sent that way, and the tell row's text goes as an ordinary prompt once the turn
has ended; the TUI never steers on its own, and a queued prompt becomes a steer
only when the person presses the send-now key (Ctrl+Enter or Ctrl+J on an empty
composer), which takes the oldest one. A steer Hermes does not take waits in
the TUI's own queue for the running turn to end, whatever the busy mode, so it
never interrupts that turn. A steer Hermes does not answer within its answer
budget (120 s, longer when held behind a /compress) goes back to the composer
and is never re-sent.

## Look

Its look is the rail and kind colours the owner picked on 2026-10-22: each
transcript block on a thin `┃` rail with no fill (grey for the person's prompt, the
skin's accent for a reply, a call's state colour for the call), a call's state
in its mark's glyph and colour as the dag view draws it (running blue `○`, done
green `●`, failed red `✗`), its name in its tool family's hue at 4.5:1 on dark
and light, consecutive skill loads and tool-detail reads folded into one row,
and the composer between two full-width rules with no side edges; none of it
changes what the TUI sends or answers.

## Agent views

The subagent views (the agent view under the info line, always expanded while
there are agents, as the owner asked on 2026-10-21; the list Down opens on its
rows; one agent's log) read with `subagent.tail` only, the tail of the log the
person opened. In a dag run the agent view is a folding tree, as the owner
asked on 2026-10-22: a header row per node (a fold triangle, its state glyph,
its label, then category, model:effort, status and tokens), under an open node
its child's latest call and latest line (thinking, Hermes' progress line or its
reply), running and failed nodes open, layers set apart by blank rows, folded
to fit the view's cap before a count row cuts it; Down gives the tree the keys
(the arrows and Space fold), and a new turn keeps the open run's lanes in the
roster. A run that is over leaves the view as the turn that ended it ends (the
owner's call of 2026-10-26); its end print in the transcript and `/dag` keep
its graph. Two keys in the agent list, and in the tree on the highlighted node's
child, act on that agent, and only on the person's keypress: `x` interrupts it
(`subagent.interrupt`) once a second `x` confirms, and `s` steers it
(`subagent.steer`) with text the person then types and sends; the TUI never
interrupts, steers or answers for a subagent on its own.

## Shell commands, rewind and mouse

A line the person sends that starts with `!` is their own shell command: the
TUI sends it with `shell.exec`, which Hermes runs outside the model's context
under its own 30 s limit and dangerous-command refusals, shows what it printed
and its exit code when that is not 0 or nothing was printed, and sends nothing
else that way: only a line whose leading `!` the composer showed (a collapsed
paste whose text starts with `!` goes to the model), never a refused steer or a
queued prompt that happens to start with `!`. A rewind (Esc Esc on an empty
composer, `/rewind`) cuts the session's history before the prompt the person
picked, and only when they send the prompt that replaces it (`prompt.submit`
with `truncate_before_row_id` and `confirm_truncate`). Mouse reporting (clicks,
the wheel and a held button's motion, modes 1000, 1002 and 1006, never 1003)
is on only while the agent list or the `/theme` picker takes clicks (clicks and
the wheel, without 1002) and in a pager, and off while the window is resized
and on every exit. With `OMH_TUI_MOUSE=1` it is on wherever the TUI can tell
which screen row a report lands on: on the main screen a drag, a
double click or a triple click selects rows the live region printed, by their
place in what it printed (`LiveRegion.doc_row`), shows them reversed and
copies them; a row it cannot map for certain is never guessed at, and the
wheel up opens the transcript view. Without it the wheel and a drag on the
main screen are the terminal's. A plain left click on an
agent opens its log, one on the list's `main` row leaves the list. In a pager
the wheel scrolls, and in a pager and on the main screen a drag, a double
click or a triple click copies what it
selected, rails and a reply's margin left out: as OSC 52 to a terminal that
honours it as it ships (kitty, Ghostty, WezTerm, Alacritty, outside tmux),
through `pbcopy` on a Mac with no SSH between it and the screen (inside tmux,
only once a fixed `tmux show-environment SSH_CONNECTION` answers within 1 s
that the variable is not set), and otherwise as OSC 52 the footer says was
only sent. A report that starts
while reporting is on, or within 0.5 s after it goes off, types nothing if it
arrives whole within 0.8 s of its first byte. If 300 ms pass after that byte
without the next, the byte is read as Esc, and the rest is dropped only if it
arrives within 0.5 s after that. One that starts later and is split right after
its first or second byte is read as keys.

## The bot board

The bot board (Ctrl+S, `/bots`, `src/tui/bot_board.py`) only reads. For the
Hermes root the TUI runs under and each named profile beside it
(`<root>/profiles/<name>/`), it reads `gateway_state.json`, `config.yaml`,
`profile.yaml` (for Hermes' display name only), Hermes' `memories/MEMORY.md`
and `USER.md` (each only as a regular file, at most 1 MiB), the directory listing of the OMH store's `memory/records/` when
`config.yaml` names that store, and `state.db`, the latter opened `mode=ro`, and immutable when no `-wal`, `-shm` or
`-journal` is beside it (no connection has it open), so SQLite creates no
`-wal` or `-shm` there; with a connection open, the read takes its read mark
in the existing `-shm`, as every reader of the store does. It never opens the
store outside SQLite, since closing a descriptor on it would drop this
process's SQLite locks on it. It probes the pid a gateway record names with
signal 0 and reads that process's start time and state (`/proc` on Linux,
`sysctl(KERN_PROC_PID)` on macOS) and, for a running gateway, its resident
memory (`/proc/<pid>/statm`, or `proc_pidinfo`, which answers only for this
user's processes); it sends no other signal, and nothing to the gateway. It reads on one thread for the session, never on the render path,
and reads nothing while the board is closed.

## Sessions it refuses, and what it writes

It never attaches to a session another runtime owns: when the launcher sets
`HERMES_TUI_GATEWAY_URL`, it exits and names `hermes`. It writes no transcript,
attachment, secret or server-request frame to disk or to a log, and prompt text
in one place only: each line the person sends from the composer is appended to
Hermes' own input history, `$HERMES_HOME/.hermes_history`, the file `hermes
--tui` reads and writes, in its format (`+`-prefixed lines under a `#`
timestamp line). It only appends there (opened `O_APPEND` and `O_NOFOLLOW`,
created mode 0600), reads at most the file's last 1 MiB and only when it is a
regular file (no symlink or FIFO), and never writes an answer to a question
Hermes asked or masked input there. An image the person attaches (Ctrl+V, a
drop, `/image`) is a file Hermes stages and names; the TUI reads that file
once, only when it is a regular file of at most 20 MB (opened `O_NOFOLLOW`
and `O_NONBLOCK`), keeps its bytes in memory and nowhere else, and has
Hermes let go of it (`image.detach`). A prompt that goes with the image
stages those bytes again through Hermes' `image.attach_bytes`, the call
Hermes' own remote clients use, and nothing else is staged until Hermes has
taken them. The other files it writes are metadata: the
launcher's active-session file (the session id); when `omh` launched it, the
file `omh` named in `OMH_TUI_SESSION_FILE`, in `omh`'s private 0700 launch
directory (opened `O_NOFOLLOW`, mode 0600), holding the open session's id, the
Hermes home it runs on and the ids of the sessions this launch had open
before, which `omh` reads for its exit card and removes with the directory;
the relaunch marker beside it, when the person picked a restart after an update;
and what OMH's own HUD reader
and model-chain picker already write under the OMH home (the HUD fan-out cache
and its lock, and the chains `/omh-model` saves), and a fallback marker at the
path `omh` named, holding what the TUI printed about why it did not start,
which `omh` prints again once Hermes' own terminal (which clears the screen)
closes, and then removes. A pasted clipboard image is saved by Hermes' own
clipboard helper where Hermes stages images, as the stdio entry saved it.

## Connections and the import allow list

The frontend makes one network call of its own, the update notice: at most
once a day per OMH home, on a background thread, an HTTPS GET of npm's latest
`oh-my-hermes` version from `registry.npmjs.org`, keeping only the version
(`tui/update_notice.py`, listed in INVARIANT 2's `NETWORK_CLIENT_BRIDGES`; off
with `OMH_TUI_UPDATE_CHECK=0`, `omh theme update-check off`, or `omh
update-check` set to `off`). Beyond that it opens no socket. It strips the sidecar and
attach URLs from the child's environment, and reaps the child when it exits,
SIGTERM and SIGHUP included; the child's only connections are the two above, to
the person's own Hermes home (the WebSocket goes to the URL the gateway's grant
names). INVARIANT 2 holds it to a closed allow list measured from it
(`HERMES_INTERPRETER_SCRIPTS`, which the owner approved as asyncio and
websockets only, loopback to the person's own gateway): the imports it makes,
Hermes' functions named one by one, the `asyncio` names it uses,
`websockets.asyncio.client.connect`, and a list of attribute and reflection
names it may not use. The script builds exactly one `AttachApi`, in
`attach_api()`, with that function's own nested `grant`; `connect` goes only
into its `dial` slot; `dial` is called only on an object traced, by name, to
`attach_api()`'s result, with the url `grant()` returned on that same object,
and always with the literal `proxy=None`; no `_`-prefixed attribute is read
except on `self` inside a method of a class it defines, and `self` is bound
nowhere else; `type` is not used outside annotations; and `os.environ` changes
only as the `TERMINAL_CWD` set-and-restore and the removal of
`LAUNCH_POLICY_ENV`, whose one binding anywhere, a module-level assignment, is
pinned to its literal tuple. That blocks the realistic drift of a later edit
calling another Hermes, network or subprocess helper; it is not a sandbox, and
does not catch an allowed Hermes function called with other arguments, or check
where the grant's url points.

## herdr

Inside a herdr pane, and only there (`HERDR_ENV=1` and a `HERDR_PANE_ID`, the
pane environment herdr's own Hermes plugin is gated on too; that plugin only
reports a session id, never a state), the TUI tells herdr the state its title
shows, so herdr's agent list can name it: it runs `herdr pane report-agent
<pane> --source omh:tui --agent omh --state <state>`, with `waiting on you` as
`blocked`, `running` as `working` and `idle` as `idle`, each time that state
changes and never per frame, and `herdr pane release-agent` on the way out,
since herdr keeps the pane's agent after the TUI exits until told. The agent
label is `omh`, one herdr does not know: a known label (`hermes`) would tie
the report to herdr's own Hermes process and screen detection. The binary is
an absolute `HERDR_BIN_PATH` or `herdr` on PATH, the person's own; the verbs
and flags are fixed and only the binary and pane id come from that
environment, with no text from the session. One call runs at a time on a
worker thread, so the loop never waits on herdr, and only the newest waits
behind it (a later change replaces it, and the release replaces any report
and stops the one in flight); each call gives up after 1 s and fails without
a word (no herdr, a dead socket, a timeout), and an exit waits at most 2 s
before it stops the release. herdr's CLI reaches herdr over its own local
socket: no network call. Outside herdr nothing is spawned. No session id is
sent: herdr keeps one only from its own `herdr:*` sources.

The gateway child does not get the pane's `HERDR_PANE_ID`; herdr's CLI and
skill still work there, without a current-pane default. herdr drops the same
one name for its own pane-less popups. Where the gateway runs, herdr's Hermes
plugin (gated on `HERDR_ENV=1` and that id) would otherwise report a
`herdr:hermes` session for the pane, and herdr then refuses the TUI's own
reports from then on (measured on herdr 0.9.5: the pane stayed at `working`,
or left the list); a gateway daemon started from the child would also keep the
pane's id after the pane closed.

## Restarting Hermes' gateway

`/gateway restart`, typed by the person or offered once after an update (see
Restarting after `omh update`), restarts Hermes' gateway
(`src/tui/gateway_restart.py`, in INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`);
`/gateway` with anything else goes to Hermes as typed. It is offered only
attached to a shared gateway, with a session to reattach to. It first asks in the slot, naming what the gateway's record
(`gateway_state.json`, read as the bot board reads it) says the restart
affects: the profiles it serves, the messenger platforms connected to it, the
work it runs (turns and cron jobs), and this session's own turn. For a gateway
a custom supervisor runs (`--external-supervisor` in its recorded argv) that
running work finishes first, up to `HERMES_RESTART_AFTER_TURN_TIMEOUT` when
it is set, else `agent.restart_after_turn_timeout` read from the gateway
home's `config.yaml`, as Hermes reads them; any other gateway drains the same way
if Hermes' own systemd or launchd service runs it (Hermes sends it SIGUSR1,
which its argv does not show), so the slot says the drain depends on a service
running it, and otherwise the work is interrupted. Without a live record it
says who else uses the gateway is unknown. In a named profile the shared
gateway serves it offers two restarts: that profile alone (Hermes re-serves it
inside the shared process at once, so the profile's running turns stop now;
new OMH code is not loaded) and the whole gateway (`-p default`, as Hermes'
Desktop addresses that process), which the drain line names.
Nothing runs unless the person picks one. Then it runs Hermes' own command as
Hermes' updater runs it, `<HERMES_PYTHON> -m hermes_cli.main -p <profile>
gateway restart --yes --detach`, with the interpreter and import path the
launcher handed the TUI and without Hermes' gateway markers, in a session of
its own, stdin closed and its output in an unnamed temporary file (unlinked
as it is created) of which only the last lines are read back, into memory.
Hermes decides the rest (the service manager, the drain, a profile its shared
gateway serves); the TUI signals no gateway and kills no process. While the
command runs, however long, the TUI respawns no gateway child, and sends
nothing that calls the gateway except `/stop` (what else the person sends
goes back to the composer; Esc and Ctrl+C still interrupt); past 180 s it
says once that it still waits. Once the command succeeds it reattaches to the
same session as a respawn does, outside the respawn's limit, trying a gateway
that is not answering, or not resuming, again each second for up to 60 s; the
composer's draft stays and nothing is sent again. Exit 0 alone is not taken
for a restart: only a changed owner epoch says the gateway is back, and
otherwise Hermes' own last lines are shown. It says the gateway now runs the
newer OMH only when the gateway's recorded start had preceded the plugin
bundle's install before the restart and no longer does after it. A failure
says Hermes' words and the command to run instead.

## Restarting after `omh update`

`omh update` moves `<installer root>/current` and leaves a running TUI on the
generation it started from. A TUI that runs from an installer generation reads
that link at most every 5 s (`src/tui/generation_watch.py`: one `readlink`; once
it differs, also the update's state file; no network call, nothing written). A
move counts only once that file names the generation active: the pointer moves
before the update has finished, and a failed update moves it back and deletes
that generation. Then the info line says `restart to update`, and a TUI `omh`
launched asks once, in the slot, with Not now first, and only when a restart
could go at once. The same check holds the question and a Restart already
picked: a running turn, one about to start (the TUI's own `continue`, Hermes'
queued redirect), a `/compress`, a session switch, what the session waits on
between turns (background processes that wake it, delegated children), a `!`
line or a slash command still out, a `/bg` or `/btw` answer still out, Hermes'
gateway restarting, another open question, an open pager or picker, and what the
person typed or queued. A pointer that moves back cancels a Restart still
waiting.

The TUI restarts nothing itself. It creates the marker `omh` named
(`RELAUNCH_FILE_ENV`, in `omh`'s private launch directory, opened `O_NOFOLLOW`,
mode 0600, holding `plan` in plan mode and otherwise empty) and exits
`RELAUNCH_EXIT` through its normal shutdown, so the terminal is handed back as
at any exit. Plan mode carries over; yolo the TUI set goes off, as at any exit. The `omh` waiting on it then starts
`<installer root>/current/venv/.../python -P -m omh.cli` with its own homes,
scope and profile and `--resume <id>` (`src/commands/bare_launch.py`, in
INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`), and holds its own generation until
that exits. A 78 without the marker is an ordinary exit code. A new TUI is not
told to restart again: the generation it runs is the one `current` names.
`UPDATED_ENV` in that launch makes the new TUI offer `/gateway restart` once,
with Cancel first, when the shared gateway still runs older OMH plugin code. It
never restarts the gateway without the person's pick. Each such restart leaves
one waiting `omh` holding its generation until the session ends.

## Job control, and what OMH does not do

Ctrl+Z stops the process group, the gateway child with it, as Hermes' own CLI's
Ctrl+Z does, and fg continues both; a shared gateway, which is not in that
group, goes on. Stopped for longer than the shared gateway waits on a send (30
s) while it streams a turn, the child is dropped as a stalled peer, and at fg
the TUI spawns it again and resumes the session, as after any lost connection.
OMH itself still makes no LLM call; every model call, and every other network
call the gateway makes, is Hermes'. This is a foreground terminal the person
launched, not a background runtime, a transport bot, or a third process bridge:
the child relays one terminal's frames and executes nothing; a gateway it
started is Hermes' own, which exits once idle.

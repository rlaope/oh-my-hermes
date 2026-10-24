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
session ownership, then starts OMH's frontend in place of its own. That
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
rewind as Hermes' revision-fenced `session.mutate`, images staged through
Hermes' `image.attach_bytes`, approvals and clarify questions the gateway asks
as events), and passes everything else as it is. On any other Hermes it runs
Hermes' stdio entry in its own process, as before. Which one is decided by what
imports in that Hermes, never by an error's wording. When that child exits on
its own with a failure (never after a normal exit, after the person quits, or
for a gateway another runtime owns), it spawns it again the same way and
resumes the session that was open (`session.resume`), at most 3 times in 60 s,
as Hermes' own TUI does: the open question and those waiting behind it close
unanswered, a turn that was running is reported lost and never sent again, and
past that limit it exits as it would without recovery, naming `hermes --tui`.

## What it sends and answers

It relays only what the person types; on its own it reads Hermes' settings and
command catalog as a session opens and, at a fresh start, `session.list` to
name the last session under the banner, and, beyond opening and closing
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
`/model` picker (bare `/model`, listed from `model.options`) is sent as Hermes'
own `/model <name> --provider <slug> --session` through `slash.exec`, so it
switches that session only, and a name or slug that could read as a flag is
left out of the list. `/cost` and `/permissions` run Hermes' `/usage` and
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
has ended; the TUI never steers on its own, and a queued prompt is never turned
into a steer. A steer Hermes does not take waits in the TUI's own queue for the
running turn to end, whatever the busy mode, so it never interrupts that turn.
A steer Hermes does not answer within 120 s goes back to the composer and is
never re-sent.

## Look

Its look is the rail and kind colours the owner picked on 2026-10-22: each
transcript block on a `┃` rail with no fill (grey for the person's prompt, the
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
roster. Two keys in the agent list, and in the tree on the highlighted node's
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
with `truncate_before_row_id` and `confirm_truncate`). Mouse reporting is on in
one state only, the agent list open, and off in every other and on every exit.
A plain left click on an agent opens its log, one on the list's `main` row
leaves the list, and every other report does nothing. A report that starts
while reporting is on, or within 0.5 s after it goes off, types nothing if it
arrives whole within 0.8 s of its first byte. If 300 ms pass after that byte
without the next, the byte is read as Esc, and the rest is dropped only if it
arrives within 0.5 s after that. One that starts later and is split right after
its first or second byte is read as keys.

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
Hermes asked or masked input there. The other files it writes are metadata: the
launcher's active-session file (the session id), and what OMH's own HUD reader
and model-chain picker already write under the OMH home (the HUD fan-out cache
and its lock, and the chains `/omh-model` saves), and a fallback marker at the
path `omh` named, holding what the TUI printed about why it did not start,
which `omh` prints again once Hermes' own terminal (which clears the screen)
closes, and then removes. A pasted clipboard image is saved by Hermes' own
clipboard helper where Hermes stages images, as the stdio entry saved it.

## Connections and the import allow list

The frontend opens no socket and makes no network call, strips the sidecar and
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

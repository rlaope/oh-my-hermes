# Changelog

All notable changes will be documented here.

## Unreleased

![Sprite Forge patch notes](https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/assets/omh-sprite-forge-patch-notes.png)

- **A rename's stale export is named before the turn ends.** When a turn
  leaves a Python module exporting a name it no longer defines, OMH names the
  line at the turn's first stop as `path:line`, so the model can fix it. That
  covers an `__all__` entry, and a `from module import name` whose workspace
  module no longer has the name. It needs no language server and is silent
  otherwise. Measured on four models, the rename template that models kept
  missing went from 8/12 to 12/12, with +3 of that from the note itself. The
  pre-registered gate failed on its token clause (1.097x against 1.05x), and
  the owner overrode it because the gap was run-to-run variation
  ([measurement](benchmarks/live-model-tools/v1/README.md)).

- **Vim mode in the composer.** With Hermes' `display.vim_mode` on
  (`hermes config set display.vim_mode true`, then start `omh` again), the
  OMH TUI's composer edits modally, read from the active profile's config.
  It starts in INSERT, where every key works as before except Esc, which
  goes to NORMAL and closes the `/` or `@` menu, and does nothing else: it
  no longer arms the clear or the rewind, cancels nothing and interrupts no
  turn. In NORMAL a letter is a command, never text:
  `h l 0 ^ $ w b e j k gg G`, `i a I A o O`, `x X dd D C cc S s r`, `d c y`
  with a motion, `p P`, `u` and Ctrl+R, with counts, and Esc there does
  what it always did, so Esc Esc still clears or rewinds; during a turn,
  Esc on an empty composer arms the interrupt and a second Esc sends it.
  Enter sends from either mode, and in NORMAL always sends, a `\` before
  the caret included. Paste chips and image tokens
  are one character to every command, `p` puts them back with their text
  or image, and the info line says `INSERT` or `NORMAL`. Questions Hermes
  asks, masked input, the tell row, pickers and the agent list keep their
  own keys. The supported set and how it differs from Hermes' own Vi mode
  are in the Installation guide. With the setting off or absent nothing
  changes. Requested by Dan Rio (#2434).

- **The exit card drops its `resume:` label.** Leaving the OMH TUI prints
  the session's title and, after a blank line, `omh --resume <id>` alone,
  ready to copy.

- **`agent-debug` sees a turn that ended without a reply.** A new finding,
  `silent_turn_end`, cites a turn whose last tool result was followed by an
  empty assistant row and then nothing: no reply, no further call, until the
  next user message. It cites the tool row and the empty row, the call, and
  the result's exit code (130 for an interrupted command). When one is found,
  the incident leads with `turn_ended_without_reply` ahead of correlations
  such as a compaction or an unwatched background process, because the
  silent end is the symptom itself, and proposes reading the host's agent.log
  `Turn ended: reason=` line for that timestamp before changing anything.
  Both state.db and `--session-record` are read; without `tool_calls` the kind
  is listed unavailable.
- **The `/theme` picker scrolls on a short terminal.** Where the slot held
  fewer rows than there are launch looks, the arrows still reached the
  looks past it, but they were never drawn (on a 16-row terminal, ember; on a 24-row one, kanagawa-wave).
  The list now scrolls so the highlighted look always shows, moving only
  when the highlight would leave it, and a click lands on the look drawn in
  that row.

- **A Kanagawa Wave theme and launch look.** `omh theme use kanagawa`
  selects an indigo palette with warm ivory text and muted blue and violet
  accents, adapted from rebelot/kanagawa.nvim (MIT, Copyright (c) 2021
  Tommaso Laurenzi). Like the other four it sets no background, so the
  terminal's own shows through. `/theme kanagawa-wave` selects the matching
  launch look: a rule above and below on a dark sumi-ink ground (Kanagawa
  Lotus on a light terminal), with an ocean swell for its living wallpaper.
  Contributed by Dan Rio (#2436).
- **A failed CI or merge watcher no longer leaves the session silently
  stopped.** When a watcher you armed exits non-zero, its notice opens a turn;
  that turn now starts with a short directive: if the work it watched is still
  the session's to finish, do it and arm the next wait, otherwise say plainly
  that the session has stopped and what you have to decide. If the turn ends
  with nothing armed anyway (no notifying background process, background
  delegation or scheduled follow-up job), the reply ends with one sentence in
  its own language saying nothing will wake the session again. Both halves
  read only records: the host's row kind and notice header, and the turn's own
  tool results. A killed watcher, a zero exit and a person's own message get
  nothing.

- **A steer reads as the prompt it is.** A steer you send during a turn
  shows as a prompt row (`❯ <text>`), as Claude Code shows one, in place of
  the dim `↪ steer queued by Hermes · <text>`. It stays dim right above the
  working row until the turn takes it in, at the first tool that finishes or
  when the turn ends, then reads as any prompt you sent where the model got
  it. Hermes reads a steer only between steps, so one sent during a long tool
  call waits there until that call ends. A turn you stop before taking it in
  says `not read — the turn stopped first`.

- **`OMH` in the info line's badge is a pale silver blue.** It was the
  faint grey of the brackets around it; it now reads in `#C3D2E3` beside the
  launch look's `Native`, moved toward black on a light background as far as
  body-text contrast takes.

- **A coding turn ends with one consistency check, when the edit has a copy
  or a reference elsewhere.** When a turn in the coding posture edited source
  code, OMH can continue it once at its first stop. It asks the model to look
  for other copies or call sites of the logic it changed that have to change
  with it, and to fix them, without re-running tests for the check. That is one
  extra round, so after a Python edit it is skipped when none of the four
  signals below is found in the workspace's other Python and config files.
  It fires when:

  - a changed definition is also defined in another file;
  - a removed or renamed name is still used in another Python or config
    file;
  - a function whose signature changed is named in another file, or a class
    whose constructor, annotated fields or abstract methods changed;
  - a replaced line appears in another file.

  It also fires, as before, when that search cannot be made:

  - a non-Python source file changed;
  - a Python file changed with no pre-edit text kept for it: through `sed`,
    `execute_code` or a delegated child, or past OMH's snapshot limits;
  - a changed file does not parse or is too large;
  - a change touches no definition, import or docstring;
  - the workspace walk passes 5,000 entries or its time limit (a workspace
    that ran over is not walked again for five minutes);
  - a Python file or a directory in the workspace is a symlink that leaves it;
  - an unedited Python file is too large or unreadable;
  - any error.

  There is no other fallback. A change the four signals cannot see is skipped:
  a function body that changes behaviour without changing its signature,
  and a reference that exists only in prose such as docs. The search skips
  hidden, version-control, virtualenv, cache and `node_modules` directories,
  and build output: a `build` directory holding a `lib`, `lib.*`, `bdist.*`,
  `temp.*` or `__editable__*` directory or no `.py` file in its first two
  levels, or a `dist` directory with no top-level `.py` file. Any other
  `build` or `dist`, such as a scripts directory or a namespace subpackage, is
  searched.

  On the bench corpus the always-on check fixed a second copy of the changed
  logic far more often: 76 vs 38 of 90 runs, pooled over five measurements. It
  cost about 1.37x the median tokens. The trigger kept those fixes and stopped
  the check on edits with no copy: 0 of 54 sessions against 54 of 54, with the
  same passes. Strong models' median tokens fell to 0.68x and 0.75x of the
  always-on check in two runs. One clause of the pre-registered gate failed in
  each run; the owner overrode it. The decision is recorded in
  [the bench README](benchmarks/live-model-tools/v1/README.md#owner-decision-2026-10-31).

  If nothing more changed, the model replies with the single line
  `OMH: no further changes.`, and OMH puts the answer it had already given
  back in that line's place, so `--oneshot`, API and delegating callers get
  that answer unchanged. Hermes's own CLI shows the restored answer a
  second time; the OMH TUI keeps the one line. Delegated children never get
  the check. `agent.max_verify_nudges: 0` turns it off, together with OMH's
  other end-of-turn nudges.

- **`omh update` no longer deletes the skill pack a running Hermes gateway
  still uses.** A gateway follows `current/skills` to the generation behind
  it once and keeps that directory until it restarts. Update kept only the
  active and the previous generation, so two updates in a row deleted the
  one the gateway was serving, and Hermes showed zero OMH skills (`skills
  89 installed` on the launch card, OMH's 0) until a restart. Update now
  records when each generation was activated and also keeps the one that
  was current at each gateway's last recorded start, in the default home
  and every profile, until a later update sees that gateway started again.
  The `hermes gateway restart` hint still names the restart that picks up
  the new pack. With no recorded start, retention is unchanged. The old
  command runs the cleanup, so this holds from the update after the one
  that installs it.

- **The background-process row moves onto the info line, and the working
  row keeps its blank row on a tall terminal.** The row that names a
  process Hermes runs in the background stood above the composer's top
  rule; it is now on the info line under the composer, after the badge and
  the branch (`[⚚ OMH Native]  ✳ background  terminal(<command>)  8s`), with
  its colours, its ticking clock, who will be told when it ends, `+N more`
  and the finished state whose Enter reports the result. The title, model,
  context and effort stay on the right. As the line narrows the title goes
  first, then the row shortens and goes, and only then do the model, the
  context and the effort shorten. During a long turn on a tall terminal,
  `✻ Working…` read glued to the last tool row, since a turn's rows cut
  short gave up the blank row over the working row first. That blank row
  now stays, and the oldest row goes instead, while six rows still show
  above it; on a shorter terminal it still gives way first, so it never
  costs one of the few rows.

- **The info line shows the context as a gauge with its token counts.**
  The bare `ctx 37%` under the composer is now
  `ctx ━━━━──────── 37% 74k/200k`: twelve cells, the filled ones and the
  percent in the context's colour (warning from 80 % full, error from
  95 %), the rest dim, then the tokens the context holds of the most it
  can, in `k` and `M`. On a narrow
  line the token counts go first, then the gauge, leaving `ctx 37%`, before
  the context goes. Under `NO_COLOR` the filled and the empty cells still
  tell how full it is.

- **A `/compact` that is still running shows it is.** Hermes can take a
  minute or more to summarize the older turns, and until its report came
  the screen showed only the started notice and nothing moved, so a
  compression that was working read as a stuck one. While a `/compress` (or
  `/compact`) is out and no turn runs, the working row now shows a spinner
  and `Compressing…` with the time it has taken so far, and it goes away
  when the report or the unanswered notice lands. It offers no Esc, since
  Esc between turns sends no interrupt and so does not stop a compression.
  The working glow does not start for it, and a prompt typed meanwhile
  still goes out as before.

- **The default look keeps the terminal's own background.** Spectrum set
  its navy ground with OSC 11, and Otty took a set background only on the
  cells written after it, so the launch card showed holes of the terminal's
  own black. The default look, which draws no picture, now takes the
  terminal's background as its ground; the other looks keep theirs.

- **The working glow is smaller.** The light that goes round the screen
  while a turn runs read too big and hid most of the top row's text as it
  passed. Its trail is half as long (a seventh of the way round, from a
  third), so it covers half as much of that row at a time, and the top and
  bottom rows are half a row thick, without the faint tint they laid under
  the light's inner half.

- **The default look, spectrum, keeps its background colour and draws no
  picture.** Its pixel aura is gone: the wallpaper still sets spectrum's
  ground, and the other looks keep their scenes. An idle screen on
  spectrum no longer wakes four times a second to paint nothing.

- **The living wallpaper is pixel art, in the brand's pixel-aura style.**
  The scenes drew their motifs in characters (`%t;:`, rings of `O`), which
  read as broken text. Every scene is now drawn in half blocks, two square
  pixels to a cell (`▀` in the top pixel's colour over the bottom one's,
  `▄`, and a space on the colour where both match, since a block glyph
  leaves the terminal's line spacing as a stripe), in the language of the
  `oh-my-hermes` pixel-aura short: a mosaic of solid square tiles, dense in
  the middle and scattering out to single tiles, with four-point `+`
  sparkles that grow and fade. spectrum is the pixel aura itself, in the
  short's violet, pink, cyan, mint and periwinkle; the other looks keep
  their motif in the same language, from small bitmaps kept as data: a clean
  crescent moon in a pixel halo with soft tile clouds, pastel jellyfish with
  pulsing bells, a sun in a breathing glow, blossom clusters with falling
  petals, ribbons of scattered tiles, a flickering flame in a warm glow with
  rising embers, and a cloud raining into a rippling puddle. The motifs sit
  low on the right, where the launch card and a working session's rows leave
  the screen blank, and a big screen (140×40 or more) draws the sprites' art
  pixels two pixels square. The rules are unchanged: blank cells only, never
  in the scrollback, at most a sixth of the screen lit, no pixel past 3:1
  against the ground; colours keep their hue under that cap (mixed from a
  dark shade rather than into the ground) and a motif's shades are spread
  within it instead of collapsing onto it.

- **Korean typed from Termius keeps its spaces where they were typed.**
  Termius sends every syllable a Korean (or other) input method commits as
  its own bracketed paste, and on a slow link the space typed after a
  syllable arrives in the same read. The OMH TUI asked Hermes whether each
  one-line paste was a dropped file and typed it only once Hermes answered,
  while the space went in at once, so `안녕 하세요` came out as `안 녕 하세요`
  and the last syllable of each word slid past its space. Only a paste
  shaped like a path (`/`, `~`, `./`, `../`, a drive, `file://`, the same
  first test Hermes' drop detection makes) still waits for that answer; any
  other text paste is typed at once, in order with the keys around it.

- **`omh coding run --owner codex` finishes when an agent shell starts it
  (#2402, reported by @vince2930).** Every unit inherited the dispatcher's
  stdin. An agent shell such as Hermes' terminal tool keeps an open pipe on
  that stdin and never closes it, and `codex exec "<prompt>"` reads a piped
  stdin to EOF even with the prompt in argv, so the unit waited until its
  deadline and failed as `timeout` (exit 124) whatever `--timeout` said. A
  unit, a declared verification command and the dispatcher's git calls now
  get the null device as stdin; the workspace preflight's git blob, the one
  call that passes input, still goes through its own pipe.

- **A game now passes visual QA only when it boots, answers input and keeps
  running, and a scene is looked at after every change that affects what
  renders.** While building, `frontend` captures the affected surface (for a
  3D or canvas scene the default camera and each declared preset) and reads
  the capture before the next change; a change not looked at is not done,
  and the final 1440/768/375 loop still runs. `visual-qa` gains
  `references/playable-check.md`: a game or interactive scene passes when
  the booted first frame is not blank or one flat colour, the frame after
  the declared input differs where the input should move something, idle
  frames seconds apart differ (background-only animation does not count),
  and the console shows zero errors across boot and input. A missing capture
  is BLOCK, reading code never passes, and a run with no WebGL context is
  recorded as `environment: no_webgl` instead of being judged a blank frame.

- **A Kimi main session now gets a short execution calibration of its own.**
  The new `omh.main-calibration` system-prompt section renders once at session
  start (no per-turn cost) for a main session whose model resolves to the Kimi
  family: decide minor choices and note them, ask only before irreversible or
  externally visible actions, call the obvious tool instead of describing it,
  read the request's verb (explain or check answers, build or fix does the
  work), and bound repeated searches. Delegated children (`platform ==
  "subagent"`) get nothing from it and keep `omh.child-calibration`; every
  other family renders nothing until an A/B shows it needs a block.

- **The OMH TUI's background-process row shows for a local session.** A
  local session's process is recorded under its route,
  `agent:<namespace>:local:dm:<stored id>`, which the row never matched,
  so it never appeared. It now matches that key or the bare stored id, and
  no prefix or suffix of either. With `compression.in_place: false` the
  row and an unreported end now survive the rotation to a new stored id.
  The row's spinner steps once a second, like its clock, so an idle session
  with a process draws 1 frame a second, not 6, and none under the pager.
  A messaging session resumed in the TUI (a bot profile's Telegram chat)
  shows the processes its own turns and its subagents started, matched on
  the route Hermes records on the session's row and on the spawning
  session's id; after a `/new` on the same chat, neither conversation
  shows the other's.

- **A steer sent while a reply streams no longer erases that reply.** When
  Hermes read the steer before a second model call, the OMH TUI replaced the
  whole streamed text with the last call's at turn end. Once you steer, what
  streamed now stays as it was, and only what the final adds past it (a
  footer) is added. The `↪ steer queued by Hermes` row shows after the reply,
  not between the two calls: Hermes sends nothing that marks where one call
  ends, so the TUI cannot place it there reliably. A long one-paragraph
  reply now wraps only its last rows each frame, so a frame no longer costs
  more as the paragraph grows; agent names drop a goal's trailing colon
  (`Interrupted child alpha.`); and `/title X` shows the title bold instead
  of `**X**`.

- **An approval no longer folds away the `cd` or the assignment that aims a
  risky command, and it marks a download piped into a shell and a
  world-writable `chmod`.** `cd ~ && …; rm -rf ./*` and `T=/; …; rm -rf
  "$T"/*` used to show only the `▲ rm` row with the `cd` or `T=/` inside
  `+ N other commands`; a directory change (`cd`, `pushd`, `popd`) or a
  variable assignment (`T=/`, `printf -v`, `${T:=/}`) now stays listed
  whenever a listed command comes after it, and `echo`-like noise still
  folds. When rows run short and Hermes named a risk OMH found, the
  spacing and the rule go first, then the rows fold step by step, the
  last one before each risky command going last, then every row that is
  not risky: a `▲` row is never cut while another command's row shows,
  and at the same number of `▲` rows no command that may change something
  is hidden where the slot used to show it. When Hermes named none,
  nothing folds and the slot lists and cuts from the end as before, risky
  rows too. A quoted here-document body (`<<'EOF'`) inside `$(…)`, such
  as a commit or PR body, is read as text; an unquoted one's `$(…)` and
  backticks are read for what they run, a `<<` inside `$((…))` is a
  shift, and a here-string (`<<<`) or a nested subshell (`((cd a; rm -rf
  b); ls)`) hides nothing after it. A download run as a script
  (`curl … | sh`, `bash <(curl …)`,
  `eval "$(curl …)"`, `sh -c "$(wget -qO- …)"`, and inside a `-c` script,
  a substitution or after `then`), decoded text piped into a shell
  (`base64 -d | sh`, `xxd -r`, `echo | tr`, `openssl … -d`), `find
  -delete` or `-exec rm`, and `chmod` with a mode that lets others write
  (`777`, `666`, `o+w`, `a+w`) now get their own `▲` row, the cases
  Hermes' approval table flags; `echo "$(curl …)"`, `x=$(curl …)`,
  `diff <(curl a) <(curl b)` and `find … -print` do not.

- **Each OMH TUI launch look now has a living wallpaper: its own background
  colour and a scene that keeps moving.** While the TUI runs it sets the
  terminal's background to the look's colour with OSC 11 and puts the
  terminal's own back on every way out: on exit, after a crash or a signal,
  while the job is stopped with Ctrl+Z, and as soon as the wallpaper is
  turned off. Each scene has one or two motifs drawn big in dense
  characters, with light particles round them: moonlit is deep navy with a
  large crescent moon whose glow pulses, drifting clouds and twinkling
  stars; sakura dusky plum with a blossoming branch and falling petals;
  aurora deep teal with tall waving curtains of light; ember dark brown-red
  with a flickering campfire and rising sparks; gold a large sun with
  turning rays; violet large drifting bokeh; graphite rain over a rippling
  puddle; spectrum a prism fanning a beam into five hues. A light terminal
  gets each look's pale ground. The theme is measured against the ground,
  and every word and mark also keeps its floor against the terminal's own
  background, where the session's rows stay after exit; a look changed
  mid-session prints the session again on its ground. At most a sixth of the
  screen is lit and no cell passes 3:1 against the ground; the scene is
  drawn on blank cells only, never over text, a band or into the scrollback:
  blank rows whole and the tail of a row with text two cells past it, the
  transcript's rows too, so the motifs on the screen's right side stay in
  view over a full session (a selection across rows then copies those
  glyphs; `/wallpaper off` keeps it clean), repaints only the cells that
  changed every 0.25 s, pauses while the composer holds text, and stands
  still with reduced motion. It shows at truecolor on a terminal that
  answered the background query, not under `NO_COLOR`, and not where `/theme
  light|dark` names the other side from the terminal's own. It is on by
  default; `/wallpaper on|off` (alone, it switches) and `omh theme wallpaper
  on|off` save the choice as `wallpaper` in the theme record, and
  `OMH_TUI_WALLPAPER=0` holds it off in one terminal. The `/theme` picker
  shows each look's colours on its ground.

- **Copying from the pager after an emoji copies the right text.** The
  pager's drag, double click and highlight counted columns by code point
  while the row is painted by glyph, so after a ZWJ family, a skin-tone or
  VS16 emoji the cells under the pointer were the wrong ones (a double click
  on the next word copied nothing) and the highlight could change style
  inside one emoji, breaking it. They now count by glyph, as do the recall
  glint and the running box's aura in `/dag`. A copy hands back the text's
  own code points, so a decomposed macOS path from `/logs` still matches its
  file, and a subagent's log row and a bot's message are cut between glyphs,
  never inside an emoji, a flag or a letter with its accent. `/logs` shows a
  tab as spaces and no longer lets a colour code in stderr shift the columns a
  click or a drag lands on.

- **The second Ctrl+C of the OMH TUI exits, and the launch, a resize and the import cost less.** After a
  Ctrl+C interrupts a turn, the queued prompt it puts back in the composer no longer eats the second press:
  that press exits as the info line says, with Shift or Alt held too, and only while the line says so; after
  an interrupt it says so over an open steer, rewind or tell as well. What the
  composer holds is not kept on exit; prompts already sent or queued are in Hermes' history, where Up finds
  them, and a submit still waiting on its pasted image keeps the press from exiting. The launch logo's contrast lift
  parses each colour once and is cached (first paint about 12.6 -> 10.3 ms, same bytes); a full redraw
  prints the rows it measured instead of rendering the kept blocks twice (a long session's settled resize
  about 270 -> 205 ms); and the bot board's module loads when the board opens, not with the TUI.

- **The OMH TUI has eight launch looks, and a look now tints the chrome.**
  `/theme` adds `sakura` (pastel pink, sky blue and cream), `moonlit`
  (moonlight yellow and silver over navy), `aurora` (emerald and teal into
  violet) and `ember` (amber through orange to crimson) to `spectrum`,
  `violet`, `gold` and `graphite`, each with a set for dark and one for
  light backgrounds. Every look, the four earlier ones too, now also paints
  the composer's rules and the frames drawn like them in its card-edge
  colour, and a tool call's rail and the working row's spinner in its label
  colour, each lifted to 3:1 against the background; a failed or denied
  call's rail stays red. Body text, the grey details, the reply's rail and
  the state colours keep the theme's, and `spectrum` stays the default with
  its logo unchanged. The picker, `/theme <look>`, Tab completion and the
  saved `launch` key take the new names; an unknown saved name still warns
  and falls back to `spectrum`.

- **The working glow no longer blanks the screen's top row.** While a turn
  ran, the OMH TUI painted the whole top row as the light's track, so that
  row's text (the logo's first line on the launch screen, or the oldest
  row of a short session) was hidden for the whole turn. The row's own text
  is now painted again under the light, and only the cells the light
  reaches cover it.

- **`/glow off` turns the OMH TUI's working glow off, and it now shows in a
  short session too.** `/glow on|off` (alone, it switches) is saved beside
  the theme under the OMH home, so it holds in every later session;
  `omh theme glow on|off` saves the same choice from the shell, and
  `omh theme glow` shows it. `OMH_TUI_GLOW=0` still holds it off in one
  terminal. The light used to be
  drawn only once the session filled the screen; it now goes round a
  session of any length, over the blank rows under it. A prompt's band no
  longer runs into the right margin the glow keeps: it ends one column in,
  as it starts one column in on the left.

- **A light goes round the OMH TUI's screen while a turn runs.** It runs
  along the terminal's whole edge, clockwise, once every four seconds, with
  a round head and a trail in the launch look's logo colours that fades
  out; nothing else of the edge is drawn, and it is gone when the turn
  ends. It moves by the clock and repaints the edge every 0.05 s, so it
  glides round corners instead of stepping. It needs the truecolor depth
  with motion on; `OMH_TUI_GLOW=0` turns it off. To keep the edge free, the
  TUI draws its rows one column in from each side and keeps the screen's
  last row blank, whether a turn runs or not, so nothing moves as the light
  comes and goes. The light is taken off before anything scrolls, so none
  of it reaches the scrollback.

- **Gemini 4 Argon replaces Gemini 3.1 Pro in the shipped chains.** Google
  made Argon generally available on 2026-10-13. Every slot 3.1 Pro held now
  names `gemini-4-argon` at the same effort: `writing` and `google-search`
  at `medium`; `visual-engineering`, `artistry`, `x-search`, and
  `synthesize` at `high`; and the X-platform affinity. The id has an exact
  contract read from ai.google.dev: 1M unified context, 65,536 output per
  synchronous request (1M with long decode), and a `low`/`medium`/`high`
  thinking ladder with `medium` as the default and no off switch. `off`
  and `minimal` are raised to `low` on record; `xhigh` and `max` pass
  through, because nothing documented sits above `high`. Dated snapshots
  project onto it. Cost estimates use the 2/10 list price with 0.10
  cached input, which rises to 4/20 on 2026-12-01. Provider checks know
  that Google's API and OpenRouter serve it. On Hermes, 3.1 Pro's `medium`
  slots were sent as `low`, because Hermes allows only `low` and `high` for
  a Gemini 3 Pro id. Argon's `medium` is sent as `medium`. Gemini 3.1 Pro
  is retired under the superseded-generation rule. It stays recognized,
  priced, and provider-mapped, so `omh model-chains set` can still name
  it. The `gemini` family calibration applies unchanged. Both site pages,
  the generated install table, and the model-setup skill say so. This is
  an editorial change (owner decision) and has not been measured: no
  served Gemini route was available to probe.

- **Six more model categories you can route a subagent to.** `google-search`
  (Gemini 4 Argon first, for research grounded in Google Search), `x-search`
  (Grok 4.7 first, for live search on X), `review` (GPT-6.1 Sol at xhigh, so
  a different model tries to break the diff), `swarm` (DeepSeek V4.1 Flash
  at low, for many parallel workers), `forensics` (GPT-6 Astra at xhigh, for
  root-causing a live symptom or a trace) and `synthesize` (Claude Opus 5.5
  at xhigh, for merging many results into one answer) join the eighteen
  shipped chains, in the Hermes lane, the Codex and Claude Code tables, the
  delegate-route tool and the public chain table. Each chain ends on a model
  from another provider. They are opt-in: no role or task size picks them,
  so every existing route is unchanged. Two heads repeat an earlier
  category's (`forensics` shares `ultrabrain`'s, `synthesize` shares
  `architect`'s), so an unrouted child on those models is still labelled
  with the earlier name; a lane routed through `omh_delegate_route` keeps its
  own. Six HUD labels move with the new chains: DeepSeek V4.1 Flash at low
  now reads `swarm`, Gemini 4 Argon at medium `google-search`, Kimi K3.1 Pro
  at high `x-search` and at xhigh `review`, and GPT-6.1 Sol at xhigh and
  Grok 4.7 at high, which had no label, read `review` and `x-search`.
- **The pager copies on drag, without the transcript's left bar.** In a
  pager (Ctrl+O, `/history`, `/logs`, `/dag`, an
  agent's log, the bot board) the TUI now takes the mouse: the wheel scrolls three lines,
  a drag selects and copies on release without the rails or a reply's
  margin, a double click copies a word and a triple click a row, and the
  footer says `✓ copied N chars to clipboard`. The copy is OSC 52 for kitty,
  Ghostty, WezTerm and Alacritty, `pbcopy` on a local Mac otherwise, and
  else OSC 52 the footer says was only sent. The main screen keeps the
  terminal's own selection, since taking the mouse there would take the
  wheel and the scrollback, and there each block keeps its thin `┃` rail,
  which that selection copies: a painted full cell that copied as a space
  read too heavy. Under `NO_COLOR` your prompt's rail is the light `│`, so
  it is told apart from a reply's.
- **Fourteen more models cost out at their vendors' list prices.** OMH
  already recognized Grok 4.7, 4.6, 4.5 and 4.3, DeepSeek V4 Pro, Gemini
  3.8 Flash, 3.6 Flash and 3.5 Flash-Lite, GLM-5.3-FlashX, Qwen3.8-Max and
  Qwen3.8-Flash, Solar Pro 4, MiniMax-M3 and MiniMax-M3.1-Flash, but it had
  no price for them, so a run on one that the host recorded no cost for
  showed no estimate. Each now
  carries the first-party list price read on 2026-10-28, with its cached-input
  rate where the vendor publishes one. The rows also note what the table
  cannot represent: Grok's 200K whole-request tier, DeepSeek's off-peak half
  rate, the Gemini Flash introductory price that doubles on 2027-01-01, and
  MiniMax-M3's 512K tier. The xAI, DeepSeek, Gemini and Z.ai ids also get
  provider checks; Qwen, Solar and MiniMax have no provider family to name.
  No shipped chain named any of them until Grok 4.7 joined `x-search` (above). GLM-5.2 was costed at the GLM-4.x rate
  (0.6/2.2) and now uses its own 1.4/4.4. Its Ultrafast serving moves from a
  halved figure to the same base rate, as no separate tier rate is published.
- **The route hint stops saying the same thing twice.** Route hint text is
  about 18% of the OMH text a model reads per session, and part of it repeated
  other text in the same block: a hint's `adjacent_workflows=` line that equals
  the block's top-level one, and a `fallback_action_label=` or
  `next_action_label=` that only respells its action's underscores. Each one
  now renders only when it differs from the text it would repeat. Rendered
  before and after on the same 68 routing-intervention hints, the block went
  from 106,957 to 98,121 characters (8.3%), and no hint grew. Selection, the payload, `first_response_shape=` and
  `not_evidence_yet=` do not change, and the per-turn ratchets drop with the
  render (`pre_llm_call` 5786 -> 5632, fallback 7338 -> 7184).
- **A long turn in the OMH TUI no longer ends with blank rows over the
  composer.** Once a turn's output scrolled the prompt off the screen, the
  `↳ you:` reminder and the blank row over it took two rows on the bottom
  rows. That scrolled two transcript rows into scrollback, where nothing can
  bring them back. When the turn ended, the region kept its height, so the
  done line (`✻ 7m 11s · 12 tools`) stood three blank rows above the
  composer, and with the plan shown any turn left one more over the plan,
  whose own blank row the running turn had. The frame that ends a turn now
  gives up the rows nothing in it takes: the reminder, its blank row, and the
  blank row over the plan. The done line sits one blank row above the
  composer or the plan, as between any two blocks. The composer rises by
  those rows, at most three, left blank under the footer, and the next turn's
  output takes it back to the bottom rows.
- **The answer-first plan line stops repeating its whole rule.** While a
  plan is open, every turn a person opens carried the 445-character
  `TODO_ANSWER_FIRST_RULE`, and Hermes keeps each turn's injection in history
  until compaction (11,125 characters over 25 turns in one owner's three
  days). The rule now spends the reconciliation rule's turn budget: whole on
  the three turns after any plan write, then `TODO_ANSWER_FIRST_RULE_SHORT`
  (253 characters), which keeps the precedence, both incident guards and the
  record-first resume. A live A/B over five models, a checkable claim in a
  person's turn after 20 quiet plan turns, counted unchecked agreement or
  deferral in 1 of 119 turns with the short line, 2 of 120 with the full rule
  and 4 of 48 with the pre-#1705 drive.
- **A routed session carries the route hint's boundary sentence once.** Every
  `[OMH Route Hint]` closed on the same 197-character `Boundary:` line, and
  Hermes replays each hint, so a session routed on several turns held one copy
  per turn (3,090 characters over 15 hints in one owner's three days). A later
  hint now drops the line when the host-injected part of history already
  carries it; a first hint, an unreadable history, or a person quoting the
  line keeps it, and the route fingerprint is still taken from the whole hint.
- **Character sprite sheets become aligned game frames (`sprite-forge`).**
  An image model draws a character sheet whose frames differ in scale and
  foot position, so the character swells and bobs in game. The new
  `sprite-forge` skill keeps the sheet a grid on flat `#FF00FF` (never a 1xN
  strip, wide effects in their own sheet) and ships an optional standalone
  Pillow helper, `toolkit/scripts/forge.py`, that keys the background,
  splits cells, applies one common scale and puts every body's feet on one
  shared baseline. `qc.json` records `body_scale_cv` and `anchor_y_std`
  against 0.08 and 0.05, and a `REGENERATE` verdict exits 3 so the sheet is
  redrawn rather than patched. Without Pillow, `--help` still works and any
  processing request exits nonzero with no output. OMH generates no images;
  the host's own image tool draws the sheet. (#2335)
- **`visual-qa` checks motion in animated and simulated output.** A new
  `references/motion-continuity.md` checks spawn position against the
  declared origin, per-frame displacement against the declared speed, force
  direction against observed motion and monotonic HP bars, and it replays
  the deploy, travel and engage flow independently instead of reading it
  off cost or clear numbers. (#2335)
- **`show-reel` captures reels from a running game.** `references/game-capture.md`
  keeps events, sound cues and titles in one `timeline.json`, pins the game
  build, holds a reel whose gameplay event has no sound cue, and records a
  real voice's source URL, hash and excerpt; impersonating a real voice is
  refused. (#2335)
- **`deliverable-package` tracks `archived` and `published`.** A file is
  archived only with its hash, version and catalog row read back, published
  only when the destination's own URL resolves to the same hash, and the
  final file is the one the person approved, never the newest mtime. (#2335)
- **An approval in the OMH TUI shows every risky command, not just the one
  Hermes named.** Hermes names a command line by the first dangerous pattern
  it matches, and the slot printed the line as one wrapped block. One real
  request chained 14 commands and read as "recursive delete", while the same
  block force-removed a worktree, force-deleted two branches and deleted a
  remote branch. The slot now splits the line at its top-level `&&`, `||`, `;`
  and line breaks, keeping a here-document with its command and reading no
  comment. Each command is listed on a row of its own, and each one that runs
  `rm` recursively or on a path from `/`, deletes or force-pushes a remote
  branch, force-deletes a local branch, force-removes a worktree, hard-resets
  or force-cleans is marked `▲`, with the home directory written `~` where the
  shell would read it so. Only when the list does not fit, and Hermes' own
  description names a risk the slot marked, do the commands that change
  nothing (`cd`, `echo`, `ls`, `grep`, read-only `git` and `gh` and the like,
  writing no file, with no assignment in front and no risk inside quotes) fold
  into one `+ N other commands (cd, git, …) · ctrl+o shows all` row; every
  other command stays listed. Hermes knows far more dangerous patterns than
  the slot, so when it flagged one the slot does not know, nothing folds and a
  long list is cut from its end with the usual Ctrl+O marker. Risks Hermes did
  not name get a `✦ OMH also sees:` row under its header. Quoted text and the
  arguments of `echo` or `grep` never match. Each choice now has an icon and a
  tone: `✗ deny`, `✓ allow`, `★ always allow`, `✎ tell Hermes`. The
  highlighted one is bold on a band of its tone. Ctrl+O still pages the
  command whole, as Hermes sent it. Deny stays first and selected, and the
  keys do not change.
- **The OMH TUI says when OMH caught a model mistake.** OMH's catches
  reached only the model, so an install looked like it did nothing. Now the
  moment one happens the transcript gets one row, `✦ OMH` stepped through
  the launch look's logo colours and the words in its label colour, so it
  follows `/theme`: `✦ OMH 🔁 stopped a loop of N identical calls` (the
  repeat guard's first refusal of a streak), `✦ OMH 📖 pointed the re-read
  at line 1667` (the first note on a truncated read's refused re-read),
  `✦ OMH 📋 kept going, plan has 2 open items` (a turn continued over an
  open plan), and `✦ OMH ⏰ flagged a wait with nothing armed to wake it`
  (the turn's unarmed remote-wait directive). Nothing prints otherwise, and a resumed
  session does not replay earlier catches. The hooks record each catch
  beside their unchanged decision in `<omh_home>/runtime/catches.json`
  (`omh_catch_log/v1`): a kind from a closed set and small integers, never
  model text, arguments or paths; the HUD payload carries the reading
  session's newest few as `catches`.
- **The OMH TUI shows a session's background processes, and offers Enter
  when one ends unreported.** A `terminal` command Hermes ran in the
  background with `notify_on_complete` off ended without waking the
  session, and nothing on screen said work was still running. While this
  session owns one, a row above the composer says
  `background  terminal(<command>)  1h 07m 13s` and, once the turn is over,
  who will be told: `🔔 will ping you when done`, `🔔 will ping you on a
  match` (watch patterns), or `🔕 Hermes won't be pinged · OMH is watching
  it`. When a process in that last state ends after the turn, the row turns
  green, `✓ … finished 0:12 ago` (`+N more` when others ended too), the bell
  rings once, and Enter on an empty composer sends one prompt asking the
  session to check the results; nothing is sent on its own. The TUI reads
  Hermes' `processes.json` read-only, matches rows on the session's own key,
  and asks a host process by pid and recorded start time whether it still
  runs. A process it cannot ask that way (a sandbox, or off POSIX) says
  `🔕 won't ping you · ask Hermes for the result` instead, shows only while
  its row is listed, and is never called finished.
- **A generation's own skills pack is never registered, and a home left on
  one is moved to the pointer.** 4.0.3 stopped `omh setup` from registering
  the running generation's pack (`generations/<id>/skills`) beside the shared
  `current/skills` pointer -- once the next update moved the pointer, every
  OMH skill resolved to two files and Hermes listed none of them -- and
  retires such entries from every home. `omh chat
  --auto-apply-target-change`, the last writer of that path, now registers
  the pointer too. A primary home naming only an older generation's pack is
  migrated to the pointer the way a bot profile already was, instead of
  being read as the opt-out and losing every OMH skill once the pack is
  collected; only the installer-managed command, which retires the pack in
  the same write, counts it as a registration. A relative entry, which
  Hermes anchors at its own home, never matches.
- **A skills entry spelled through `${VAR}` is matched the way Hermes reads
  it.** Hermes expands `${VAR}` and `~` in `skills.external_dirs` before it
  resolves an entry, but setup, update and `omh doctor` expanded only `~`,
  so `${XDG_DATA_HOME}/omh/generations/<id>/skills` beside the pointer was
  neither retired nor reported and the home lost every OMH skill once the
  pointer moved. Such entries are now expanded first; one whose variable is
  unset is left untouched, as Hermes leaves it. A Windows entry rooted
  without a drive (`\omh\...`), which Hermes loads from its home's drive, is
  matched on every Python version instead of through 3.12 only. A relative
  entry, which Hermes reads under its own home, is no longer resolved
  against the directory `omh` runs from, so update cannot retire it or read
  the home as registered through it, and doctor cannot count it as a second
  managed directory. Uninstall's
  check for a store another Hermes home still names, `omh hermes
  readiness` and the installed-skill weight advisory expand entries the same
  way and read a relative one under the home that names it, so uninstall
  keeps a store a home names as `../omh/skills`.
- **Setup, update and doctor read every skills entry from the home that
  names it.** The registration migration, the generation-pack retirement,
  the two-directories finding and the registered check now read a relative
  entry under that Hermes home and a Windows entry rooted without a drive
  on the home's drive, as Hermes does, instead of skipping the first and
  resolving the second on the drive `omh` runs from. So `../.omh/skills` or
  `../omh/generations/<id>/skills` beside the pointer is retired and
  reported, and `omh update` run from `D:` still retires `\omh\...` when the
  home is on `C:`. Registration no longer adds the pointer beside an entry
  that already names it another way (`C:\omh\current\skills` on Windows,
  `${VAR}`, `~`, or relative to the home), and `omh uninstall
  --registration-only` removes every spelling setup retires (`${VAR}`, `~`,
  relative to the home, or through a symlink). Nothing is retired or
  removed that Hermes does not read through that home.
- **`/compress` works in the OMH TUI, and `/compact` runs it.** Hermes'
  shared gateway (Hermes v0.22) refuses `/compress` as a typed command, so
  the TUI said Hermes could not run it in a TUI session. The gateway child
  now runs it, and `/branch`, `/retry`, `/undo`, `/stop`, `/bg`, `/btw`,
  `/rollback`, `/reload`, `/reload-mcp`, `/tools`, bare `/plugins` and
  `/config`, through the gateway call Hermes' own TUI uses. `/topup` goes to
  Hermes, and the commands only Hermes' classic CLI runs leave completion.
- **The OMH TUI no longer shows a blank screen when you switch to its
  terminal and back.** A resize signal (a tab shown again, a split laid out
  again) redraws the session from memory, and the erase that starts that
  redraw was written on its own before the session was printed again, so
  the screen went blank for a moment. The erase now goes out in the same
  synchronized update as the frame drawn after it, so a terminal that holds
  the update (DEC 2026) swaps the old screen for the new one in one step.
- **The TUI's menus lose their bands, a sent prompt gains one, and the
  bottom line names the branch.** The completion menu, the session, model,
  rewind and launch-look pickers, the agent list, the delegation view and the
  bot board's sessions draw no fill: the highlighted row is a `❯` and a bold
  name in the skill hue, other commands keep that hue and their descriptions
  are muted. A prompt you sent runs on a band to the right edge, tinted by
  the launch look. The one line under the composer starts with
  `[⚚ OMH Native]` and shows the session directory's git branch with its
  changed and untracked counts, read off the screen's thread, first on its
  right. The working row, the
  plan and the composer get a blank row between them where the terminal has
  one to spare.
- **A long `/compress` is waited for, and side answers are not lost
  silently.** The TUI waits 660 s for `/compress`, Hermes' own budget,
  instead of 120 s, and past that says the compression may still land
  rather than inviting a second one. A command Hermes refuses while it
  compresses says so. `/stop` reports an interrupt only when it stopped a
  turn, and stops the session's processes even when its read fails. A `/bg`
  or `/btw` answer for a session left meanwhile names that session, and
  leaving a session with one still running says it will not show.
  `/topup` goes to Hermes only on a shared gateway.
- **The live region reads more calmly while a turn runs.** A mid-turn
  `↳ you:` row and a steer run on your sent prompt's band, with a blank row
  over the sticky prompt. Hermes' background review is one dim row naming
  each skill once. The plan's done rows are quiet and fold into `✓ N done`
  before a row still to do is cut, and Ctrl+P folds the plan to its header
  and current item (the header names the key). The working row keeps
  Hermes' spinner verb and shows a status such as `🧠 OMH — recalled 4
  memories` after its facts, dim. Each reply opens with `⚚ Hermes · <model>`.
- **A command typed during a long `/compress` keeps its answer, and Ctrl+P
  matches its hint.** Hermes' shared gateway answers a connection's calls one
  at a time, so while a `/compress` this TUI sent runs, every call sent
  meanwhile waits for it; the TUI gave each 120 s, so past that `/undo`'s
  draft or `/retry`'s resend was dropped while Hermes still ran it. Every
  call sent then (a command, its `command.dispatch` fallback, a prompt, an
  interrupt) now waits for the compression's time left plus its own budget,
  at most 780 s, and a typed command says Hermes runs it once the compression
  ends. On a terminal too short for the plan, Ctrl+P no longer sets a fold
  the screen cannot show, so the header never offers `ctrl+p expand` for a
  plan the key cannot expand. A redraw due while a pager is open (a catalog,
  rewind or resume answer) waits until the pager closes, so the session is
  no longer left twice in scrollback.
- **A promo or demo video asked for in a shared channel reaches
  `show-reel` when the channel's backfill is only greetings and thanks.**
  On Discord, Hermes puts the messages others posted since the bot's last
  turn before `[New message]`, and any such backfill made a closed request
  ("Make a demo video for the app") ask instead. The request now routes as
  it would without the backfill when the backfill is the Discord adapter's
  own shape -- the `[Recent channel messages]` header, the `[unverified]`
  notice exactly when a sender is tagged, and `[<name>] <text>` lines with
  a one- or two-word name -- and every message is acknowledgement-only
  chatter: greetings, thanks, acks, times of day and "all", "everyone"
  or "folks" ("morning all", "thank you", "ok, nice!"), with no noun,
  verb, number, question mark, link, code or emoji and no pronoun but the
  "you" of "thank you". Any other
  backfill, a reply pointer or an attachment note still makes it ask. A
  closed request beside a character that folding removes entirely
  (U+2017, U+203E, a bare combining mark) is no longer admitted.
- **An image you attach in the OMH TUI is an `[Image #N]` token in the text,
  as in Claude Code.** Ctrl+V, a dropped file and `/image` put the token at
  the caret, in place of the `📎 shot.png  Backspace removes` row above the
  composer. Images are numbered upward through the TUI run, past any number a
  resumed session already holds. The TUI keeps the image's bytes and Hermes
  holds it only while its prompt is sent: the prompt stages exactly its own
  images once Hermes has admitted the turn before it. So deleting the token
  (Backspace, Cmd+Backspace, Ctrl+W, Ctrl+U, Ctrl+K, Ctrl+C, Esc Esc) removes
  the image; before, Cmd+Backspace cleared the text and left the image
  attached. An undo puts both back, and so does Up/Down through history over
  a draft. The sent prompt keeps the labels and lists under its echo each
  image whose staging Hermes answered (`⎿  [Image #1]`). A queued prompt, and each command in
  flight, goes with its own images. A `!` line or a command that sends no
  prompt gives its tokens back to the composer, with a notice. Typing the
  label yourself attaches nothing.
- **A queued prompt can be sent into the running turn now, and one line sits
  under the composer.** As in Claude Code, a muted row under the queued
  prompts says `ctrl+enter to send now · ↑ to edit` while a turn runs; on an
  empty composer the key sends the oldest queued prompt into the turn as a
  steer and takes it off the queue. A queued `!` line, skill prompt or plan
  prompt keeps its place and shows no row. Where the terminal has not shown
  that it tells Ctrl+Enter from Enter, the row names Ctrl+J, which every
  terminal sends apart from Enter; with text typed, Ctrl+J still adds a line
  and Ctrl+Enter steers that text, as before. A sent-now steer Hermes refuses
  goes back to the head of the queue as it was, and one it took but had not
  read when the turn is stopped is queued again, with a notice. The info line
  no longer says `/steer <text> steers`; `/steer <text>` still works and
  stays in `/help` and the `?` list. The branch row is gone: the info line
  starts with `[⚚ OMH Native]` and the branch, then the mode and the keys
  that matter, with the title, model, context and effort on the right, and
  the row goes back to the transcript. Between turns it no longer says
  `? for shortcuts`: the launch card names `? every shortcut`, and `?` still
  opens the list. As the line narrows the right side's fields go first, then
  the branch's name is cut, then the badge shortens to `[⚚ OMH]` and `⚚`;
  the mode's label and a question's or picker's keys keep their words. The
  start-up query now asks every terminal for its kitty keyboard flags
  (`CSI ? u`): one that answers gets them pushed, Otty with its
  `kitty-keyboard` setting on among them, and names Ctrl+Enter from the
  first frame; a terminal the environment does not name (over SSH) must also
  name itself through XTVERSION as one known to read them, never Ghostty. The
  push is undone on every exit but `kill -9`. A steer or a second
  `/compress` that waited behind a compression and went unanswered now says
  how long it really waited, not 120 s or 660 s.
- **The exit card is the session's title and how to resume it.** Leaving
  the OMH TUI printed five lines: the title, a line of id, turns, messages
  and duration, a line of tokens and model, `omh --resume <id>` and
  `omh -c "<title>"`. It now prints the title (`untitled session` when
  there is none) and, after a blank line, `resume: omh --resume <id>` with
  the whole id, plus `-p <profile>` for a profile launch, then a blank
  line so the shell prompt does not sit right under it. The
  `-c "<title>"` line is gone with the counts, since the id always opens
  this session and a title can be shadowed by a newer `<title> #N`.
- **The `/sessions` picker reads as a table, and `/resume` is `/sessions`.**
  The session you are in heads the list under `Current` (named `this
  session` until it has a title), and the rest sit under a muted heading for
  the day each started (Today, Yesterday, Previous 7 days, Earlier), in
  Hermes' order inside a day. Age and message count are right-aligned in
  columns of their own, and a rule sets the list off from its header and
  its filter row, in the `/rewind` and `/model` pickers too. The arrows and
  Page keys move past the headings, a heading never ends the visible list
  with its sessions below, and a filter keeps only the headings with a
  match. The `/` menu offers `/resume` under its own name once what you type
  starts it and is not in `sessions`. `/res`, which highlighted Hermes'
  `/compress`, now starts with `/resume`; every other short prefix keeps
  the top row it had. On Hermes' shared gateway, which resumes ids only,
  `/sessions <title>` and `/resume <title>` were refused `not_found`. A
  refused title is now looked up through the gateway's exact-title
  `session.list`, over the whole store, then among the listed sessions
  ignoring case. The one session with it opens; several (titles that
  differ only in case) or none open the picker filtered by the title.
- **A prompt sent now is put back only when Hermes really dropped it.** The
  OMH TUI counted a sent-now steer as read only after a tool finished and the
  turn took a further step, so Esc in between could put back a steer Hermes
  had already joined to the stopped tool batch, and resending it doubled it.
  It now counts as read at the first tool that finishes after Hermes took
  it, since Hermes finalizes even an interrupted batch. A sent-now steer
  Hermes refuses after its turn ended and the next queued prompt started
  goes back to the composer with a notice, instead of running after that
  later prompt; this includes a refusal that arrives while that prompt
  waits on the default-model check, which before took its place and lost
  it. A prompt held for that check is never replaced: the queue waits
  behind it.
- **`omh uninstall` removes an OMH home under `/var` or `/tmp` on macOS
  again (#2359, reported and fixed by @Kenmege).** The uninstall guard that
  keeps a home configured through a symlink walked every ancestor of the
  configured path, and on macOS `/var`, `/tmp` and `/etc` are themselves
  root-owned links into `/private`. Every home under them, including the
  per-user temporary roots in `/var/folders`, was therefore kept with
  "passes through a symlink or directory junction". A root-owned link
  directly under the filesystem root now counts as an OS alias; a link
  anywhere below it, or one a user owns, still refuses, and Windows never
  takes the exemption. The same rule applies to the menu-bar refresh that
  `omh update` skips for a linked home.
- **Delegated agents no longer stop on a repository convention the brief
  overrides.** The goal echo-back told an agent to stop whenever its brief
  conflicted with anything, so a brief saying "do not create a branch" met
  `AGENTS.md`'s "branch first" and the agent declined without making a
  change. The brief now outranks repository workflow rules, and only a
  brief that contradicts itself is stopped on.
- **product-ab prices cached input once.** Hermes' usage file counts cache
  reads inside `input_tokens` on the Codex route, and the lane priced them
  again as cache reads, so one task read $35.77 instead of $4.98. The control
  model moves from the retired `gpt-5.6-sol` to `gpt-6.1-sol`.
- **An image pasted or dropped right before Enter goes with that prompt.**
  The OMH TUI used to send the text and leave the image in the next draft
  when Enter beat Hermes' answer to the paste. Now the prompt waits for the
  answer and goes with the image, as in Claude Code, and the composer shows
  a muted `waiting for the image…` row meanwhile, with the seconds after
  three. A one-line text paste sent at once joins its prompt the same way.
  Esc, or Ctrl+C, gives the held prompt back. A paste Hermes never answers
  holds the prompt only until it expires.
- **`omh doctor` and the probe read the skill pack you actually run, on a
  migrated install too (#2358, reported by @yqm-307; #2378, reported by
  @mazzy89).** A managed install serves its skills from a generation behind
  the `current` pointer, and a host migrated from the 3.x layout keeps
  `~/.omh/skills` as a frozen copy. Three read-only diagnostics looked at
  that copy instead. The `workflow_engine_reach` advice measured it, so a
  migrated host was told `dag-ulw` was not installed (it postdates the
  copy) and a host without the copy was told no install existed; neither
  report could change, since `omh update` never touches the copy. It now
  measures the pack doctor resolved, and an unmeasurable install names the
  file or directory that was missing. The plugin's standalone probe matched
  only the copy's path in `config.yaml`, which registers the pointer, so it
  reported the managed skills unregistered; it now accepts the pointer, a
  generation's pack, the recorded pack and the copy, matched by real path,
  and checks for `omh-routing` in the pack in use. The chat status card
  carried the same mistake. Separately, `omh doctor` run from the 3.x
  bootstrap venv stopped at once with `support refuses symlink component:
  .../generations/bootstrap-legacy/skills`, because it read the support
  files through that generation's link and the support reader refuses every
  link. Doctor now reads through the link the way `omh update` does, so the
  full report prints. A link the installer would also refuse is a blocking
  `skills_dir_link` check that names it, and any other refused path fails
  `local_modifications` and `guidance_projection` with the reason, while
  every other check still runs. The advice still never moves doctor's
  status or exit code.
- **product-ab gives the OMH arm the same reach as the Hermes arm.** The OMH
  arm's unit was scoped to `src/` and `tests/` while the Hermes arm's prompt
  set no limit, so a task whose fix regenerates `docs/WORKFLOWS.md` or a
  skill body was one only the Hermes arm was allowed to finish. The unit
  scope is now the whole checkout.

- **show-reel now checks a film's motion the way an editor would, and has a
  kinetic-type lane.** `motion_check.py` reads every frame at the film's own
  frame rate and reports the share of still frames, each still stretch, cuts
  per 10 seconds and back-and-forth flashes. The default `general` profile
  flags a still stretch over one second; the `kinetic` profile, for fast
  launch films, asks for 40% still frames or fewer and no still stretch over
  0.6 seconds. `--endcard` leaves the end card out and `--reference` prints a
  reference film's numbers beside yours. `music_tools.py analyze --bpm`
  reads fast tracks at their real tempo instead of halving them, and reports
  where the music drops, which `timeline.py` exposes as `music.drop1` cues.
  Hard cuts listed in `project.json` `cuts` keep `render.mjs`'s motion blur
  inside each shot, so the first frame after a cut is never a blend of two
  shots. `qa_check.py` gains `max_h264_level` and macOS `hardware_decode`
  policy keys, `finish.py` keeps 1080p share copies at H.264 level 4.2, and
  `mix.py` lists sound effects that sit under the music. The opt-in
  `references/kinetic-type.md` covers beat-unit authoring, the drop and the
  kinetic gate, and stays out of explainer and evidence films. The method
  notes were informed by Scenario's Kinetic Film exploration; OMH wrote its
  own wording and code.

- **A delegated child no longer dies on a model its inherited provider does
  not have.** A route written with no provider runs on the session's own, and
  `omh_delegate_route` checks that provider can serve the model first. Two
  gaps let a known-bad route through: a session on `custom:<name>` was looked
  up under that spelling while OMH records the bare `<name>`, and a relay
  block counted as serving every model even when its `providers.<name>` block
  in `config.yaml` lists the models it has. Both now resolve, so a session on
  a Claude-only relay sending a `gpt-6.1-sol` category head is caught. When
  exactly one provider you configured is known to serve the model, the route
  pins it instead of refusing (`provider_pinned` in the result names the
  inherited and the pinned provider), on `set` and `fallback`; otherwise it is
  refused as before, naming only providers that could serve it.

- **A package installed into Hermes' own Python is now named when the plugin
  still cannot see it.** On a Hermes install its package manager prepares,
  copying `oh-my-hermes` into the managed interpreter's `site-packages` made
  `omh` import when that interpreter ran alone, even with Hermes' `-I` flag,
  while `omh_probe`, `omh_loop`, `omh_decision_gate` and `omh_interact` kept
  reporting the package absent. The cause is Hermes, not the install: when
  Hermes starts, its package manager takes the interpreter's own
  `site-packages` off `sys.path` and imports from the dependency environment
  it prepared. An `absent` `package_backend` block now carries
  `off_path_install`, the directory where that skipped install sits, and its
  text says why the plugin cannot import it and that there is still no
  supported way into that environment, instead of telling the person to
  install the package they already installed. `omh_interact`'s chat fallback
  now carries the same block beside `package_backend_unavailable`, so it says
  which failure it met. `docs/INSTALLATION.md` explains the case and how to
  check what the plugin sees (#2415, reported by @trend0522).

- **Native Loop, the decision gate, chat recording and the other
  package-backed tools now work on a Hermes install its package manager
  prepares.** Hermes loads the OMH plugin with its own interpreter, and on
  those installs nothing could put the `oh-my-hermes` package where that
  interpreter imports from, so `omh_loop`, `omh_decision_gate`, `omh_team`,
  `omh_agent_board`, `omh_source_trust` and `omh_interact`'s session
  recording were off. `omh setup` and `omh update` now record where their own
  `omh` package is installed (the installer venv, Homebrew, `uv tool`, `pip`,
  or the npm/Bun cache) in the plugin bundle's manifest, and the bundle
  imports `omh` from there when Hermes' interpreter has none of its own. Only
  `omh` itself is imported from that directory, only from a wheel install at
  the bundle's exact version, without writing bytecode into it, and an `omh`
  the interpreter already has always wins. Run `omh update`, then restart
  Hermes. When the recorded package is missing or another version, the
  refusal says which and names that same repair, and `omh doctor` reports
  the bundle as stale (#2166, #2415).

- **Memory recall works on long pastes, saved memories lead back to the
  original words, and `hermes backup` includes OMH memory.** A message that
  pastes a log or document next to a question used to rank memory against
  the whole paste; the chat-turn recall query now keeps the person's own
  words (other speakers' Discord channel backfill, host notices and loaded
  skill bodies are left out, a replied-to message and the same speaker's
  recent lines are kept) and cuts a long turn to its question, else its last
  sentence, else its tail, at most 250 characters. CLI recall and coding-handoff packs keep their raw task text,
  and the prefetch receipt records only the method and lengths. A capture
  made through `omh_memory` now records its Hermes session, and
  `omh_memory recall` rows carry an `origin` the model can open with
  `session_search` to quote the person's message; it is read-only from
  Hermes' `state.db`, and OMH still stores no transcript. The memory
  provider's `backup_paths()` hands `<omh_home>/memory` to `hermes backup`,
  and a restored `principal.key` is tightened back to 0600 on its next read.

- **The OMH pane in Hermes Desktop reads idle when nothing is running and
  keeps the plan and status bar in agreement.** Old runs no longer keep it
  looking busy. OMH catches and the delegation graph appear alongside the
  plan, board and active fanout graph, while individual subagent rows stay
  in Desktop's Agents panel. Calmer colours keep running work distinct from
  waiting or finished work, and the pane follows Desktop's language when
  Korean is selected.

- **A dag-ulw node left open for hours says so.** `omh_dag status`, `ready`
  and `settle` give every open node its age (`open_for_s`, from when it first
  went out, so re-offering it does not reset it). One open past an hour is
  listed in `stuck`, counted on the run's status line (`1 open past 1h (Docs
  body 2h 10m)`), and named in `say` with what to check: no child took it,
  its child still runs (`delegate_task action=list`, then settle failed and
  repair when none is live), or it came back and was never settled. A run
  whose wave never started or whose child went silent used to look the same
  at two minutes and at eight hours. The marks are profile settings under
  `plugins.entries.omh.settings`: `dag_stuck_after_s` (default 3600, 0 turns
  the warning off), `dag_stale_after_s` (default 600) and
  `dag_max_lost_reoffers` (default 3); a value that is not a number is named
  in the result's `limits` and the default kept. OMH still starts no timer,
  so the warning shows only when the parent calls the tool. Proposed by
  @yqm-307 in #2427.

## 4.0.3 - 2026-10-27

- **`plan` and `ralplan` name the goal beyond the request, the raw material,
  and an outside judge.** Before splitting tasks a plan states what should
  happen once the requested result exists and whether it aims there, and adds
  the access an executor needs to work at that level unattended as its own
  tasks; it starts from raw logs, traces or data rather than a digest, names
  the methods a leading practitioner would use, and gives every verification
  step a judge other than the planner or executor, recording a missing one as
  an evidence gap; it restates the deliverable as verbs and brings other
  fields in as practitioner actions, never as voices to imitate. The lines sit
  after each bar's first four items, so capability rows do not move, and they
  reach the portable projection.
- **3D and canvas scenes have a craft and QA bar.** A user ran the same voxel
  pagoda garden prompt through two agents: both consoles were clean, and the
  OMH build was judged less colorful. Its first frame was flat noon under its
  own "golden hour" subtitle, and its birds read as floating black cubes, and
  nothing in the catalog named a 3D scene, so neither the build nor its own
  visual review checked for either. `frontend` gains
  `references/rendered-scene-craft.md` (the first frame keeps the scene's own
  promise; a warm-or-cool key light, a sky fill, explicit tone mapping,
  shadows and fog before more geometry; small animated objects read as what
  they are; the capture matrix), one body line pointing at it, and the
  phrases `three.js scene`, `threejs scene`, `webgl scene`, `voxel scene` and
  `voxel art scene`, with `scene`, `voxel`, `art` and `three` held back to
  whole phrases. `visual-qa` captures a scene's booted first frame, its
  camera presets and each advertised time of day, and records a claim the
  frame does not show, an unreadable small object, or flat light as a
  difference.
- **A finished `/goal` leaves its whole time in the OMH TUI.** When a goal
  shown above the composer turns done, the transcript keeps `✓ goal done ·
  46m 2s · 7/20 turns · <title>`, timed from the goal's own `created_at` to
  `updated_at`, so a goal that ran across many turns is not read off the last
  turn's `✻` line. It is said once, sends nothing, and leaves the time out
  when either stamp is missing.
- **The gateway-attach child no longer aborts when Hermes' gateway hangs up
  first (#2327, reported and first fixed by @skihyeon in #2328).** Its
  `omh-attach-stdin` thread read the TUI's input through `sys.stdin.buffer`
  and so held that buffer's lock while it waited. When the owner's side of
  the WebSocket ended before the TUI closed its input, interpreter
  finalization closed stdin on the main thread, waited a second for that
  lock and aborted the process (`Fatal Python error: _enter_buffered_busy`,
  exit -6), on every Python from 3.11 to 3.14. The TUI then reported
  `the Hermes gateway exited (code -6)` instead of the child's own code 1.
  The thread now reads the stdin descriptor directly, which holds no lock,
  and frames lines as before. The child exits with the code `main()`
  computes, and normal shutdown still runs, including the atexit handlers
  that Hermes' in-process stdio entry registers.

- **GPT-6.1 Terra is onboarded.** OpenAI released it on 2026-10-26. The
  id now has an exact contract read from developers.openai.com: 1.05M
  context, 128K output, and a `none` to `max` effort ladder with `medium` as
  the default. That is GPT-6 Luna's shape, so `none` is sent as is and only
  `minimal` is raised to `low` on record. Before this, OMH passed every rung
  through unadjudicated. `gpt-6.1-terra-pro` and dated snapshots project
  onto it. Cost estimates use the 1/5 list price with 0.05 cached input.
  Provider checks know that Codex, the OpenAI API, and OpenRouter serve it.
  The `gpt` family calibration applies unchanged, and no shipped chain names
  it. To try it now, use
  `omh model-chains set <category> "gpt-6.1-terra:medium, ..."`. On the
  live-model-tools corpus at `high`, Terra passed the same 18 / 30 instances
  as GPT-6.1 Sol with about 5% fewer tokens, at half the list price.
  Hermes through origin/main `a382af23f4` clamps its `max` to `xhigh` on the
  Codex route.

- **The OMH TUI shows up in herdr's agent list.** herdr lists each pane's
  agent as idle, working or blocked, but reads Hermes' state from Hermes' own
  title and screen, which the OMH TUI does not draw, so a pane running `omh`
  was missing from the list. Inside a herdr pane (`HERDR_ENV=1` and
  `HERDR_PANE_ID`), the TUI now reports the state its title shows through
  `herdr pane report-agent` (source `omh:tui`, agent `omh`): a question or
  approval waiting on you is `blocked`, a running turn `working`, otherwise
  `idle`. It reports only on a change, off the render loop, sends only the
  newest state when herdr is slow, and releases the pane on exit. The Hermes
  gateway the TUI starts does not get the pane's `HERDR_PANE_ID`, so herdr's
  own Hermes plugin cannot claim the pane and lock those reports out; herdr's
  CLI and skill still work from Hermes' tools, without a current-pane
  default. Outside
  herdr nothing changes and nothing is spawned; a missing or unresponsive
  herdr is ignored.

- **Setup no longer writes a second `plugins.enabled` when a column-0
  comment sits inside `plugins:` (#2304).** Hermes' own config separates the
  children of `plugins:` with `# ====` banners written at column 0. OMH's
  config readers and writers ended a top-level node at the first unindented
  line, comment included, so an `enabled:` list below such a banner was
  never seen: the guard passed, setup inserted a second `enabled:` under
  `plugins:`, and Hermes then refused the whole file as a duplicate key, so
  no plugin selection was read at all. A comment now never ends a node, in
  every line reader and writer of the config adapter (`plugins`, `skills`,
  `memory` and `display`), so setup adds `omh` to the one existing list and
  uninstall takes it back out. Setup also reads its composed text back
  before returning it and refuses, with the file untouched, when it would
  not hold exactly the earlier `plugins.enabled` names plus `omh`.

- **The installers no longer run Python modules from the current directory
  or `PYTHONPATH`.** `install.sh` and `install.ps1` start venv creation, pip,
  the command-discovery probes, and the OMH CLI with `-I`, or with `-P -E` in
  direct-Python mode so `pip --user` still sees the user site; the printed
  fallback commands carry the same flags. A `venv.py`, `pip.py`, or `omh.py`
  in the directory the installer runs from is no longer imported.

- **`omh uninstall --remove-files` / `--all` refuses to delete an OMH home it
  cannot prove OMH created.** OMH_HOME is removed only when it holds a
  readable, unlinked `oh-my-hermes` schema-1 manifest; otherwise it is kept
  and listed in `kept_paths` with the reason, and `--dry-run` reports the same.
  HOME, HERMES_HOME, their ancestors, and the filesystem root are never
  removed, and a home configured through a symlink or junction (by
  `--omh-home`, the persisted `omh_home` binding, or `OMH_HOME`) is kept even
  with `--force`. Linked plugin directories are not followed, team manifests
  authorize single files rather than directories, the command venv is removed
  only when it carries a venv marker and an OMH entry, and the menu-bar app
  directory only with a matching OMH LaunchAgent.

- **`omh_delegate_route` refuses providers you have not configured.** `set`
  returns an error and writes nothing when the explicit provider, or the one a
  `routing/model-providers.json` route resolves to, is not linked through
  auth.json, config.yaml, `.env`, or `routing/providers.json`, is not a
  configured custom provider, and is not the session provider. `fallback`
  skips such candidates, lists them in `skipped_unconfigured`, and falls back
  to inherit when none remain.

- **Temp and lock files no longer use predictable names that a planted
  symlink can redirect.** The jev ask ledger writes through `mkstemp`; the
  awareness delivery lock opens with `O_NOFOLLOW` and refuses anything that
  is not a regular file; the self-update pointer and launcher swaps use random
  names created exclusively; and browser skill promotion temp names gain a
  random token.
- **A dag-ulw run that ended leaves the area under the composer on its own.**
  Once a run was over its tree folded into one line, `DAG · <name> · done
  9/9`, which stayed under the info line for as long as the HUD kept the
  settled graph (15 minutes). The whole finished tree also came back while
  the next turn ran. The run's end print in the transcript already holds the
  final graph, and `/dag` draws the whole of it, so the view under the
  composer now empties when the turn that ended the run ends. It goes in the
  frame that prints the end, from the end print's own read, even when the
  panel's slower read still shows a lane running. A run that later turns
  move on (lanes still running, a repair or an extend round) keeps its tree
  between turns and into the next one, as before. On the bottom rows the
  rows the tree gave up stay blank under the info line until output fills
  them, so the composer does not move up and no blank band opens between
  the run's last lines and the composer. The run's finished children leave
  the agent list with it, so they are not listed in its place once the
  graph leaves the HUD. Subagent rows outside a dag run are unchanged: a
  finished turn still shows each agent's verdict until the next prompt.

- **The TUI's working row counts tokens while the turn streams.** The
  `↓N tokens` on the working row moved only when Hermes sent a usage report,
  which it does after an API call ends, so a one-call reply showed nothing
  until it was over. It also read the wrong number. A fresh session's first
  turn took its first report as the starting point and showed no tokens at
  all, and the done line said `✻ 4s` with no `↓`. Hermes' gateway now starts
  its counters over at every turn, so every later turn subtracted the last
  turn's total: nothing showed until the new count passed it, and then a
  small wrong number (`↓48 tokens` after 2m 37s). The row now counts up from
  the reply, the reasoning (when `display.show_reasoning` sends it) and each
  tool call's arguments as they arrive, at about four characters a token and
  one per CJK character, and moves to Hermes' count at each report without
  ever going back during the turn. A counter that starts over is detected
  and counted from zero, and the done line carries Hermes' count.

- **Leaving the OMH TUI says which session it was, only the `omh` way, and
  Ctrl+C leaves during a turn.** Closing a session `omh` opened now prints
  an OMH card in place of Hermes' exit summary: the title, the session id,
  turns, messages, how long `omh` ran, tokens split and summed over a
  `/branch` chain as Hermes does it, the model, and `omh --resume <id>`
  plus `omh -c "<title>"` when Hermes' title lookup would open that same
  session (it prefers a newer `<title> #N`) and the title does not start
  with `-`. After a `/new` with nothing said, the card names the newest
  earlier session of the launch that has messages. Hermes' summary, which
  named `hermes --tui --resume`, no longer prints: the OMH TUI exits with
  a code of OMH's own, which Hermes' launcher prints no summary for, and
  `omh` returns 0 to the shell as before. A resumed session gets the card
  too: the old line came from the state database's end stamps, and Hermes
  leaves a resumed session's old `ended_at` in place until a prompt
  reopens it, so reopening a session and leaving printed no `omh` line.
  The OMH TUI now records the open session and its Hermes home in a
  private file `omh` names for the launch, and the end stamps are only the
  fallback for Hermes' own terminal. A session nothing was said in gets
  one line saying there is nothing to resume. The Ctrl+C that interrupts a
  turn also arms the exit, so a second press within 2 s leaves while the
  turn is still `interrupting…` (it used to be swallowed, with no hint),
  and the info line says `ctrl+c again to exit` then too. The info line
  also leads its right side with the session's title, cut to 24 cells, and
  drops it first on a narrow terminal.

- **Esc, Ctrl+C and an approval deny stop the turn again on a Hermes whose
  TUI attaches to the shared gateway.** On Hermes bf0203a794 the OMH TUI sent
  `session.interrupt` the way the stdio entry takes it, with only the session
  id. The canonical gateway stops a turn only for the execution generation it
  runs, so it refused every stop with `stale_generation`. The TUI said
  "Hermes did not interrupt the turn: stale_generation", and the turn ran on
  in the shared gateway, after the TUI exited too. The attach child now sends
  the stop with the generation it tracks from the session's snapshot, events
  and prompt receipts, as Hermes' Ink TUI does. Refused as stale, or with no
  generation known, it reads the session once and sends the stop once more at
  the generation read, only while that read says a turn runs. The stdio wire is
  unchanged.

- **The OMH TUI shows this machine's Hermes bots on a read-only board.**
  Ctrl+S, or `/bots`, opens it full screen. The first page lists the Hermes
  home the TUI runs under and each named profile beside it, each with its
  gateway as `gateway_state.json` records it (state, pid, running agents,
  every platform's state), its sessions counted by source, how many were
  active in the last 24 hours, and when the last one was. Enter opens a
  profile's sessions, newest activity first, and a session's last 40
  messages; ← or Esc goes back, and r reads again. It reads again every 5 s
  off the screen's thread. A gateway reads as running only while the process
  its record names still runs and is the one that wrote it, and a platform's
  state left by a stopped or restarted gateway shows as last recorded. It
  counts active sessions, not open ones: a Slack gateway never ends a chat,
  so a bot idle for weeks still had dozens open. Each `state.db` is opened
  read-only, and immutable when nothing has it open, so not even SQLite's
  `-wal` and `-shm` appear beside it; the only signal is a signal-0
  liveness probe, and nothing is sent to the gateway.

- **The OMH TUI switches models the way Hermes' own TUI does.** Attached to
  a shared Hermes gateway, every `/model` the TUI sent (a picker pick, a
  typed `/model <name>`, `/model --refresh`) was refused as
  `Unsupported_command.`, because that gateway runs no `/model` through
  `slash.exec`. A pick and a typed `/model <name> [--provider <slug>]` now go
  as the `config.set model` Hermes' own TUI sends, which the gateway child
  turns into the owner's `session.mutate model`. A pick is for this session
  only; a typed one keeps Hermes' own `model.persist_switch_by_default` rule
  on the stdio entry, as before; `/model
  --refresh` opens the picker over a list Hermes asks the providers for again.
  When Hermes' configured default model changes while a session runs (the
  person, a bot or the agent edited the config), the session switches to it
  at the next turn boundary, before the next prompt goes, and says so in one
  line, and the info line shows the new model; a
  model picked with `/model` stays until the default itself changes. Hermes'
  refusal codes (`unsupported_command`, `model_resolution_failed`,
  `session_busy` and the rest) now read as sentences that say what to do
  instead. A model Hermes asks to confirm (cost, data policy, a large
  context) is asked about in the prompt slot, as Hermes' own TUI asks it:
  keeping the session's model is the first choice and the one selected, and
  only "switch anyway" sends the switch again with Hermes' confirmation.


- **Byte-identical managed plugin files no longer block setup or update
  (#2300).** A managed plugin file whose current bytes match the incoming
  bundle no longer needs `--force` merely because its hash differs from an
  older installed manifest. The normal install rewrites that manifest. A file
  whose bytes diverge from the incoming bundle is still protected, including
  by the staging revalidation, and a non-forced setup or update refuses to
  replace it. Managed skill `SKILL.md` files follow the same rule: one that
  already holds the bytes the install would write is not reported as a local
  modification; support files keep the manifest-only comparison.

- **`omh doctor` adds independent personal-file and state-write privacy
  controls (#2300).** `--no-personal-files` never opens or reads the bodies of
  `SOUL.md`, `memories/MEMORY.md`, or `memories/USER.md`; the
  `soul_missing_or_starter` and `hermes_memory_staleness` advisories are
  reported as `skipped`, with the reason, rather than as passing checks.
  `--no-state-write` does not create or update `runtime/state.json`, leaves
  JSON `state_log` empty, and skips the `runtime_artifacts` and
  `workflow_state` `.doctor-write-test` probes. Those two checks instead
  report a non-writing permission result with write access explicitly not
  probed. No writes under the OMH home were observed in this mode, but the
  Hermes loader-registration smoke can still copy the plugin into a temporary
  directory when a Hermes install is found. Both flags work with human and
  `--json` output; `--no-personal-files` does not disable Hermes `config.yaml`
  reads.

- **`omh setup --dry-run` no longer applies model aliases, and the model
  step reports a broken Hermes instead of a traceback (#2299).** With
  `--model-setup --apply-model-config --model-config-digest D`, a dry run ran
  `hermes config set model.aliases.*` and wrote the alias while the payload
  said `dry_run: true`. It now runs no mutating Hermes command, still checks
  the digest, and reports `apply.status: "dry_run"` with the exact commands
  it would run; the human summary prints each as a "would run" line, and the
  interactive question asks whether to list them rather than to apply. When
  Hermes' `config.yaml` does not exist (a dry run on a fresh home, or
  `--skip-apply`), the step reports `status: "hermes_config_missing"`; when
  it exists but cannot be read, `status: "hermes_config_unreadable"` with a
  next action to fix its permissions. Either way setup exits 3. When a
  `hermes` command exits nonzero or times out, it reports
  `status: "hermes_command_failed"` and exits 1. All of these used to stop on
  a `HermesCommandError` traceback. The
  setup JSON `ok` and the recorded `last_setup.ok` now follow the exit code,
  so a model step that could not run no longer reads as success.

- **`omh setup --interactive` without a terminal refuses instead of
  crashing or taking every default (#2295).** With stdin closed (`<&-`) it
  stopped on an `AttributeError` traceback; with stdin from `/dev/null` or a
  pipe the wizard read EOF at every prompt and recorded the defaults as the
  user's choices. It now writes nothing, prints one line naming the same
  command with `--interactive` swapped for `--no-interactive --json`, adds
  that as `next_command` in a JSON record when stdout is not a terminal, and
  exits 1. Piped answers into `--interactive` therefore stop working; pass
  the choices as flags instead. A closed stdin no longer crashes bare `omh`,
  `omh theme`, `omh model-chains` or `omh model-chains interview` either.

- **The OMH TUI no longer opens a blank band above the running calls.** On
  the bottom rows, a frame that got shorter (an approval or other question
  answered mid-turn, a picker or menu closing, live thinking folding while
  details are shown) turned the freed rows into blank rows at the top of the
  live region. The running calls, the working row and its tip jumped down,
  leaving up to a third of the screen blank between the last settled call and
  the running ones until more output filled it. The freed rows now go under
  the live block and above the working row. The running calls stay right under
  the transcript they continue, the working row and its tip stay on the
  composer, and the composer still holds its row. Output arriving later fills
  the blank rows downward, as printed output would.

- **`omh setup` records the release that is installed.** After the
  documented stable curl install, a plain `omh setup` recorded
  `release_channel=preview`, the `main` archive URL, `source_ref=main`, and no
  version, although the release wheel was installed, and a SHA-pinned install
  lost its commit the same way. With no `--channel`, `--version`, or
  `--package-url`, setup now reads the package's PEP 610 `direct_url.json`: a
  release wheel or tag archive records `stable` and its version, the `main`
  archive or a commit (including `pip`/`uv tool install git+...`) records
  `preview` with that ref. npm, Bun, and Homebrew installs record the package
  version and no channel. A `uv tool install` pinned to a commit, a release
  tag, or the release wheel URL is now told to reinstall at the new pin with
  `uv tool install --force ...`; `uv tool upgrade` answered "Nothing to
  upgrade" for those. The stable installer's failed-lookup hint no longer
  suggests `OMH_VERSION=1.0.6`, and `install.ps1` now prints the interpreter it
  picked and probes it with `-I`, as `install.sh` does.

- **Russian ships as a trigger language pack, and a later turn in a
  user-installed pack's language re-arms the route hint (#2284).**
  `src/routing/trigger_packs/ru.json`, contributed in #2284, carries 278
  phrases across 49 skills, such as `сделай ревью кода`, `найди баг`,
  `сделай лендинг` and `составь план реализации`. A Russian word scores on its
  own only when it is a software word (`баг`, `лендинг`, `рефакторинг`,
  `деплоя`); every other word scores only inside its phrase, so a phrase made
  of everyday words (`составь план`, `сборка упала`) asks one question instead
  of dispatching; a skill credits at most one such Russian phrase per message,
  so two of them in one sentence, overlapping or apart, ask as one (the Korean
  pack's phrases still add up, as they were written to); and phrases
  an everyday sentence contains (`починить`, `по расписанию`,
  `в чём проблема`, `убедись`) are not in the pack. A test re-derives the
  pack's hold-back from its phrases and a reviewed list of software words.
  Cyrillic and Greek now get the word edges Latin has, so a phrase no longer
  matches inside a longer word: `ревью` inside `превью`, `выкати` inside
  `выкатил`. `ultrawork` carries no Russian phrase: its body would exceed the
  27,300-byte shipped-body ceiling, as with `vi`. On later turns the awareness
  gate read only shipped cues and ASCII tokens, so a message written wholly
  in a user pack's non-Latin script never recomputed its route hint, while
  the same message on a first turn was hinted. The gate now arms when that
  user pack earns the message a hint, and not on a pack phrase alone.
  Shipped packs, `ru` included, stay outside this gate on purpose: a later
  turn in Russian does not re-arm the hint through it. The phrases have not
  been reviewed by a native speaker. `ru` is an input language only: it is
  not a `--language` / `OMH_LANG` output choice.

- **A Jev mention that is negated no longer counts as consent to ask Jev.**
  The consent gate used to grant consent whenever a message named Jev, so
  "ask jev? no, review locally" let `omh_jev_ask` send the request. Consent
  now requires a Jev mention with no negation or refusal cue anywhere in the
  person's message (English cues and contractions, a few other Latin-script
  words, and Korean forms such as `말고`, `안 써` and `제외`), and a message in
  a script the gate cannot read for negation is denied. This fails closed: an
  affirmative ask that carries its own negation, such as "claude 말고 jev로
  물어봐", is denied and has to be rephrased.

- **The memory store and the principal key refuse symlinked or out-of-store
  targets.** Every directory from `<omh_home>/memory` down to a write target
  is checked: a symlink or Windows junction, a non-directory, or a path that
  resolves outside the store root is refused, and a target file that is a
  link or not a regular file is refused before writing. The principal key is
  created with `O_EXCL|O_NOFOLLOW`, read with `O_NOFOLLOW`, and must be a
  32-byte regular file owned by the current user. Block, dreaming, reminder,
  session, receipt, journal and counter-lock writers go through the same
  guard. The checks run before each write rather than through a directory
  fd, so a swap between check and write is still possible, and the Windows
  junction and no-`O_NOFOLLOW` branches have not been run on Windows.

- **`omh uninstall --remove-files` / `--all` removes only the entries OMH
  created and keeps the rest of the OMH home.** Once the home is proven
  OMH-owned, uninstall removes the top-level entries OMH writes (the
  `OmhPaths` locations plus a fixed list of other OMH writers, their lock and
  temp sidecars, and OMH's `*` `.gitignore`) and lists every other entry in
  `kept_paths` with the reason "not created by OMH". The home itself is
  removed only when nothing else is left, and `--dry-run` reports the same
  split. An OMH-created directory such as `runtime/` is still removed with
  everything inside it.

- **The Jev ask ledger is written through a pinned directory fd on POSIX.**
  The ledger directory is opened once with `O_DIRECTORY|O_NOFOLLOW`, checked
  to be a directory owned by the current user, and every later step (lock,
  read, temp create, replace, cleanup) runs relative to that fd, so swapping
  the parent directory for a symlink mid-write no longer redirects the
  ledger, and a symlinked ledger file is neither read nor replaced. Windows
  keeps the path-based write, where a parent swapped between the check and
  the write is still followed.

- **Replies read like a person who did the work wrote them.** OMH now ships
  a human-voice pass adapted from `blader/humanizer` (MIT, v3.1.0): the
  always-on reply rule adds one sentence (result first, no chatbot openers or
  closers, staged contrasts, or decoration), the common rail points every
  skill at the new on-demand `omh-routing/references/human-voice.md` before
  prose a person reads, and that reference covers the strongest English
  tells plus Korean habits (번역투 nominalisation, register drift in a banmal
  persona). The persona still owns the voice; the pass edits content and
  structure only. `omh quality-evidence reply-lint` reports the
  high-precision shapes as a new `ai_writing_tell` finding, skipping code and
  quoted lines. The awareness primer budgets move 1440 -> 1560 and
  3520 -> 3630 for the one sentence.

## 4.0.2 - 2026-10-24

- **Install, update and uninstall keep shared state until a profile's
  teardown succeeds (#2280).** Detaching one profile could delete stores,
  records or the `omh` command that another Hermes home still used, and a
  full teardown could delete shared roots before a child's guarded config
  write refused. Shared stores, records and the command are now kept while
  any other Hermes home references them, and a failed child detach keeps
  them, reports a partial result with a nonzero exit, and can be retried
  once the config is repaired. A dry run is conservative while profiles
  remain attached. Managed skill registrations are removed even when the
  primary skill store differs from a bot's runtime store. An unreadable
  profile config is reported by name and healthy profiles go on. Update
  prints one final JSON result after every profile, with a nonzero exit
  when a required refresh fails, instead of success-shaped JSON before a
  profile failed. Contributed by @frirenai.

- **The TUI no longer draws a month-old fanout as live work.** With no
  native delegation graph, the HUD drew the newest verified fanout contract
  under `~/.omh/coding/fanout/` however old it was, so a fanout prepared once
  and never dispatched still showed `1 agent · DAG · fanout … · 1 waiting`
  weeks later. A fanout is now drawn only while it is current: one whose units
  all settled leaves after the 15-minute linger a settled native graph gets,
  and one with a prepared or running unit stays for 24 hours, the window a
  delegation record is kept. Its age runs from the last change to its
  directory, contract, dispatch summary or in-flight markers. Both the
  delegation graph and the older subagent graph read the same gate, and the
  record on disk is left alone.

- **`omh setup` is shorter on first use and names `omh` as the next step
  (#2282).** Fresh noninteractive setup output falls from 36 to 24 lines:
  repeated successful paths and advanced tuning advice leave the normal
  completion screen. The optional coding, provider and model choices are
  explained more briefly in English, Korean, Japanese and Chinese, with the
  same choices, defaults and disclosures. Completion names `omh` first and
  keeps the reload, PATH, preview and profile-failure guidance. With no
  terminal or no Hermes, setup prints an 11-line first-use guide instead of
  the command inventory. Both launch paths, the OMH TUI and the Hermes
  fallback, now get the resolved Hermes home (`HERMES_HOME`) instead of
  inheriting another one. Structured JSON is unchanged. Contributed by
  @frirenai.

- **Vietnamese trigger phrases follow a native speaker's review (#2262).**
  The review flagged 11 of the pack's 109 phrases. Nine are reworded into
  the forms a Vietnamese speaker uses, often keeping the English term (`kiểm
  tra accessibility`, `kiểm tra screen reader`, `kiểm thử WCAG`, `kiểm tra
  kiểu red team`), and two keep their original wording. verification-gate
  gains `gộp` phrasings (`xác minh trước khi gộp`) beside its `merge` ones,
  which stay because `gộp` is not a router token. The routing effect is
  measured: the two `gộp` phrases clarify instead of dispatching, `kiểm tra
  điều hướng với bàn phím` now clarifies with accessibility-audit as the
  candidate where the old phrase fell back, and `kiểm tra kiểu red team`
  clarifies with adversarial-consensus as before. No routing rule changed;
  the five skill bodies that list these phrases are regenerated. Contributed
  by @PhucNguyen-Dev.

- **`omh_agent_board` states the fields a `prepare` needs, and names the
  one that is missing (#2277).** The schema required only `action` and
  `request_id`, so a `prepare` built from it left out `coordination`,
  `operation`, `board`, `profile` and `arguments` and came back as
  `invalid_request_or_board_store`, the same reason an unreadable board store
  gives. The schema now carries a top-level `oneOf` with the two closed
  shapes, and the tool description lists the prepare fields, because Hermes
  removes a top-level combinator from every tool schema before any provider
  sees it. A `prepare` that still omits one is refused as
  `invalid_prepare_input` with `fields` naming the missing names and no
  values; a missing `board` keeps `board_required`, a host without the board
  engine still answers `omh_agent_board_core_unavailable` first, and `status`
  is unchanged. `docs/AGENT-BOARD.md` lists the refusals that come before an
  engine record.

- **Kimi K3.1 Pro replaces Kimi K3 in the shipped chains.** Every slot K3
  held now names `kimi-k3.1-pro` at the same effort: `deep`, `architect`,
  `unspecified-high`, `quick`, `writing`, `visual-engineering`, `artistry`,
  `capable`, the `main` suggestion, and the X-platform affinity. Both site
  pages, the generated install table, and the model-setup skill say so;
  the four lean READMEs link to the canonical table. K3 is retired under the superseded-generation
  rule. It stays recognized and priced, so `omh model-chains set` can still
  name it. The Highspeed tier joins no chain. The `quick` chain therefore
  no longer offers a Kimi Ultrafast swap in `omh model-chains interview`,
  because no K3.1 Ultrafast tier is priced. This is an editorial change
  (owner decision) and has not been measured yet.

- **A remark after a request is read by its kind, more widely (#2243
  follow-up).** A retraction is read by its verb stem (`…, side note, I'm
  cancelling that`, `…, fyi backing out of this`, `…, calling the whole
  thing off`), a stated precondition holds (`…, need to confirm it's safe on
  my side`), and a contrast after a wish turns to what follows (`…, fingers
  crossed but let's not`): each holds where it started a graph run before.
  Who asked needs someone other than the speaker as its subject, or a
  passive (`…, approved by the CTO`). More remarks keep the request: an
  aside marker of any kind (`…, also, …`, `…, off topic, …`), a request on
  someone's behalf or for a purpose (`…, the PM's request`, `…, at the
  request of QA`, `…, on behalf of legal`, `…, it's for the audit`), a toast
  (`…, here's to a clean run`, `…, may the build be green`), a
  back-reference (`…, consistent with the RFC`, `…, like we did for
  billing`), `…, no deadline` and `…, bear with me`. A toast, a wish, a
  back-reference or an attribution keeps only when what it carries is clean:
  a negation of doing the work holds wherever it is said (`…, here's to not
  doing it`, `…, here's to letting sleeping services lie`, `…, the team lead
  asked us to leave it`, `…, cheers don't bother`), while a negated outcome
  keeps (`…, hope nothing breaks`, `…, btw it won't touch prod`, `…, fwiw no
  exceptions`, `…, hope we don't break imports`: a `don't` that governs an
  outcome verb asks for the work all the same). A flat refusal holds
  (`…, btw, no`). What a third party said, wanted or told us is read by
  the kinds a bare remark is: a clean approval keeps, with intensifiers,
  punctuation and a when or what for around it (`…, legal said a big yes`,
  `…, the lead said absolutely, go for it`, `…, the client wants it by
  friday`), and so do thanks, a greeting, a sign-off and a wish (`…, the
  lead said thanks a ton`, `…, the PM says hi`); after an aside marker a
  plain statement keeps too (`…, fwiw QA says the suite is faster now`).
  A refusal, a hedge or anything unknown holds (`…, QA says hard no`, `…,
  fyi the lead said meh`), and so does sarcasm: a mocking idiom or an
  approval dressed in filler or said twice (`…, the lead said yeah right`,
  `…, ops said sure, in your dreams`, `…, the lead said oh sure`, `…, QA
  said yeah yeah`). A negator before the reporting verb holds whatever was
  said (`…, nobody said yes`, `…, ops never said go`, `…, nobody signed
  off`), and so does one before an attribution verb (`…, no one on the
  team gave the go-ahead`). A subordinating condition opener holds where it
  opens a clause (`…, assuming QA says it's fine`, `…; as soon as the lead
  says go`); inside a clause it constrains the work and keeps, and an
  adjective never counts (`rename every module as long as the import paths
  stay the same`, `… using the provided helper`). A reported wish keeps
  only as a wish alone or that the work goes well (`…, the lead said hope it
  goes well`; `…, the PM said good luck lol` holds), a doubled assent is no
  thanks (`…, QA said great, great` holds), and under an aside a reported
  negated state, reluctance or blocking status holds (`…, btw legal says
  the contract isn't signed`, `…, btw ops says staging isn't up`, `…, btw
  ops says prod is frozen`), while a negated problem keeps (`…, fwiw QA
  says it isn't a problem`). A status word that is also good news holds
  only of a person away or a system down (`…, fyi the lead said she's out
  today`, `…, btw ops says the cluster is down`); of a work item it keeps
  (`…, btw ops says the fix is out`, `…, fyi ops said the error rate is
  down`). Thanks for a negation mocks wherever it is said (`…, thanks for
  nothing` holds). A relative what is no reported speech (`…, hope it's
  what the PM wants` keeps as a wish). Korean reported speech is unchanged
  and reads as on main.

- **The launch card shows skills from its first frame.** The skills section
  said `loading…` for about 1.4 s on a warm launch and 1.8 s on a cold one.
  Hermes names its skills only in the `session.info` it sends after building
  the session's agent: plugin discovery, `AIAgent` setup and its skill scan.
  The OMH TUI's own share is under 0.1 s. The card now keeps the skills it
  drew in `<omh_home>/tui/launch-skills.json`, written atomically and
  best-effort, with the Hermes home and profile they were drawn for. The
  next launch on that home and profile draws them at once, with a dim
  `last-known` mark on the title row. When the session's own skills arrive
  they replace the snapshot whole, so a skill removed since then leaves the
  screen. The card keeps its height through the swap. The snapshot holds
  the names as drawn, so the first frame imports no skill catalog. A first
  launch, a launch on another Hermes home or profile, or a snapshot that is
  unreadable or from another schema still says `loading…`. Hermes is
  unchanged.

- **Kimi K3.1 Pro and K3.1 Pro Highspeed are onboarded.** Moonshot released
  them on 2026-10-23. Both ids now have exact contracts read from
  platform.kimi.ai: 1M context, thinking always on, and a `low` / `high` /
  `max` effort ladder with `max` as the default. A request for any other
  rung is raised on record (`medium` to `high`, `xhigh` to `max`, and
  `off`/`minimal` to `low`), the same way Hermes' Kimi provider sends it.
  Before this, OMH passed `medium` through and called it unadjudicated.
  Cost estimates use the list prices: 2/10 per MTok, and 4/20 for
  Highspeed, which keeps the 0.20 cached-input rate. Provider checks know
  which catalogs serve each id. The `kimi` calibration applies unchanged.
  K3.1 Pro takes every slot Kimi K3 held (the shipped-chains entry above),
  and Highspeed joins no chain. The K3-vs-K3.1 benchmark pair is the
  follow-up and needs a served route.

- **A newer delegation route stays newer after another session's `set`
  (#2251 follow-up).** When an `omh_delegate_route set` wrote its route but
  failed to write the conversation's entry, the conversation's older entry was
  ignored only while the profile-wide restore record still named that writer.
  Once another session's `set` replaced the record, the older route came back
  at the conversation's next `delegate_task`. Each `set` now first records
  the route it wrote in `~/.omh/routing/conversation-writes.json`, one stamp
  per writer (the session, or `task:<id>` for a host that names no session).
  Another writer's `set` does not replace it. The stamp stands in for the
  older entry, so the conversation's next dispatch runs on the route it set
  last, and so does a delegate child inheriting from it, even when the older
  entry was from an earlier turn or from the session a compaction continued.
  A stamp never brings back a route that a `clear`, a chain exhaustion or a
  turn end took out, even when that removal's own write failed: each marks
  the conversation's stamps released first. A reapply, a repeated `set` of the
  same route and a child inheriting its parent's route are unchanged. Stamps
  are kept for six hours, at most 64. A missing or corrupt file reads as "no
  newer write", which is the behaviour before.

- **A cleared or exhausted delegation route stays gone (#2251
  follow-up; #2258, #2264, #2268).** `clear` and chain exhaustion now
  release the conversation's own route inside the same lock as the
  restore, after it. Before, the release took a second lock. When that
  lock timed out, the cleared route,
  or the model that had just failed, came back at the next dispatch of the
  same task. A turn-end restore whose write is refused now keeps the route
  recorded, because the keys still hold it. A session-start restore that
  cannot release a gone writer's route reports a degradation instead of
  leaving it to the six-hour bound. A `delegate_task` that runs on another
  session's route because its own `state.db` row cannot be read now says so,
  in the hook result and in Hermes' log. A corrupt `_delegate_from` cycle can
  no longer make a session inherit its own stale route.
  `omh_delegate_route action=status` reports the conversation's own route
  beside the profile-wide keys. Before it releases, a `clear` or a chain
  exhaustion stamps the entries it takes out in
  `~/.omh/routing/conversation-take-outs.json`, inside the restore's lock
  and whatever the restore decided, so a failed release cannot bring the
  cleared route back at the same task's next dispatch. When the 2 s
  dispatch-lock wait times out and the unlocked read finds nothing to
  change, the `delegate_task` goes ahead instead of being refused.

- **A delegation route belongs to the conversation that set it (#2251).**
  The three `delegation.*` keys are shared by every session on a profile.
  When session A ran `omh_delegate_route set` and session B set its own route
  before A's `delegate_task`, A's child ran on B's model and nothing reported
  it. B's turn-end restore could also take the route away from A. Each route
  is now also recorded per conversation in
  `~/.omh/routing/conversation-routes.json`. Just before Hermes reads the
  keys for a `delegate_task`, `pre_tool_call` puts the dispatching
  conversation's own route back. A delegate child's workers get the route of
  the conversation the child was delegated from, as they did before. A
  conversation that set no route gets the profile's default, not another
  session's live route. If OMH cannot do that, the call is refused with a
  typed status naming both sessions, and no child starts. A dispatch on a
  session's own route still writes nothing. A small window remains, because
  Hermes reads the keys after the hook returns. A wait for a person to
  approve the call is part of that window.

- **TUI text stays readable on a mid-grey background with every skin.**
  A colour that needed lifting for contrast stopped at the skin's own
  light ink. Crimson's is #FFEDE6, which reaches only 4.36:1 on #707070,
  so its labels, headings, warnings and errors read below the 4.5:1
  floor; between #6E6E6E and #747474 every skin did. The lift now goes on
  to white or black where that ink falls short, so every text ink meets
  4.5:1 and every glyph meets 3:1 on any grey.

- **The launch has a look of its own, and a card.** The owner asked for new
  logo colours and for more than the logo, like the skills box in Hermes'
  own session panel. A fresh session's launch now draws the logo, the
  banner's title and a launch card in one of four launch looks: `spectrum`
  (the default: the logo swept through the five tool-kind hues, a box per
  section), `violet`, `gold` and `graphite`. The card names the model and
  effort, the new session, the last session with its `/resume` id, the first
  keys, and the skills Hermes has. OMH's skills are grouped by capability
  family, with the ulw lanes on their own row, and Hermes' own skills by
  category. It fills in as `session.info` and `session.list` answer, sits
  under the banner until the first prompt, then stays in scrollback above
  it. `/theme` alone opens a picker that previews each look as you move
  (on the logo and the card at launch, in a compact preview later); Enter
  keeps it under the OMH home, and `/theme <look>` keeps one at once.
  The logo is coloured cell by cell, with a darker drop shadow, at 3:1 or
  more on dark and light backgrounds. The skin file Hermes' banner reads is
  unchanged.

- **A `dag-ulw` in the composer glows.** Typing `dag-ulw`, `dag ulw` or
  `/dag-ulw` in the TUI's composer runs the word's letters through violet,
  magenta, pink and lavender with a brighter band sweeping through them,
  and draws the composer's rules heavy in the same gradient with a band
  travelling along them, the way Claude Code marks `ultrathink`. It adds no
  rows and leaves the caret and the cells alone, ticks only while the word
  is there on a truecolor terminal, stands still at 256 or 16 colours, and
  is bold without colour with `NO_COLOR`. The word takes the glow in place
  of its `/name` colour.

- **The dag-ulw TUI reads at a glance on a big run.** The owner's GIF review
  and an audit at 100×30, 150×42 and 200×50 found the transcript flooded by
  147–219 rows per print under the 48-node cap, and a tree whose short titles
  left the figures ragged at the right edge. A print now leaves the
  Dependencies list and the Node details to `/dag`. A run of up to 12 lanes
  still prints every box and arrow; a bigger one prints its header, a row
  per layer, the boxes the moment changed and
  `… N more nodes · /dag shows the whole graph`, and its end is the whole
  run's tally and its failed or stuck nodes. A layer the node cap emptied
  keeps its row. Tree titles take the task line of a node's prompt after a
  short label, cut at a word past 52 cells, and the figures stand in fixed
  columns. Boxes
  grow to 48 cells and cut a long title in its middle. Counts are the run's
  lanes and the edges between them, with thousands separators and `B`/`T`
  token tiers, a capped layer reads `28 of 640 nodes`, and the agents chip
  counts the running lanes. The launch fills the screen with the composer
  on the bottom rows, the composer keeps its rules and a
  `↑↓ browsing · esc to type` hint while the tree has the keys, and a run
  that settles or shrinks mid-turn keeps its rows until the turn ends
  instead of leaving a blank band above the composer.

- **`omh setup`'s provider step ends on one Enter.** After the provider
  list, a second prompt, `Add another provider by name (Enter to skip)`,
  always followed and waited for its own Enter. The step looked finished
  while it was still blocked. The list now has an **Other provider -- type
  its name** row just above skip. The name prompt appears only when that
  row is ticked; it keeps the duplicate and invalid-id checks and the kind
  menu, and an empty line still ends it. The row is never pre-ticked, it is
  refused beside skip like any other row, and it is never written to
  `~/.omh/routing/providers.json`. In the typed menu, typing only that row's
  number adds it to the ticked rows; it does not replace them, so found
  providers are not recorded as excluded. In the arrow-key menus (the
  provider list and the single-choice menus, such as the provider-kind
  menu), digits now build a row number: `1` then `7` is row 17. Before, the
  list toggled row 1 and then row 7, which silently excluded a found
  provider. The kind menu returned row 1 and left the `7` to be read by the
  next "Provider name" prompt. While a digit could still be extended, a
  note under the menu shows it (`Row 1_ -- type a second digit, or
  Space/Enter ...`). Menus of up to nine rows behave as before.

- **`/omh-doctor status` runs doctor (#2221 L4).** After a slash skill, a
  status question shows OMH's status card. The exception is a skill whose
  own work is that status, and doctor is now one of them. The card counts
  setup gaps but not install health: on an install whose managed skill
  file had drifted, it read "OMH setup gaps: 0" while doctor reported
  `local_modifications` and `guidance_projection`. A stop after
  `/omh-doctor` is still a stop, a question about the skill is still
  answered, and the bare `/omh-doctor` runs as before. Every skill in that
  status-is-the-work set now has a routing case and a test that turns red
  if it is dropped from the set.

- **Preserve adaptation outcomes and native DAG goal context.** Planning,
  implementation, DAG and verification guidance share one on-demand procedure
  for reuse decisions, user-agreed losses, early/final output comparisons and
  separate technical/output-quality verdicts. Native DAG tasks now carry the
  saved run goal through reload, retry, repair and extension; verifiers are told
  to check the whole goal, not only local VERIFY. Contract tests establish
  instruction delivery, not live-agent compliance or artistic quality.

- **The route hint no longer starts dag-ulw on a split the router only asks
  about (#2232 follow-ups).** A split into parallel parts ("fan out across the
  services …", "split … into parallel lanes", "병렬로 나눠서 …") started a
  dag-ulw run from the hint on 36 survey rows while the router only clarified.
  Now named work asked to split runs as a graph on both: a work verb after the
  split (`fan out across the services and migrate each one`, `…, then
  integrate`, `모듈을 병렬로 나눠서 리팩터링해줘`) or a work noun as what splits (`the
  migration is big, split it into parallel lanes`), in an imperative, a
  polite request, or after `tell me when done:`. A split of text to translate,
  a proposal or a plan said (`how about we …`, `my plan is to …`, `maybe …`), a
  question how to split, a report, breadth alone, or one named object (`이 함수
  병렬로 나눠서 구현해줘`, `README 병렬로 나눠서 …`, `fan out the image resize into
  parallel workers …`, `the checkout page: split it into parallel parts …`) is
  asked about on the router and offered in the hint, never started; a count or
  들 after a demonstrative is several objects (`이 세 서비스 …`). More Korean
  request forms count (`닫아`, `고쳐`, `올려라`, `주라`, `고고싱`, `놔라`, `해주십쇼`,
  `요망`, `…해 주시면 감사하겠습니다`), breadth words `쭉` and `하나도 빠짐없이`, `… fix
  them all`, and `rewrite` and `reimplement` are changes. What follows a request
  in a later clause keeps it only on positive evidence, in Korean and English:
  a keeper by shape (an urgency or a deadline, a start cue, thanks or
  politeness, with an intensifier or a request ending: `…해줘, 최대한 빨리`,
  `…해줘, 금요일까지`, `…해줘, 지금 바로`, `…해줘, 부탁할게`, `…, by friday please`,
  `…, no rush`, a per-unit spec such as `…, one commit per package` or `…, a
  separate PR per repo`), or a follow-on after a sequencing connective that
  asks for more work (`…해줘, 그리고 README도 갱신해줘`, `…해줘, 그 다음 테스트 돌려줘`,
  `모든 패키지 업데이트해줘, 패키지마다 changelog도 써줘`, `…, then run the tests`), with no
  hold or joke in any clause after the request. A final `…, ok?` on any request
  and a report on the result, by its opening (tell, ping, notify, message, show
  or send me, let me know, report back, then which, any, the ones, each, when,
  once or a result noun: after a quantifier the clause turns on its subject (the
  targets with any finite verb report, `… which ones can't be upgraded`; a person
  with a modal or an intention asks, `… which ones you'd skip`; a bare infinitive
  asks), `when`/`once` needs a completion that ends the tail, and deliberation is
  no report: `… and report any that fail`, `… and
  let me know which ones break`, `…, and notify me when it's done`; not `…, and
  send me any concerns`, `…, then tell me which ones you'd recommend`), are read off before
  the request is; any other `let me …` and a tail that asks for anything before
  the work (`…, then tell me why we shouldn't`, `…, then tell me the risks
  first`) hold it. Every hard exclude reads the whole text, and a deferral is
  one (`… later`, `… in a bit`, `… tomorrow`, `… tonight`, `… next week`, `PR들 전부 나중에 …`;
  `… by tonight` and `…, 내일까지` are deadlines and run, and a time inside a past
  clause, `… we deployed on monday`, is none either, while a time ahead of now is,
  `… we deployed next week`). A colon list after a
  breadth head is one request when every item opens on a verb of work (`for each
  open PR: rebase, squash, merge`); an item that opens on a status or carries a
  hedge ends it (`…: done, done, conflict`, `…, too risky though`). After a
  Korean request anything else keeps nothing, and the message is read whole, as
  on main (`…해줘, 아 잠깐만`, `…해줘, 해도 되나`, `…해줘, 확인해줘`). After an English
  request a remark keeps it only when it is of a keep kind, in any words and
  with any intensifier: gratitude (`…, thanks a bunch`, `…, thx so much!!`,
  `…, much obliged`), a sign-off (`…, have a good one`), a wish (`…, fingers
  crossed`, `…, wish me luck`), a back-reference (`…, as discussed`, `…, same
  as last time`), who asked (`…, my manager asked for it`, `…, approved by the
  CTO`), an aside marker of any kind and a harmless statement (`…, fwiw the
  tests are flaky`, `…, also, the new keyboard is lovely`, `…, off topic, the
  sofa arrived`), or no pressure
  (`…, no worries`, `…, take your time`, `…, whenever works`). An unknown
  remark holds, so the request is offered, not started, and a refusal class
  holds even inside a keep kind: a new request (`…, run the tests`), a hold, a
  joke or a retraction (`…, never mind`, `…, forget I said that`), a status,
  something asked before the work, a warning (`…, fwiw last time this broke
  CI`), a hedge or thinking aloud (`…, not sure though`, `…, spitballing`),
  deliberation or the decision handed back (`…, what do you think`, `…, your
  call`), a person's modal (`…, we'll see`), a question, a negation (`…, not
  yet`), a deferral or a condition. A past
  inside an embedded question (`어떻게 나눴는지 설명해줘`), a report after a -고 work
  verb (`… 고치고 뭘 고쳤는지 보고해줘`) and a change aimed so a thing does not happen
  a few words off (`… 안 되게끔 수정해줘`) count too.
  `일정 간격으로` is a schedule.

- **`NO_COLOR` turns off colour in the whole OMH TUI (#2223 review item
  17).** With `NO_COLOR` set to any non-empty value (no-color.org), only the
  motion and the delegation graph used to honour it. The transcript,
  composer, agent view, pager and pickers still painted truecolour: 326
  colour codes in the redesign's scene A and 486 in scene B. Now the app's
  theme drops every colour, and so do the skin's logo, a box graph drawn in
  the transcript, and the rows on an approval's, a notice's or a command's
  band. Both scenes write none. Bold, dim, italic, underline and reverse
  stay, and the bands themselves are not drawn. Two rows that only a
  background marked are reversed: a menu's or list's highlighted row, which
  is also bold, and the pager's and `/dag`'s footer bar. Every state keeps
  the glyph it already carries. With `NO_COLOR` unset or empty nothing
  changes: both scenes are byte-identical to before.

- **A plain request for a change over many targets can run as a dag-ulw
  graph.** "rlaope로 올린 hermes upstream pr들 전부 확인해서 닫을건 닫고
  리뷰반영할건 리뷰반영하고 rebase할건 리베이스하고" went to web-research on the
  router and ulw-work in the route hint; it now dispatches dag-ulw. The router
  dispatches dag-ulw only on positive evidence: a change verb from a closed
  allow list (fix, update, rebase, close, migrate, 고쳐, 올려, 리베이스, 반영, …)
  in request form, on a breadth object that names independent units
  (`열린 PR들 전부 리베이스해줘`, `열린 PR들 전부 리베이스 해줘`, `모든 패키지 버전
  올려놔`, `fix all the failing tests`, `update every service to node 22`), or
  two named parts asked for in parallel. rebase, merge, bump and fix count
  inside a Korean request (`rebase까지 ㄱㄱ`), and a push counts only after a
  change (`리뷰 코멘트 반영하고 force push ㄱㄱ`); `모든 브랜치 push 해줘` is one
  command. More request forms count: `해줘요`, `해주세용`, `해 놔줘`, `시켜줘`,
  `올리자`, `리베이스 고`, `부탁`, `upgrade해줘`, `몽땅`, `최신화`, and `for each of my
  PRs: …`. A count is many only for PRs, repos or branches with a breadth word
  after it (`PR 3개 전부 리베이스해줘`, `PR 5개 다 머지해줘`); `PR 3개 리베이스해줘`,
  `파일 2개 수정해줘` and `테스트 3개 다 고쳐줘` stay small single tasks, and `PR 3`,
  `3번 PR` and `#3` stay one PR. A past in a modifier names the units (`내가 올렸던 PR들 전부
  리베이스해줘`, `충돌났었던 브랜치들`), and a report after an English change is
  its tail (`fix all the failing tests and tell me which ones were flaky`). A
  stop or a hold, a
  condition, a past or a completion as the predicate, a recurring schedule in
  any of its shapes (`매일 아침`, any noun with `마다` but a unit of work such as
  `반나절마다` or `배포마다`, `매 분기`, `2시간에 한 번씩`, `하루 두 번`, `주 2회`,
  `3일 간격`, `하루 걸러`, `격주로`, `자정에`, `every hour`, `each morning`, `twice
  a day`, `on every push`, `cron으로`, `스케줄 걸어서`; `서비스마다` and `PR마다` still
  mean each of them), one pull request (its
  number, `PR number 2240`, `2240번 풀리퀘`, `pull 951`, `my latest pull
  request`, `PR 하나`, its link, or one singled
  out by a modifier: `어제 내가 연 PR 테스트 전부`), one branch (`feature/x`,
  `현재 브랜치`, `this branch`), one fault with one fix in any words (`안 돌아가`,
  `안 먹어`, `돌지 않아`, `페이지가 하얗게 나와 고쳐줘`; `안 되게 고쳐줘` is a
  change), work until a condition, and a request
  that opens with a sigil or names a skill, ulw or a retired engine, also with a
  Korean particle (`loop로`, `github-event-ops에서`, `루프로`) or as the
  instrument anywhere (`… git-workflow로 리베이스해줘`, `… with git-workflow`),
  never qualify, and neither does an explicit invocation of a skill or the loop
  (`use git-workflow: …`). The route hint starts dag-ulw only on
  that same reading; work over many targets without it (`review all open
  PRs`) is at most offered, as one question with dag-ulw as the candidate.
  Reading, summarising, measuring, sharing or checking verbs are not on the
  list, so those requests route as before. Coordinated workers on one shared
  task list stay on ulw-work. Measured on the frozen sets under
  `.omc/research/dag-default-routing/acceptance/`; prompts outside them are not
  measured. A Korean loanword or counter after a stop verb is its object
  (`/ulw-work 멈춰 리뷰어`, `멈춰 서버 두 대` run), and `멈춰 그거 아님` is a stop.
- **The dag tree under the composer holds still when Down gives it the keys,
  and keeps a run's lanes until a payload shows the run over (#2224's delta
  review).** With the keys the tree cuts the same rows as without them, so
  Down only highlights a row; the done layers that gave way at the top stay
  out, and the last row says `↑↓ to browse` when it counts one of them as
  well as rows below. A new turn's kept lanes now go only on a payload whose
  graph shows the run over (its one summary line); a payload with no run in
  it (no session, a graph that lingered out of the HUD, an error) drops
  nothing. A window shrunk under three rows gives the keys back to the
  composer, and INSTALLATION.md says → opens a row and Space flips it.

- **Code review separates response shape, evidence, and review depth.** Native
  and portable skills now ship on-demand finding-validation, architecture-delta
  (including shared-code extraction proof), and risk-selection methods. Reviewer
  returns require structured `spec_axis`, explicit `could_not_assess`, and a
  separate unranked `verification_gaps` array; old returns omitting these fields,
  using a spec string, or ranking gap rows no longer satisfy the contract.
  Ordinary findings keep P0–P3 and low/medium/high confidence. Located evidence
  rejects malformed line syntax and blank text; real paths, ordered/in-bounds
  ranges, actual reads, and claim truth still require reviewer checks. These are
  instruction and schema contracts, not a new review runner or measured gains
  in model detection, false positives, semantic accuracy, or review cost.

- **A dag run's view under the composer is a folding tree that says what each
  child is doing (the owner's ask of 2026-10-22).** Each node is one header
  row: a `▾`/`▸` fold triangle, its state glyph (the running spinner in the
  running blue, a red `✗` once failed), its label in bold, and `category ·
  model:effort · status · ↓tokens` at the right edge. Under an open node,
  two `›` rows show its child's latest call
  (`terminal(gh pr checkout 138300)`) and its latest other line: a thinking
  line, Hermes' progress line (the tool names of its last five calls) or its
  reply, whichever came last, never repeating the call above it. A repair
  hangs under the node it repairs as `↻ repair N`, N its repair cycle (the
  delegation graph now carries a repair node's `cycle`), so a second repair
  reads `repair 2` after the first one's nodes leave the drawing. Running
  and failed nodes open, and so does a node with one of them under it; done
  and waiting ones stay shut, and a blank row sets each open layer apart.
  The agents no node names close the tree as `other agents`. A run taller
  than the view's third of the screen shuts its quiet layers, folds a busy
  layer's quiet nodes into one `▸ N more` row, then shuts open nodes, before
  a last row counts what is cut. Down gives the tree the keys: ↑↓ move, ←/→
  and Space fold, and Enter, `x` and `s` open the highlighted node's child's
  log, interrupt it and steer it as the agent list does. A new turn keeps
  the open run's lanes, so their rows stay without waiting for the next
  frame, and drops them on the first payload that shows the run over. When
  rows run short, the shut all-done layers are cut before anything else, so
  running and failed nodes keep the rows. A fold lasts as long as its run:
  a new run, or another session, starts with none. A click on a tree row
  highlights it, and on a node's row opens its agent's log. In a dag run
  Down opens the agent list only when fewer than three rows are left for
  the tree, and the info line's count leaves out a superseded repair
  attempt's lane.

- **The OMH TUI's transcript tells blocks, states and tools apart at a glance
  (the rail and kind colours the owner picked on 2026-10-22).** On v4.0.1 a
  tool's name, its arguments, its duration and its `⎿` results were all one
  teal, calls were stacked with no gap, and nine of the fifteen rows in the
  owner's screenshot were skill loads and tool-detail reads. Now each block
  hangs on a continuous `┃` rail with no fill: grey for your prompt, the
  skin's accent for a reply, and a call's state colour for the call. A call's
  mark and rail follow the dag view's rule, each state in its own glyph: a
  running blue `○` (the same blue as the working glyph, the agent spinners, `●
  main` and a running lane in the dag tree), a green `●` once done, a red `✗`
  when it failed or was denied (the one mark: the answer row under a denied
  call keeps its words and drops its own); a failed call no longer sits on a
  red band. Its name is bold in its tool family's hue (skills orchid, shell
  amber, files peach, web lime, delegation and the dag magenta), each at 4.5:1
  on dark and light terminals; arguments are grey and results a fainter grey.
  A blank row separates two calls. A run of `skill_view` and `tool_describe`
  calls is one row, `● Loaded 4 skills + tool details · …`, unfolded again by
  Ctrl+O, and an interpreter fed its script through a heredoc reads
  `terminal(python3 script · 23 lines)` while any other command shows its own
  first line. The composer sits between two full-width rules behind `❯ ` with
  no side edges, as in Claude Code, and your echoed prompt and a command's
  echo hang on the same `┃ ❯`, so a bare `❯` is only ever the composer. A
  `/name` that names one of the TUI's commands or Hermes' skills is bold in
  the skill hue in the composer, in the echoed prompt and on the `↳ you:` row;
  a path, an unknown `/foo` and a slash inside a word stay plain. Agent rows
  read a short title (the goal up to its first field label such as
  `DELIVERABLE:` or the end of its first sentence; a dag lane keeps its label)
  and lead their figures with the model, which stays longest as the row
  narrows. The agent log's tool rows take the same hues.

- **A resumed `/skill` prompt, the heredoc command count and short agent
  titles read right in the OMH TUI (#2223 review follow-ups).** A session
  resumed at launch printed its history before Hermes named the session's
  commands and skills, so a resumed `/dag-ulw go` stayed plain for the whole
  session while the TUI's own `/model` was bold. Once that catalog answers, a
  resumed prompt whose `/name` it resolves otherwise is drawn again, with the
  full redraw a resize does; when no resumed prompt the redraw would print
  changes, nothing is redrawn. The heredoc summary counts one command a line around the script,
  and another heredoc's body, a `#` comment and a `\` continuation count
  none: `python3 - <<PY … PY` followed by `cat > notes.md <<EOF` with three
  lines read `+ 5 commands` and now reads `+ 1 command`. An agent's short
  title no longer ends at an abbreviation (`e.g.`, `i.e.`, `etc.`, `vs.`,
  `cf.`): `Fix e.g. the bug. Then …` read `Fix e.g` and now reads
  `Fix e.g. the bug`.

- **Native Hermes children receive their own model calibration (#2214).** A
  separate child-only system prompt section selects one exact-model override,
  family block, or generic fallback from the child's own session model, never
  parent configuration. It applies at every native-child effort, including low,
  unknown, or absent effort, because section metadata does not reliably expose
  reasoning effort. Fanout retains its `high`/`xhigh`/`max` threshold, recorded
  family fallback, and family-only measurement arm. The standalone plugin and
  coding control plane share the same stdlib-only calibration definitions and
  resolver; protocol text, goals, and existing calibration wording are unchanged.
  The section reaches newly built prompts, not already frozen resumed prompts.
- **Scrolling up in the OMH TUI stops at the top of the session.** The
  launch scrolled your shell's rows and the launcher's warnings into the
  terminal's scrollback and kept them there, so the wheel walked from the
  TUI's logo straight into the shell history from before `omh` started; in
  Terminal.app all 80 rows of a test shell history were still above the
  session. The launch now erases the scrollback (ED 3) right after that
  push, as every full redraw (a resize, Ctrl+L, `/redraw`, `/theme`, a
  session switch, a rewind) already does and as Hermes' own TUI does in its
  default alternate-screen mode, and the same run measured 0 of them. The
  TUI still runs on the main screen, so scrolling, selecting and copying
  stay your terminal's own, and when you quit the session stays above your
  shell's prompt, as any output does. A terminal that ignores ED 3 keeps the
  earlier rows one scroll up, as before. A default iTerm2 asks once whether
  a control sequence may clear the scrollback and keeps it until you choose
  Always Allow (a resize or Ctrl+L could already ask the same), and inside
  tmux ED 3 clears that pane's history, as `tmux clear-history` does.

- **A skill command typed once in the OMH TUI shows as one input row.**
  `/dag-ulw <request>` printed `> /dag-ulw <request>` twice: the command's
  echo, then the prompt the skill sends, which shows Hermes' `display` for
  the turn. Hermes got one `command.dispatch` and one `prompt.submit` either
  way; only the screen doubled. Once `command.dispatch` answers with a skill's
  prompt, the TUI takes the echo back and the prompt row is the input. That
  row shows Hermes' `display`, the same row a resumed or rewound session
  draws for the turn, or the line as typed when Hermes names none. A dispatch
  notice, such as stacked skills loading, goes under that row, also when the
  prompt waits behind a running turn. A refused prompt reads as one for a
  typed prompt. A built-in command that sends a prompt with no `display`
  (`/plan`, `/retry`, `/learn`, `/init`) keeps its echo above what it sends,
  as Hermes' own TUI shows it, and commands that print output keep their
  echo. The same line sent twice still shows twice and is sent twice.

- **A skill command sent over a picked rewind replaces the picked prompt.**
  With a rewind picked (Esc Esc or `/rewind`), a line starting with `/` ran
  as a command. A skill's prompt then went as a plain `prompt.submit` without
  `truncate_before_row_id`, so Hermes kept the prompt you meant to replace and
  everything after it, and the rewind stayed picked for the next prompt. A
  prompt a command sends (a skill, `/plan`) now goes in the picked prompt's
  place, as a typed prompt does: the session is cut there, the screen is
  redrawn from the cut, and the rewind clears; `/steer <text>` sent between
  turns does the same. A command that only prints (`/help`, `/usage`) runs
  and leaves the rewind picked. `/retry` and `/undo` take the last turn back
  in Hermes themselves, so they cancel the rewind and say so: `/retry`
  resends plain, and the prompt `/undo` puts back in the composer goes plain
  when you send it. Before, a rewind left picked after `/undo` sent that
  prompt as a cut at a row Hermes had removed; Hermes refuses that cut, and
  the prompt was gone from the composer. A rewind picked while either was
  out, or the rewind list left open, goes too. For any other command, a
  rewind cancelled before Hermes builds the command's prompt, or picked
  (again) after the command went, cuts nothing and stays picked for the next
  prompt.
- **A Hermes slash-skill turn routes on what the person typed, not on the
  skill body Hermes pasted in.** Hermes sends `/dag-ulw <text>` to every hook
  as the skill's whole `SKILL.md` inside a frame, and OMH routed that body as
  the person's words: the owner's `/dag-ulw` turn got ulw-work and ulw-plan
  hints, and never the "call omh_dag define" one. `person_request_text` now
  reads the frame back the way Hermes' own `describe_skill_invocation` does
  (one skill, a bundle or stacked `/a /b`, a bare invocation, a runtime note,
  a shared session's sender prefix), so a skill of OMH's own routes as
  `/<skill> <instruction>`. Another skill's turn is a host-command turn and
  gets no OMH route hint: the person chose that skill. Only a turn that opens
  with the frame's exact first line is read this way, so typed messages route
  as before. A dag-ulw turn's first `delegate_task` with no `[dag:` marker,
  before the conversation has a run, is now sent back to
  `omh_dag action=define` once; `omh_dag status` with no run says to start
  with `define`; and the dag-ulw skill says never to `delegate_task` before
  `define` returns its calls.
- **A question, a status word or a stop after `/dag-ulw` starts no run, in
  Korean, Japanese and Chinese as in English.** Every Hermes `/dag-ulw` turn
  now routes as the sigil form, and that form read only English question
  words: `/dag-ulw 이게 뭐야?`, `/dag-ulw 어떻게 써?`, `/dag-ulw CI 통과했어?`,
  `/dag-ulw /ulw-plan what is it?`, `/dag-ulw 停止` and `/dag-ulw cancel order`
  dispatched a graph run. A question after the sigil (and after any skills
  stacked on it) is now answered; `status`, `show me the run`, `뭐 남았어?`,
  `still running?`, `状态` and `/dag-ulw /ulw-plan 상태 보여줘` read as status;
  `停止` and `止めて` cancel; an English stop word with other words asks which,
  as it does after the bare name; and a capability question that names
  dag-ulw gets the answer, not dag-ulw's run card. A request that holds a
  question word, opens on a request verb, or is asked politely still runs
  (`/dag-ulw 왜 깨졌는지 찾아서 고쳐줘`, `/dag-ulw migrate the billing service?`,
  `/dag-ulw 나눠서 구현해줄 수 있어?`).
- **After an explicit skill invocation the skill runs, unless the words stop
  it, ask how its run stands, or ask what it is.** `/ulw-work stop`,
  `/omh-plan stop`, `/ulw-work 그만`, `/ulw-plan what does this do?` and
  `/ulw-work status` dispatched the skill they named, typed or as Hermes'
  slash-skill turn: the router's explicit-invocation rule read a sigil as a
  command before its stop and question guards. One rule
  (`invocation_cues.invoked_instruction`) now reads the words after a sigil
  for the router, the chat wrapper and Hermes' route hint alike. A stop with
  no task object (`stop`, `그만`, `이거 취소`, `停止`, `止めて`, `取消`) and a
  question about the skill (`what is it?`, `이게 뭐야?`, `어떻게 써?`, `何これ`,
  `这是什么`) are answered, and a request to see how the run stands
  (`status`, `show me the run`, `상태 보여줘`, `뭐 남았어?`, `끝났어?`,
  `is it running?`, `状態`, `状态`) shows OMH's status card. Everything else
  runs the skill: a stop verb with a task object (`/ulw-work kill the zombie
  processes`, `/omh-git-workflow abort the rebase`, `/ulw-loop 로그 폭주
  멈춰줘`), a question with one (`/omh-code-review is it safe to merge?`,
  `/ulw-plan how should we migrate billing?`, `/omh-app-debugging why did the
  run stop?`), a report (`/ultrawork broke my build`), and a status request
  to a skill whose own work that status is (`/omh-running-work-board status`,
  `/omh-deploy-and-monitor status`, `/omh-verification-gate is it done?`,
  `/omh-ops-observability-card status`). A question about an `omh-` skill is
  answered about that skill, not with OMH's intro card.
- **A stop of the invoked skill's own run is a stop.** `/ulw-loop stop the
  loop`, `/omh-code-review 리뷰 취소`, `/ulw-interview 인터뷰 그만`, `/omh-plan
  cancel the plan`, `/omh-app-debugging stop debugging`, `/ulw-work stop
  ultrawork` and `/ulw-loop stop ulw-loop` started the skill they stopped.
  The skill's names (its catalog name and label) and the words for its own
  run, picked by the words of those names (loop, review, plan, interview,
  debugging, work, ulw, research, audit, qa, analysis, triage, onboarding,
  learning), in Korean, Japanese and Chinese too (`/ulw-loop ループを止めて`,
  `/omh-code-review 取消审查`, `/ulw-plan 计划取消`, `/omh-code-review 코드 리뷰
  취소`), now count as the stop's object, so these are answered; a stop of
  anything else is still work (`/omh-data-pipelines stop the pipelines`,
  `/ulw-loop stop the loop when tests pass`, `/ulw-loop 무한 루프 멈춰`,
  `/omh-plan cancel the plan for the free tier`). A Korean stop said with why
  (`그만해 비싸`, `멈춰 너무 오래 걸려`), a stop after `no` (`no stop`), and the
  Chinese `别做了`, `不要做了`, `算了` and `停一下` are stops too, and so is a
  Korean stop followed by fillers, a negation or what the person is in the
  middle of (`멈춰 일단`, `취소해 이거 아니야`, `그만해 지금 회의 중`); a Korean
  stop verb before a noun is that noun's stop, work (`/ulw-work 취소해 주문`,
  `/ulw-work 멈춰 서버`). After
  `/omh-cancel` a stop is that skill's own work and dispatches it, as on
  origin/main.
- **After a skill that explains or judges what the person points at, a
  question about "this" or "it" is its work.** `/omh-code-review how is it?`,
  `/omh-code-review 这是什么`, `/omh-codebase-onboarding what does this do?` and
  `/omh-paper-learning what is it?` run the skill; only a question that names
  the skill (`what is omh-code-review?`, `what does this skill do?`, `이 스킬
  뭐야?`) or asks how to use it (`어떻게 써?`, `how do I use it?`) is answered
  about it, after any skill. Only the skill's hyphenated or coined name
  names it (`what is omh-rust?`, `what is ulw-loop?`): "a skill", a bare
  `스킬`, a name after an article and a name that is a single common word
  name a thing, so `/omh-docs what is a skill?`, `/omh-frontend what does the
  frontend do?` and `/omh-rust what is rust?` run their skill; `/ulw-work
  what is ulw?` names ultrawork by its short name. `/omh-context-budget-review
  status` runs the context budget review, whose work that status is; only a
  skill whose job is reporting a state runs on a status request, and after
  any other the status card shows (`/omh-cancel 상태 보여줘`, `/omh-doctor
  status`, which ran their skill on origin/main). A
  sigil's name is read in any case, as Hermes reads it (`/ULW-LOOP stop the
  loop`). An
  invoked skill's `omh-` label no longer makes its words an OMH intro or
  quickstart question: `/omh-paper-learning what is it?` got OMH's intro card
  on origin/main.
  After `/dag-ulw`, a stop verb with an object (`/dag-ulw kill the zombie
  processes`) asks once whether to stop the run or start one on that work,
  dag-ulw's own reading of a stop word with other words; origin/main started
  a run.
- In the frozen acceptance set's 3,097 labeled explicit invocations, typed
  and as Hermes' turn, no stop, status or question-about-the-skill row starts
  a run (origin/main started one on 2,183 of 2,241), and none of the 856 labeled
  work rows is answered instead of run; four questions about the run after
  `/dag-ulw` are answered and three stop verbs with an object after it ask
  once, by dag-ulw's own reading. Rows outside that set are not measured.

- **The OMH TUI's own commands work typed in any case.** `/Rewind`, `/HELP`
  or `/Steer <text>` used to miss the TUI's command table, which matched the
  name exactly, and went to Hermes as typed. Hermes matches its commands
  whatever their case, but it cannot open the TUI's rewind list or show its
  help, so the command did not do what it does in lower case. The TUI's
  commands and their aliases now resolve whatever their case, as Hermes'
  do; the echo keeps what you typed. The completion menu, the `/name`
  highlight and `/help`'s Hermes list match names the same way, so `/Dag-ulw`
  is highlighted as the skill Hermes runs for it. A name the TUI does not
  have, and a skill, still go to Hermes as typed.

- **The README and the GitHub Pages site are a lean landing page (#2269,
  #2271, #2272, #2274).** All four READMEs open with the spectrum
  OH-MY-HERMES wordmark, then the app-icon logo, the tagline "All-in-one
  package for Hermes Agent. Install once, then just type `dag-ulw`.", the
  two install lines (`curl …install.sh | sh` and `omh setup`), five
  one-line bullets, and the `dag-ulw` clip. The longer install options and
  details sit behind a link and two collapsed toggles. The site's landing
  page is rebuilt around the same copy, with the real TUI recording, every
  install path, the community and sponsor sections, a spectrum aura on the
  hero and the DAG-ULW band, and a header button with the live GitHub star
  and npm install counts.

- **Every timestamp read from outside OMH refuses hour 24 on Python 3.14
  too (#2263).** CPython 3.14 reads `T24:00:00` as midnight of the next
  day, where 3.11 to 3.13 raise. 85 of the 108 `fromisoformat` calls in
  `src/` read text from outside OMH's own clock; they now go through
  `strict_fromisoformat` (or a standalone script's own copy, tested equal) and
  refuse it on every supported Python. Before, on 3.14, a model-supplied
  todo `done_at` was stored verbatim, memory records stayed eligible until
  the next midnight, and connector receipts and routing observations were
  admitted. Valid timestamps, including a real `T00:00:00`, are unaffected.
  A source gate pins the remaining raw calls, each with its reason.

- **Bare `omh` opens the OMH TUI with a Hermes gateway already running
  (#2249).** On current upstream Hermes, the stdio gateway entry refuses a
  home a running gateway owns, so bare `omh` fell back to Hermes' own TUI
  every time. The TUI's gateway child now attaches to the profile's shared
  gateway where Hermes has the attach API, and starts Hermes' own gateway
  with idle exit when none is running, as Hermes' Ink TUI does. Older
  Hermes, with only the stdio entry, works as before. When the OMH TUI
  cannot start, its reason now prints again after the Hermes TUI it falls
  back to closes.

- **`omh setup` finishes with a config key that holds a dot (#2248).** A
  provider key such as `z.ai-coding-plan:` under `providers:` stopped setup
  at `[2/5] Connecting OMH to Hermes` with `too many values to unpack`.
  Such a key is now read as one key, not a level of nesting, in the dry run
  and the real run.

- **`omh-ai-job-search` is a new installable skill (#2253, #2261).** An
  AI-assisted job search for any profession, adapted from the upstream
  ai-job-search methodology to Hermes' own research and document tools. It
  confirms the person's profile and preferences, shortlists real vacancies
  with their sources and fit reasons, drafts truthful, versioned
  application material for review, and prepares interviews. A stdlib-only
  `job_state.py` tracks applications locally; an application counts as
  submitted only on confirmed evidence, and a malformed timestamp (hour 24
  included, on every Python) is refused before any write. An employer's
  hiring request is not routed to it. Contributed by @frirenai.

- **`research`, `source-finder` and `web-research` share a bounded
  multi-source search (#2255).** A "find this" request is decomposed into
  queries, searched and read with the host's own tools, fused into
  requirement-level coverage, and followed up within a bound. An optional
  `omh_search` plugin tool helps with that. There is no new command, mode
  or required provider key. An unavailable, failed or unsearched source is
  not reported as zero hits. This is a draft candidate: search quality and
  installed-model behaviour have not passed acceptance. Contributed by
  @frirenai.

- **Three executable domain-science skills: `omh-geospatial-analysis`,
  `omh-biomedical-evidence` and `omh-molecular-docking` (#2235, #2241,
  #2245).** CRS-aware polygon intersection and area in projected metres
  (Shapely/PyProj); captured BioMCP public-source responses reconciled
  offline into an evidence matrix that keeps disagreements and gaps; and
  standalone AutoDock Vina docking with reproducible settings and per-model
  integrity checks. They are opt-in. Their helpers ship as inert files:
  installing a skill neither runs a helper nor installs a scientific
  dependency. On macOS the helpers' path guards, and show-reel's, accept
  the system `/etc`, `/tmp` and `/var` links into `/private`, and every
  other symlink is still refused. Docking refuses one file passed as both
  receptor and ligand, however it is spelled. Contributed by @frirenai.

- **Skill replies end on their result, not on a list of things not done
  (#2238).** The shared closing guidance asked for a list of what was not
  checked or executed and for a question at the end, so a briefing could
  close on "I did not install or change settings" when neither was asked
  for. The shared closing rule, in every skill body, now orders a reply as
  result, relevant evidence and limits, the required observed run summary,
  then one specific question about the content only when a real decision
  or a useful discussion remains. Completed work needs no question, and
  unrelated non-action footers and generic offers to continue are left
  out. Requested work that was not done, a failed retrieval, an unavailable
  check and a permission decision stay explicit, and a discussion question
  grants no permission. Contributed by @frirenai.

- **Windows staged self-updates work under PowerShell 7 (#2218).** The
  generation-pointer junction now gets an absolute target, which
  PowerShell 7 requires; a relative one staged the update and then failed
  at activation. POSIX symlinks keep their relative targets. Contributed by
  @frirenai.

- **`ulw-research` records inspectable evidence (#2227).** Claims and
  sources carry typed provenance, ownership and counter-search checks, so
  correlated republications cannot count as independent corroboration. An
  exhausted budget is kept apart from completed research. `python -m
  omh.workflows.research_dossier <json-file>` validates a dossier's record
  structure, with distinct exit codes for valid and invalid input. Passing
  it is not factual truth or evidence that a source was read. Contributed
  by @frirenai.

- **`omh-show-reel` is a new installable skill (#2212, #2220).** A
  multilingual show-reel and launch-film workflow ("Create a launch film.",
  "제품 쇼케이스 영상 만들어줘", `/show-reel …`), with an optional motion and
  audio toolkit that ships as inert files. Its engine, project layout and
  QA tools match upstream revfactory/showreel (MIT) at a pinned revision,
  and the render receipt records its quality settings. Narration reaches a
  network service only when the person runs the opt-in script with
  `ELEVENLABS_API_KEY` set; without it, the reel falls back to music and
  captions. A film named inside another request (an issue title, a Slack
  post, "make the launch film shorter") keeps that request's owner.
  Contributed by @frirenai (carries #2195).

## 4.0.1 - 2026-10-22

- **`omh doctor`'s real-loader probe can observe a load on Windows, and on the
  install `omh setup` makes.** The probe wrote a synthetic `config.yaml` naming
  no `plugins.entries.omh.settings.omh_home`, and the plugin refuses to load in
  a native host whose profile names no store (#2037) -- so every install
  `omh setup` registers reported `loader_probe_failed` and the row could only
  ever read `real Hermes loader not observed`. It now carries the binding the
  real home declares. The child process also gets the OS baseline
  (`SystemRoot`, `SYSTEMDRIVE`, `windir`, `TEMP`, `TMP`): without
  `SystemRoot`, `import asyncio` dies with `WinError 10106` before the plugin is
  reached, which read as a plugin load failure on Windows.

- **A Hermes home whose path holds `#`, `?`, or a `%` followed by two hex
  digits is read, and no stray file is created beside it.** Ten read-only
  opens of Hermes' `state.db` and `kanban.db` built `file:{path}?mode=ro`
  from the bare path, which SQLite parses as a URI. A `#` or `?` cut the
  path: the open lost `mode=ro` and created an empty writable file at the
  cut, and a `%41` opened another directory's file, or none. The resume
  line after a TUI exit, the cost receipt and `omh_run_summary`, the
  delegation ledger's root walk, the native delegate and kanban HUD
  readers, and `omh_dag`'s free slots then found nothing. They now open
  through one bundle helper, `sqlite_readonly.connect_readonly`, which
  quotes the path's file-system bytes. A policy test fails any
  `sqlite3.connect(..., uri=...)` in `src/` whose URI is built from an
  unquoted path.
- **A complaint, a question or a stop that opens with a skill's name no
  longer runs the skill, in the shapes measured.** `ultrawork broke my
  build`, `dag ulw failed again`, `ralplan 때문에 빌드 깨졌어`, `maestro failed
  again`, `ultraqa 또 실패했어`, `code-review 결과가 이상해`, `ralph broke my
  build`, `ultrawork 이거 어떻게 써`, `ultrawork still running?`, `ultrawork
  stop`, `ultrawork stop, too expensive` and `loop 멈춰` are answered
  directly, and Hermes' route hint neither offers the skill nor calls it
  explicitly invoked. The reading is `name_report_cues` in the plugin
  bundle, which the router, the retired-engine aliases and the route hint
  share:
  - the name, or the skill's own output, is the subject of a finite verb
    (`broke`, `failed again`, `is too slow`, `output was wrong`);
  - a Korean predicate after it is a complaint, negated or past (`너무
    느려`, `안 돼`, `또 실패했어`);
  - the name is the cause (`때문에`);
  - a stop word is all there is, said once or twice or with its reason
    after it;
  - a question asks about the skill.
  A report counts only after a name that can mean nothing but the skill (a
  coined name such as ultrawork, or a hyphenated id such as code-review): a
  name that is also a word may open a sentence about the person's own thing
  (`frontend is broken on safari`, `code review takes forever`), which keeps
  its route. After dag-ulw, ultrawork and maestro a question that opens
  with a question word is answered whatever it asks (`dag ulw 결제 api 뭐야`),
  and after ralplan unless it deliberates the work (`ralplan how should we
  split the billing refactor` still plans). After a skill whose work is
  answering what is running, wrong or left, that question is its work
  (`app-debugging what's wrong`). A request still runs the skill:
  `ultrawork fix the broken build`, `dag ulw the build that broke`,
  `ultrawork failed again, rerun it`, `… one more time`, `… 다시`, the name
  said again (`ultrawork failed again, ultrawork it again`), a request after
  a use clause or credit (`ultrawork 하고 나서 배포해`, `ultrawork 덕분에 빨리
  끝났어, 결제 모듈도 이렇게 해줘`), and every sigil form (`/dag-ulw broke the
  build, fix it`). A stop of the dag-ulw run said as an act after words that
  may name the work (`dag ulw 결제 취소 처리해줘`, `결제 작업 중단 걸어줘`,
  `취소 버튼 눌러줘`) and an English stop word beside such words (`dag ulw
  cancel order`) now ask which (owner decision O7).

- **dag-ulw works on a Docker or SSH terminal whose user has a writable
  home.** There a child's `write_file` lands inside the backend, so OMH's
  host-side check refused every node with `handoff_missing`, and on SSH a
  child often could not even create the host's OMH path on the remote.
  `omh_dag` now records the terminal backend Hermes resolves for the
  profile when a run is defined. Before the run's first node goes out, it
  reads the terminal user's `$HOME` once through Hermes' live environment
  and pins `<home>/.omh/dag` on the run, where every node writes its
  handoff and its dependents read it; with no terminal environment up yet,
  nothing goes out and the result says to run one terminal command first,
  in the same turn (OMH never starts one). A home that is a link is judged,
  and pinned, as the directory it points at. A home another user can write,
  one in a shared temp directory, one with whitespace in it, or one OMH
  cannot read keeps this host's path, as before. `settle` reads the handoff inside the backend under the host's
  rule: a regular file and no link, so a missing file, a directory or a
  link is still refused. When the terminal cannot be reached (its
  environment is gone, Hermes' registry cannot be read, or no answer
  comes), the node is accepted with `handoff_checked: false` and the
  reason, and every view says `handoff not checked`: `omh_dag status` and
  the run's status line, the boxes and the tree, `omh hud --graph`, the
  TUI's transcript block and its one-line summary, and the chat count line
  and end post. A read the parent's interrupt stopped settles nothing. The
  read runs only once every other check of the settle passed, through
  Hermes' base `execute`, so it never enters Docker's recovery of a gone
  container. A local terminal, or a backend OMH does not read (`modal`,
  `daytona`, `singularity`), keeps the host check as before.
- **dag-ulw routing reads remarks, bug reports, questions and polite requests
  as what they are.** The router and Hermes' route hint read the same
  `dag_ulw_cues`, so each change holds on both paths. `can you dag ulw the
  migration?` and `could you please dag ulw …` now start a run. A polite
  question about it (`can you explain dag ulw?`), or one that weighs it
  against another way (`can you dag ulw this or should I just fix it
  myself?`, `would you dag ulw it, if you were me?`), is answered. A cache
  that breaks when two named modules request at once (`api 모듈과 ui 모듈이
  동시에 요청하면 캐시가 깨져, 고쳐줘`) stays one ultrawork fix, while
  failing tests fixed `병렬로 (각각)` still reach dag-ulw. A question or
  explain request about splitting work (`explain how to split …`, `show me
  how to split …`, `is it possible to split …`, `how do I split …?`,
  `병렬로 나눠서 하는 방법 설명해줘` / `알려줘` / `방법이 뭐야`) no longer
  starts a run or hints "Start at once". A proposal such as `how about we
  split …`, `can we split …?` or `… 구현해줄 수 있어?` still asks for the
  work. A remark whose subject holds the split (`the fan out across the
  services is too high`) and a split whose object is one paragraph or
  sentence (`split the paragraph into parallel parts for the translation`)
  no longer start a run or hint "Start at once" either.
  A Korean stop word after the name no longer starts a run unless the words
  around the last stop word make it work: a work noun or verb after it
  (`… 취소 기능 구현해줘`), a request verb of its own ending the message
  (`… 취소 내역 확인해줘`, `… 종료 훅 등록해줘`), a condition before or after
  it (`… 실패하면 중단해줘`, `… 취소 시 환불되게 해줘`), or a work word as the
  object of `꺼줘` (`다크모드 꺼줘`, not `… 작업 꺼줘`). With none, a stop noun after words that may name the
  work (`dag ulw 주문 취소`, `dag ulw 주문 취소요`, `dag ulw 취소 요청`, a
  verb-form cancel after more than three words, or a stop of the work on a
  cancel feature such as `… 취소 기능 만드는 거 그만해줘`) neither cancels
  the run in progress nor starts one, and neither does a cancel followed by
  a restart (`… 지금 거 취소하고 결제 모듈부터 다시 해줘`): the router
  clarifies and the hint asks one question naming both readings (owner
  decision O7). A question about stopping (`dag ulw 취소 어떻게 해`,
  `dag ulw 멈출 수 있어`, `dag ulw 중단하면 어떻게 돼`), or whether it stopped
  (`dag ulw 취소됐어?`, `dag ulw 멈췄어`, `dag ulw 확인해줘, 취소됐는지`), is
  answered, unless a re-run request comes first (`dag ulw 다시 돌려줘, 아까
  취소한 거` runs). So is a sigil
  before a question (`/dag-ulw what is it?`, `/dag-ulw how do I cancel the
  run?`), unless it goes on to ask for work (`/dag-ulw explain the plan, then
  run the migration` runs). These cancel. On main
  the polite endings, `그만 돌려`, `멈춰라`, `취소요`, `정지`, `스톱` and `꺼줘`
  started a run, `취소해줄 수 있어?` was answered, and `can you stop dag ulw`
  clarified:
  - a verb ending, plain or polite, after up to three words (`주문
    취소해줘`, `취소해줘요`, `취소하세요`, `취소 부탁해`, `취소해줄 수
    있어?`, `그만 돌려`, `멈춰라`);
  - the bare stop word, with a bare `요`, `좀` or `ㄱ` or after stop adverbs
    (`취소`, `취소요`, `정지`, `스톱`, `꺼줘`, `지금 바로 취소`);
  - a word for the run, with or without a modifier (`작업 취소`,
    `진행 중인 작업 취소`, `그것도 취소`, `다른 거 취소`, `저거 말고 이거
    취소`);
  - the act of stopping after those (`작업 취소 처리해줘`, `런 중단 요청
    보내줘`, `취소 눌러줘`), and a stop that did not take (`취소했는데 계속
    돌아가`, `취소 눌렀는데 계속 돌아가`);
  - an English stop after `can you` (`can you stop dag ulw`).

  `dag ulw 주문 취소 기능 구현해줘` still runs.
- **The delegate route tool answers right at its edges.** An alias (`*name`),
  `<<`, or a tag Hermes cannot build (`!!merge`) given as a value in
  `config.yaml`'s `model` or `delegation` section, on a nested line or inside
  a flow collection too, or in a root `base_url`, `api_base` or `provider`,
  now refuses every route, with or without a provider (`config_unloadable`).
  Hermes cannot load the file when an alias has no anchor, a value is `<<`,
  or a tag is not one it builds, so a route written there never took effect
  while OMH answered `routed`; a defined alias refuses too, because the
  check does not follow anchors. In the managed config the same values make
  their section unreadable. A route that names no provider over
  a direct `delegation.base_url` is checked against the provider Hermes
  names that endpoint (`anthropic`, `openai-codex`) instead of the main
  session's, since Hermes builds the child there; a `custom` endpoint is not
  checked, and one the check cannot read keeps the session's check.
  `fallback` with no category now continues the category this
  conversation's own route was set under, so a model in two chains no longer
  fails as ambiguous. It refuses when the model is not in that chain, and a
  route set by model alone still needs the category. `docs/INSTALLATION.md`
  now says that `false`, `no`, `off` and zero for `model.provider` read as
  unset only up to Hermes v0.21.3 and as set from v0.21.4, and why OMH still
  refuses on them.
- **The OMH TUI's composer stays still when a turn ends with agents listed
  under it.** On the bottom rows the agent view took the working row's place
  once the turn ended, so at 12 rows with the plan and seven agents the
  composer's box moved up a row and came back down when the next turn
  started. Once a turn ends there, the view no longer takes the working
  row's place: it gets the rows the slot, the menu and the composer leave
  it, less the working rows, and never fewer than the turn's last frame gave
  it. That place stays blank above the composer until output fills it. A
  draft, a menu or a question that squeezed the view as the turn ended
  gives the rows back when it closes. A view that wants more rows than it
  did drops the hold, so it does not snap back when it wants fewer again,
  and so does a frame drawn above the bottom rows. The cost, measured over
  1,287 cases: at 8, 9, 12 and 13 rows with the plan, 54 idle views keep 1
  or 2 fewer rows than before, the same 54 where the composer used to jump,
  and each keeps at least one row (a header, a running agent or the `+N`
  count). A test now pins that a finished DAG run counts at its one summary
  line in the agents block's budget. The docs say what the DAG tree takes:
  up to a third of the rows (8 of 24, 13 of 40), and no more rows than the
  tree has, so a five-lane run's seven-row tree takes 7 at 24 and at 40.
- **A delegated goal ends with its run marker, so a preview shows the task.**
  Hermes previews each `delegate_task` goal by its first 40 characters on a
  Discord tool-progress post, the CLI and the TUI, so a dag-ulw node's
  leading `[dag:<run>/<node>]` marker and an `omh_team` helper's leading
  `[omh-team:<team>/<unit>/attempt-<n>]` key took the whole preview
  (`🔀 Delegating 1 tasks: [dag:billing-refactor/invoic...`). `omh_dag` and
  `omh_team` now write the marker at the end of the goal, on the label's
  line (`Render invoice PDFs from the new template [dag:billing-refactor/invoice-pdf]`),
  and the binding reads the last whole marker in the goal, on any line, and
  binds only when it is its own lane's: a goal handed out before the update
  still opens with it and still binds, and text a model adds after the
  marker no longer leaves the child unbound and its node offered again. A
  node label or a part title that holds either `[dag:` or `[omh-team:` is
  refused, so a label cannot name another node or team part. The OMH TUI
  drops a whole marker wherever it is from a `delegate_task` row and an
  agent row, also a marker head Hermes' cut left at the end of a goal
  (`… to API [dag:ex...`), even where Hermes' cut of the whole row follows
  it; a head too short to name its kind (`[`, `[d`, `[o`) only after a
  space. Hermes' own lines (the Discord post, its completion line) keep
  what its cut leaves: after a short label, the marker or its head
  (`2 tasks: Export API [dag:export/api] ...`).
- **One verification rule for Hermes `delegate_task` children, and a doctor
  row for the platform they are marked with.** The protocol section's
  verification rule now binds a child whose task changes files or other
  state (a deploy, a migration, remote or config state), not only files. Its
  goal echo-back asks for the numbered criteria only when the goal has them,
  so a `/review` reviewer is not asked for criteria it was never given; fanout
  unit prompts keep the unconditional line. The `coding-handling` harness line
  and `omh coding composition-guide` now state the same conditions: the
  harness no longer makes the verification pass mandatory on every prompt.
  `omh doctor` gains `plugin_delegation_protocol`, which reads the installed
  Hermes `tools/delegate_tool.py` for `platform="subagent"`, the platform the
  section renders for, and warns when it is gone. The unknown-role warning in
  `pre_tool_call` is removed: Hermes reads only `action` from that hook's
  result, so it never reached anyone, and the child's own `pre_llm_call` turn
  already warns about an unknown `[omh-role:...]` marker in its goal.
- **A conversation keeps its delegation graph across Hermes' rotating
  compaction.** With `compression.in_place: false`, Hermes moves a
  conversation to a new session id mid-run. The HUD graph, the TUI's agent
  tree and `omh hud --graph` then read only the new session: its lanes
  vanished, and a child that stopped afterwards (Hermes names the new
  session as its parent) never read done. The graph now reads the ledger,
  the `omh_team` record and the `omh_dag` run under every session of the
  conversation, as the compaction links in `state.db` join them. A stop the
  ledger could not join is matched to its child, and `omh_dag` reads it the
  same way: a dag-ulw node whose child came back before a Hermes restart
  reads `returned` instead of being offered, and run, again. A chat post
  goes on from the last post any of those sessions recorded, so the run is
  not announced again. A child whose own session rotated is read through its
  continuation, so it shows running while its continuation runs, instead of
  `unknown (compacted)`, which also posted it as Stopped mid-run. Its output
  tokens (the agent view and the graph) add up over every session it wrote
  in, instead of stopping at the rotation. Hermes' default in-place
  compaction keeps one session id, and its graphs are unchanged.
- **A Hermes restart no longer leaves a team part waiting four hours.** A
  helper runs inside the Hermes process that started it, and a restart ends
  it without the `subagent_stop` callback, so `omh_team` held the part as
  out until its four-hour bound blocked it as `delegation_not_returned`.
  The dispatch now records that process (pid and start-time fingerprint,
  through Hermes' own `gateway.status` probes, imported when called, and
  where the pid was read: on Linux the boot id and pid namespace, on macOS
  the hardware UUID, on Windows the `MachineGuid`), and the first
  `team_start` after a restart hands back each part whose process is gone:
  same attempt, no try spent, said as "Hermes restarted while 1 part was
  out; it starts again." A part with no recorded process, one recorded on
  another machine or in another container, or one whose process cannot be
  told alive or gone, waits for the bound as before.
  On Linux the boot is part of where the pid was read, so a reboot,
  `wsl --shutdown`, `docker restart` or a recreated container also reads as
  unknown: the team part waits the four-hour bound, and a dag node stays
  running with no bound, as before. Where that id cannot be read, or on
  another platform, nothing is recorded and the hand-back is off: the team
  part waits the four-hour bound and a dag node stays running, as before.
  Hand-backs are counted apart from re-emits for a slow start: after three,
  a part blocks as `helper_lost` ("Hermes kept restarting while its helper
  was out"). A dag-ulw node whose
  child a restart ended no longer stays `running` with no bound: its ledger
  entry records the same process, and `omh_dag ready` offers the node again
  at once, at most three times per attempt, then says on every `omh_dag`
  reply to settle it. The delegation graph no longer draws an ended team
  helper as a lane of its own. Start lines name how many parts start:
  "Started 1 part", "1 starts now and the rest wait for the parts they
  depend on", and no line says "1 parts".
- **The delegation graph keeps a long duration whole, draws no `?` title, and
  puts a repair above what waits on it.** A duration of 100 hours or more
  (`111h 06m`) is measured as it reads, so a box widens by one cell at the
  100-hour mark instead of cutting it to `111h 0…`, and the tree's
  columns give it the cell. A node no record titles reads its own name: a
  team part its unit id, a child `session <tail>`; a drawing or chat post
  given no title reads `untitled`. Where a dag-ulw node failed and was
  repaired, the repair takes its own frontier between that node and what
  comes after it (Verify export no longer sits beside the repair it waits
  for); the parents line and Dependencies keep the recorded edges. An end
  post says `(sent, no child seen)`, not `(dispatched)`, for a stopped team
  part whose child never appeared. `OMH_SUBAGENT_GRAPH` is read in any case
  (`OFF`, ` Off `), in the HUD and for chat posts; the ledger keeps
  recording while it is off.
- **A child's answering model is judged on its own calls, not Hermes'
  auxiliary ones.** Hermes records a compression or vision call in
  `session_model_usage` under a non-empty `task`, on the aux route's model.
  The HUD's served-model check counted those rows. One compression call on
  another model turned a child's `agreement` into
  `unknown/multiple_usage_models`, and a child whose only rows were auxiliary
  read as a `disagreement` with the model it asked for. The answering model,
  its count, and the model the HUD row and the delegation graph show for a
  child whose session row names none now read only rows with an empty
  `task`. Tokens, calls and recorded cost still sum every row, because
  auxiliary calls are real spend, and a child whose only calls were
  auxiliary is still priced at the model they ran on. One approximate figure
  moves: a child whose session row names no model, with its own calls on one
  model and an auxiliary call on another, now gets the model, category and
  `~$` estimate that a child whose session row names that model already got.
  Before, it got none, or `$0.0000 (unknown)`. A `state.db` without the
  `task` column reads as before.
- **A skill body edit no longer rewrites the six host installer directories.**
  Every `.<host>/install.sh`, `install.ps1` and `manifest.json` embedded the
  full per-file SHA256 list, the installers twice, so a one-line `SKILL.md`
  change moved all 18 files. The per-file digests now live once, in
  `agent-skills/.omh-agent-skills-manifest.json`: the exact receipt
  `omh install --target agents` writes, generated beside the pack and pinned
  by `docs agent-skills --check` as a canonical file. The installers are
  static per host and read that inventory. As before, they refuse a symlink,
  an extra file or a missing file in the source and verify every digest
  before the first write, then copy the inventory verbatim as the target
  receipt. They accept only the exact layout the producer emits, sorted and
  unique, with no row outside the `files` block. Without that, a row one
  reader skipped could make the copied receipt own a user's own skill, which
  `omh install --target agents` would later delete as retired. Each host
  `manifest.json`, and the `host_adapter` block of
  `omh install --target agents --host <host> --json`, drops `files`,
  `source_digest` and `digest_format` and names the inventory in a new
  `inventory` field; the schema stays `omh_host_adapter/v1`.
  `omh quality-evidence agent-skills` compares scan paths with that inventory,
  and the `source_digest` its receipts record keeps its definition and value,
  so stored receipts still compare.
- **The OMH TUI shows each subagent's output tokens.** A row in the agent
  view under the composer ends `12s · 3 tools · ↓1.2k tokens`, and the
  agent's log header carries the same count. While a subagent runs, the
  count is read from its own Hermes session in state.db (one read-only query
  per HUD poll, only while one runs), so it grows a poll behind each model
  call; once it finishes it is Hermes' own count. There is no token part
  until there is a count, and a narrow row drops it first. The delegation
  graph carries the same fact on each lane bound to a child (`output_tokens`
  in `delegation_graph/v1`, dag nodes included), and `/dag`'s Node details,
  its boxes and the tree show it where the line has room; once a lane
  carries a count, the boxes make room for one through the first hour of a
  run (`● Running 59m 59s · ↓999.9k`). Chat posts do not change.

- **`dag ulw`: a big job runs on its own as a graph.** Say `dag ulw <goal>`
  (also `dag ulw해줘`, `ulw dag`, `/dag-ulw`), or ask for a big job whose words
  say how it splits (parallel lanes, a fan-out, parts integrated afterwards)
  or how wide it reaches (every module, the whole codebase), and Hermes plans
  it as a graph of small nodes, runs the ready ones in parallel on its own
  `delegate_task` children, settles each from its handoff file, verifies the
  goal with a separate node, repairs failed nodes (two cycles each; a failed
  verification runs again after its repair, and only that re-run passes it),
  and adds the work the goal check finds missing to the same run (two rounds)
  before it reports. It starts at once and asks only for scope, spend or an
  irreversible step. A question about it ("dag ulw는 뭐야?", "how does dag-ulw
  handle repairs?") is answered, not run, and a stop, cancel or status word
  said to it ("dag ulw stop", "dag ulw 상태 보여줘") starts nothing: Hermes'
  route hint points that turn at the run's own `omh_dag` cancel or status.
  - The new `dag-ulw` skill carries the run loop and the planning doctrine;
    the new `omh_dag` tool keeps the run (`omh_dag/v1`), refuses cycles,
    unknown or self edges, shared write scopes without an edge and more than
    48 nodes, and never hands out more `delegate_task` calls than Hermes'
    background pool has free (read from `delegation.max_concurrent_children`
    and this process's running units in `state.db`). The run record keeps
    each node's prompt (at most 3,000 characters a node, created mode 0600),
    so a compacted parent can still hand nodes out; it keeps nothing a child
    returned. A node after a repaired one reads the repair's handoff files.
    `extend` adds nodes to a run whose nodes all passed, under the same
    refusals over the whole run, and every node records where it came from
    (`define`, `repair:<root>`, `extend:<round>`).
  - Big work reaches it by intent, in `omh chat` and in Hermes' own per-turn
    route hint alike (one reading, `plugin_bundle/omh/dag_ulw_cues.py`): on a
    route the router already gave `ultrawork`, never when ultrawork is named
    (`ulw`, `ulw-work`, `ultrawork`), and never for ultrawork's own
    coordinated workers or delivery cycle. In Hermes, a request no hint rule
    matched reaches it only when it says outright how the work splits. A
    concurrency word that names the bug or the feature ("fix the bug where
    uploads run in parallel", "동시에 두 요청이 오면 캐시가 깨지는 버그 고쳐줘")
    keeps the request where it was.
  - Graph topology is decided once, in `plugin_bundle/omh/dag_core.py`.
    `omh_team`, the fanout contract, a dag run in the delegation graph and
    the graph drawing read it there, with their refusals, layers and merge
    order unchanged (5,000 random graphs, old and new code, no difference).
    The delegation graph's own layers and a team's stages keep their walks:
    on a repeated node id or a hand-edited cycle the core answers otherwise.
  - The TUI panel, `/dag` and `omh hud --graph` draw the run under its name;
    on Discord, Slack, Telegram, Mattermost and Matrix a reply carries the
    start block once, one status line when counts change (none added when
    the parent's reply already is one), and the end block once the run is
    over. Nodes added mid-run hang from where they came from in the drawing,
    and the next status line names them once (`+1 added (repair: Docs
    body)`). A delegated child's own turn never gets a post. In the TUI the
    plan holds the run's layers, the graph its nodes, and the agents block
    only the children the graph does not draw; the agent view and a
    `delegate_task` tool row name a node's child by its label. The transcript keeps the
    run's graph as boxes (the tree where boxes cannot be drawn) at define,
    at each repair and extend with the added nodes marked, and once at the
    end, when the turn that ended the run is over; a chat never gets the
    boxes. `/dag` closes a run's graph with its critical path and the nodes
    that block the most others.
  - Coding nodes go to Codex or Claude Code only when the person chose that
    owner within the last day through `omh chat` or `omh coding` (the
    router's explicit-choice record, read exactly as the router reads it).
    Then `omh_dag` lists the ready coding nodes under `export` instead of
    handing them to `delegate_task`, and `omh_dag action=export` writes the
    fanout units and returns the `omh coding fanout` commands; verification
    and review nodes stay native, and an exported node is never handed to
    `delegate_task` again. The day is dag-ulw's own rule: an external CLI
    spends the person's money and quota, so a stale choice starts nothing.
    Hermes chat on its own records no choice, so there every node runs on
    `delegate_task`.

- **The delegation graph is drawn as frontiers of boxes, and `/dag` is
  interactive.** The boxes stand in frontiers (a node's longest path of
  recorded edges), side by side over a `· Same frontier` label, with one
  connector from each frontier to the next; each box holds the title, the
  category and model, the status and the parents (`← Export API`, or `Start
  node`). The drawing implies no edge: under the boxes, `Dependencies` lists
  every recorded edge exactly, and `Node details` gives a card to each
  running or stuck node and, in `/dag`, to the highlighted one. A frontier goes on one row while its boxes can narrow to fit, and
  wraps only past that. In the OMH TUI a box's border, title and status take
  its node's state: running blue, handed out indigo, failed red, done the
  terminal's foreground, waiting dim, selected violet; every state keeps its
  glyph and word. `/dag` opens the graph full screen and redraws it from the
  HUD's newest read: Tab and Shift+Tab move the highlight, Space folds a box,
  d shows or hides Node details, and nothing is sent anywhere. This replaces
  the #2179 boxes in `/dag` and `omh hud --graph`; the panel under the info
  line keeps the tree, and the chat posts are unchanged.

- **Vietnamese ships as a trigger language pack.** `src/routing/trigger_packs/vi.json`,
  contributed by @PhucNguyen-Dev (#2182), covers 20 of the 21 skills the `id`
  pack covers, with phrases such as `rà soát mã nguồn`, `kiểm tra khả năng
  tiếp cận`, `build thất bại` and `lập kế hoạch thực hiện`. The rule that
  makes a shipped pack phrase count only as a whole phrase now keys on script
  rather than on ASCII. The router folds diacritics, so `cần`, `bạn` and
  `thêm` score as `can`, `ban` and `them`; keyed on ASCII, no Vietnamese phrase
  was phrase-only, its words scored alone, and English sentences such as "can
  I ban this user from the chat" named a pack lane. A pack phrase whose letters
  are all Latin, with or without diacritics, now scores only as a whole phrase
  and merges after the `ja`, `ko` and `zh` phrases; Indonesian routes as
  before. With its words out of scoring, the pack can use the loanword
  Vietnamese developers say: `merge` replaces `hòa nhập`, and the backend
  phrase becomes `thiết kế contract cho endpoint`. A bare phrase clarifies
  with its skill named and dispatches where an English word the skill carries
  comes with it. `ultrawork` carries no Vietnamese phrase: its always-loaded
  body has 3 bytes left under the ceiling. The phrases have not been reviewed
  by a native speaker. `vi` is an input language only: it is not a
  `--language` / `OMH_LANG` output choice.

- **A delegation route is refused when Hermes would not send the child where
  it says.** `omh_delegate_route` wrote model, provider and effort, and
  answered `routed` even when Hermes would build the child elsewhere. That
  was measured with Hermes' own resolver functions, imported from `git
  archive` copies of Hermes main `8b9ac5773e`, `v0.22.2` and `v0.21.1`:
  - With `delegation.base_url`, `delegation.api_key` and
    `delegation.api_mode` set, a route to `anthropic` built a `custom` child
    on that endpoint, using `delegation.api_key`.
  - With a local `model.base_url` and no `model.provider`, Hermes'
    local-endpoint fallback ignored the requested provider. The child went to
    OpenRouter with the OpenRouter key, or the dispatch failed for want of
    one.

  `set` and `fallback` now refuse these cases with `status: error`, a
  `reason`, and `conflicting_keys`:
  - a direct `delegation.base_url` that overrides the provider, or that
    names it but has no `delegation.api_key` of its own, so the parent
    session's key would be sent;
  - a route with no provider that would remove an SDK provider beside that
    endpoint;
  - the local-endpoint fallback;
  - a managed config (`$HERMES_MANAGED_DIR` or `/etc/hermes`) that sets the
    endpoint or pins a route key;
  - a managed config that gives `delegation` one non-null value, which
    replaces the whole section;
  - a config line OMH cannot read safely, including a repeated key, a merge
    key, a value continued past its line, and a `model:` or `delegation:`
    given as an alias, anchor or tag. A one-line flow mapping there is read,
    the shape Hermes' own `save_config` keeps.

  `openai` is refused under the local-endpoint fallback, because Hermes
  v0.21.1 to v0.21.3 send it to OpenRouter. A spelling Hermes versions read
  differently, such as `n` or `0e0`, is undecidable. A route that names no
  provider still writes over `delegation.base_url`, and `status` names that
  endpoint under `child_endpoint`.

  A refusal changes nothing in `config.yaml` and records nothing: no restore
  record and no provenance. The route lock's file is the only file left.
  OMH changes none of the keys it names. Restoring the person's own values is
  never refused. A leading byte-order mark before `delegation:` is now kept,
  and that section is reused instead of a second `delegation:` being
  appended. Hermes' loader rejected the duplicate.
- **A Hermes compaction no longer reads as the end of the work, for the
  delegation route or for `omh_team`.** Hermes' rotating compaction
  (`compression.in_place: false`; the default in-place compaction keeps one
  session id and was never affected) closes the running session row with
  `end_reason` `compression` and goes on in a new row that names it as its
  parent. Three OMH readers took that for an ending or a different session.
  The session-start restore of a delegation route read the writer's closed
  row as "not live" and put the person's baseline back while the compacted
  conversation was still dispatching; it now follows the continuation, keeps
  the route while any continuation is running, restores once Hermes closed
  every one, and holds it as `continuation_unverified` when the continuation
  cannot be read, for at most six hours of the route's age
  (`continuation_unverified_expired` after that). A team helper that compacted
  came back under its new session id, which matched nothing, so its part
  stayed `dispatched` until the four-hour bound blocked it as "never came
  back"; the return now links to the attempt through the earlier segments the
  new id continues. A parent that compacted after `team_start` lost its team:
  `team_reconcile` and `team_status` from the new segment answered
  `team_not_found`, and a helper's start or stop naming the new segment was
  dropped; the team is now found under the segment that started it, and a
  `team_start` there binds to the plan accepted before the compaction. All three
  read only the links Hermes itself writes on a compaction (the closed row's
  end reason, the new row's `parent_session_id`, and its inherited
  `_delegate_from`), never the same parent or a nearby time, and delegate
  children under a segment do not count toward the lineage bound. A return
  whose links cannot be read links to no part: it is kept on the team as
  `unlinked_returns` and said by `team_reconcile` while a part is still out,
  and a part still out at the four-hour bound stops as `return_not_linked`
  instead of "never came back". A team asked for from a session whose earlier
  segments cannot be read is refused as `team_lineage_unverified`, with the
  reason, instead of `team_not_found`. The conversation identity the HUD,
  board lanes, cost receipts and `fallback` own records by now decides each
  link with the same predicates, so the five row shapes where it used to
  answer differently agree: a rotated delegate child keeps its earlier
  segment (and its route position), a stale sibling Hermes left beside a
  continuation under any segment is counted in the conversation, a reset fork
  is never a continuation whether or not it sits beside one, and a rotated
  branch keeps its inherited `_branched_from` lineage. Every segment of a
  conversation, the middle ones included, answers the same set. Past 64
  rotations the identity, like the walkers, stops at 64 links and keeps what
  it verified up to there, so which end drops out depends on the segment
  asked from; it used to have no bound.
- **A delegation child's model verdict rests only on what the run recorded.**
  A HUD row's `model_attestation` says whether the model that answered a
  child is the model it asked for. It had two ways to report a match it could
  not prove. A child whose session row names no model was judged against the
  current `delegation.model`, which OMH rewrites for each dispatch and puts
  back at turn end, so the same finished child read `agreement` or
  `disagreement` depending on when the HUD was read. And the request was read
  from `sessions.model`, which Hermes rewrites to the answering model on a
  session's first accounted call when that call names a billing provider, so
  a substitution on a child's first call read as `agreement`. The request now
  comes from the `Model:` line of the identity trailer Hermes stored with the
  child's first system prompt (`requested_source: prompt_identity`), written
  before its first call. Hermes rewrites that stored prompt from the running
  model, which after a fallback is the fallback, at an in-place compaction
  (its default) and at the start of a later turn, so the line is read only on
  a first segment with no archived message and at most one user message.
  Not covered: a row Hermes creates late (a retry after a transient create
  failure, or a re-create after the row disappeared mid-run) carries the
  in-memory prompt, and nothing in the row marks it. Without an attested
  request no agreement is reported. These cases read `unknown`, and the
  basis says which:
  - `requested_model_not_attested`: no stored first prompt names a model
    (none is stored, the row is a compression continuation, the schema lacks
    the columns, the read failed, or the trailer has no `Model:` line), and
    `sessions.model` agrees with the answering model.
  - `requested_model_prompt_may_be_rebuilt`: a first segment's stored prompt
    was withheld (an archived message, or more than one user message), and
    `sessions.model` agrees with the answering model.
  - `no_requested_model`: neither an attested stored prompt nor
    `sessions.model` names a model.

  In the first two cases, a `sessions.model` that disagrees with the sole
  model the usage rows name reads `disagreement`. The answering side is
  judged before any of the three: no usage row (`no_usage_observation`) or
  more than one usage model (`multiple_usage_models`) also reads `unknown`.
  `delegation_route` is no longer emitted. Measured read-only over every
  delegation child row in two local Hermes databases (a profile and a
  pre-update backup, 550 children; rows still only in the WAL were not
  read): 518 requests attested by the stored prompt, 32
  withheld (28 compacted in place, 4 with more than one user message); 513
  `agreement`, 30 `unknown` because the prompt may be rebuilt, 7 `unknown`
  with more than one usage model. Before the change the same rows read 543
  `agreement` and 7 `unknown`.

- **Delegated work is drawn as a graph in the OMH TUI and `omh hud --graph`,
  and reported in chat replies at three moments.** A conversation's
  `delegate_task` children, its `omh_team` parts, or a fanout's units are
  drawn as boxes with their title, category, model and effort, and state,
  joined by the edges OMH or Hermes recorded: a dispatch from parent to child,
  or a `depends_on`. Lanes one turn dispatched form a wave; waves are not drawn
  as dependencies, and a wave that settled more than 15 minutes ago leaves the
  drawing while newer work moves. Where boxes do not fit, or a shape cannot be
  drawn without implying an edge, the same graph is a compact tree. The OMH
  TUI draws it live above the plan, with two-line boxes where four-line ones
  do not fit its third of the screen, and `/dag` opens it whole in the pager.
  The `[Agents]` block stops repeating a native lane the graph draws, and its
  header then counts only the rows it still lists, so the lanes have one
  count line, also past the eight rows it lists. On Slack, Discord, Telegram,
  Mattermost and Matrix a reply never carries the boxes. The reply Hermes
  sends gets a code block naming the run (`DAG · <name> · <N> tasks · <W>
  layers`, then one line per layer) once when the run starts, a plain count
  line (`DAG <name> · 1/3 done · 1 running`) on a turn its counts changed, and
  a short block once when every lane has settled, or when nothing has moved
  for 15 minutes: each lane under Done, Failed or Stopped, the lane that
  failed first and the totals. Where a block and the reply do not fit one message, the count line
  goes in its place; where even that does not fit, a later reply carries it.
  OMH sends nothing itself. A category is shown only where the route OMH
  recorded matches the model the child ran, and no field reads current
  config: what has no record is `?`. The structure comes from a new
  metadata-only record, `delegation_ledger/v1`, written from Hermes'
  `subagent_start`, `post_tool_call` and `subagent_stop` hooks; a
  conversation's record that no hook wrote for a day is removed.
  `OMH_SUBAGENT_GRAPH=off` turns it off everywhere. The TUI no longer draws
  the fanout-only `DAG · N ready` block; a fanout is drawn by the same view.
  A native child with no news for 30 minutes is `unknown`, an `omh_team`
  repair is `repairing` only while its child runs, and a stuck fanout unit
  (its dispatcher's `unit_state`) is drawn `stuck`. In the TUI the graph is
  in the theme's colours: edges step from violet to blue down the layers
  (`dag_edge_start`, `dag_edge_mid` and `dag_edge_end`, which a palette can
  name), a box's border shows its state, and every colour is measured against
  the terminal's background. It is painted at the depth the terminal takes
  (24-bit, 256 or 16 colours, none with `NO_COLOR`), and colour changes no
  character or width. A chat post is always plain text.

- **`omh_delegate_route` `fallback` advances only the calling conversation's
  own route (#2175).** With two sessions on one profile, `fallback` took its
  chain position from whichever session had routed last: the newest
  provenance record, or the live `delegation.*` keys whenever OMH had written
  them. One session's route then decided another's fallback: an error naming
  a model the caller never routed, a fallback from the other session's
  model, an exhausted chain while the caller's own chain still had
  candidates, or the other session's live route advanced one step with the
  caller recorded as its writer. The position now comes from the newest
  route-leaving provenance record whose `session_id` belongs to the calling
  conversation, which is the host's session id plus its compression
  continuations, the set the HUD already owns route records with. The live
  keys count only when the restore record names a writer in that
  conversation and the file still holds that write. A conversation with no
  route of its own gets the existing `no active route to fall back from`
  error with `position_source: "none"`, and nothing is written. A record
  that names no session is nobody's, so a call that reaches the tool without
  the host's session id gets that error too. Like `set`, a fallback still
  writes into the profile-wide keys, and it now does so from its own
  position. Where another session's route is live, the fallback that 4.0.0
  refused with a category mismatch now replaces that route with the
  caller's next candidate, and when the caller's own chain is exhausted it
  clears that route, as the issue scopes. The leaked-route check before a
  baseline is captured still reads every session's records.

- **Every Hermes `delegate_task` child gets OMH's delegation protocol.** The
  `coding-handling` harness requires the protocol in every delegated or
  reviewer prompt, runtime-native spawns included, but a Hermes-native child
  got it only when the parent model pasted it into the goal. The plugin now
  registers a second system prompt section, `omh.delegation-protocol`, which
  renders only for a session Hermes builds as a `delegate_task` child
  (platform `subagent`). It carries the goal echo-back, verification-stop and
  re-review-cap lines that `omh coding composition-guide` returns, which now
  read the same definitions. Only the goal echo-back applies to every child.
  The verification rule is framed for a task that changes files, and the
  review rule for a child that reviews work against stated success criteria.
  The section also reaches children no OMH-guided parent wrote, such as
  Hermes' own `/review` reviewer, whose brief from Hermes states no success
  criteria, so the review rule's condition does not match it. The section
  renders once in each child's system prompt. The `coding-handling` harness
  and `omh coding composition-guide` (its `applies_to` and its printed
  header) now tell the parent not to paste the protocol into a Hermes
  `delegate_task` goal, and still to embed it for Codex, Claude Code and
  other runtime-native spawns. A goal that pastes it anyway carries it twice. The parent's own
  prompt, the dispatched goals and the bot persona do not change. Each
  child's system prompt grows by 1,007 characters: the 920-character section
  plus Hermes' framing (#2174).

- **`omh_probe` says why its own package probe did not import, and a broken
  import hook cannot make the classifier raise.** When `omh.probe` alone fails
  to import, the probe's bundle answer now carries a `package_probe` row with
  that failure, so the `package_backend` row, which reports the Loop backend,
  is no longer the only reason given. An import hook that raises for the name
  `omh` itself now reads `broken` instead of raising out of `omh_loop`,
  `omh_decision_gate` or `omh_probe` (#2166 follow-up).
- **A plugin-only install says why native Loop has no backend.** Every
  documented install puts the `oh-my-hermes` package in OMH's own environment,
  so the interpreter Hermes runs usually cannot import it. `omh_loop` still
  refuses there with `service_unavailable` and reads or writes no Loop state,
  and now carries a `package_backend` block: `absent` when the interpreter has
  no `omh` package, `incompatible` when it finds an `omh` that lacks a module
  or name the bundle imports, and `broken` for any other failure while
  importing it, including one that is not an `ImportError`. A present `omh`
  never reads as absent, and the block names the plugin's own version beside
  the package's. The detail used to say "install oh-my-hermes or use the omh
  loop CLI". It now says the plugin is registered, that an environment Hermes'
  package manager prepares has no supported way to add the package yet, that
  an environment you manage yourself can take it, and that
  `omh --omh-home <that home> loop status` reaches the same Loop store.
  `omh_decision_gate` raised `ModuleNotFoundError` there for a payload of the
  required shape; it now answers `unavailable` with the same block and records
  nothing. `omh_probe` reports the same state as its own `package_backend`
  row, apart from registration, and answers from the bundle whenever the
  package's own probe cannot be imported, where it used to raise for a present
  but broken package. A sweep that called each of the 22 tools and 10 hooks on
  a plugin-only host, with one or more payloads each, found no other raise.
  The Installation page now lists native Loop, the decision gate, `omh_team`
  and `omh_source_trust` among the features that need the package, and no
  longer tells every reader to install it into Hermes' environment (#2166).
- **Bare `omh` opens the OMH TUI on Bun and npm installs (#2168).** The npm
  and Bun launcher puts its extracted cache on Python's import path only
  inside its own process, and the TUI's interpreter, started `-E -P` by the
  frontend shim, could not import `omh`: bare `omh` said `the OMH TUI could
  not import itself: No module named 'omh'` and opened Hermes' own TUI.
  `omh` now hands the TUI the directory it imported its own `omh` package
  from, in `OMH_TUI_SITE`, and the shim's bootstrap puts that directory first
  on the import path when the interpreter does not already import `omh` from
  there. It then writes no bytecode: the launcher checks its cache against a
  digest on every run, and rebuilds a cache that has bytecode in it. `-E -P`
  stay, so Hermes' `PYTHONPATH` still never reaches the OMH interpreter, and
  `omh` sets the variable on every launch, so a value left in your environment
  does not choose the tree.

## 4.0.0 - 2026-10-19

- **Indonesian ships as a trigger language pack.** `src/routing/trigger_packs/id.json`,
  contributed by @fauzibrevy-hub (#2154), covers the 21 skills the `ja` and
  `zh` packs cover, with phrases such as `tinjau kode`, `audit aksesibilitas`,
  `build gagal` and `lakukan riset mendalam`. It is the first pack in a
  Latin-script language, and that shares the English token space: Indonesian
  borrows `bug`, `crash`, `error` and `file`. So a shipped pack phrase written
  entirely in ASCII now scores only as a whole phrase. Its words never join the
  skill's trigger tokens, and the lexical shortlist leaves it out of the
  skill's English document and anchors. Tests hold every skill's trigger
  tokens, lexical document and anchors equal to the view with its ASCII pack
  phrases taken out, and refuse an ASCII hold-back entry that none of the
  pack's own non-ASCII phrases carries. ASCII pack phrases merge after the
  `ja`, `ko` and `zh` ones, so `SKILL.md` descriptions and capability rows,
  which show only a skill's first triggers, keep the cues they showed before.
  Phrases that routed ordinary Indonesian chat (a team work plan, "ask me one
  at a time", a medicine reminder) did not ship, and neither did a few that
  read as word-for-word translations. `ultrawork` carries one Indonesian
  phrase, `implementasi paralel`: its always-loaded body had room for one
  under the byte ceiling. `id` is an input language only: it is not a
  `--language` / `OMH_LANG` output choice.
- **OMH TUI tool calls read as in Claude Code.** Each call is one row,
  `⏺ read_file(README.md)  0.2s`: a `⏺` in the accent while it runs, green
  once done, red when it failed or was denied, in place of the `✓` and `✗`
  marks, then the tool's name and what it ran on in parentheses. What it
  printed, and an edit's diff, hang under `  ⎿  `, as a command's output
  does. A read or a load no longer echoes the first lines it read: it says
  `Read 715 lines` (`read_file`), `loaded skill omh-docs` (`skill_view`) or
  `12 matches` (`search_files`). A resumed session's earlier calls read the
  same way, with a dim `⏺` (Hermes' record keeps no outcome) and an edit's
  diff under it, in place of the `· read_file  README.md` rows with a blank
  row between each.
- **An answer you gave Hermes reads under the call it was about.** The
  record of an approval or a question (`✓ allowed once · <command>`,
  `✓ blue · Which colour?`) was written above the turn's live tool calls, so
  with one row per call it stood over the first read of the turn. It is now
  the first row under the call that asked, `⎿  ✓ allowed once · <command>`,
  on the same green or red band; a denial reads `⏺ terminal(…)`, then
  `⎿  ✗ denied · …`, then Hermes' denial line. With no call running (a
  subagent's question after its turn), it is still a row of its own. A
  clarify question Hermes timed out, or one you cancelled, says so once under
  its call (`⎿  ✗ timed out · Which colour?`), not again in a bare
  `⎿  timed out` row under that.
- **An OMH TUI diff no longer doubles each changed line.** Hermes pads every
  added and removed line of an edit's diff with spaces, to 143 columns in a
  live patch, so on any narrower terminal each green or red band wrapped into
  a second, empty band row. A diff line's trailing spaces are dropped now;
  the band still reaches the right edge.
- **The OMH TUI's working row reads as Claude Code's.** It was a braille
  spinner and Hermes' kaomoji text (`⠋ (⌐■_■) analyzing... (12s)`). It is now
  `✶ Analyzing… (12s · ↓1.2k tokens · thinking with high effort · esc to
  interrupt)`: a glyph turning through `· ✢ ✳ ✶ ✻ ✽` (still under reduced
  motion), Hermes' verb without its face or dots (`Working…` when it gives
  none; a stall or retry notice, `No response from provider in 120s —
  reconnecting…`, keeps its words), and the effort when the session reports
  one. A tip naming a key sits
  under it, one a turn, on a terminal 16 rows tall or more
  (`⎿  Tip: ctrl+o shows the whole transcript`); it is local text and nothing
  is sent. `interrupting…` lines up under the same glyph column.
- **Your prompt and a turn's end read as in Claude Code.** A prompt in the
  OMH TUI transcript is a dim `>` and dim text, with no tinted band behind
  it, and a command's echo takes the same `>` (`> /model`). The `↳ you: …`
  reminder over a running turn loses its band too: `↳ you:` in the accent,
  your words dim. A turn's done
  line is one dim line under the reply, `✻ 5s · 3 tools · ↓1.3k`, without
  the rule that ran to the right edge.
- **The OMH TUI's composer is a rounded box over one dim info line, as in
  Claude Code.** The composer's two rules, the mode row and the dark status
  band are gone. The composer sits in a box (`╭─╮`, `│ > … │`, `╰─╯`) that
  keeps its colour in every mode, and the line under it, two cells in under
  the box's text, says the mode or the keys that matter now on the left (`? for shortcuts`
  while the composer is empty, `⏵⏵ accept all on (⇧⇥
  to cycle)` in accept's colour, `⏸ plan mode on (⇧⇥ to cycle)` in plan's, a
  question's or a picker's keys) and the model, `ctx 5%` and `effort medium`
  on the right, with the OMH HUD's repeat and in-flight tool counts first
  when there are any. The `⚚ OMH` brand and the `idle` / `running` words
  are gone: the working row, the strip and the queue rows already say them,
  and during a turn the left names only the steer keys, since the working
  row already offers `esc to interrupt`.
  On a narrow terminal the right side gives way first, the model shortening
  to `deepseek-v4.1-flash` and then `v4.1-flash` before it goes. The line is
  on every terminal of 3 rows or more, so the mode is never hidden, and the
  agent list now opens from 6 rows (and 20 columns) instead of 10. A `!` shell line keeps its `! shell`
  label, and its `>` mark turns the accent colour.
- **The OMH TUI opens on a clean screen.** As it starts, what your terminal
  showed above the cursor (your shell, the warnings `hermes` printed) scrolls
  up into the terminal's own scrollback, and the TUI starts on the top row.
  Nothing is erased: scroll up to read it, until a full redraw (a resize,
  Ctrl+L, `/redraw`) clears the scrollback. A launch that falls back to
  Hermes' own terminal leaves the screen as it was.
- **Hermes' note about a skill named like a built-in command is no longer an
  OMH TUI notice at every start.** Hermes' own bundled `plan` skill shares
  its name with `/plan`, so every start said `Hermes' command catalog: slash
  command /plan unavailable — name taken by built-in; use /skill plan`.
  `/help` now lists those notes, in Hermes' words, under the skill count; a
  real discovery failure (skills, quick commands, plugins) is still a notice.
- **`omh handoff-risk-scan --repo` completes on ordinary repositories.**
  The scan charged the raw bytes of every Git listing to its 1 MiB metadata
  budget, and the index listing with its stat lines alone prints about 190
  bytes per short-path entry, so a clean repository of 4,500 short-path
  files, or 6,538 files with 59-byte paths, ended in
  `scan_error / metadata_oversized`, far under the documented 10000 entries
  (#2157, reported by @jhlee0409). The budget now charges what the scan keeps:
  the HEAD and branch output, each committed path with its mode and object id,
  each index path the commit lacks, and the untracked listing; a path in both
  the commit and the index is kept and counted once. The 10000-entry and
  1 MiB limits are unchanged. The tree and index listings are read in 64 KiB
  pieces up to a fixed cap derived from them, and a longer listing still kills
  the Git process and ends the scan with `metadata_oversized`. Git output the
  scanner failed to read is a scan error, never an empty listing.
- **A party named before a Korean data-share place, or after an English one,
  keeps the review.** Korean puts the data, and any party, before the place,
  and only the place was read: "보험사가 원하는 고객 엑셀 개인정보 마스킹해서
  개발팀에 보내줘" read inside and named no review. Every word outside the
  places and before the requested verb must now be a closed word, as English
  already reads the span before a send: data containers and field names in
  either script, a verb the rule knows, an inside place word, a determiner or
  a softener, and a word that says whose records the data holds (고객, 회원,
  환자, ...) only bare and right before a data word. A party acting
  ("보험사가 원하는"), owning ("보험사의", "고객의"), a purpose ("협력사용",
  "보험사를 위한") or any other noun ("삼성 고객 파일") keeps the review, and
  "-기 전에" is a step rather than a place. Korean also read only the first
  sentence; a later one now counts when it sends, names a recipient or a
  place outside, or names a party acting ("... 개발팀에 보내줘. 벤더한테도
  보내줘.", "... 보험사가 볼 거야."), and remarks alone ("급해요.") say
  nothing. In English a place now ends with its sentence (".", "!", "?" or
  ";" before a space), so "... send it to the dev team. It's urgent." names
  no review, while every sentence is still read for sends and the words after
  a place must be remarks -- thanks, please, urgency -- so "... to the dev
  team. Acme will review it." and "... Also cc Acme." keep it. A line break
  alone ends no sentence, because the router reads it as a space; a period
  before a space ends one even after an abbreviation ("Acme Inc. today", "the
  U.S. team"), which only cuts a place short. Between a send and its "to"
  only closed words may stand, read as the span before the first send is:
  the data, also as protected, counted or the version the redaction made
  ("the anonymized copy", "both files", "the updated file", "the customer
  export"), the verb's particle, "straight" or "directly", and remarks; so
  "send it where Acme wants it, to the dev team" and "send the Acme copy to
  the dev team" keep the review, and so does any other word there ("send the
  sorted export to the dev team"), the safe direction. The Korean reader no longer
  opens a quote at an apostrophe after a Latin letter or digit, nor closes
  one before a Latin letter, so the router and the hint read "고객 정보
  마스킹해서 Acme's team에 보내줘. It's urgent." alike; a quote a Korean
  particle follows ("'고객 정보'를") is still a quote.
  Measured against main on sets written before the change (104 Korean
  outside rows, NFD copies included; 80 Korean inside controls; 57 English
  sentence-end rows) and every earlier data-share set: no request to an
  outside party lost the review on admission, router offers or the hint, and
  the router and the hint never disagree with every cache cleared (three
  disagreements on main). Korean outside rows gained the review on
  admission and the hint from 16 to 98 of 104, and on router offers from 2
  to 26; the six left are two that name a regulator, which reads as a legal
  question, and one that names no personal data, each with its NFD copy.
  Korean requests sent on in a later sentence gained it from 0 to 12 of 12.
  English inside requests followed by a remark stopped firing (20 to 5 of
  20), and no English inside request on these sets or the review's starts
  firing. Of 196 Korean inside rows that read inside on main, 8 now fire, the
  safe direction: an order history, survey responses, "this month's" orders,
  and "고객의" (a customer's), each with its NFD copy. On the review's own
  sets no outside request lost the review either, and 19 more Korean inside
  rows now fire for the same kinds of word: time words ("이번 달", "지난달",
  "어제 받은", "오늘 안에"), descriptors ("주문 내역", "거래 내역", "설문 응답",
  "가입 정보"), an inside team acting ("우리 팀이 만든", "개발팀이 요청한"), and
  "고객의".

- **A plural possessive no longer hides the rest of a message from routing.**
  The routing masker read the `'` of "the customers' export" as an opening
  quote. Nothing closed it, so everything after it was masked and no matcher
  read the verb or the place: "Redact the PII in the customers' export and
  send it to Acme." got no data share review from the router or the hint, and
  in "explain the users' '$ulw-work' snippet" the possessive paired with the
  next quote and left `$ulw-work` to dispatch. A `'` that ends a word now
  opens no quote: one right after a letter or digit that is not East-Asian
  wide (CJK, kana, Hangul or fullwidth), and right before whitespace, one of
  `.,;:!?)]`, an East-Asian wide character or the end of the message. It
  still closes one that is open. A `'` after a space or an East-Asian wide
  character (`고객' list`), or glued to more text (`f'$x'`, `API''`), still
  opens one.
  The data share review also reads `’` between two letters ("it’s", as Mac
  and iOS type it) as an apostrophe, as it reads `'`, not as a quote.
- **Two OMH TUI subagents whose goals start alike read differently on the
  strip.** The strip names an agent by the first words of its goal, and two
  goals that began the same were numbered with those words, so two shell
  tasks read `1·Run the shell  2·Run the shell` and nothing said which was
  which. Agents that share a name now show the word where each goal parts
  from the one nearest it, out of any quotes or backticks around it (with the
  next word when it is one like `in`), so goals that part at `` `echo alpha` ``
  and `` `echo beta` `` read `…alpha` and `…beta`; the numbers stay only for
  goals whose words still read the same.
- **A fresh OMH TUI session no longer shows the last session's subagents.**
  Hermes writes a session's `state.db` row on its first prompt, so a new
  session's key mapped to nothing until then, and the HUD reader fell back to
  every conversation's recent delegate children: a session nobody had typed
  in yet opened with `[Agents] │ [global] 2 done` and the previous session's
  rows. The TUI's own key now owns no children until its row exists, and the
  panel stays empty. Other readers that name an unmapped reference (the
  desktop pane, the plugin tools) keep the documented global fallback.
- **Denying an OMH TUI approval also stops the turn, as Esc does in Claude
  Code.** A deny went to Hermes and the turn went on, so the model often
  tried the next thing straight away. Every deny the person gives (Esc,
  Ctrl+C, `d`, `n`, Enter on deny, and Up then Enter typed ahead) now sends
  the explicit deny first, so the waiting tool ends denied, and then
  interrupts the running turn (`session.interrupt`, the call Esc makes on an
  empty composer); with no turn running only the deny goes, and the mode row
  then says `d or esc denies`. An approval a
  subagent asked for stops the session's whole turn. The tell row is the one
  deny that does not stop: it redirects the running turn instead. The mode
  row says so in plain words, `↑↓ pick · enter confirms · d or esc denies and
  stops`, down to `esc denies and stops` on a narrow row.
- **An OMH TUI approval can be denied with what to do instead.** Telling
  Hermes what to do after a deny took a deny, then a separate Ctrl+Enter
  steer. The approval's last row, `no, and tell Hermes what to do instead`
  (last, as Claude Code puts its "No, and tell Claude" row), sends the
  explicit deny at once, so the turn is not held, and opens the composer
  labelled `↪ tell Hermes what to do instead · enter sends · esc cancels`.
  What you send goes into the running turn as a steer through the same path
  as Ctrl+Enter (a refused steer waits in the queue, an unanswered one comes
  back after 120 s), or as an ordinary prompt once the turn has ended, which
  waits behind a prompt you queued and never steers it; the tell row of a
  later approval keeps that composer open with what you typed. Esc sends
  nothing more and brings your draft back. Deny stays first and
  highlighted, the highlight still stops at both ends, and no digit or
  letter but `d` and `n` answers.
- **An OMH TUI approval offers Hermes' "always allow" when Hermes does.**
  The OMH TUI left Hermes' `always` choice to `hermes --tui`. When Hermes
  lists it (it leaves it out where a permanent allow is refused, such as a
  command its smart approval flagged), the approval now has a fourth row
  under allow this session, labelled with what it allows, `always allow
  recursive delete (Hermes saves it)`: Hermes saves that kind of command in
  its config (`command_allowlist`), so later ones run without asking. Like
  every allow it takes the arrows and Enter; the transcript records
  `✓ always allow sent (Hermes saves it) · <command>`.
- **Every OMH TUI question asks for your attention, not only an approval.**
  An approval rang the bell; a clarify question, a sudo password or a secret
  signalled nothing, and Hermes drops a clarify question nobody answers after
  300 s by default. Each request now rings the bell once as it opens and,
  on a terminal that shows them, sends the notification a long turn's end
  sends (OSC 9 in iTerm2, WezTerm and Ghostty, OSC 777 in foot and rxvt),
  saying what Hermes asks (`Hermes asks: Which colour?`, never a value).
  `OMH_TUI_BELL=0` keeps all of it quiet.
- **The OMH TUI stops billing your answer time to Hermes.** While an
  approval or a clarify question was open the working row kept spinning,
  `⠼ working… (16s · ↓262 tokens)`, beside the status line's `waiting on
  you`; a command you took 20 s to allow then read `✗ terminal  rm -rf
  ./tmp-a  21.8s`, as if it were slow. The working row now reads `? waiting
  on you (11s)` with no spinner and one clock, that wait's (the OMH tool
  count beside the model shows no seconds of its own meanwhile, and leaves with the
  turn instead of lingering into idle); a tool's row
  leaves the wait out of its time; and the done line keeps the turn's wall
  clock with the wait beside it, `✻ 30s (27s waiting on you) · 1 tool`.
- **The OMH TUI's transcript records how each question ended.** A clarify
  question left only Hermes' tool row (`✓ clarify  Which colour should I
  use?  2.5s`), a `✓` even when it was cancelled, and the answer appeared
  nowhere but in the model's reply; a sudo or secret prompt left nothing.
  Like an approval's `✓ allowed once` / `✗ denied`, the answer now goes
  above the call it was about: `✓ red · Which colour?` (ticked labels
  joined, or what was typed, as Hermes reads the answer: without the
  `(Recommended)` tag it shows on a choice, and with empty items of a
  multi-select answer left out), `✗ cancelled · <question>` or `✗ skipped`
  (also a multi-select answer with no item left), and
  for sudo or a secret only `✓ answered` or `✗ declined`, never the value. A
  question Hermes withdrew reads `✗ timed out`, `✗ interrupted` or
  `✗ withdrawn (<reason>)` with what it asked, in place of the amber
  `Hermes withdrew its <method> request (<reason>).` A clarify call that got
  no answer is a red `✗ clarify` row with `cancelled`, `timed out` or `not
  delivered` under it, not a `✓`.
- **OMH TUI clarify questions that take several choices are answered with
  several.** Hermes' `multi_select` was never read: the question looked like
  any other and went back as one label, and an answer typed as `1,3` reached
  the model as one string. Such a question now says `(choose one or more)`
  and boxes each choice; Space or the choice's digit ticks it, Enter sends
  the ticked ones (the highlighted one alone when none is ticked), and an
  answer of your own joins them. The answer is the JSON list Hermes' Ink TUI
  sends (`["ham","cheese"]`, in the order ticked), in the same `answers`
  frame as before; a single-select question is unchanged.
- **An OMH TUI question says when others wait behind it.** A second request
  that arrived while one was open queued with nothing on screen to say so;
  the open question now ends its first words with `· 1 more question
  waiting` (or the count). A request the TUI cannot show (a terminal read, a
  vault prompt) that arrived behind an open question waited for it to close
  before its decline was sent; it is declined at once, with its notice, as it
  is when nothing is open.
- **OMH TUI clarify choices wrap instead of being cut to one row.** At 80
  columns `❯ 1. Blue/green with a full traffic switch after smoke tests pass
  on the gree…` lost the `(Recommended)` tag Hermes puts at the end of the
  first choice, and the rest of a choice up to Hermes' 8000 characters. Each
  choice (an approval's too) now wraps under its number, the slot counts
  rows rather than choices, and a terminal too short for every choice keeps
  the highlighted one whole, or its first rows, with `… ctrl+o shows all`.
  Choices it cannot list are marked beside the list on the side they are cut
  (`… +3 more choices, 1 ticked · ctrl+o shows all`; an approval's
  `… more choices`, which numbers nothing), so a cut tell row or a ticked
  choice scrolled away is never silent, and the marker no longer ends the
  question's text.
- **An OMH TUI question you cannot see whole says so, and Ctrl+O shows it.**
  A long approval command showed its first 6 of 20 lines at 24 rows, and
  Ctrl+O did nothing while the approval was open; below 10 rows a cut had no
  marker, at 6 rows no command row was drawn at all, a narrow terminal cut the
  approval's header, and under 6 rows or 20 columns a sudo, secret or typed
  clarify question showed no label. Every cut now ends with `… ctrl+o shows
  all` (`… +14 more lines · ctrl+o shows all` under a command's first lines),
  from 6 rows a command's first row is drawn, the header and a value prompt's
  label wrap, a tiny terminal keeps one row for a typed question's label, and
  Ctrl+O while a question is open pages it whole: it answers nothing, and q
  or Esc returns to the question with the same row highlighted.
- **Enter on an OMH TUI `/` or `@` menu takes the highlighted row, as in
  Claude Code.** A command typed in full still runs on the first Enter. Esc
  closes the `/` menu, and both menus stop at their ends.
- **The OMH TUI's Ctrl+R search and agent list stand where the composer
  was**, as the pickers do: the composer is hidden, the search's caret is at
  the end of its query, the agent list takes every key (only its own act, so
  typing never turns into a steer; Esc, Left, `q` or Ctrl+C leaves it), and
  the mode row says their keys.
- **An interrupted OMH TUI turn says so until Hermes stops, and the queue
  waits.** After Esc or Ctrl+C the working row says `interrupting…` until the
  turn ends, and the queue does not start: queued prompts come back into the
  composer unsent, a queued `!` line waits until your next prompt.
- **The OMH TUI's `/model` picker opens on the session's model.** It marks
  that model (first, when no provider lists it) and shows `Model (12/162)`
  once it scrolls.
- **OMH TUI list commands leave no echo in scrollback.** Bare `/sessions`,
  `/rewind`, `/keys`, `/history`, `/logs` and `/redraw` leave no `> /name`
  row.
- **New OMH TUI keys.** Ctrl+X opens the session picker, Ctrl+_ and Ctrl+Y
  undo and redo in the composer, and Ctrl+Z suspends to the shell on POSIX
  (Hermes' gateway stops with it; `fg` draws it again under what the shell
  printed). Where Shift+Enter would send, the mode row names the
  newline keys while a draft spans lines.
- **`/omh-model` no longer stops the OMH TUI's gateway.** A reply keeps
  streaming underneath and a question closes the picker with nothing saved;
  the picker stops at its ends and says `esc cancel`.
- **A crashed Hermes gateway comes back.** When Hermes' `tui_gateway` exits
  with a failure, the OMH TUI starts it again from the launcher's
  environment and resumes the session, saying so (`The Hermes gateway exited
  (code 1): starting it again and resuming session <id> (1 of 3 in 60 s);
  what you type waits until it is back, and ctrl+c leaves.`), at most three
  times a minute.
  Each attempt waits up to 15 s for the new gateway (`HERMES_TUI_STARTUP_TIMEOUT_MS`
  when set, as in Hermes' own TUI), Ctrl+C or Ctrl+D while it waits leaves
  with the new gateway stopped, and one that exits before it resumed the
  session uses an attempt, as in Hermes' own TUI. An
  open question closes unanswered, a running turn is reported lost and not
  sent again, a steer the old gateway had not answered, and what was typed
  in an approval's tell field, come back to the composer at once, the
  subagents on the strip stay there (those still
  running marked interrupted) rather than reappearing as look-alike rows in
  the HUD's `[Agents]` block, and what you queued comes back as after an
  interrupt.
  AGENTS.md and CONTEXT.md now say the frontend spawns one child at a time
  and respawns it so.
- **The OMH TUI's composer sits right under the output until the screen
  fills, then stays on the bottom rows.** A fresh session showed the banner,
  then 20 blank rows (110x34) to 36 (200x50), then the composer, and 6 to 12
  blank rows stayed above it after a short turn, during an approval and after
  a resize: the live region was padded to the screen's height at every start
  and redraw and never got shorter. It is now drawn right under the last line
  printed (one blank row under a turn, the spacer every block opens with) and
  follows the content until its last row is the screen's last row; from then
  on it keeps its height, so a list or question closing above the composer
  leaves blank rows above it, filled by the next output, and does not pull it
  up. A resize or a redraw starts again under the output. Short of the bottom
  rows the `/` and `@` menus open under the composer where they fit, as in
  Claude Code, so typing `/` no longer moves the composer down by the menu's
  height and Esc back up; on the bottom rows they open above it, and output
  that brings the composer there while one is open takes it above with that
  output, so closing it moves nothing. The startup query
  that asks for the background colour also asks for the cursor's row (CSI
  6n, inside the same 0.1 s wait), so a start from the last row of a
  terminal already holding output is on the bottom rows from its first frame;
  only a terminal that does not answer that cursor-position query follows the
  content until the TUI's own output has filled the screen once.
  Lines that leave the top of the streaming tail are written over the rows
  they were drawn on, so the rows under them are not painted again, and while
  the screen is not yet full a new tail line is inserted where it goes (IL),
  so the composer and the rows under it move down without being painted again
  (a reply streaming onto an empty 40-row screen writes 232 bytes a frame,
  where following the content had doubled it to 605).
- **Each tool call is its own row, and a cut output names the key that shows
  the rest.** A turn's calls were folded under one `⏺ Tool calls (2)` header;
  each call is now a row of its own (its mark, name and what it ran on) with
  what it printed under it, as in Claude Code, and the `parallel ×K` badge
  that header carried is gone with it. A tool's output, a diff and a
  command's output cut short end `… +N lines · ctrl+o shows all` (rows for a
  command), where they named `/history` or nothing: Ctrl+O opens the details
  view at its end.
- **A finished plan leaves the OMH TUI's panel.** The plan stayed above the
  composer into later, unrelated turns. Once every item is done it now shows
  `✓ 3/3` until the turn ends and then goes, as Claude Code's list does, with
  its final list written to the transcript above the done line under the
  header the panel showed (`[Plan] │ ✓ 3/3`, as `/todos` now heads it too); one already
  finished when the session opens is not drawn, and a new plan is. The
  `[Plan] │ 2/6 .` dot was the header's walking ellipsis, caught at one dot;
  it is gone, and the active item's colour wave still shows work moving.
- **The OMH TUI states the approval mode once.** After Shift+Tab the mode row
  said `⏵⏵ accept all on · approvals off for this session` while the status
  line said `yolo mode: off`: that chip read Hermes' saved state through the
  HUD, which lags behind a switch. The status line no longer carries it; the
  composer's rules and mode row (the status line on a short terminal) say the
  mode, as Hermes confirmed it for the session, in the words the docs use.
  The mode row also says what each mode means and what Shift+Tab turns on
  next, Claude Code style: between turns `? shortcuts · ⇧⇥ accept all/plan ·
  ctrl+t effort (medium)` (it said `⇧⇥ mode · ctrl+t effort` with a separate
  `effort medium` on the right), in accept all `⏵⏵ accept all on · Hermes asks
  no approvals in this session (⇧⇥ plan/normal)`, in plan `⏸ plan mode on ·
  prompts go as /plan (⇧⇥ normal/accept all)`, with shorter forms of the same
  words on a narrow row. The effort is said once, as `ctrl+t effort (medium)`,
  and the keys list uses the same words for Shift+Tab and Ctrl+T. It names the
  level Hermes' config sets from the start of each session, `/new` and
  switches included (read from the settings the TUI already reads), until
  Hermes names the session's own once it has built the session's agent, and
  where none is configured it says `ctrl+t effort (default)` (the
  provider's own default applies) instead of no level at all; Ctrl+T steps
  from the level shown.
- **A first Ctrl+C between turns says `ctrl+c again to exit` on the mode row**
  for the 2 s a second press exits in, as Esc's first press does, instead of
  leaving a `Ctrl+C again to exit` notice in the scrollback every time.
- **The OMH TUI shows three things Hermes sends it and it dropped:** what the
  background review saved to memory or skills (`review.summary`, a transcript
  line), a standing `/goal` (`session.control.update`, one row above the
  composer worded as Hermes' Ink goal bar: `⊙ goal · 3/20 turns · <title>`,
  parked or paused with its reason), and a mixture-of-agents turn (`moa.*`:
  each reference model's answer as a collapsed `◇ Reference 1/3 — <model>`
  row, and `MoA: refs 2/3` then `MoA: aggregating…` on the working row). The
  gateway already wrote these to the TUI; showing them sends nothing.
- **The status line follows a light terminal.** It kept the palette's dark
  bar on a light screen (sky's `#0A2229` under white). On a background the
  terminal reports light (or `COLORFGBG` names, or `/theme light`) the bar is now a light tint of
  the palette's own bar colour, its words still 4.5:1 and its `│` dividers
  3:1 against it; a dark terminal, and one that reports nothing, keep the
  palette's bar.
- **The keys list names the `/model` picker** beside the `/sessions` and
  `/rewind` lists, which take the same keys (`?`, `/keys`, and INSTALLATION's
  table).
- **A team inside the company is internal for data-share-review, in English
  as in Korean, and only when it is proven inside.** Owner decision
  (2026-10-16): sending personal data to a team in the same company is
  internal, so the review does not fire; it fires only when the data leaves
  for an outside party (a vendor, provider, partner, contractor, third party,
  or an external service). English admission read any verb that sends a file
  as the file leaving, wherever it went: "redact pii in the export before we
  send it to the dev team" dispatched the review. The gate fails safe: a place
  is inside only when every word of it is an inside word, in closed tables
  both languages read -- an anchor (a teammate, a colleague or coworker,
  internal, in-house, QA, staging, a test or dev server; 사내, 내부, 동료,
  스테이징), a team or department with an owner (our, my, another, or an
  internal function such as data, dev, marketing, finance, hr; 우리, 다른, 개발,
  재무, 인사), a determiner, or a system beside an anchor (the internal wiki,
  the staging server; 사내 위키). Any other word keeps the review: a company
  ("the Acme team", "Acme's data team"), a client or customer ("the customer
  success team", "고객지원팀"), an organisation ("the Department of Health",
  "은행 담당 부서에", "다른 회사 동료에게"), a relative clause ("a former
  colleague who now works at Acme"), a place after "at", "of" or "for" ("the
  data team at Acme", "the dev team for review"), a team with no owner ("the
  team", "팀 전체에"), and Hangul in an English place. In English, only closed
  words -- where the data is, a determiner, the speaker, data containers and
  personal-data field names -- may stand from the lead verb to the first
  send, its object included ("the export Acme will get", "the CSV the bank
  wants" and "before Acme sees it" keep the review). A word that names whose
  records the data holds (customer, user, patient, client, member, employee,
  staff, student, donor, applicant, subscriber, account) may stand there only
  right before a data container or a field name, not possessive and not
  after "for", "to" or "from": "the customer export", "the patient CSV" and
  "the user logs" describe the data, while "the customer's export" and "the
  export for the customer" keep the review;
  every later send must name such a place after its "to" or "with", and so
  must every place it joins ("the data team and Acme", "cc the auditor");
  "give", "hand" and "pass" without "to" send nothing to the person and
  otherwise take their first object as the place ("give Acme a copy" keeps
  the review). A Korean place is read back, however many words, to a step or
  a joined form of a verb the rule knows, so a noun ending in 서 or 고 is read
  on ("경찰서 보안팀에" keeps the review); every place in the sentence must be
  inside, and an English recipient word ("vendor team에") keeps the review.
  Both surfaces mask quoted, code, link and relayed text before they call the
  rule, and each passes the masker's own report that it removed something, so
  no place is then proven inside ('the "Acme" data team', "the dev team
  https://acme.com"). Measured against main on 160 requests written for this
  change, 140 written blind by a separate agent, and the reviewer's sets
  written before reading the code (`mine2.tsv` and its NFD copy, `adv.tsv`
  to `adv4.tsv`, `r3.tsv`, `r3b.tsv`): on these sets no request to an outside
  party lost the review on admission, the router or the hint, and the two
  surfaces never disagree with every cache cleared. Korean outside requests
  gained it (29 to 40 of 40, 32 to 34 of 35, 34 to 53 of 53, 10 to 31 of 31,
  1 to 18 of 18), and 47 adversarial rows written for the compound-modifier
  rule ("the customer export the regulator wants", "the patient CSV for the
  insurer", "the customer's export") lost nothing. Inside requests that still
  fire, the safe direction: English 2 of 36, 12 of 35 and 14 of the
  reviewer's 31 (each for where the data goes: a manager, HR, the intranet,
  a bare "engineering", "in Seoul"); Korean 2 of 36, 14 of 35 and 5 of 20.
  The three requests the decision named without a file ("redact the pii and send it to the dev
  team") were never admitted, since English admission needs a file-shaped
  carrier; they are pinned as negative controls. Every table is pinned by a
  literal snapshot, and a list of outside words must keep the review. Files
  and folders stay inside only in Korean ("엑셀로 내보내줘").

- **Korean spend and data-share requests reach their gates.** "내 카드로
  결제해줘", "이거 결제해줘" and "송금해줘" fell back with score 0, "고객 정보
  마스킹해서 벤더한테 보내줘" dispatched gateway-intent-card, and "개인정보 지우고
  외부에 공유해줘" asked about automation-blueprint: both gates' admission rules
  read only an English lead. A Korean request puts its verb last, so a new
  bundle reader (`korean_request`) reads the request clause's last predicate,
  and only when a request ending closes it ("-해줘", "-해 주세요", "-해줄래?",
  "부탁해"), the way "please" marks an English one. It skips a greeting or an
  address before the request ("안녕하세요.", "헤르메스,"), removes a label's
  text ("버튼 라벨: ...") and quoted text, and drops what comes before a
  negation it knows (말고, 않고, 마시고, 마세요, 마요, 없이): "카드로 결제하지
  말고 견적만 보내줘" asks for the quote. spend-gate admits it when that
  predicate spends (결제, 송금, 이체, 구매, 주문, 예매, "사줘", ..., but not "결제
  처리해줘"); books, tops up, subscribes, renews or donates something one pays
  for with a price, money, the person's wallet or account, or a card as the
  means in its own clause ("카드로 호텔 예약해줘", not "가격 5000원으로
  갱신해줘" or "제 카드 정보 갱신해 주세요"); or sends money as its object
  ("엄마한테 10만원 보내줘", not "결제 금액 10,000원 영수증 이메일로 보내줘").
  data-share-review admits it when it protects personal data (익명화, 가명 처리,
  비식별화, or masking, deleting or covering personal data) and the data
  leaves: a recipient named as where it goes ("벤더한테", "외부에"; not
  "업체 목록에서" or "업체별로"), or a verb that sends it to no team, file or
  folder of the person's own ("스테이징에", "개발팀에", "엑셀로"). Each gate
  scores only its own phrases, which an admitted request always says, with
  no boost: one phrase scores below the dispatch line, so the router asks, as
  it does for "please send money", and a second one (the person's card, a
  recipient) dispatches the gate unless another skill outscores it. The
  Korean phrases live in the bundle beside the English ones, since the rules
  read them, and "예약" and "보내" are declared as shared with
  automation-blueprint. Measured on seven sets of everyday-sense Korean
  negatives (90, 80 and 42 of my own sets, and a reviewer's 82, 34, 75 and
  27), no sentence names either gate on either surface. Recall is partial: on
  a set written blind by a separate author and first measured at an earlier
  version of the rule, the router offers 23 of 40 spend requests and 19 of 40
  data-share requests (the hint 24 and 21). Every set has since been read
  while the rule was revised, so none is held out for this version.

- **Korean diagram, LLM-wiki and token/cost requests stop going to the wrong
  skill.** codebase-uml's diagram check compared the composed words
  "다이어그램" and "시각화" with the router's NFKD-folded tokens, so no Korean
  diagram request reached it: "코드베이스 다이어그램 그려줘" asked about
  codebase-onboarding while the in-session hint named codebase-uml. Both words
  are folded before they are compared and read as prefixes, because Korean
  attaches the particle ("다이어그램이"). On the router the English boundaries
  hold in Korean too: 클라우드, 인프라, 쿠버네티스 and 서브넷, bare or with a
  particle ("클라우드의"), mark an infrastructure diagram that is the bundled
  `architecture-diagram` skill's job unless a Korean or English code word is
  also there. Because the check now runs, "시각화해줘" joins the skill's
  Korean whole-phrase-only tokens: the trigger "코드베이스 시각화해줘" made it a
  scored token of its own, which would have named the skill for "매출 데이터
  시각화해줘". "LLM 위키" and "LLM위키" now name the pattern Hermes' bundled
  `llm-wiki` skill builds, as "llm wiki" did: the wiki blueprint withdraws,
  and so does the greenfield interview, which Korean, exempt from the
  weak-evidence check, dispatched on that guard alone. English llm-wiki
  requests still clarify; their leading candidate moves from deep-interview
  to the next scored skill. ops-observability-card loses its bare "비용" and
  "토큰" triggers, which dispatched it for "토큰 저장 방식 바꿔줘" and "이 API 호출
  비용 줄이는 코드 짜줘"; its Korean trigger count drops from 9 to 7. The
  card's guard keeps them as telemetry words, as it keeps "token" and "cost",
  but no longer reads "알려줘" as a status request, a word its English list
  never had. Korean token and cost usage is read from "토큰 사용량", "토큰 사용
  추이", "토큰 소모(량)", "토큰 소비(량)" and "비용 모니터링", each as a whole word
  ("토큰 소비" is not "토큰 소비자"), and only when the sentence's final
  predicate asks to see the usage -- show, tell, check, compare, monitor,
  track, how much, how is it, a report, or "is a lot" / "is fast" -- or the
  sentence ends on the phrase itself ("이번 주 토큰 사용량"). The final predicate
  is the last word, or the word before it when the last word is the
  auxiliary written apart ("보여 주세요", "알려 줘", "확인해 주세요") or a spaced
  ending matched whole ("모니터링 해줘", "추적 해 줘", "얼마 나왔어"), so 해제해줘
  and 하지마 are predicates of their own. Every other final predicate leaves
  the phrase uncounted: work (만들어줘, 추가해줘, 고쳐줘, 파싱해줘, 작성해줘, 짜줘,
  줄여줘), so "토큰 사용량 API 만들어줘" and "토큰 사용량 버그 고쳐줘" stay on
  ultrawork, and any other question shape too. A modifier earlier in the
  sentence ("기능별 토큰 사용량 알려줘") does not stop a usage question. The
  guard's English-shaped token arm is unchanged: 토큰 or 비용 beside 보여줘,
  상태 or 요약 still opens the card, as on main ("토큰 사용량 제한 로직 보여줘",
  "토큰 사용량 요약해줘"). So does a how-to or a check under a report predicate
  ("토큰 사용량 파싱하는 방법 알려줘", "토큰 사용량 버그 확인해줘"), as on main,
  where English asks or answers directly. Usage requests whose final
  predicate is outside the report set no longer reach the card; this is a
  class, not a list. Measured examples that dispatched it on main and now
  ask: "토큰 사용량 어떻게 돼?", "토큰 사용량 얼마나 돼?", "토큰 사용량 궁금해", "토큰
  사용량 확인 가능해?", "토큰 소모 심하네", "에이전트 비용 추적해줘", "오늘 LLM 비용
  얼마 나왔어?", "이번 달 API 비용 얼마야", "이번 달 비용 얼마 나왔어" and "토큰
  얼마나 썼어?"; "토큰 사용량 리포트 만들어줘" dispatches the
  greenfield interview. English asks or answers directly on the same shapes
  ("how is my token usage?", "how much did the API cost this month"), and
  questions about what was spent belong to Hermes' /usage and /insights per
  the card's Do-Not-Use. Measured with
  `build_chat_interaction_payload` (`source="discord"`), `awareness_route_hint`
  and the skill candidate line at main and at this head, over both corpora
  (unchanged except three English llm-wiki clarifies whose leading candidate
  moved), the triage probes, 134 Korean probes of our own and the review's
  probe sets: Korean diagram requests that dispatch codebase-uml go from 1
  to 5 of 25, plus 4 that now ask with it leading, and no Korean diagram
  negative moves toward it; of 21 LLM-wiki requests, which went to wiki (18)
  or dispatched the interview (3), 20 now ask and one dispatches
  materials-package on "PDF"; ops-observability-card dispatches none of our
  24 everyday-sense negatives (20 before), 4 of the review's 52 code and
  everyday requests (44 before; the 4 dispatched it on main too), 22 of our
  24 usage requests and 31 of the review's 36 (all before). A held-out set of
  48, written after the first fixes were chosen, moved the same way:
  codebase-uml dispatches 0 -> 4 of 8, wiki reaches 7 -> 0 of 7 LLM-wiki
  requests, and ops-observability-card dispatches 9 -> 0 of 10 negatives and
  7 of 8 usage requests (8 before). Adds 21 negative controls and 29
  interventions.

- **The OMH TUI catches up with Claude Code and oh-my-pi.** It reads on a light
  terminal: it asks the terminal for its background colour before the first
  frame (OSC 11, at most 0.1 s, with `COLORFGBG` as the fallback) and measures
  its theme against it, so prompts and replies are the terminal's own text
  colour, every coloured word reaches 4.5:1 and every rule or mark 3:1 on that
  background (the status line's against its own bar), words that sat on the 3:1 decoration colour moved to colours that
  read, and a light background gets light diff bands (on white the body text
  measured 1.08 to 1.13:1 before); `/theme auto|light|dark` picks the background
  for the open session. A slash command is echoed as `> /name arg` and what it
  prints stays in the transcript under it, a long output as its first 12 rows
  and a count of the rest for `/history`; nothing a command prints opens the
  pager any more, so typed-ahead keys are no longer swallowed and the output is
  still in scrollback afterwards. Hermes' own notices (`notification.show`:
  the agent still starting, credit warnings) show on one row above the
  composer, replaced by the next, withdrawn by key, or gone after their time,
  where they were dropped before; and a refused call reads as words (`/undo` on
  an empty session: `No user messages to undo.` instead of
  `command.dispatch failed (4018): no user messages to undo`). Agents show in
  one place: the HUD panel's `[Agents]` block steps aside while the strip and
  the list hold agents (the panel said "2 running" minutes after both had
  finished), agents whose goals start alike are numbered on the strip, and the
  status line says `idle · 2 agents running` while agents outlive the turn.
  Mouse reports are on only while the agent list is open, so during a turn the
  wheel scrolls and a drag selects; the strip is reached with Down. Up and the
  new Ctrl+R search reach earlier sessions' prompts: the TUI reads Hermes' own
  input history (`$HERMES_HOME/.hermes_history`, the file `hermes --tui`
  keeps) and appends each line you send to it in that file's format, opened
  append-only and without following a symlink, created mode 0600. Esc twice
  clears a draft into the session's history, or, on an empty composer between
  turns (and `/rewind`), lists your prompts: the one you take comes back to
  edit, and sending it truncates the session before it (`prompt.submit` with
  `truncate_before_row_id` and `confirm_truncate`) and redraws from the cut.
  A line that starts with `!` runs in Hermes' shell (`shell.exec`, 30 s at
  most, dangerous commands refused) and shows `> !cmd` with its output and
  exit code; it never reaches the model, and during a turn it waits in the
  queue. A paste of more than 3 lines or 800 characters is one atomic chip,
  `[Pasted text #1 +60 lines]`, sent whole and shown compact in the
  transcript. The working row counts the turn's tokens, each turn ends with
  `✻ 34s · 3 tools · ↓1.2k`, a turn of 10 s or more ends with the terminal's
  notification (OSC 9, OSC 777 or the bell; `OMH_TUI_BELL=0` silences it), and
  the terminal title names the session and its state. A tool row shows the
  first three lines of what the tool printed (a failed one its error's first
  line, or the last three lines when only its exit code says it failed), and Ctrl+O opens the whole transcript with every detail. In the agent
  list, `x` twice interrupts the highlighted agent and `s` steers it with the
  next line you send. The plan panel follows Hermes' `todo.updated` at once
  instead of waiting 2 to 8 s for the HUD's next poll. Every repaint is one
  synchronized update (DECSET 2026). While Hermes asks something, the mode row
  names that question's keys, and neither row offers Esc for an interrupt
  while anything else takes Esc (a question, a picker, the search, the agent
  list, a picked steer or rewind, a draft); the strip ends with `↓ agents`; a narrow approval keeps a key hint
  and a wrapped command its indent; the banner is one row (the model is on the
  status line, the keys on the mode row) and a fresh session names the last one
  with its `/resume` command. Claude Code's names work: `/cost` and
  `/permissions` run Hermes' `/usage` and `/approvals`, `/todos` prints the
  whole plan, bare `/model` opens a picker of the models Hermes offers and
  switches this session to the one picked (it printed the current model
  before), and `/export` first says that Hermes exports a profile archive, not
  the transcript. Alt+Backspace (and Ctrl+Backspace) deletes the word before
  the caret, and Alt+B and Alt+F move by a word under the kitty keyboard
  protocol too, where they did nothing. A start on a terminal of 100 columns
  and 24 rows or more shows the OH-MY-HERMES block logo above the banner, from
  the shipped skin and in its gradient, lifted to read on a light background.
  Motion follows one rule set: a reply opens with `⏺` in the text colour and
  a tool call's name in the tool colour; a running tool's `⏺` pulses (each call on
  its own clock) and settles to `✓` or `✗` before it reaches scrollback; a
  highlight sweeps across the working row's verb; `OMH_TUI_REDUCED_MOTION=1`
  or `NO_COLOR` holds everything still and repaints once a second. Your
  prompt sits on a tinted band to the right edge (an erase in that background,
  so a copy picks up no spaces), a prompt the queue sent says `⧗ from queue`,
  and a steer shows as `↪ steer · <text>` under what is running until Hermes
  answers; its row then lands at the next block boundary. A steer answered
  while a tool ran used to close the tool group and mark the running call
  `▪` cut off, and one answered mid-reply split the reply in two. A command
  typed during a turn (its echo and output) and the agent list's steer and
  interrupt rows wait under what runs the same way, and two commands out at
  once each print under their own echo. Each turn's
  done line sits on a thin rule to the edge, and the answer you gave an
  approval is written above the call it was about, `✓ allowed once ·
  <command>` on a light green band or `✗ denied · <command>` on a light red
  one; failed and denied tool rows with their lines and error notices sit on
  the red band too, a denial shows the one red `✗` (no amber `⊘`), and with
  no background reported nothing is banded. A turn's last lines and its done
  line sit right above the panel on a full screen, where blank rows used to
  stay under them, more the taller the last tool group was (23 for 12 calls
  at 40x100; origin/main had the same gap).
  A call Hermes only drafted (`tool.generating`) and never started, such as a
  streamed attempt it discards and retries, leaves no row and is not counted
  in the done line, where it settled as `▪ tool_call`; a deferred tool's
  `tool_call` draft becomes the call it reached. The plan header's `parallel
  shot ×N` badge, and the desktop pane's chip, show only a count of 2 or
  more, so calls run one after another no longer read `parallel shot ×1`.
  The composer wraps between words instead of splitting a word at the edge,
  as the echo of the sent prompt does, with one difference: a space stays on
  the row it ends, so a word with no room left for the space typed after it
  moves to the next row (the echo keeps the word there and drops the space),
  and a tab with no room takes a row of its own.
  While you pick from a list, the composer is hidden, as in Claude Code: an
  approval, a clarify question with choices, and the `/sessions`, `/rewind`
  and bare `/model` pickers stand where the composer was, with no rules (a
  picker keeps the caret at the end of its filter row, where its typing
  goes), and the draft comes back as you left it when the list closes (a
  question waiting behind the first opens before the composer is drawn
  again). An approval lists deny, allow once and allow this session one per
  row, deny highlighted (`❯`); Up and Down move as Left and Right do, stop at
  either end so Up then Enter still denies, and no number picks one. A
  clarify question numbers its choices and ends with `Other (type your
  answer)`, Hermes' wording; that row, or any character that picks nothing,
  opens the composer as the answer field, and Up or Down goes back to the
  list. A picker's filter is its last row. A clarify or sudo answer used to be
  typed into the composer in place of the draft, which came back as plain
  text with its caret at the end: a paste chip in it no longer expanded, so
  sending it sent the chip's label instead of the pasted text.

- **A portable host is no longer told to load a skill only Hermes ships.** On
  main the Agent Skills bodies and references named 17 such skills 63 times:
  by label (`omh-research-department`), by backticked or hyphenated canonical
  name, or by a one-word name right after "route to" or "routed to". None of
  these remain. A Do Not Use When line that hands its request only to such
  skills now keeps the request and loses the pointer, so the skill still says
  what it is not for. The rule reads the shipping set, so the pointer comes
  back once one of its siblings ships portably. Every other sentence is
  rewritten for that projection only: a list line through the new
  `PortableLine`, which keeps its portable wording beside the Hermes text; a
  description or other single-text field through `portable_overrides` (the
  portable frontmatter now reads a description override); and the wiki
  blueprint reference through `PORTABLE_REFERENCE_REWRITES`. A gate reads
  which skills each projection ships and fails, by path and line, when a
  portable body or reference names one the portable projection does not ship.
  A second test fails when a skill that a rewrite leaves out starts shipping
  portably, so the rewrite is re-read. Hermes bodies, references and their
  digests do not change.

- **A host turn or a thank-you gets a direct-answer card.** `omh chat
  route-hint` and the example shims showed the generic no-hint card, with "Open
  omh" and "Clarify" buttons, beside a route decision that said to answer
  directly: on a turn Hermes wrote from one of its session-command templates, on
  "thanks!", and on every other route the router answers in chat. Where the hint
  rail had named a workflow beside such a decision, the card offered to open it
  ("how long does it take to become a doctor" offered `omh-doctor`). The card
  could not tell these routes apart: the compact `route_decision` it reads cuts
  the reason to thirteen characters. The router now names each answer-in-chat
  fallback with a stable `reason_code` (`direct_answer`, `host_command_turn`,
  `native_loop_cadence`, `typed_loop_goal`, `loop_construct`, and `file_lookup`)
  on the route and on `route_decision`. The key is additive and absent on every
  other route, and `reason` keeps its prose. A direct-answer code gives a new
  `direct_answer_route_hint` card with no actions and no tool checkpoint, which
  says no OMH workflow is needed; its `next_backend_commands` no longer lead
  with a hinted workflow, and the human `omh chat route-hint` summary reads the
  card instead of the hint beside it. The router's next action, claim boundary,
  clarification and routing instruction, and the wrapper's file-lookup and
  direct-answer cards and its loop-timer check, read the code instead of
  matching the reason's wording. A turn Hermes wrote around an OMH status,
  quickstart or intro question ("omh status" under a `/plan` or heartbeat frame)
  became that OMH card in `omh chat interact`, beside the router's decision to
  answer it directly; it now gets the direct-answer card the router decided, as
  it already did for a catalog question. Where the wrapper does turn a route
  into an OMH card, it drops the replaced reason's code from the route and from
  `route_decision`. Measured over both corpora on Discord, plus 18 messages on
  four sources, at `origin/main` dc6933c3a and at the head: no route,
  interaction card or next action moved. The route-hint card moved on exactly
  the 271 direct-answer routes and nowhere else, and its backend commands on the
  58 of them where the hint had named a workflow. Of the 271, the 211 corpus
  rows are all negative controls, 165 from the no-hint card and 46 from a
  workflow card. Over four Hermes frames around six OMH questions on four
  sources, the interaction card moved on the 72 host turns that had become OMH
  cards, and on none of the same questions typed by a person.
  `host_owned_command_turn`, a pass-through over the bundle's
  `host_command_turn`, is gone; the router and both wrapper payloads call the
  bundle's predicate.

- **spend-gate and data-share-review admit the same requests on the router
  and the in-session hint, whatever courtesy opener is used.** Four readers
  of a request's opening -- spend-gate's clause rule, data-share-review's
  lead, the loop-on-a-timer verdict and the router's command word -- each
  kept their own list of openers, and the lists had drifted: "hey, redact pii
  in the export before we send it to the vendor" reached data-share-review
  and the same sentence opened with "hi,", "pls" or "would you" did not. One
  bundle list, `request_lead.COURTESY_OPENERS`, now serves all four; a "."
  right before a "/" stays with what follows, so `ok./loop` keeps OMH's
  sigil. "pls", "plz" and "kindly" mark a spend as "please" does, and so
  carry its known residual: "pls pay with my card in safari is broken"
  reaches the gate as "please pay with my card in safari is broken" already
  did. "hermes," before a data-share request is the address it is for
  spend-gate; Hermes named after it still withdraws the review ("before
  hermes uploads it"), a trailing ", hermes" included, and the docstring now
  says so instead of claiming only a Hermes setting does. The hint also
  stops naming spend-gate where the router withdraws it: the everyday-sense
  pair for its cap and wallet phrases moved from the router into
  `spend_signals`, whose clause rule applies it, so "can you check out the
  spending cap for the city council budget" gets no gate on either surface.
  A loop's prompt and the gate named as a command are exempt on both
  surfaces, as they are from the request marker, so "run spend gate on my
  spending limit" dispatches the gate instead of a clarify without it. The
  gates' spaced names ("spend gate", "data share review") are no longer
  direct invocations for the hint, which follows the router's verbs ("use
  spend gate") and the hyphenated names. data-share-review's hint reads the
  router's own trigger table as whole words, so "anonymize the dataset
  before we upload it to the provider", which the router dispatches, gets
  its hint and arms awareness on a later turn. Measured with
  `build_chat_interaction_payload(source="discord")` and
  `awareness_route_hint` at `dc6933c3a` (identical on every row to the
  branch's first base, `cd8a879db`) and at this head over both corpora, the
  follow-up probe sets, every string in the two skills' test files and a
  matrix of 33 openers over 17 requests (2,632 sentences): neither corpus
  moved on the router or the hint; router/hint agreement on whether the gate
  is offered went from 260/281 to 297/297 for spend-gate and from 61/78 to
  152/154 for data-share-review (the two left are one transcript-excerpt
  sentence, in two of the sets, that the router dispatches to its owner,
  media-input-operator). Outside the two gates, an opener new to a reader
  now reads as the bare request does, or as the request after "please" for
  an opener that marks one. Behind 11 openers over every corpus case that
  opens with a Latin word (12,740 routes), 166 routes outside the gates
  moved and 161 now match that reference: 76 requests that open on a fix,
  build or change verb, behind "hey,", "hi,", "so", "just", "let's" or "i
  need you to", dispatch (46) or ask (30) with ultrawork leading, where they
  went to feedback-triage (30, among them three negative controls such as
  "fix the broken wheel on my shopping cart") or a clarify led by another
  skill; 12 cadence reports behind four openers each
  (48) clarify instead of dispatching automation-blueprint; loops on a timer
  get Hermes' `/loop` (20) or, after a cadence naming ulw-loop, OMH's loop
  (8); and two pay-on-my-behalf feature requests after "pls" and "kindly"
  clarify as after "please" (2). The other 5 are "configure web search"
  after "hey,", "hi,", "so", "just" or "let's", which now asks with
  websearch-setup leading, as "please configure web search" does, where the
  bare request dispatches websearch-setup (before: dispatched web-research).
  The money cues of a send or transfer are read as words, so "please
  transfer the balance with my card-on-file" stays admitted. Internal: one
  offers-itself table row per gate, spend-gate's clause tokenized like every
  other skill's message, and the misleading `_WHOLE_WORD_ROUTE_HINT_RULES`
  replaced by the hint's phrase readers.

- **Every skill says one thing about spends, retired siblings, review
  retries and the one plan checklist.** A `loop` step that would move money
  goes through `spend-gate` first while the loop carries on, in that skill's
  own terms: an agent run on a schedule never spends, and a no-agent script
  that pays is a spend set up now. `ultraperf` stops sending a declared metric, baseline
  and benchmark to `performance-goal`, a skill #1691 folded into `ultraperf`
  itself; a declared goal starts from its baseline there, as its recovery note
  already said. `decision-prototype`'s compact body now carries the line that
  hands a multi-question feasibility probe to Hermes' bundled `spike`, which
  only its on-demand full contract held. `code-review`'s two references agree
  on a failed review return: when the host checked the return against the
  schema, the same reviewer is not asked again, because Hermes' completion
  message carries no retry count to wait for. The route hint's `plan_todo`
  line and the context tool hint name all three plans only `omh_todo` holds (a
  planning run, an accepted plan or a code-story template), so a code-story
  run is no longer pointed at `todo_list`, whose write would be held. The
  grounded-citations ledger and verify rule, the blocked-page recovery note,
  the curator-ledger reading rules, `report-package`'s `powerpoint` rungs, the
  native-tool presence clause and the shared-rail pointer are each one string
  their skills compose, where they had been retyped.

- **Memory recall no longer fills a pack with records that share only the
  project's name.** A query term that more than half of the records the pack
  could serve hold, when there are at least five of them, never makes a record
  match on its own. A subject's replaced values, stale records shown only for
  inspection, and extra copies of one summary are not counted. The term still
  orders records of equal coverage, a record that carries it as a tag still
  matches on it, a subject's current value that shares it still takes an older
  value's match on another word, and a query whose every term is common keeps
  them all. A record that met the query only on such a term is excluded as
  `common_terms_only`, and that overlap no longer triggers the active-tier
  fallback; a query that overlaps nothing, or overlaps only through stemming,
  still falls back. It is not idf, and a rare term gains nothing. Measured
  against `origin/main` at 03741a6a8 by replaying the 2026-10-14 memory A/B
  store (21 records, 11 tasks) through the prefetch selector: the two control
  tasks, which no record answers, served 12 records before and 4 after; each
  of the nine memory tasks kept its record in the pack, and one more of them
  now leads with it. On blind rounds 3 to 6 and their tie-flip twins (176
  cases, the lead-record rule), 0 wins, 176 ties, 0 losses; one round-5 case
  and its twin now hold back a second topic record that shared only the common
  word. Those rounds were seen while choosing the rule.

- **What a Hermes background-review or `/btw` fork still does to OMH on the
  0.21.1 plugin floor is written down, and the floor stays at 0.21.1 (a #2112
  follow-up).** On Hermes 0.21.1 such a fork's turn end still calls OMH's
  `on_session_end` under the person's session id, and that call carries no
  `parent_session_id`; Hermes 0.21.2 stops calling it for a fork. `CONTEXT.md`
  now defines the **Detached fork** and records what that turn end does,
  measured by calling OMH's hooks with the arguments the fork sends as read
  from Hermes source. A route written during a Hermes turn stays in place,
  because the restore is scoped to the task that wrote it and the fork's task
  id is its own. A route recorded without a task id but under the person's
  session id is put back at the fork's turn end. The metadata-only
  `plugin_session_end` checkpoint can carry the fork's time. None of it was
  observed on a live 0.21.1 host. The entry also names the tool hooks a fork
  reaches on every release, `transform_tool_result` included, and the
  unbuilt OMH-side fix (correlating the turn id `pre_llm_call` saw). Raising
  `requires_hermes` to `>=0.21.2` was rejected because it would drop every
  0.21.1 install. Docs only; no code changes.

- **On a gateway turn OMH routes on the person's own words.** With Hermes'
  Discord tools loaded, every Discord message reaches OMH behind
  ``[Triggering message id: `…` — use as `message_id` for reply/react/pin via
  the discord tools.]``; a reply adds a pointer that quotes the message replied
  to, a channel can add backfilled history before `[New message]`, and a shared
  session puts `[<name>] ` before the text. The in-session route hint, the
  candidate line, the chat router and the wrapper read all of it as the
  request. On `origin/main` 42ad99ec7 the trigger note alone changed the hint on
  102 of 787 intervention cases and 41 of 748 negative controls, and the route
  on 159 and 404 of them: "please pay with my card for the summary report" went
  to `gateway-intent-card` instead of the pre-spend card, and "what is a web
  crawler" dispatched `web-research`. One helper, `person_request_text`, now
  removes that material before any route is decided; a reply's quoted text is
  context, not the request. What OMH hands on still carries the whole turn: the
  routing prompt a bridge forwards to Hermes, the coding handoff and the plan
  keep the quote, an attachment's path and the backfill. The sender prefix is
  removed only on a turn from a messaging gateway (the platform in the hook,
  the `discord`, `slack` or `telegram` source in the router and the wrapper),
  since Hermes writes it nowhere else, and even there a bracket that names a
  skill, `omh` or `ulw`, an invocation, a relay header, or a second bracket
  stays: `[omh] status`, `[deep-interview] …` and `[ulw] fix the flaky tests`
  route as before on every surface. A role marker is read from the person's own
  text. A reply pointer ends at the `"]` after its quote and an image
  description at the `~]` after its closer-look note, so a `]` and a blank line
  inside either no longer cut them; QQ's `[Quoted message]:` block, which has
  no close, leaves the turn whole. The context brief and the plugin tools'
  standalone fallbacks now skip a turn Hermes wrote from a session-command
  template, as the hook and the wrapper already did. Measured over both corpora:
  behind a trigger note, a reply pointer in either Hermes order, or a reply
  quoting a skill request, nothing differs from the bare request on the hint,
  the route or the wrapper's next action; behind a sender prefix on a
  messaging turn, only a request that itself opens with a bracket differs, and
  it reads as it did before. Routed bare, no route moved; the hint moved to
  none on the 8 Hermes host frames in the corpora, and two loop requests behind
  a sender prefix now start the cycle, as the same request without the prefix
  does.

- **A refused or Hermes-recovered fanout unit ends in a true state.** A unit
  refused after a capacity-reuse reservation (no provable write fence, or the
  reused worktree's preflight), or one whose dispatch raised before its spawn,
  left its in-flight marker behind, so `fanout status` had to compare write
  times to avoid reading it as in flight; every path out of a unit dispatch
  that got its worktree now clears the marker, and a refusal for a worktree it
  did not get still leaves another dispatch's marker alone. The opt-in Hermes recovery lane
  (`--on-failure=hermes`) sent its file-tools-only child a prompt asking it to
  run a verification pass and commit, which it cannot do, and nothing did
  either afterwards, so a `completed` recovery left edits unchecked and
  uncommitted. The child now gets an edit-only prompt. What the failed attempt
  left in the worktree is committed on its own before the child starts; when
  the child completes, the dispatcher commits its edits on the unit branch and,
  under `--run-verification`, runs the unit's declared checks on that commit.
  The dispatcher's commits and checks run inside the unit's write fence (the
  child does not), and the lane refuses before the child starts when no fence
  can be proven or the unit's branch is not checked out. A new file -- a
  tracked file moved to a new path included -- is committed only inside the
  unit's `file_scope`; one outside it (a `.env`, a build artifact) is never
  committed and is named in the record, and the lane refuses before the child
  when the failed attempt left one. The attempt's
  `unit_state` is `verified` only when the child changed something, all of it
  was committed, and those checks ran on it and passed. `fanout status
  --wait`'s documented codes and bounds, and the deadline `ulw-maestro` names,
  are now pinned by parity tests against the command's constants.

- **A profile is served only its own consolidation brief, and
  `plugins.entries.omh.settings.dreaming_mode` turns the brief off for that
  profile (#2087).** Profiles that bind one OMH store, such as every profile of
  a gateway running `gateway.multiplex_profiles: true` against `~/.omh`, shared
  one `memory/dreaming.json` and one `memory/consolidation.json`. A nearly full
  `MEMORY.md` in one profile raised a brief that every other profile was then
  served on every turn, and all profiles' turns moved one interval counter. The
  counters and the brief now live under
  `memory/profiles/<sha256 of the Hermes home>/` (the slot the group-activity
  status already keys by). The pack, the chat notice, `omh_memory`, `omh memory
  dream` and `omh doctor` read the brief of the Hermes home they are bound to.
  Measured with two profiles on one store, profile A over its headroom floor,
  20 interleaved turns each. Before, B's pack carried a brief on 20 of 20
  turns, 14 of them with A's `headroom_below_floor` reason. The shared interval
  fired 6 times for B and once for A, and A raised a brief led by its headroom
  reason 6 times, because each brief B raised replaced the `last_reasons` that
  suppression compares against. After, B's pack carries A's reason on 0 turns,
  each profile's interval fires 4 times in its own 20 turns, and A's
  headroom-led brief is raised once. `dreaming_mode: off` in
  a profile's own `config.yaml` stops that profile's brief from being raised,
  served or reported, including one written before; bare `off` and `false`
  both mean `off`. Unset keeps `reminder`, the default. Any other value, or a
  config OMH cannot read, also keeps `reminder` but is reported as
  `mode_setting_unrecognized`, in `omh memory dream`'s `mode_setting` and as
  `omh doctor` advice. On the first attended session start after the upgrade, a
  single-profile host moves its old home-wide files into its profile directory
  and keeps a pending brief. Two cases leave them unread: the profile already
  has its own files (`omh memory dream --evaluate` raised a brief first), or
  the profile is routed, which every profile of a multiplexed process is, even
  a single profile under `gateway.multiplex_profiles: true`. `omh memory
  retire --apply` retires an expiring-only brief in every profile's directory. Thanks
  to @kanzaka110 for the report and @sanjkrsna for pointing at the
  per-profile key.

- **`omh install --force` reads Hermes' curator ledger once, and names the
  ledger it could not read when it reports what a removal lost.** Under
  `--force` the install read and parsed the whole ledger again for a replaced
  Hermes edit, again for a skill it cleared, and again for every retired
  directory it removed, beside a comment saying it read the ledger once. The
  read it already made now also keeps every write the ledger records when a
  local change may be overwritten, and each of those reports takes that list.
  On a synthetic 190.8 MB ledger (16,000 rows in the shape Hermes wrote before
  0.21.4, 20 files each, 30% of them under the OMH pack), a `--force` install
  that replaced two skills and removed three retired directories went from 6
  ledger reads in 8.1 s to 1 read in 2.9 s with the same result; a `--force`
  with nothing to lose went from 2.9 s to 2.7 s, and a plain install from
  2.3 s to 2.0 s. With no row under the pack, that `--force` with nothing to
  lose is slower, 0.19 s to 0.54 s, because it now parses every row where it
  used to skip them all, while the one that replaced and removed went from
  5.4 s to 0.54 s. When a ledger could not be read, each replaced edit or
  `--force` removal that lists what Hermes still holds a copy of carries
  `ledger_copy_partial: true`, and one summary line after those lists names
  what could not be read and says they count only what could be; a `--force`
  removal OMH could not judge for that reason now names it too, and a
  `--dry-run` result carries `unreadable_ledgers`. A ledger with more than one
  torn line is named once, with a count, instead of once per line. The ledger
  reader no longer drops every write when given a generator of directories,
  resolves those directories once per read instead of once per write, and
  builds a row's `after` list once instead of once per file the row listed
  before; `omh doctor` judges Hermes edits once instead of twice.

- **A checked team no longer checks a part while its helper's work sits
  unmerged in the worktree Hermes gave it, and the board fan-in asks Hermes
  only for transitions it lands.** With Hermes' `delegation.worktree_isolation`
  on, an `omh_team` helper edits a worktree of its own, and its work reaches
  the session's workspace only when the session merges it. `team_reconcile`
  still ran each part's check in that workspace, so a check could pass on a
  tree without the part's work and accept it. It now reads each returned
  helper's branch (`hermes-subagent/subagent-<id>`, from the subagent id
  Hermes' `subagent_start` carries) and its worktree (`.worktrees/subagent-<id>`,
  found by path even when the helper left the branch for a detached HEAD or a
  branch of its own) with read-only git. While the branch's last commit or the
  worktree's HEAD is missing from the workspace's history, or the worktree
  holds uncommitted changes or untracked files, it checks nothing and is
  refused as `helper_branch_unmerged`, naming each branch in `unmerged`. OMH
  never merges. A branch git cannot read makes that part's check
  inconclusive, so the team still reaches a stop. Work held by neither the
  branch nor the worktree (a branch renamed or deleted after its worktree was
  removed) is not looked for, and a host that names them differently leaves
  the guard off.
  The helper's own instructions no longer say the workspace is shared: they
  say the check runs in the parent session's workspace, and that a helper in a
  worktree of its own commits on its branch. In `ultraqa`'s board fan-in
  reference the main session no longer prepares `request_review` on a `done`
  fixer row or `request_changes` on a row no review run holds, both of which
  Hermes refuses: the fixer's own run ends with `kanban_request_review`, and a
  failed re-check this session ran is a `comment` on the row, with sending it
  back left to the operator's `hermes kanban reopen-review`.

- **`omh_gather_evidence` bounds the paths a probe's arguments name.** The
  allowlist matched a command prefix and left the rest free, so
  `python3 -m compileall /any/path` compiled files anywhere and printed their
  paths and the source line of any syntax error (#2137, reported by
  @simongonzalezdc). A compileall argument, the value of an omh option that
  opens a path, and a `git diff` path argument must now be relative, free of
  `..`, and resolve inside `workdir` after symlinks; a path refusal names the
  rule, never the path or where a symlink leads. compileall also needs at
  least one such path, because with none it compiles every directory on
  `sys.path`; it refuses `-i` (paths read from a file or stdin), `-b`
  (bytecode written beside the sources, past the private pycache) and
  `-d`/`-s`/`-p`; and it runs with `-e .`, so a symlink below a compiled
  directory that leads out is skipped, and with `PYTHONSAFEPATH`, so a
  `compileall.py` in `workdir` no longer runs in place of the stdlib module
  (Python 3.11 and later; an older `python3` ignores it).
  `git diff` refuses `-O` (an order file read from anywhere), and its path
  bound stops the switch to `--no-index` that two paths with one outside the
  repository caused, which printed both files; a `:/` pathspec or
  `<rev>:<path>` still reaches the whole repository, as a bare `git diff`
  already does. `omh doctor` refuses `--profile-isolation`, and
  `omh release evidence-bundle` refuses `--write` and a `--verify` PATH.
  Evidence probes and `omh_team` checks now run with no stdin.

- **The plugin's route hint reaches the router in Hermes chat, so your own
  trigger packs hint there too.** Hermes imports the plugin bundle as
  `hermes_plugins.omh`, one package deep, and there the bundle's
  `from ...routing` imports climb past the top-level package and raise
  ImportError even when Hermes can import `omh`. Four of them had no absolute
  fallback, so in every Hermes chat the bridge to the router for user trigger
  packs (#1539) returned nothing: a phrase from
  `<omh-home>/routing/trigger-packs/` got `no_hint` from the plugin while
  `omh chat route-hint` hinted it. Coding-delivery hints also asked the user to
  choose the executor instead of carrying the router's owner decision, and the
  visual-QA and office-material cue tables were the bundle's copies. Each import
  now falls back to its absolute `omh.` form, and the bridge still resolves on
  each call. Over both routing corpora (1,535 messages, measured against
  42ad99ec7), the plugin's hint with `omh` importable differed from the package
  layout's on 118 messages before, each in the coding-owner decision, and on
  none after. Where Hermes cannot import `omh`, the usual install, nothing
  changes; `docs/INSTALLATION.md` now lists the trigger-pack hint and the coding
  owner among what that turns off. A test loads the bundle under Hermes' own
  package name, and a gate requires every bundle import that climbs above the
  bundle root to be paired with its absolute form and, at module scope, to bind
  the router's object there. Reported with a reproduction by @fauzibrevy-hub
  (#2129).

- **`omh coding status-board` shows Hermes' delegate children and kanban
  workers beside the fanout units.** The board listed only fanout units, so the
  command could not show the work `omh_hud` already showed. It now reads the
  same two readers the HUD uses (`hermes_delegation` over `state.db`,
  `kanban_board_reader` over `kanban.db`), opening both read-only, and lists
  each worker with its source and state in a second table under one headline.
  The rows keep the board's running-first order, and a kanban lane whose
  heartbeat stopped is counted with the stuck units. A Hermes database that is
  missing, unreadable, refused or read only in part prints a line saying so
  instead of an empty list. To tell those cases apart, both readers now report
  a `read_status`, which the HUD payload does not carry. A reader that reaches
  its selection bound now says so (`selection_capped`), and the board then
  shows its counts as lower bounds ("at least 96 running") instead of as
  totals. A kanban lane that never started reports no elapsed time instead
  of 0; the HUD still draws it as before. The fanout rows render as before.
  The run-efficiency route reason now says the report reads the supplied
  timings and context budget plus Hermes' recorded usage for a named session,
  with provider, billing and cron not observed; it still described the
  supplied-metadata report from before #2114.

- **`omh chat route-hint` names no workflow on a turn Hermes wrote for its own
  session command.** On such a turn (a `/plan` frame, a `/loop` wakeup, a
  `/goal` continuation, a heartbeat, a goal-mode kanban nudge, a `/blueprint`
  seed) the route decision already said `fallback`, but the hint beside it was
  read from the frame's text and named a workflow: the `/plan` frame came back
  hinted `command-operator`, and each of the 16 seeds Hermes' own
  `build_blueprint_seed` writes for its built-in blueprints `automation-blueprint`.
  The hint now reads no request on such a turn, as the plugin's `pre_llm_call`
  hook already did. Measured against `origin/main` at 03741a6a8 over both
  routing corpora, every host frame behind each gateway prefix, and the
  frames' bodies without them (1,678 messages): 101 hints moved to none, every one on a host turn, and no route
  decision moved on either payload. The router's reason for these turns no
  longer lists commands, so it cannot fall behind the frames OMH recognizes (it
  had left out `/blueprint` and `/initiate-setup`). The `spend-rails.md`
  reference both targets ship no longer names OMH's browser adapter, which
  another host does not have; the Hermes body still does.

- **The OMH TUI keeps the keys typed right after Esc, and stays fast in long
  sessions.** Esc followed by a key within about 50 ms lost both keys (Esc then
  `/quit` left `quit` in the composer, for Enter to send as a prompt); a
  character sent in the same burst as an Esc now types (tmux before 3.5 sends
  them that way), and Esc then a key in separate reads acts as both. Option+←
  and Option+→ in macOS Terminal.app move by a word. A bracketed paste whose end
  marker never comes ends after 0.5 s of silence instead of swallowing every
  later key, Ctrl+C included; for the second after, or while the rest of it
  keeps arriving, a line break adds a line instead of sending the prompt. `/new`
  no longer keeps a resumed session's banner for the next redraw, and an image
  Hermes attached (`/image`, `/paste`, a drop) after you left the session it was
  sent for is a notice instead of a chip in the new one. A call the gateway
  leaves unanswered for 120 s (Hermes' own TUI's limit) is dropped, with a
  notice for one a person waits on. A full redraw (a resize, Ctrl+L, `/redraw`,
  a switch or a resume) prints the last 3,000 rows under `⋯ N earlier messages ·
  /history shows all`, and `/history` renders a page at a time. The TUI holds a
  session's last 2,000 messages and the composer its last 1,000 prompts, and an
  edit's diff is held as its UTF-8 bytes (one 200-line truecolor edit: 16,508
  bytes, 28,558 as parsed lines). Measured against `origin/main` at 14cc8731a
  with the review lanes' in-process harnesses (load average 10 to 30): at 1,000
  turns a redraw took 14.8 s and 118 MB at its peak and now takes 0.27 s and 4.5
  MB, and `/history` opened in 5.7 s holding 65 MB and now in 6 ms; a key in a
  500-turn session takes 0.19 ms (was 1.35), a key in a 2,000-line paste 13 ms
  (169), Up there 0.35 ms (254), a spinner tick over a streaming
  20,000-character paragraph 0.26 ms (40), and a tick with an agent's 400-row
  log open 0.06 ms (95). The loop wakes for gateway events and HUD changes
  instead of reading every 50 ms: event to frame 0.1 ms median (30), and an idle
  TUI wakes about once a second (19). Bare `omh` reaches `hermes` in 46 ms (445)
  without importing its command tree, and the first frame no longer waits for
  the busy-mode read. A HUD read over 5,000 run directories checks only the runs
  it shows and reopens only binding files that changed: 190 ms (708).

- **Skill text decides which skills are OMH's by the installed label, and the
  spend, browser, schedule, and parallel-tool skills say what Hermes does.**
  `skill`, `rules-distill`, and `skill-health` no longer treat any `omh-*` or
  `ulw-*` name as OMH's: one shared sentence says an OMH-managed skill is one
  OMH installed under a label its catalog renders, and a companion the person
  or an agent created is theirs whatever its name. The `skill_manage` refusal
  suggests a companion name without OMH's prefix (`plan-notes` for
  `omh-plan`). `parallel-tools` reads each MCP server's
  `supports_parallel_tool_calls` and offers that flag, with an update only on
  request, instead of describing a version-currency check. A recurring job or
  a page step that would move money goes from `automation-blueprint` or
  `browser-operator` to `spend-gate`; `loop` sends an unattended schedule
  through `automation-blueprint` instead of straight to Hermes' cron tool; and
  `browser-operator` carries the unattended-run rule the other operator skills
  state, with Hermes' card prompt recorded beside the spend gate's typed yes.
  `command-operator` and `spend-gate` say what Hermes does with a
  `pending_approval` command at v2026.9.7 and on upstream main: it is stored
  and never run, and `/approve` resumes only a run still waiting on an
  approval. `spend-gate`'s portable body drops the `hermes chat -q`
  parenthetical, the OMH browser adapter line, and the `pending_approval` rule,
  which a host-neutral held-command rule replaces; prose that named a sibling
  by its catalog name now writes the label `skill_view` loads, and the spend
  and data-share references name only states their skills keep.

- **A `/blueprint` seed is Hermes' turn, and a spend is spend-gate's wherever
  it is asked.** When `/blueprint` matches, Hermes rewrites the turn to a seed
  that asks for the blueprint's settings and then creates the cron job
  itself; OMH now reads that seed's frame as a host turn, so it gets no route,
  no route hint and no candidate line, where before it dispatched a file,
  toolbelt or observability skill. A person typing the seed's first line alone
  still routes to automation-blueprint. A loop on a timer whose prompt spends
  the person's money ("loop every hour and buy the tickets for me with my card
  if they drop under $50", or the same as a typed `/loop 1h ...`) opens
  spend-gate instead of being answered with Hermes' `/loop`, since a scheduled
  run never spends; Hermes' own `/loop` wakeup turn is unchanged. Naming the
  gate as a command ("use spend gate") now asks for it. The router, the route
  hint and the awareness markers read one phrase table for the gate, so "go
  ahead and pay the 402 challenge for the dataset" no longer hints a research
  skill while the router opens the gate. A renewal, tip, booking,
  subscription, donation or top-up paid "from my wallet" is no longer dropped
  as everyday wording, and paying with the person's card, or reviewing the
  pre-spend card, no longer opens the image-card skill, while an image card of
  "my card game stats" or "my card collection" still does.
- **Memory recall no longer lets a colloquial query's particles, endings and
  fillers decide which record leads.** A Korean query run loses the particles
  and request or verb endings it ends in while two syllables stay (자동으로 is
  scored as 자동, 확인해주세요 as 확인, 경로 stays whole), and a run that is
  one of them whole (해주세요, 에서 after a Latin word) adds nothing. Korean
  discourse fillers, intensifiers and demonstratives (그냥, 진짜, 그거 ...),
  English hedges (honestly, literally, kinda, really ...) and the Japanese and
  Chinese wrappers って, なってる, 什么时候 and 一般 join the closed query-side
  lists. All of them still order records of equal coverage; records are
  tokenized in full. The strip never makes a query fall back to every word
  (which would promote 어떻게 or "what" to content): the unstripped content
  is tried first, and a two-letter word written in capitals (PR, CI, DB) is
  scored as a name, so "what about CI" no longer falls back either.
  Measured against `origin/main` at 4d3c10141 with the
  blind-round harness and its lead-record rule (distractor ids sort first, so
  a tie goes against this change): round 4, 20 cases, 5 wins, 15 ties, 0
  losses; its tie-flip twin 4 wins, 16 ties, 0 losses; round 3 and its twin
  0 wins, 20 ties, 0 losses each; the 40-case pre-registered corpus served
  identical packs. Those rounds were seen while writing the change. On two
  rounds frozen by a writer who never saw the code (24 owner-style cases
  each), it scored 2 wins, 21 ties, 1 loss and 2 wins, 22 ties, 0 losses. The
  loss is a query whose topic record shared the particle form (모델로) that
  now only orders records.
- **Bare `hermes` is stock Hermes again.** With bare `omh` opening the OMH
  TUI, OMH stops styling Hermes' own terminal: setup and update write no
  `display.interface`, `display.skin` or `display.sections`, install no
  status widget and no skin files, and ask no display question
  (`--no-omh-tui` is accepted and does nothing). The OMH plugin stays loaded
  in `hermes`, so its tools, hooks, memory and skills still work there; the
  HUD and `/omh-model` are the OMH TUI's. An install an earlier version
  styled is migrated by the next `omh setup`, `omh update` or `omh apply`,
  primary home and every bot profile: a display key OMH's record says it
  wrote goes (or goes back to the value consent replaced), an `omh*` skin
  goes with or without a record after a theme the person picked is saved
  under the OMH home, and a value the person changed or OMH cannot
  attribute stays. The widget and skin files go where a manifest (or, before
  the release, the shipped bytes) proves OMH wrote them; an edited one, and
  the skin the config still names, stay. A key in a YAML shape the editor
  refuses holds the release, and is named, until a later pass can take it;
  once a pass leaves none, `display_released_at` in the write record keeps
  later updates from taking back a skin, or a skin file, the person picks
  afterwards. `plugins.enabled`, `memory.provider` and the registration are
  never touched by it. A home left unregistered keeps its config and loses
  only the old files. `omh theme use` now saves to
  `<omh_home>/tui/theme.json` (a profile's own store when it names one) and
  the OMH TUI opens with it, `omh --profile <name>` included; `omh theme
  repair` is retired (it says so and exits 0). Where the OMH TUI cannot
  start, `omh` says why in one line and opens `hermes --tui` for a reason of
  the OMH TUI's own, or plain `hermes` under `TERM=dumb`, `OMH_NO_TUI=1` or
  without Node. The `hermes_tui_*` doctor checks and the post-update
  `OMH TUI:` verdict are retired with the surface they judged, and
  `omh setup --json` moves to `hermes_native_setup/v2`. See "Returning
  hermes to stock Hermes" in docs/INSTALLATION.md.

- **`omh quality-evidence agent-skills` reports Agent Skills host evidence
  per host and scope.** For every Agent Skills host adapter, in repo and user
  scope, it records five stages (installed, discovered, nominated, loaded,
  executed) and never infers one from another. `installed` is observed by
  OMH: it reads the host's scan path under `--project-root` or `--user-home`
  and compares every file with the `omh_host_adapter/v1` manifest; the read
  writes nothing. The later four stages stay `not_observed` with each host's
  `probe_unsupported` reason, since OMH has verified no credential-free,
  non-interactive listing command, makes no model call, and starts no host
  session. The only host process it runs is the readiness module's approved
  `--version` probe, for a CLI in that probe's set; it runs whenever such a
  CLI is on PATH, where readiness ran `pi` and `opencode` only as pi-family runtime hosts.
  Each `omh_agent_skills_discovery/v1` receipt binds that host version, the
  OS, the scan path, the manifest's `source_digest`, and the pack
  `catalog_revision`; the parser rejects a receipt that fails the checks
  docs/AGENT-SKILLS.md lists. `--receipts` compares an earlier `--json` run
  with the current pack and host versions; an unreadable scan path exits 3,
  and a missing root is refused. Built on the stage model, host descriptors
  and fixture tests @blrain3 contributed in #2093.
- **Bare `omh` opens the OMH TUI, OMH's own terminal over Hermes' gateway.**
  `omh` runs `hermes --tui` with OMH's frontend in place of Hermes' Ink app,
  so Hermes' launcher still resolves the profile, the resume target and
  session ownership, and every model call, tool run and approval decision
  stays Hermes'. Finished lines go to the terminal's own scrollback and only
  the region under them repaints; once the composer has reached the bottom
  rows it does not move when the plan and agents panel, or a question Hermes
  asked, grows or shrinks. Nothing is
  answered for the person: Esc, Ctrl+C, `d` or `n` declines, and allowing a
  command takes the arrows and then Enter. When the TUI cannot start
  (Windows, no `termios`, no Node, an OMH that cannot import itself, gateway
  drift) it creates a file `omh` named for that launch and exits 75, and
  `omh` opens Hermes' own terminal. The boundary is in CONTEXT.md ("OMH TUI", "Hermes gateway
  protocol"); the gateway slice it relies on is declared in
  `src/tui/gateway_contract.py`. The composer sits between two rules drawn in
  the input mode's glyph and colour, over a mode row that names the mode or
  the keys that matter now; replies open with `⏺`, a diff numbers its lines
  in a gutter, and the status line reads brand, model, context, state.
  On the terminals Hermes' own TUI trusts with it, it asks iTerm2, kitty,
  WezTerm, tmux, VS Code and Windows Terminal for the kitty keyboard protocol
  and xterm modifyOtherKeys, and Ghostty for modifyOtherKeys only, so
  Ctrl+Enter and Shift+Enter arrive as keys of their own, while every key the
  TUI binds decodes as before and so does each Ctrl chord xterm sends as one
  control byte (Ctrl+2 a NUL, Ctrl+3 Esc, Ctrl+8 Backspace);
  `OMH_TUI_KEYBOARD=legacy` keeps the plain bytes. Shift+Tab cycles normal,
  accept all and plan: accept all turns off Hermes' approvals for that session
  only (Hermes' per-session switch, never `approvals.mode`), is shown on the
  composer once Hermes confirms it, or when Hermes confirms neither it nor
  the switch back off, and the TUI sends that session an explicit off before
  it leaves it, and plan sends each prompt as `/plan <text>`; where Hermes has
  approvals off on its own, Shift+Tab sends nothing and turns plan on and
  off beside accept all. Ctrl+T or `/effort <level>` sets the session's
  reasoning effort, Ctrl+Enter or `/steer <text>` adds typed text to the
  running turn (a steer Hermes does not take waits in the queue for the turn
  to end), queued prompts are listed above the composer and Up takes them
  back to edit, `?` or `/keys` lists every key from the table the docs are
  held to, and an approval rings the terminal bell once (`OMH_TUI_BELL=0`
  silences it).
  A turn's subagents show as a strip on the mode row; Down opens them as a
  list, and Enter or a click opens one agent's read-only log, with mouse
  reports on only while an agent is there to click.

- **In the OMH TUI, `/reload-skills` makes a newly installed skill runnable,
  and a turn of unknown gateway events says so.** `/reload-skills` (or
  `/reload_skills`) has Hermes re-scan its skills in the gateway itself, then
  reads the command list again, so a skill installed after the TUI started
  (`omh update`, `/skills install`) runs as `/<name>` without a restart. The
  command list is read for each session the TUI opens, so a project's own
  skills follow its workspace; its warning (skill, quick-command or plugin
  discovery failed, or skills that run only as `/skill <name>`) shows once; `/help` lists Hermes'
  commands by category with a count of skill commands and is paged when long;
  and completion also matches part of a name, so `/uml` finds
  `/omh-codebase-uml`. A turn that brings no event the TUI shows, only types
  it does not know, gets one notice pointing at `omh doctor`, whose OMH TUI
  check now prints the installed Hermes commit next to the one the TUI was
  declared against. `omh` opens Hermes' own terminal only on exit 75 together
  with a file it named for that launch, so a 75 Hermes returns for a reason
  of its own ends the launch like any other exit code. The HUD's agent panel shows a
  Hermes-native subagent whose session has ended as finished at once, where
  it showed it running for up to 150 seconds. A plan item carrying an escape
  sequence is stored without it, where the sequence's parameters (`[31m`)
  used to stay behind as text.

- **The OMH status widget and the Hermes Desktop pane keep ordinary
  punctuation and drop whole escape sequences.** Their character allowlists
  dropped apostrophes, commas, question marks and quotes, so a plan item
  `person's` rendered as `persons`, and they removed only an escape's ESC byte,
  leaving `[31m` behind as text. The widget, the Desktop pane and the OMH TUI's
  panels now share one allowlist and one escape rule and render the same text.

- **Temp directories, RFC 4122 UUID directories and Hermes session ids no
  longer read as credentials.** The opaque-value check took the hyphens of a
  UUID, a run of Python `tempfile` names, or a numbered temp directory among
  words for a secret split into fragments, and a path segment that opened with
  `_` or `-` (`_temp`, `-Users-name-project`) or held an uppercase UUID made a
  whole path suspect. A memory capture whose `source_ref` was such a path
  stored it as `[redacted]` and went to review instead of auto-approval, and
  work-resume items and completion summaries carrying one became `[redacted]`.
  Over 2,000 generated paths per shape, a UUID directory went from 100%
  flagged to 0%, three chained `tempfile` names from 51.8% to 0%, a Hermes
  request dump name from 7.8% to 0%, and a Hermes session directory from 1.7%
  to 0%. A value split into fragments beside one of these names is still
  caught at the rate the same value is caught with nothing beside it, and
  detection over 25,000 generated split secrets moved from 17,571 to 17,568.
- **A new `spend-gate` skill shows what a spend will cost before the agent
  moves any money, and calls it done only on a receipt.** It covers every
  rail: a card checkout in a page, an HTTP 402 or pay-per-request call, a
  wallet transfer, a booking or deposit, a paid data endpoint, and a renewal
  that charges again. Before money moves the person sees a pre-spend card
  with the payee and its exact origin or address, the item, the total with
  fees and currency, the rail, the cap and what remains of it, the refund
  terms, whether the spend can be undone, and who approves it (the person
  whose money moves), and the person's typed yes in that session is required
  whether or not Hermes shows an approval prompt of its own. A host prompt
  that appears is recorded beside that yes; one that did not appear, or an
  auto-approval, is no confirmation, and a choice picked in `clarify` counts
  as the typed yes. A run nobody can answer -- a scheduled job, a webhook, an
  API-server or single-query run, a background worker, or a delegated
  subagent -- never spends: it prepares the card for the person's next
  interactive turn. A payment set up to recur without the agent (a
  subscription, a standing order, a capped auto top-up, a script with no
  agent in it) gets its card, typed yes and cap now. A quote is not a
  purchase; only an observed order id, transaction id, or receipt header
  completes a spend, an outcome nobody saw is `unknown` and is reconciled
  before any retry, a payment Hermes holds for approval (it never runs on its
  own) is never re-run or reworded and is recorded as not submitted, and a
  declined card is not retried. The cap ledger
  keeps metadata only. Hermes' saved-card fill, `clarify`, and the optional
  `stripe-link-cli` and `mpp-agent` skills are used only when present;
  without the fill tool the person enters the card and the agent never types
  one into a page. OMH moves no money and holds no credential. The skill is
  guidance only: no hook holds a payment tool call.

  Routing is deliberately conservative and closed-world, because the gate's
  phrases are everyday words that also name payment features, labels, bug
  reports, product ideas, articles and questions. The gate is offered only
  when the message is marked as a request outside the gate's own phrase:
  "please", "can you", "could you", "would you", "will you", "go ahead", "I
  need you to", "I want you to", an address to Hermes, or an amount or "for
  me" as the spend's object: outside the gate's phrases and before "at",
  "for", "from", "in", "on" or "to", and for "for me" after a word of its
  own since the last phrase ("transfer 40 dollars", "buy the cheapest one
  for me", "pay for me with my card"; not "pay with my card for $0 orders is
  broken", not "book the flight with my card for me never shows up", and not
  the "for me" of "buy it for me"). An imperative with none of these -- "pay
  with my card for the hotel", "buy it for me" -- routes as before the skill
  existed: that recall is given up so "Pay with my card in safari is broken"
  never reaches the gate. A marked message still has to lead with the spend:
  the sentence's first words after filler, up to the first comma, colon,
  question mark, "and", "if", "when", "which", "about" and the like, must
  open with a spend addressed to the agent -- "buy", "pay", "order", "book",
  "renew", "place the order", "complete the checkout", "use my card", and
  the like, not an idiom ("pay attention to the spend cap", "pay a visit")
  -- and one of the gate's phrases must be in that clause, each followed
  only by the end of the clause or the start of the next ("when it is back
  in stock"), "for", "on", "at", "from", "to" or "in", "with" the person's
  own card or an amount, an amount, "please", "now" or "right away"; "or"
  after the phrase makes a comparison, not a request. "send" and "transfer"
  also need money, an amount, or the person's own card or wallet; "did the
  payment go through" counts only when the agent paid. The skill scores only
  on that clause, there is no boost, and nothing stands down another skill's
  guard: a spend dispatches only when its clause scores high on the gate's
  own phrases, otherwise the gate leads a clarify, and every other sentence
  routes as before the skill existed. The route hint and the awareness
  markers read the same clause, as whole words. The bare words `spend`,
  `pay`, `checkout`, `wallet` and their siblings score only inside a
  complete phrase, and `budget` is not one of the skill's words at all.
  Budget variances, payment failure, checkout, 3DS and crash reports, a
  feature request, browser logins, spend-approval research, checkout test
  failures and issue triage, purchase acceptance criteria and a saved-card
  settings toggle keep their owners.

- **Session usage and the skill-draft check recognize an OMH skill by its
  catalog label, not by the `[omh] ` description prefix (#2120).**
  `canonical_skill_for_label` answers from every label the catalog renders or
  rendered, retired skills included, and `omh quality-evidence session-usage`
  reads it for a SKILL.md load, a reference-file load, a compaction
  placeholder, and a frontmatter name line. A prefixed description still
  counts under a name the catalog does not render, so no session that counted
  before stops counting. The 3.0.0 entry for session usage, which names the
  `[omh] ` prefix as the OMH-skill signal, no longer describes it.

- **A new `data-share-review` skill prepares a dataset, log, ticket export, or
  transcript excerpt to leave the team, and calls it redacted only after the
  file that leaves was scanned.** It asks where the file goes and what that
  destination needs, classifies every field as a direct identifier,
  quasi-identifier, secret, free text, or not personal, reads a row only when
  per-column shape counts leave a field unclear, drops what is not needed
  before masking anything, and keeps any pseudonym mapping at a local path
  outside the shipped file. The verdict is `redacted` only after an observed
  residual scan of the exact file that leaves counts every class, free text
  included; without one it is `not_observed`. Counts come from Hermes'
  `search_files` in its `count` mode or a detector script run through
  `execute_code` that prints counts only; that script's stderr and any
  traceback return too, so it catches its own errors without echoing a value.
  The skill says plainly that Hermes' `privacy.redact_pii` and
  `security.redact_secrets` cover gateway chat identifiers and tool output,
  never a file that leaves. What left is recorded as metadata only:
  destination, date, fields, row count, and digest. OMH uploads nothing, keeps
  no raw value, and leaves the lawful basis to `legal-compliance-review`. Chat
  routing to it is deliberately conservative: the words it lives on (redact,
  PII, pseudonymize, strip, export, vendor) also name code, Hermes settings,
  legal questions, issue triage, messages and posts, so it takes nothing
  another skill holds. It has no routing boost, no other skill's guard stands
  down for it, and it is scored only when a sentence leads with redact,
  pseudonymize, anonymize, or de-identify on a file leaving the team, such as
  "de-identify this export for the researcher". Logs for a GitHub issue, a
  transcript excerpt, or a dataset for a contractor stay with the skill that
  holds them, while Hermes' own skill index, or naming the skill, can still
  select it.

- **The coding lane works with Hermes' own delegation, board, and debugging
  skills instead of beside them.** `ulw-work` loads a Hermes-only
  `native-delegation` reference before a `delegate_task` dispatch. Each lane it
  writes itself carries an `output_schema` holding only the fields integration
  reads; the host's `schema_valid` is read only from a result returned in the
  same turn, a later completion message is checked against the schema by hand,
  `completed` is never read as validated, and a lane's answer stays its own
  report until the verification fan-in runs. With the user's
  `delegation.worktree_isolation` on, each lane works on its own
  `hermes-subagent/…` branch, so integration is a merge the parent performs
  before any check, after committing whatever a lane left uncommitted in its
  worktree: the checked team lane now says a check run before that
  merge tests a tree without the lane's work, and the file-ownership manifest
  is compared per lane branch. A one-shot run, which is also how a kanban
  worker runs, that is refused for its delegation budget finishes the
  remaining lanes inline in dependency order instead of retrying. The kanban
  lane recipe adds `completion_contract` (the board refuses completion until
  the repository's required checks pass on the PR's current head, a record the
  closing brief still checks against the PR head), `goal_mode` with
  `goal_max_turns`, `kanban_request_review` into the review column, and
  `kanban_schedule` where the worker has it; `omh_agent_board` now admits the
  two goal fields on a create and reads back a card in the host's `scheduled`
  status instead of failing the receipt. `agent-instructions` documents how
  Hermes loads context files: one file type per session, `.hermes.md` first,
  every `AGENTS.md` from the repository root down, and a per-directory
  `AGENTS.override.md` the inventory has to list. `plan` treats a file saved
  by Hermes' built-in `/plan` as its draft after that turn, with pasted code
  reduced by the proportion check and acceptance still taken only from the
  user. On Hermes, `decision-prototype` keeps its decision record when the
  bundled `spike` builds the experiment, `app-debugging` writes its records at
  each phase of the bundled `systematic-debugging` and counts a
  `python-debugpy` or `node-inspect-debugger` read as one observation, and
  `ask` takes only the invocation from the bundled `claude-code`, `codex`, or
  `opencode` skill for a CLI advisor the user named, with no CLI as the
  default.

- **Generated skills follow more of Hermes' own skill-authoring
  conventions.** Every Hermes skill body now opens its trigger section with
  `## When to Use`, the heading Hermes' skill linter looks for, and carries
  `license: MIT` and `author` in its frontmatter (the Agent Skills projection
  carries `license` only, the field that spec defines). Pointers to the
  references the router skill owns (the shared rail, the Jev rail,
  structural code search, workflow artifacts) are written as the call that
  loads them, such as
  `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`,
  instead of a bare path the model had to translate. A test now holds every
  shipped `SKILL.md` free of Hermes' inline-shell shape, which Hermes would
  run as a command when `skills.inline_shell` is on.

- **Three request shapes that belong to a skill Hermes bundles, or to a
  work board, stop dispatching an OMH skill.** An architecture diagram of
  cloud or infrastructure pieces described in words, with no codebase,
  repository, module, folder, `src` tree, CDK or Terraform named, no longer
  dispatches `codebase-uml`; Hermes bundles `architecture-diagram` for it.
  An English message naming an LLM wiki no longer reaches the wiki
  blueprint, nor the research department unless one is named outright;
  Hermes bundles `llm-wiki`. A review of what sits on a kanban, board, task,
  Trello or Jira card no longer opens an image card; a dashboard, scoreboard
  or storyboard card still does. Each of those turns now asks instead.
  Measured on the chat-interaction surface over both routing corpora, every
  sentence literal in the routing tests, the sentences this change was
  probed with, and its reviews' sentences: those are the only routes whose
  action or selected skill moves, each from a dispatch to a clarify. arXiv
  lookups, citation checks and paper research route as they did. The
  research-department body maps Scout to the `research` and `web-research`
  lanes its prepared plan emits, and handoff policies, like Do Not Use When
  lines, name siblings by the labels `skill_view` loads.

- **Skill bodies name their siblings by the name Hermes can load, and say
  which requests belong to a skill Hermes bundles.** A `## Do Not Use When`
  line that hands a request to a sibling used to name it by its catalog name
  (`connector-operator`, `strategy-brief`, `research`), which `skill_view`
  cannot load because the installed directory carries the display label
  (`omh-apps`, `omh-decide`, `ulw-research`). The renderer now writes the
  label in both the Hermes body and the Agent Skills projection; the catalog
  keeps canonical names, so routing and the deference graph are unchanged. A
  sibling that is no longer installed keeps its catalog name. The Hermes
  frontmatter gains `metadata.hermes.related_skills`, derived from those same
  lines, which `skill_view` returns beside the body; Hermes' per-turn skill
  index does not read it, and the index size is unchanged. A skill whose job
  overlaps a skill Hermes bundles now carries one line naming which request
  belongs to the bundled one: `requesting-code-review`, `systematic-debugging`,
  `simplify-code`, `spike`, `dogfood`, `llm-wiki`, `grounded-citations`,
  `arxiv`, `architecture-diagram`, `github`, `claude-code` / `codex` /
  `opencode`, `sdlc-review`, `meeting-action-items`, `humanizer`, `pdf` /
  `docx` / `powerpoint` / `xlsx`, `hermes-agent-skill-authoring`, and
  `competitor-news-monitor`. Those lines are Hermes-only, no other host
  bundles those skills: the deferral lines `web-research`,
  `research-department`, `visual-qa`, `ultraqa` and `code-review` already
  carried for `grounded-citations`, `arxiv`, `competitor-news-monitor`,
  `dogfood` and `sdlc-review` keep their wording and now leave the Agent
  Skills projection too, each counterpart named once per skill.
- **The memory and learning skills now read what Hermes' own learning loop
  wrote or is holding: pending memory writes, staged skill writes, the skill
  audit ledger, curator run reports, and the one memory-provider slot.**
  `memory-sync` lists the memory writes Hermes holds for approval under
  `pending/memory/` as proposals the person decides with `/memory approve` or
  `/memory reject`, reports a native write that comes back `staged: true` as
  waiting rather than saved, and reads each file's cap from the inventory,
  with the fallback figures taken from the plugin bundle's own Hermes memory
  reader rather than a second copy. Hermes' `write_approval` is described
  as Hermes' gate on Hermes' own writes: a safe `omh_memory` capture is still
  approved by OMH's auto-safe policy with no person in the loop, OMH never
  approves or rejects a pending write, and it never proposes turning the gate
  on.
  `external-connector-readiness` states that Hermes runs one external memory
  provider, so adopting another provider where `memory.provider` reads `omh`
  stops OMH's per-turn recall and dreaming reminders and leaves `omh_memory`
  refusing to recall or write records; the switch stays a proposed diff the
  user applies. It also records the plugin install scan and the OSV malware
  check for `npx`, `uvx`, and `pipx` MCP servers only from output that was
  seen, since a quiet install or launch is not a clean result.
  `workflow-learning` reads the skill audit ledger and reports agent or
  background-review skill writes that no store route accounts for as
  `unreviewed_native_write` (no OMH record of the write, not proof nobody
  reviewed it), and counts an approved update as landed from the ledger only
  when an `agent` or `user` entry creates, edits, patches, or writes the
  approved file after the approval;
  `instinct-ledger` keeps such a write out of an instinct's evidence and
  promotes through store routes; `rules-distill` lands an approved candidate
  in the user's own Hermes skills through `skill_manage`, never an OMH-managed
  skill, and reads curator run reports as one observation each.
  `skill-health` reads the ledger for managed skills changed outside OMH,
  `lint_warnings` from skill writes, and `hermes skills check` for hub
  updates, and never presents use or load counts as a reason to prune,
  archive, or retire a skill. `skill-scout` fills its candidates from
  `hermes skills search` and `inspect` with each source's trust level, and a
  scan verdict only from install or audit output. `prompt-import-readiness`
  starts from the `hermes import-agent --dry-run` preview, which skips Claude
  Code's slash-command prompts and does not read Codex prompt files, makes a
  skill the conversion target, and checks names against built-in commands,
  quick commands, plugin commands, skill bundles, and skills in the CLI's
  order. The seven feature-surface skills among these state their own Why
  and Do-Not-Use.

- **The run-efficiency report now carries what Hermes itself recorded for a
  named session, and the tracker skills point at Hermes' own usage, compaction,
  tool, agent, stop, and skill surfaces.** `omh runtime efficiency-report
  --hermes-session <id>` adds a `host_usage` section from the part of the cost
  receipt `omh_run_summary` returns that Hermes itself accounts for in
  `state.db` (the session, its delegated children, and its kanban workers;
  executor-reported fanout units are left out), read-only: observed only when
  that usage recorded tokens, with each amount's basis kept beside it (a
  Hermes estimate is not a charge), while a session Hermes has no row for, one
  with no recorded tokens, or a Hermes home whose `state.db` is missing or
  unreadable stays `not_observed` with that reason instead of reading as
  zero, and provider billing stays `not_observed` either way. The cost
  receipt now names which of its reads hit a bound (`truncated_sources`).
  `run-efficiency`, `ops-observability-card`, and `context-budget-review`
  answer "what has this conversation used or cost" by what each Hermes
  surface shows: `/usage` this session's tokens and context, `/insights` an
  estimated cost across recent sessions, and `omh_run_summary` this
  conversation's recorded tokens and cost; `context-budget-review` stops
  sending the question to the ops card, which cannot answer it.
  `context-budget-review` turns its summarization checkpoint into a
  `/compress <focus>` the person runs, offers `--preview` only in the classic
  CLI or on a messaging platform and never when the surface is unknown,
  because a modern TUI that does not parse the flag compresses for real, and
  counts a preview only from Hermes' own "no changes made" reply. `toolbelt-readiness` counts a tool deferred behind
  tool_search as present, never missing. `running-work-board` adds this
  conversation's Hermes delegate children and kanban workers from `omh_hud`.
  `cancel` clears OMH state with OMH's own commands and hands host work to the
  person's own Hermes stop commands (`/stop`, `/loop stop`, `/goal pause` or
  `/goal clear`, `/heartbeat clear`, `/pause`), never ending a host process
  itself, and reports a host stop as requested until Hermes answers. `skill`
  lists, reads, and edits the person's skills with Hermes' `skills_list`,
  `skill_view`, and `skill_manage`, leaves search, install, and hiding to the
  person's `hermes skills` commands, and never edits an OMH-managed skill in
  place. `capability-toggle` sends hiding one skill on one platform to Hermes'
  own `hermes skills config`.

- **Hermes' background review and `/btw` side question no longer use up the
  once-per-session OMH lines meant for the person's next turn.** On Hermes
  0.21.1, the plugin's floor, both run as a fork of the live agent that keeps
  the session's id and names that same id as its parent, and the fork's turn
  still ran OMH's `pre_llm_call`. A review runs right after a turn, so it took
  the board card naming this chat's open lanes, counted toward the plan line's
  turns with the full reconciliation rule, and replaced the session's last
  route-hint and skill-candidate claims; a side question asked mid-turn
  cleared that turn's Jev marker, so an `omh_jev_ask` the person had asked for
  returned `consent_not_observed`. The fork was handed OMH context of its own
  as well: with Hermes' review prompts, the primer, a route hint, the
  candidate line, the plan line, and the board card. `pre_llm_call` now
  returns nothing for a turn whose `parent_session_id` equals its
  `session_id`, before it reads or records anything, which is what Hermes
  0.21.2 and later do by not calling the hook for such a fork. A delegate
  child, which names its parent's id, and a turn that names no parent are
  unchanged. The held-write line's own fork check moves to that one place.
  Other hooks a fork reaches are unchanged.

- **A Hermes edit to an OMH-managed skill is redirected, kept, and reported
  instead of breaking the next update.** Hermes' background self-improvement
  review may patch, edit, or write files into any skill it loaded, OMH's
  managed skills included, and a foreground `skill_manage` delete of one is
  not guarded upstream. The OMH plugin's `pre_tool_call` now refuses a
  `skill_manage` edit, patch, write_file, remove_file, or delete whose target
  resolves to a skill OMH's install manifest records, by installed directory
  name and never by prefix or canonical name, including an `operations` array
  sent as a JSON string. A same-name skill in the Hermes home's own skills
  directory or in `skills.create_dir` takes the edit and passes, and anything
  the hook cannot read (manifest, `config.yaml`, a stat) lets the call
  through. The refusal names where a lesson goes: a separately named companion
  skill, created where `skill_manage` creates skills, or OMH's
  workflow-learning lane. A skill OMH did not install passes untouched.
  `omh install` / `omh update` keep a managed skill as it is when Hermes'
  curator ledger (`<hermes_home>/skills/.curator_ledger.jsonl`) accounts for
  what is on disk: a changed SKILL.md only when the newest ledger write to it
  left its current content, an unchanged one when a ledger write to another
  file of the skill still matches or a file OMH renders for it that Hermes
  removed is still absent; a row's unchanged files are not counted. Only the
  directory OMH renders for the skill counts: a same-name copy of a managed
  skill elsewhere in the skills directory is never kept, carried, or cleared
  as a Hermes edit, and an edit in a directory an earlier release rendered the
  skill into, after a release moved it, is reported as `left_behind`: not
  carried, and, while the catalog ships the skill, left exactly where it is by
  every pruner, with or without `--force`; the summary says to delete that
  directory by hand once it is no longer needed. A kept skill is carried into
  a new generation on a staged update (when the install's skill profile
  carries it) and listed with the ledger's actor, action, and time. `--force`
  clears the render directory of every skill it renders again that holds a
  Hermes write, never through a category directory that links out of the
  skills directory, and the summary says whether the ledger still holds a copy
  of the replaced files and names any file it removed that OMH does not render
  and the ledger has no copy of. Pruning now follows provenance. An install
  marks every manifest record whose SKILL.md it wrote with the hash it wrote
  (`rendered_sha256`) and flags the manifest (`render_marks`). Under a flagged
  manifest, the orphan pruner and the flat-layout pruner remove a marked
  directory only when its SKILL.md still has that hash, its record carries no
  kept Hermes-edit evidence, and Hermes' ledger records no write under it (a
  recorded write counts whether or not it is still on disk, and whether it
  came before or after OMH last rendered there, which OMH cannot tell, since a
  removal is final); every other file in that directory goes with it (for a
  directory that is also a category, only its own SKILL.md and a real
  `references/` directory, and the summary names only what went), and the
  summary names each directory removed by its path
  (`removed_skill_directories` in the result) and says only what was checked.
  An unmarked record (`not_rendered_by_omh`) is never removed, with or without
  `--force`: your own skill in a category directory or beside a managed one
  stays. A marked directory whose SKILL.md changed or under which a Hermes
  write is recorded (`changed_since_rendered`) is left by a plain install in
  the skills directory it writes (a staged update starts its new generation
  without it, as it does without any other local change that is not a kept
  Hermes edit) and removed by `--force`, except under `OMH_SECURITY=strict`,
  where `--force` overrides no local change; `--force` lists it under
  `force_pruned_skills` with the files the ledger still holds a copy of and
  the files that are gone for good. A ledger that exists but cannot be read, a
  line in it that names a path in the skills directory and is not a ledger
  row, an unterminated last line (an append may be in progress), or a profile
  list under `<hermes_home>/profiles` that cannot be listed (or an entry in it
  that cannot be read) may hide such a write, so a marked directory with
  nothing else against it is left in place as `ledger_unreadable`, naming what
  could not be read and its error (`unreadable_ledgers` in the result); a
  missing ledger records nothing, and `--force` removes it on the same terms
  without claiming what the ledger holds. Ledger rows are split on a newline
  alone, as Hermes writes and trims them, so a row holding a raw U+2028,
  U+2029, or U+0085 stays one row for every reader. Every directory left in
  place is listed under `prune_skipped_skills` on every install, and the
  manifest stays byte-identical across installs over an unchanged disk; the
  summary names a `not_rendered_by_omh` directory once, on the install that
  first records it, and the other reasons each time. The first install over a
  manifest written before marks existed still applies the earlier rule once:
  it removes an unchanged directory at an OMH position inside the skills
  directory -- including one of your own, as earlier releases did -- and
  `--force` also removes a changed one; the summary names each directory it
  removed by its path and says OMH cannot tell whether it rendered it, and the
  manifest it writes carries marks. Whichever rule applies,
  a pruner never follows a recorded path out of the skills directory or a
  link that leads out, never removes a category directory or any directory
  holding other skills (a stray `guide/SKILL.md` used to take the whole
  category), and never removes, under another spelling, a directory it
  renders a skill into: on a case-insensitive filesystem, a render directory
  renamed to another letter case is recorded as the skill it holds, and a
  Hermes edit written under that spelling is recognised.
  A change the ledger does not account for still refuses the install as
  before; a managed skill whose SKILL.md is gone (in the pack the manifest
  describes, so a staged update reports it too) is rendered again and
  reported instead of refusing, and `omh doctor` says so as a
  `missing_managed_skills` warning (or that the recorded profile leaves it
  `not_restored`) instead of a blocking local modification with `--force`
  advice. `omh doctor` also gains `hermes_skill_edits`, which
  reads the ledger without writing it and reports writes under OMH-managed
  skills, and a kept skill no longer fails `local_modifications` or
  `skill_freshness`. The identity-conflict scan now covers every managed skill
  name, scans the Hermes home's own skills directory and `skills.create_dir`,
  counts a directory only when it holds a SKILL.md, matches its directory name
  or declared frontmatter `name`, and reports each contested skill name's
  outcome from Hermes' documented tier order (`shadowed` by a higher-tier copy
  on Hermes 0.21.6 and later, `ambiguous` with another external copy, or
  `separate` for OMH's canonical name) instead of `unknown`; the report schema
  moves to `identity_conflict_report/v2`. Config readers now end a quoted
  value at its closing quote, so a trailing comment is no longer read as part
  of it. `omh setup` no longer lists a hub install among its equivalent Hermes
  commands, since that copy would outrank or collide with the managed skill.

- **The document, image, visual QA, release, and meeting skills now read
  Hermes' own producers as evidence beside OMH's verdict, never in place of
  it.** `materials-package` and `deliverable-package` map each file format's
  QA rung to the bundled `powerpoint`, `pdf`, `xlsx`, or `docx` skill result
  that can show it, and judge that result by its field rather than its exit
  code: the render and recalculation scripts exit 0 with `"rendered": false`
  or `"recalculated": false` when the renderer is missing, and that leaves the
  rung not observed. Other observed evidence for a rung still counts. Slide
  or page images count only after each one was inspected, a slide render goes
  into a fresh directory and must match the slide count, a recalculation
  writes to a copy, `docx_validate.py` is a package health check rather than
  a render, and a producer's `"ok": true` is never the QA verdict.
  `deliverable-package` reports a file as generated, approved, or attached
  only from that state's own evidence, and states its own purpose and
  Do-Not-Use instead of the shared generic lines. `report-package` names the
  bundled `powerpoint` skill as a tool that builds the binary deck.
  `img-summary` reports the image generator as connected when the session has
  `image_generate`, which Hermes offers only while an image backend is
  configured, and never from a version or a key. `visual-qa` can take its own
  captures through `browser_vision` when the session has it, binds each one
  to its screenshot path, URL, read-back viewport width, and target revision,
  scores a round from the image itself rather than an auxiliary model's
  description, sets viewports through `browser_cdp` when a CDP endpoint is
  configured, and reads the console after every step; a viewport it cannot
  set is a named blocker only for its own captures, so captures from the
  wrapper, executor, or user still count, and the portable body states these
  rules without Hermes tool names. Open-ended exploratory web QA goes to
  Hermes' bundled `dogfood` skill, whose report is a set of findings and
  never a PASS. `ultraqa` runs web scenarios the same way, against the target
  the user named, with a submit, purchase, send, or delete on a live surface
  waiting for the user's approval, and states its own purpose and
  Do-Not-Use. `deploy-and-monitor` prepares a watchlist that must keep
  running as a native blueprint with a monitor-mode cron job, which the user
  or Hermes activates; the first tick is not a detected change, and a silent
  tick says only that nothing was delivered, never that the release is
  healthy. `operating-rhythm` and `meeting-brief` record each action item's
  outcome, owner, due date, dependency, acceptance condition, and source,
  with unknowns marked, and an extraction by the bundled
  `meeting-action-items` skill stays a reading of the notes until they or the
  owner confirm it.

- **`automation-blueprint` now prepares Hermes' own Automation Blueprint
  instead of a look-alike with the same name.** The record `omh ops
  blueprint` writes is renamed from `hermes_ops_blueprint/v1` to
  `prepared_native_blueprint/v1` and gains a `native_blueprint` projection:
  the `metadata.hermes.blueprint` block (schedule, deliver, prompt,
  no_agent) and the matching `cronjob_manage` create call. The stored
  prompt is the bounded request preview (the record keeps no raw request),
  the current conversation is `origin`, a report-on-change rule is a
  `[SILENT]` final reply plus `continuity`, and the fields still open are
  listed under `needs_confirmation`, `prompt` included while the silence
  rule is unsettled or the request ran past the preview, in which case the
  full prompt is written from the conversation when the job is created. The
  validator refuses a block field Hermes does not read, a `model`,
  `provider`, or `pinned` argument on the create call, and any argument the
  `cronjob_manage` schema does not advertise at the plugin floor; a model pin stays the user's (the block's own keys, `hermes cron
  create` or `edit` with `--model` and `--provider`, or `pinned=true` on
  their explicit request where `cronjob_manage` offers it). The skill and
  its recurring-surface reference map OMH's overlap, missed-run, retry,
  backfill, and failure-pause decisions onto what Hermes cron does by
  itself and name the postures it cannot honour; Hermes' re-run of a
  recurring job's fire that failed on a transient network or DNS error
  before any model call, and its global missed-run switch, are stated by
  presence in the installed Hermes, never by version. Where `cronjob_manage`
  is absent the skill hands the user the equivalent `hermes cron create`
  command. Post-activation status comes from Hermes (`cronjob_manage` list,
  `hermes cron runs`, open `hermes cron incidents`), and OMH still creates
  no cron job: activation is `/blueprint`, an accepted Suggested Cron Job,
  a create the user asked for, or a `hermes cron create` the user runs.
  Records, index caches, and saved recurring intents written under the old
  id stay readable and valid.

- **A Maestro supervisor now waits on a dispatch with one bounded background
  watcher instead of polling the roster every minute in its own turns.**
  `omh coding fanout status --wait` re-reads the same read-only roster until
  the roster itself names a reason to stop, prints only that last roster with
  a `wait` block, and exits with a code that says which reason it was: 3 at
  the first read where `stuck_units` names a unit (so a unit waiting on a
  person, held by a provider limit, blocked on a permission, missing objects,
  or stalled still stops the wait at the next read), 0 when every unit is
  terminal and `verified`, 1 when every unit is terminal and one is not, 65
  when every listed unit verified but the journal had unreadable lines (the
  roster lists units from the journal, so a torn line can hide one), and 124
  when `--timeout` passes first. A watcher that raises exits 70 with its
  traceback, because Python's own 1 already means a unit did not verify. A
  stuck unit outranks a finished roster, because a unit the dispatch summary
  recorded at `account_limit` is over and still needs a person. `--timeout`
  (default 600 seconds, at most 3600) and `--interval` (default 30, between 5
  and 300) are refused without `--wait`; an unknown fanout id fails on the
  first read rather than at the deadline; the watcher writes nothing. Without
  `--wait` the command exits 0 as before. The roster itself now reads a unit
  whose in-flight marker has no state yet as `unknown` and not terminal when
  that marker was written after the dispatch summary's row for the unit,
  instead of falling back to that row: a re-dispatched unit's old
  `account_limit` read as stuck the moment the new process started. A marker
  that is not later than the row, such as a reservation marker an early
  return left behind, leaves the row standing. The `ulw-maestro` skill now
  starts the watcher once through Hermes' `terminal(background=true,
  notify=true)` when the tool is present, waits on it in the turn when the
  spawn result says the session cannot receive the completion, reads the
  roster once on any exit, and keeps every per-poll intervention rule it had:
  exit 3 is the moment to intervene, on exit 124 a unit still `unknown` is a
  missing record to chase while only a unit still `running` gets a fresh
  watcher, and any code the watcher did not choose gets a fresh watcher only
  if units are still running.

- **OMH no longer steers the model against Hermes' own `clarify`, `/loop`,
  `/goal`, and `/plan`.** `ulw-interview` sends each question's two to four
  candidate answers through Hermes' native `clarify` tool when it is in the
  tool list or reachable through tool search: the candidates go in `choices`
  with the recommended one first, the round header stays in the message, OMH
  adds no free-input row of its own (the picker supplies one), and a second
  question joins the same call only when neither answer could change the
  other. `ulw-context` asks each frontier round the same way, one `questions`
  entry per dependency-ready decision, its identifier opening the question and
  at most four choices with the recommendation first, since decisions in one
  frontier have no prerequisite between them. Where `clarify`
  is absent, the numbered list or batch in the message stays the fallback, and
  free text is still accepted either way. `ulw-loop` gains
  Do-Not-Use lines that hand a check repeated on a timer to native `/loop`,
  an unattended schedule to a Hermes cron job, and a single objective with a
  done condition to native `/goal`. A request in one of three shapes no
  longer dispatches the goal loop or draws the `ulw-loop` route hint or
  candidate line: `loop` or `/loop` as the first word followed by its
  cadence ("loop every 5 minutes and check whether CI is green", `/loop 5m
  …`, compound intervals such as `/loop 1h30m` and short or glued units such
  as `5 min` and `5mins` included); a cadence followed directly by `loop` as
  the verb, before its object, a preposition or conjunction, or nothing
  ("every 10 minutes loop over the inbox"), in a first sentence that neither
  ends in a question mark nor asks why or how, and not after a count of two
  or more with a spelled singular unit ("every 5 minute loop …"); or a
  Korean cadence whose first clause closes on running the loop, with no
  connective such as `-는데` in it (`5분마다 … 루프 돌려줘`). The router answers it directly and names the `/loop` command; a
  request that opens by asking to write or explain a for, while, event, or
  media loop that runs on a timer is answered directly without that advice.
  Only the opening of the person's current message is read, after a
  messaging gateway's sender prefix, trigger note, reply pointer, or channel
  backfill and a courtesy opener. Everything else decides nothing and routes
  as before: a loop word elsewhere ("the retry loop fires every 5 seconds",
  the spaced `cto loop` trigger), and a loop word as an adverbial ("every 5
  minutes check CI in a loop", `5분마다 반복해서 …`, `루프 돌면서 …`, `루프
  돌려서 …`), because those words describe a fault as often as they ask for
  a loop ("every 5 minutes my pod restarts in a loop", `5분마다 반복해서 에러
  나는데 원인 찾아줘`). A skill the router reads as explicitly invoked ("loop
  every 5 minutes and run the code-review skill on new PRs") still gets the
  turn. One function decides this for the router, its loop guard, the route
  hint, and the candidate line, and the router and the hint are pinned to
  agree on every probe sentence. Such a request stays OMH's goal loop when it
  puts OMH's own form in the loop command's place (`./loop`, `$loop`, `omh
  loop`, `ulw-loop`, `ulw loop`), names the skill anywhere in an untyped
  command, names the goal loop beside the command ("goal loop", "the loop
  skill"), asks the loop to improve or enhance something, or pairs a product
  or star word with an outcome verb (lower, reduce, raise, "get us to", 줄여,
  높여, and the like) or a repeat cue (until, iteratively, keep improving), or
  a star word with a product word. A typed `/loop` with its cadence is
  Hermes' command whatever its prompt mentions, OMH's name and goal words
  included; where the prompt would otherwise have been the goal loop, the
  route reason tells the model that `/loop` repeats it as written and that
  `./loop <goal>` starts OMH's goal loop, while the visible reply keeps the
  shared direct-answer copy. `ulw-loop` named after a cadence ("every 2
  hours ulw-loop the flaky test list", "every hour ulw-loop the build
  failures on main") now opens the goal loop, where app-debugging and
  build-failure-triage took those sentences before. The turns Hermes
  writes for its own session commands are no longer routed at all: `/plan`,
  `/loop` wakeups, `/goal` continuations (with a completion contract or
  `/subgoal` criteria, after a failed quality gate, and the kick that stands
  in for a goal just sent), goal-mode kanban nudges, `/heartbeat` firings,
  `/learn`, and `/initiate-setup`, each recognised by its template's opening
  line and the fixed text that follows it, also behind the sender prefix,
  Discord trigger note, reply pointer, or channel backfill a messaging gateway
  puts before it. A frame followed by the person's own words on the same
  line, or by anything other than the text its template writes next, is still
  read as a person; a heartbeat's next line is the person's own recurring
  instruction, so typing under a pasted heartbeat frame cannot be told apart.
  The CLI and the TUI give none of these turns a `display_kind`,
  and the gateway stamps only its `/loop` wakeups and, since 0.21.4, its
  heartbeats. The router and the chat wrapper answer them directly, and the
  plugin's per-turn hook renders no route hint, vocabulary match, or candidate
  line on them, as it already did for rows Hermes stamps with a
  `display_kind`.

- **The operator skills now record what Hermes' own approval, checkpoint,
  vault, and connection surfaces answered, beside the confirmations they keep,
  and use those surfaces where they exist.** `command-operator` still
  confirms every irreversible or externally visible command in chat before it
  runs, whether or not Hermes flags it -- deleting or overwriting user data,
  discarding history or force-pushing, deleting a remote branch, dropping or
  flushing a database, a credentialed or networked mutation, device
  actuation, an install, a deploy, a production change, or an external send
  -- because Hermes' default smart approval can approve a command with nobody
  asked and its detector misses many such commands. The terminal result's
  `approval` note is recorded as additional evidence: "approved by the user"
  is the person's answer to Hermes' prompt, while a smart auto-approval or no
  note is not consent, and a `pending_approval` command has not run. A cron,
  one-shot, or webhook run denies a flagged command by default, so the
  command goes to a person's turn instead of being rephrased.
  `workspace-file-operator` keeps its confirmation and records beforehand
  whether a checkpoint covers the target: Hermes' checkpoints are off unless
  the user turned them on, and one covers only the directory Hermes snapshots,
  minus its excludes and size limits, so only the user's `/rollback` answer for
  a directory holding the target marks one available. Its harness gains that
  ladder step. `browser-operator` sends sign-ins, one-time codes, saved
  cards, and first-time logins to `browser_vault` (`fill`, `enter_code`,
  `save_login`) when the session has it, and names OMH's own browser adapter
  bridge as a blocker for the vault and for the native browser tools.
  `connector-operator` and `morning-brief` take a missing connection to
  `manage_connections` when the session has it and treat a `skipped` app as
  the user's answer; `connector-operator` still confirms an irreversible
  provider action in chat, since Hermes prompts before such a call only in
  some configurations. `morning-brief` reports that the bundled
  `google-workspace` OAuth setup requests `gmail.send` and `gmail.modify` on
  every run (its setup script takes no `--services` flag), so those scopes are
  reported as granted unless the setup script's own check lists them as
  missing. `security-safety-review` and `physical-device-readiness` emit a
  proposed `approvals.deny` list for blocked terminal commands that the user
  applies; OMH writes no Hermes config. `github-event-ops` takes its intake
  from a Hermes webhook route, treats the payload as untrusted, and reports a
  PR comment only after reading it back. `parallel-tools` proposes one change,
  `mcp_servers.<name>.supports_parallel_tool_calls: true` per named MCP
  server, instead of an update. A tool that is not in every supported Hermes
  release is named only in a sentence carrying the "in your tool list or
  tool_search finds it" rule, never a version. The feature-surface skills
  among these state their own Why and Do-Not-Use instead of the shape's
  shared lines, through a per-skill override that later skills can reuse.

- **Review and verification skills use the contracts Hermes already enforces,
  and a failing check now says whether the change caused it.** `code-review`
  prints its finding shape as a JSON Schema in the dispatch reference: a
  reviewer is handed it as the return contract, and a return that does not
  match is `not_observed`, never a pass. A `ship` has to name what it checked,
  so a verdict with no finding and nothing checked does not validate. On
  Hermes, when `delegate_task` is present, the schema goes in as that task's
  `output_schema` and the host validates the return with its one correction
  turn. Its `schema_valid` record reaches the dispatcher only when the call
  returns its results in the same turn, which is what a delegated subagent, a
  kanban worker, a scheduled job, or a one-shot run gets; there the dispatcher
  reads `schema_valid` and never the task status, because Hermes builds
  disagree on whether a contract failure is a failed task or a completed one
  carrying the raw text. An interactive session's dispatch returns a handle,
  and the result arrives later as a completion message that prints no
  validation record: a failed status naming the output contract is a contract
  failure, `completed` is not validation, and the dispatcher checks the
  summary against the schema itself. The dispatch request also marks the diff,
  logs, and pasted output
  as material under review, so a sentence inside them is a finding to report
  and never a step to carry out. Inside a kanban review worker Hermes' bundled
  `sdlc-review` owns the card's transition: `code-review` supplies the
  findings, `no_ship` becomes a request-changes transition, and a review that
  did not finish never completes a card. The Hermes-only rules ship in a new
  `native-review-contract.md` reference that the portable Agent Skills
  projection does not carry. `verification-gate` and `build-failure-triage`
  give every failing check or failure cluster an `origin` of `introduced`,
  `pre_existing`, or `unknown`, and `observed_check_results/v1` gains the
  field. `pre_existing` is proven only by an observed run of the same command
  at the merge-base in a clean detached worktree, never by stashing or
  checking out the tree the user is working in, and the row names which proof
  an origin rests on. PASS never stands beside a failing required check,
  whatever its origin: a proven `pre_existing` failure is HOLD worded as not
  charged to the change, and only when the failing run still covered the
  change, while `unknown` is HOLD with the merge-base run named as the missing
  evidence. `build-failure-triage` returns FIX_READY only for introduced
  clusters and hands a pre-existing one off on its own, with no new verdict;
  clusters of different origins share one verdict, NEEDS_MORE_LOGS while any
  is unknown. `commit-pr-authoring` lists the paths a
  commit covers so they are staged by name, never recommends `git add -A` or
  `git add .`, and writes a state-claiming subject prefix such as
  `[verified]` only as a projection of an observed ledger row in a repository
  whose log uses it. The literal prompt Hermes' kanban dispatcher opens a
  worker with is pinned as a turn on which OMH offers no code review.

- **The research skills register and check their sources through Hermes'
  bundled citation ledger, and a citation check is reported only from a run
  that checked something.** "Cite the source behind each claim" used to be a
  prose rule in `web-research`, `research-brief`, and `research`, so nothing
  recorded which source a number in a draft pointed at or whether the draft
  still matched it. When Hermes' bundled `grounded-citations` skill is
  available, the three skills now load it, register each source in its ledger
  at retrieval time, and cite a source only by the id the ledger gave it. They
  keep the run's ledger in a file of its own (`--ledger <path>`, ahead of the
  subcommand), because the default ledger is shared by the whole profile and
  another run's reset rebinds its ids. The exit status of `sources.py verify`
  on the draft is reported as the observed citation check, and with
  `--evidence` the run also fails a draft whose cited source carries no
  verbatim quote. An exit `0` that cited no source checked nothing and is
  reported as `not_observed`, as is a `web-research` answer given only in
  chat, since `verify` needs a draft file. The check compares citations with
  the ledger and is never reported as fact verification; with no run it is
  `not_observed`, and without the bundled skill the skills list and cite
  sources in prose and report the check as `not_observed`. `research-brief`
  evidence rows carry the ledger id as `[n]` and its quote, and `research`
  sets one ledger up for every lane in its first steps. `[unverified]` marks
  background the answer does not rest on and never carries the answer. Each of
  the three skills' completion checklists now names the citation check. What
  OMH adds is unchanged: the freshness window, source class, temporal
  receipts, the contested-claim gate, and the one-round stop. `web-research`
  now tries Hermes' `blocked-page-recovery` skill once for a source that
  returns 403 or 429 or sits behind a paywall or bot wall, as `research`
  already did. `research-department` gains four rules for a recurring watch: a
  watchlist and materiality threshold written once and reused, a source that
  could not be read reported as unknown coverage rather than as nothing new, a
  cutoff kept per source that moves only for a source the run covered, and
  findings counted by underlying event rather than by article. Its Scout lane
  hands a watch over named companies to the bundled `competitor-news-monitor`
  skill, it offers the bundled `llm-wiki` skill when no knowledge store is
  named, and a schedule stays a prepared job description: OMH creates no job,
  and one counts as created only from an observed `cronjob_manage` result or a
  cron listing. `source-finder` finds paper candidates through the bundled
  `arxiv` skill and records them as `link_observed`, and `paper-learning` sets
  `source_state` from how the paper was acquired: an arXiv entry is
  `metadata_only`, page text that the bundled `pdf` skill's
  `pdf_read.py --text` returned is `file_text_extraction_observed`, and a
  paper past one read budget is read in `long-document-reading`'s page ranges
  when that skill is available. `web-research` and `research-department`
  decline, to the bundled skill, a request that skill owns outright: citation
  bookkeeping on an existing draft, an arXiv search, or one news watch over
  named companies. Routing is unchanged, so a request phrased with one of
  their own triggers, such as a "citation check" on a draft, still opens the
  OMH skill first, which then hands it over.

- **The shipped model chains move to the 2026-10-13 table, and Claude Haiku
  5.5 is onboarded.** Every category chain, the `main` role suggestion, the
  public tables (`docs/INSTALLATION.md` regenerated, the four READMEs and two
  site pages), the plugin mirror, and the `model-setup` skill text carry the
  owner's table of that date. Inside a chain Claude Opus 5.5 now comes before
  Claude Fable 5.1, reversing the 2026-09-06 order, in both lanes. The
  Maestro lane's Claude Code frontier chain is `claude-opus-5-5`, then
  `claude-fable-5-1`, then the `opus` alias as the always-resolving tail
  (owner decision), its `unspecified-high` and `visual-engineering` rows now
  name `medium` and `high` instead of leaving the effort to the CLI, and the
  setup interview seeds the Claude Code `--model` preference with the pinned
  `claude-opus-5-5`. Claude Haiku 5.5 (`claude-haiku-5-5`, released
  2026-10-07) gets an exact contract with its `low`..`max` ladder (`medium`
  default; a thinking disable is accepted at `high` or below, so `off`
  passes through and `minimal` is raised to `low`), the Bedrock and dotted
  declared spellings, a display label, and placements in `quick` and
  `simple-work`. Its price row is the up-to-100K card (0.10/0.50); the
  0.50/2.50 card above 100K prompt tokens stays on the contract, so Haiku
  5.5 cost is under-reported up to 5x above 100K prompt tokens. Its shipped
  `low` rung takes effect only on a Hermes build that forwards Haiku effort:
  on the Anthropic route, Hermes through v0.21.6 sends neither thinking nor
  effort for any `haiku` id, so the unit runs at the API default `medium`;
  v0.21.7 forwards it. Claude Sonnet 5.5 joins `unspecified-low` and
  `writing`, and its cache-read rate follows Anthropic's 2026-10-07 price
  cut from $0.20 to $0.10 per MTok (0.05x input). Claude Haiku 4.5 and the
  2025 Qwen3-Coder leave every shipped chain; the bare aliases
  `claude-haiku-4-5` and `qwen3-coder` stay recognized, priced, and
  provider-mapped for an operator override, and `qwen-oauth` stays a valid
  provider kind so a recorded `providers.json` naming it stays valid.
  DeepSeek leaves `deep`, Opus 5.5 leaves the tail of `unspecified-low`, and
  Fable 5.1 leaves the tail of `quick`. `deepseek-flash` is labelled
  "DeepSeek V4.1 Flash" (the alias stays the served pointer). Two chain
  heads are now shared, so for a child with no matching route-provenance
  record `mixture_category_for` projects a visual-engineering head to
  "deep" and a capable head to "writing"; a lane routed through
  `omh_delegate_route` keeps its own category, routing is unaffected, and
  `deep-work` runs at `max` so its own label survives. Every placement is
  editorial and unmeasured except the `unspecified-high` GPT head, which
  rests on a measurement of its predecessor: on
  `benchmarks/live-model-tools/v1` (30 evaluation tasks, 2026-09-05) OMH
  routing passed 18/30 with `gpt-5.6-sol` at that head and 12/30 with
  `kimi-k3-ultrafast` there (the other 24 tasks routed to the `quick` head
  in both arms; Kimi passed 0/6 of the six search tasks). GPT-6.1 Sol itself
  is unmeasured on that corpus.

- **The plugin bundle's cold load is now held under Hermes' per-plugin load
  deadline, and `omh doctor` reports what that deadline did to OMH.** Hermes
  0.21.5 and later (and canary builds from 2026-09-25) skip a plugin whose
  import plus `register()` takes longer than `plugins.load_timeout_seconds`
  (10 seconds by default), and its plugin loader then registers no OMH tool
  or hook for that load. The bundle had never been timed. Loaded the way
  Hermes loads it, in a fresh interpreter with no bytecode cached anywhere,
  it takes 0.4-0.8 s on a contended 14-core Mac, and 0.23-0.31 s through
  Hermes' own loader in an isolated home, so no bundle code changed.
  `tests/test_plugin_load_deadline.py` now measures that cold load in a
  subprocess and fails above half of Hermes' default, on a host without the
  `omh` package and on one that can import it, and checks which of the two it
  actually timed; it compares the fastest of three runs so a starved CI
  runner does not fail it, its failure message separates a slow runner from a
  slow bundle, and a passing run prints its timings to stderr. Windows cold
  load was not measured locally: the timing that test prints on the Windows
  CI shards is the first observation of it. `omh doctor` gains a
  `plugin_load_deadline` row. It names the `plugins.load_timeout_seconds`
  value it read from the Hermes config -- only when the key is written once,
  on one line, directly under a single block `plugins:` node; anything else
  is reported as not read, never as unset. It reads
  `<hermes-home>/logs/errors.log` and its two rotated backups for the lines
  Hermes writes when the deadline costs `omh` its load: its own overrun, or a
  refusal because other plugins' abandoned loaders reached Hermes' cap. A
  record is a warning that carries Hermes' own timestamp and cause and says
  it is a past load, not the current state. Files with no record are named
  one by one, with "last 4 MiB only" beside any that was larger than what
  was read, and never as proof that the plugin loaded. A missing log, or
  something other than a regular file in its place, is `not_observed`. The
  record rides in the row's `detail` for `--json` readers. OMH reads the
  config and the logs and writes none of them.

- **A plan has one checklist: Hermes' `todo_list` and `omh_todo` no longer
  ask for the same list twice.** Hermes ships its own checklist tool,
  `todo_list`, and OMH told the model to declare every plan with `omh_todo`
  as well, so a session could declare the same plan in both tools, in
  paraphrased items, and show two lists for one plan. Wherever `todo_list`
  is present -- in the session's tool list, or found through `tool_search`,
  never judged by a Hermes version -- it now holds the steps, and the
  plugin's `post_tool_call` hook mirrors each successful `todo_list` write
  into the session's own plan todo, so the HUD panel, the Desktop pane, the
  plan-stage gate and the continuation and stall checks read one record
  whichever tool wrote it. A native `completed` is still a declaration and
  is judged against recorded commands exactly like an `omh_todo` done mark;
  a `cancelled` item shows as skipped. `omh_todo` keeps what only it
  records: `plan_stage`, the checkpoint/record/recall dossier, an item's
  `blocked_reason` and the plan's `deferred_reason`. On a plan `todo_list`
  holds, `todo_list` alone sets item states, and a recorded reason lasts
  across later `todo_list` writes while the item stays where it was or is
  paused back to pending; resuming, completing or reopening the item, or
  cancelling it while open, ends it. A planning checklist awaiting
  acceptance and an open `code-story` plan stay with `omh_todo` while they
  are open, and an accepted plan (the one `omh_team` binds its lanes to)
  until it goes stale; a `todo_list` write does not replace them, leaving
  one for unrelated work is `omh_todo action=clear` (a recorded
  `deferred_reason` only pauses it), and the session's next turn is told
  once when a `todo_list` write was not mirrored and the plan is still held
  and not deferred. Where `todo_list` is absent, `omh_todo` is the tracker exactly as before. The
  `omh_todo` description, the route hint's checklist line, the plan nudge,
  the `todo-checklist` skill and the `ulw-work` and `ulw-plan` opening steps
  now say to use one tool for the steps, never both. Where Hermes draws its
  own todo list -- the modern TUI and Hermes Desktop -- the OMH panel above
  the prompt and the Desktop pane no longer draw a `todo_list`-held plan's
  items a second time: they show a compact "in todo_list" plan summary only
  for what Hermes does not show (an item waiting on a reason `omh_todo`
  recorded, the stall finding, and in the TUI the parallel-shot badge), and
  nothing otherwise.

- **`websearch-setup` configures the web search settings Hermes actually
  reads, and OMH stops treating the removed auxiliary web-extract slot as
  configuration.** The guide's second step used to assign a model to the
  auxiliary web-extract slot, which Hermes removed before the oldest release
  OMH supports; the guide wrote a key nothing reads and its verify step could
  read that key back as success. The step is now a backend and tier choice
  over the `web` config: `web.search_backend` and `web.extract_backend` (or
  the shared `web.backend`), `web.provider_tier.<name>: free|paid`, and
  `web.keyless_fallback`. Diagnosis names which backend serves search and
  which serves extract, and why, including the releases where any
  per-capability key sends the other capability to Hermes' default backend,
  and checks the levers that need no key first: the keyless free tier, and a
  split that keeps search free while only extract uses a paid account. The
  provider key and the backend or tier change stay two separate diff
  approvals, and verify reads back the keys Hermes consumes. The guide never
  writes `auxiliary.web_extract` and reports a leftover block there as
  ignored. A `web` key missing from `config.yaml` is read as its default, and
  support is read from the merged config, never inferred from a Hermes
  version. Setup and cost phrasing now reaches the guide instead of a live
  web lookup: "configure web search" said on its own opens it, and with a
  courtesy word or trailing punctuation around it the route asks with the
  guide leading. The route also asks with the guide leading for Hermes' web
  search named beside a setup verb ("switch hermes web search to the free
  tier"), "web search backend", "web search costs too much", "the keyless
  free web search tier", and setting the web extract backend. "Configure web
  search" with an object, such as a store's catalog or a Next.js app, routes
  as before, and so do lookups, outage checks, and code changes that name
  Hermes' web search without a setup verb. Cited lookups about costs or
  vendors' free tiers stay lookups, and pricing words alone ("how much does
  it cost", a vendor's free tier, "deploy the backend") do not name the
  guide. The `omh menubar status` Models card lists the auxiliary slots every
  supported Hermes reads, without `web_extract`; the doctor advisory for
  unpinned auxiliary slots names the same slots without a fixed count and no
  longer counts a leftover `web_extract` pin as routing.

- **Achievements are read from where the bundled Hermes plugin keeps them
  now.** The hermes-achievements plugin stores `scan_snapshot.json` and
  `state.json` under `plugin-data/hermes-achievements/` in the active
  profile's Hermes home, copies an old install-directory file forward once,
  and never writes the old location again, so `omh achievements`, the
  context brief profile, and the full HUD preset reported nothing or a
  frozen copy on supported Hermes. Each file is now read from `plugin-data/`
  first and from the legacy `plugins/hermes-achievements/` only when
  `plugin-data/` has no copy, and the payload's `source` names the directory
  each file came from. A new `snapshot_freshness` block reports the
  snapshot's `generated_at`, its age, and whether it is stale by the
  plugin's own rescan rule; OMH applies the rule to the file and never calls
  the dashboard. Badge progress now comes from the plugin's `progress_pct`.
  For a tiered badge its `progress` is the raw metric count, which was read
  as a percentage (and a count of 1 as a fraction), so a count of 2 to 99
  showed as that many percent and a count of 1 or of 100 and more as 100%.
  An unlock in `state.json` still marks a badge unlocked, as current Hermes
  (0.21.4 and later) does with its sticky-unlock floor. It now fills a
  missing tier from the unlock's `first_tier`, never lowers a tier, and
  keeps the snapshot's next-tier progress instead of overwriting it with
  100%. `agent_summary.json` is no longer read: the plugin has no writer for
  it, and the profile is derived from the observed badges. The snapshot also
  carries per-session stats for the whole history, so on a real install it
  is far larger than the HUD's read cap and the HUD used to count nothing
  from it. The HUD now reads only the leading members that fit whole within
  its cap, where the plugin's sorted keys put the badge list. A total it
  cannot read is reported as `total_status: not_observed` with no
  denominator in the `ach:` segment, never as 0. Plugin timestamps, which
  are epoch seconds, appear as UTC ISO-8601 in `omh achievements` text and
  the Markdown export, while the JSON keeps the raw values. Both readers
  accept a file saved with a byte-order mark, as current Hermes (0.21.6 and
  later) does.

- **The `frontend` design contract now uses Google's DESIGN.md format, so it
  no longer contradicts Hermes' bundled `design-md` skill.** Both install by
  default and both describe a project-root `DESIGN.md`, but OMH's contract
  asked for nine numbered sections with no front matter while `design-md`
  writes Google's format: YAML token front matter and a fixed section order
  that its linter checks. A new contract is now that format (`name:`,
  `colors:`, and the other token groups in the front matter; Overview through
  Do's and Don'ts in the format's order) with OMH's Signature Element, Motion
  & Interaction, Accessibility Constraints & Accepted Debt, and Research Log
  sections beside them, which the format keeps and its order check skips.
  The surface/on-surface pairs, the focus-ring token, and the single radius
  knob carry over into the front matter and the Colors and Shapes sections.
  A `DESIGN.md` already written in the earlier numbered layout stays a valid
  contract: the skill follows and amends it in place and converts it only
  when the user asks, using a section mapping that moves decisions without
  making new ones; content other references name in the format's terms is
  written into the legacy file's counterpart section, without front matter.
  Headings are the bare section names, unnumbered, since the format matches
  heading text exactly. Authoring, linting, diffing, and exporting a file in
  the format go to `design-md` when it is available (a legacy file is not
  handed to it, since its authoring rewrites), and a lint result counts as
  observed contract evidence only when Hermes or the selected executor
  actually ran `npx -y @google/design.md lint` on the current file; otherwise
  the lint status is `not_observed`. OMH itself still runs no package and
  makes no network call. The chart-styling, component-registry-adoption (its
  motion profiles), taste-foundations, and tui-craft references now name the
  section they mean instead of a section number, and `docs/SKILL-SOURCES.md`
  records both upstreams with closure receipts.

- **Every shipped skill passes the Hermes install scanner of every
  supported Hermes release, not only one.** Hermes changes
  `tools/skills_guard.py` between releases, and the repo gate ran only the
  copy Hermes 0.21.6 ships. The scanner in Hermes 0.21.1 through 0.21.3, the
  `requires_hermes` floor, matches `context_exfil` across a whole line of
  plain words and inside a word ("A blueprint is prepared design context"
  reads as `print … context`), so `omh-routing`, `omh-wiki` and `ulw-loop`,
  and the `agent-skills/` copies of the last two, scanned `caution` there,
  which blocks a community tap install. Four lines are reworded at their
  producers with their meaning kept: the omh-routing wrapper reference
  heading is now "Context Safety For Large Output", the wiki blueprint
  reference calls a blueprint a prepared design artifact, ulw-loop's log
  rule speaks of logging a cycle to a file, and its measured-loop reference
  of re-reading a passing cycle's log. The omh-wiki skill's own boundary
  sentence, which passed only because a backticked name preceded it, now
  calls a blueprint a prepared design artifact too.
  `tests/test_hermes_install_scan.py` now runs every scanner a Hermes
  release tag from the floor up ships, each vendored verbatim under
  `tests/_vendor/` and pinned by its upstream sha256: Hermes 0.21.1 through
  0.21.3 (v2), 0.21.4 and 0.21.5 (v6), 0.21.6 (v8), and 0.21.7 and upstream
  main (v10). A release-to-scanner map is checked against the floor in
  `plugin.yaml`, so dropping a release's copy fails. The test scans
  `skills/` and `agent-skills/` under each one and pins each version's
  severity for the sentences that blocked installs (v10 scores a bare
  `setgid` and a `sudo` in Markdown as informational). It also pins a shape
  only v6 flags, a pipe into a word that starts with `zsh`, `ksh` or `dash`
  such as `| dashboard`, so the v6 copy is not redundant. Canary builds are
  not gated. `requires_hermes` is unchanged.

- **OMH memory works in messenger DMs and group channels (#2088).** Every
  gateway session was a shared surface, which denies every identity-unbound
  record, so a single user's own Slack DM recalled none of their 33 approved
  records. The provider now verifies a messenger conversation from the ids
  Hermes passes (`chat_type`, `chat_id`, `chat_name`, `user_id`, `thread_id`),
  with one structural check per covered platform (Telegram, Slack, WhatsApp,
  WhatsApp Cloud, Signal), because `chat_type` alone defaults to `"dm"` and is
  `"dm"` on the handoff fallback, a relay's default and a Slack group DM. A
  proven 1:1 DM with the only user Hermes authorizes on the platform
  (`<PLATFORM>_ALLOWED_USERS`, `GATEWAY_ALLOWED_USERS` entries of that
  platform's id shape, and the pairing store, read and never written; an open,
  empty or unlistable set has no owner) is `owner_direct` and reads, writes and
  gets the pack extras like the CLI. Any other proven DM is `direct`: a
  principal derived from the platform and the partner's id (WhatsApp's
  shortest alias), v3 captures bound to it, recall of that person's records
  only, and `confirm`/`correct`/`retire` on them. A proven group, and every
  Discord conversation (the relay can label a Discord group DM `"dm"`, and
  nothing marks a relayed event), is `channel`: a new `channel` scope keyed by
  platform and `chat_id` (threads share it; Discord threads have their own id),
  captures and recall confined to it, no blocks, reminder, brief, digest or
  demote. Every turn is bound again: a bot author or an author other than the
  DM partner makes that turn shared, also across a session id rotated inside
  the turn, and the authorized set is re-read (by file stat) so pairing a
  second person ends the owner's DM at the next turn. Unverified conversations,
  Slack slash commands and uncovered platforms stay shared. Chat-built coding
  handoffs read the lens of the session the caller names -- the `omh_interact`
  tool's own `session_id`, or `HERMES_SESSION_ID` in a command Hermes started,
  never the process-wide variable in a gateway -- and pass
  `shared_surface=True` with that session's principal or channel scope, so a
  chat nothing verified no longer receives a repository's identity-unbound
  project records.
- **OMH memory is recalled on the TUI and Desktop, outside a repository, and
  never past Hermes' spill cap.** The memory provider treated every `platform`
  other than `cli` as a shared surface, and a shared surface denies every
  identity-unbound record, and Hermes never passes a principal, so a model
  capture was never recalled on the TUI or Desktop, wherever it was made.
  Provider `initialize` now gives each session one surface class from Hermes'
  own `platform` and `agent_context`, failing closed for anything unknown:
  `operator_console` (`cli`, `tui`, `desktop`, which reach the agent through an
  OS, dashboard or Desktop-token login that already grants full control),
  `shared` (every gateway, `api_server`, `webhook`, `relay`, `acp`, an empty or
  unknown platform) and `background` (a non-primary `agent_context` such as
  `cron`). A `shared_surface=True` kwarg only tightens. A console reads exactly
  as the CLI did; shared and background reads are unchanged. `omh_memory`
  `capture` and `demote` now read the session lens like the lifecycle actions:
  `shared_surface_writes_refused` on a shared surface, `writes_disabled` in a
  background run and `session_lens_unavailable` with no lens, each writing
  nothing and saying so; `blocks` and `read` run on a console only
  (`shared_surface_reads_refused`). Blocks, the reference index, the
  `omh reminder:` line and the consolidation brief (whose demote rows quote
  USER.md and MEMORY.md) are rendered on a console only, and only an attended
  console raises or retires a brief, moves the dreaming counters or records a
  session close, so a group chat's compaction no longer reaches the TUI as this
  conversation's. Kanban workers
  (`HERMES_KANBAN_TASK` / `HERMES_SESSION_SOURCE=kanban`) keep their records
  but get no reminder, brief or digest and record no session close. The session
  lens publishes `surface_class` and the writing provider's instance: a
  provider under another's live lens (Hermes' hygiene and `/compress` agents
  load as `cli` under a gateway session when `compression.checkpoint_required`
  is on) may only tighten it, keeps that tightening for the session id only,
  re-reads the lens before every render, withdraws only its own lens and may
  replace a tighter one left unrefreshed for 12 hours; a tightening shows in
  the receipt and in `omh memory status`. Lens files written before either
  field are still read. Outside a
  repository a console's allowlist is user-global plus the current thread, so a
  capture made there (user scope by default) is recalled there; no project
  record is admitted without a resolved project, a shared surface still reads
  nothing there; `omh memory recall`, `recall-incident` and an operator
  console's coding handoff follow the same rule, while a chat-sourced handoff
  is shared and reads no user-global record at all. It still carries the
  repository's identity-unbound project records, which the live shared pack
  does not admit; the shared lens itself for those handoffs waits for the
  messenger change. `omh coding delegate` is a console only from a terminal
  and never inside a gateway session (`HERMES_SESSION_PLATFORM`). A handoff
  whose records span user-global, a project and a thread declares the
  allowlist it selected them under (`scope_allowlist` on the recall pack and
  the role context pack), so it becomes a coding delegation instead of failing
  the role pack's one-scope check, which a repository store holding a project
  and a user-global record already hit on main. Both packs accept only an
  allowlist the selector could have built for the pack's scope (one scope per
  kind, user-global only as `user-global:default`, no project but the pack's
  own), and a record outside it still fails. The whole pack now fits 9,000
  characters, 1,000 under the 10,000 at which Hermes keeps only the first and
  last 500 characters of a prefetch (`tools/hook_output_spill.py`): the
  reference index stops at 600 characters with one `<omitted count>` line,
  system blocks take the rest up to their 6,000 cap with wrapper and omission
  lines counted, and when that is not enough lower-ranked blocks give down to a
  3,000 floor, then index lines, then the brief's demote rows. Records, the
  brief's `<do>` lines and closing tags are never cut, including by the brief's
  own cap; the reminder and digest are whole or absent. The receipt names only
  what the text carries and adds `pack_chars`. A `hooks.output_spill.max_chars`
  set below 9,000 brings the spill back. Gateway capture stays refused until
  per-person and per-channel messenger memory lands.
- **A code-changing goal cannot complete until an `ai-slop-cleaner` outcome
  is recorded for it.** A goal can carry a new required acceptance criterion,
  `AC-SLOP`, and `omh goal complete` refuses such a goal (exit 1) until a done
  checkpoint cites a cleaner run record as `run:<run_id>`. The completion
  gate reads that one record and accepts it only when it names
  `ai-slop-cleaner` as its skill, names this goal, has status `completed`,
  carries a typed `cleanup_outcome`, and has evidence the
  completion-integrity classifier accepts (an empty or `TBD` summary is
  refused). `passed`, `skipped`, and `reverted` each satisfy the criterion
  and are reported as recorded; a missing record, a record for another goal,
  a started, prepared, failed, blocked, cancelled, or unknown-status run, or
  a summary that only says "skipped" without the typed field does not. One
  accepted record satisfies the criterion for the whole goal; later loop
  cycles do not need a new one. The refused payload's
  `completion_gate.slop_cleanup_check` names the record and checkpoint
  commands, and `omh goal journey` lists the record as a
  `slop_cleanup_record` gate. `omh runtime record` gains `--goal <goal_id>`
  (an existing ledger) and `--cleanup-outcome passed|skipped|reverted`,
  stored as fields beside the run's status; run statuses are unchanged.
  The criterion is armed two ways and no others. Code arms it on a goal
  linked to a loop whose authority envelope allows `repo_edit`: at
  `omh loop start`, or on an `omh loop permit` that requests `repo_edit`.
  Arming is idempotent, so re-requesting `repo_edit` also repairs an arm
  that failed after the loop was written. A goal already terminal refuses
  that start or grant, and a coding-delegation merge goal is never armed.
  Declaration arms it with
  `omh goal create --obligation slop-cleanup`, which the ultrawork skill now
  names for a code-changing goal. The remaining gap: an ultrawork goal
  created without that flag, and a loop without `repo_edit` or without a
  linked goal, carry no obligation and are not gated. The `loop` and
  `ai-slop-cleaner` skill text now name the exact record and checkpoint
  commands, and loop's cleaner pass is no longer described as optional: when
  the linked goal carries `AC-SLOP`, a skip is recorded as an explicit
  `skipped` from a completed run. Arming appends a criterion to an
  existing ledger, so a goal that was ready before a `repo_edit` loop bound
  it is not ready afterwards. The citing checkpoint is an ordinary goal
  checkpoint, so like any other it counts as progress for the loop stop
  ladder's no-progress rung; the stop ladder itself is unchanged.

- **Recall ranks by query-term coverage, capture hints at similar records,
  and a declared subject keeps only the newest value.** Relevance used to count shared
  tokens, so every shared word weighed alike. A message sharing "the plan
  for" with an offsite note outranked the one record about the backup it
  asked about, and "deployment" never reached a record that said "deploys".
  - Relevance ranks first by query-term coverage: 2 per matched content
    term plus 1 per matched tag, the old scorer's shape, so one stray word,
    however rare, never outranks a topic word with its tag. Within equal
    coverage it ranks by term frequency and length (BM25F saturation, no
    idf): with idf, a stray word one record held outranked a topic word that
    several records shared at the same coverage. Records still tied go to
    recency and usage, as before. The fields are summary, tags (weight 2)
    and record type; the type counts only beside a summary or tag hit.
    Summary length is counted in whole multiples of the average.
  - Closed lists split the query into content words and listed words, while
    records keep every word:
    - English function words and chat fillers (how, who, the, remind, quick,
      question, ...);
    - Korean bare verb endings and colloquial fillers (어케, 혹시), and runs
      that start with an interrogative or with 알려/가르쳐 (언제쯤이야, 누가요,
      알려주세요);
    - Japanese and Chinese interrogatives and request fillers (どう, すれば,
      ですか, 教えて, 怎么, 请问, 一下, ...), cut out before bigrams.

    Listed words never make a record match or add coverage, but they order
    records of equal coverage ("is there a quick start?" serves the quick
    start guide above "Standups start at 9:30"). A listed word is content
    when the raw query writes it in capitals or capitalized mid-sentence
    ("WHO?", "ask Will"), and every listed word is content when no content
    word longer than two Latin letters is left ("what is it?", "where do
    thanks go?").
  - Light English suffix stemming is applied alike to the query and the
    records. A match made only by stemming counts as overlap only when some
    record in the selection also matches unstemmed; otherwise the pack falls
    back to the active tier with the stemmed match first.
  - A temporal query ranks relevance in quarter bands below the best score
    of its coverage, so recency orders comparable matches.
  - Term contributions are integer millionths, so scores do not depend on
    summation order or the host.
  - CJK runs and bigrams, accent folding, numbers and compounds are
    untouched. Pins, attention tiers, rank fusion and the tie-breaks are
    unchanged.
  - `omh_memory` capture and correct take an optional `subject` slug in the
    closed shape `[a-z0-9][a-z0-9-]{0,47}`, refused as `invalid_subject`
    otherwise. Recall treats the newest record per scope and subject as
    current, among every non-retired record the lens admits, so an older
    value never comes back when the newest expires or is archived. It names
    the others `superseded_by_subject` with `superseded_by`. The prefetch
    receipt lists those pairs under `selection.subject_superseded`, and recall
    packs, delegation handoffs and runtime records carry and validate both
    fields.
  - A capture that goes through can report `subject_held_by` and
    `similar_record_id` (with the held summary, at 60% token Jaccard). Both
    are read inside its own scope, principal and audience, and only over
    records the calling session's lens admits, so a shared surface never sees
    a record its lens refuses. `recalls_now` and the `next_action` sentence
    say which record recall actually serves, computed with the selector.
    Neither hint holds or refuses the capture, and neither claims the facts
    are the same.
  - `correct` with a summary another record in the same confinement already
    holds now supersedes the old record with that one (history,
    `superseded_by`, `replacement: already_held`, the correction's subject
    carried over). It does so only when that record recalls now and keeps
    the fact at least as long; otherwise it reports `already_remembered` with
    the reason.
  - A record carrying `subject` is skipped (reported unreadable) by OMH
    builds from before this change, until they update; nothing is rewritten.
  - A recall pack no longer carries the memory policy's `store_dir`. The
    attach scan read an absolute store path with two random directory names
    (a CI temp root, a session-id directory) as one credential split across
    path segments, so a legitimate pack could be refused at random when
    attached to a coding handoff.
  - The recall suite corpus (`omh-memory-retrieval-fixtures/v4`) adds
    inflection, tag-only, long-versus-short, Korean, Chinese, Japanese and
    mixed-language queries, common-word negative controls, subject
    supersession, and both reviews of #2091's probe stores verbatim. Cases
    whose answer is a known cost say so in their intent.

- **`ai-slop-cleaner` reaches OMC parity without a second keyword hook.** `AI
  slop`, `deslop review`, and the request-shaped `anti-slop pass`, `anti-slop
  review`, and `anti-slop sweep` reach the cleaner through the existing route
  hint: AI slop in a code directory and a no-edit deslop review dispatch it,
  and an anti-slop pass asks first, with the cleaner among the choices. `AI
  slop` is phrase evidence only beside something the cleaner can clean -- a
  path or file name, or a code, docs, or prose target such as a module, the
  README, or an essay; beside anything else ("clean up the ai slop in my
  inbox", "... in my photo library") it asks rather than dispatching the
  cleaner. The bare word `anti-slop` is not a trigger, because as an adjective
  it names a stance or a quality ("our anti-slop policy for pull requests",
  "the README is anti-slop now") as often as a request; those stay quiet, and
  so do bare imperatives such as "anti-slop the README", which ask as they did
  before. `anti`, `anti-slop`, `slop`, `pass`, `review`, and `sweep` are held
  back from trigger-token scoring (`slop` still counts as a description word,
  and the lexical shortlist still reads the trigger text). A question about
  the word, a subagent's quoted report, and a plain "review this PR" stay
  where they were. `frontend` gains `slop ui` and the appearance phrases
  "looks like ai slop", "look like ai slop", "feels like ai slop", and
  "screams ai slop", which are phrase evidence only beside a UI surface (such
  as a page, screen, site, form, dashboard, card, section, hero, component,
  button, nav, layout, or onboarding flow): "this settings page feels like AI
  slop" dispatches frontend, while "the song lyrics look like ai slop" or
  "this tweet screams ai slop" asks instead. On code and prose the cleaner
  therefore leads: "this README looks like ai slop" and "my essay looks like
  ai slop, make it better" ask first with the cleaner leading, "this module
  looks like ai slop, clean it up" dispatches it, and "this slack message
  feels like ai slop, polish it" asks without dispatching either skill. Where
  a UI word and a code unit (module, function, class, method, code) share a
  sentence ("the layout code looks like ai slop"), the cleaner earns up to two
  context words, so it leads instead of frontend dispatching. A no-edit review
  mode inspects a drafted cleanup against the six taxonomy categories and
  returns findings in the `code-review` shape, handing fixes to a separate
  writer pass. A new `references/ui-review-checklist.md` lists six UI review
  prompts as questions a stated rationale closes, and each run closes with an
  `omh runtime record --skill ai-slop-cleaner` row. `loop` may run an optional
  cleaner pass after the judge passes, scoped to the cycle's `changed_files`,
  re-verified afterwards, and reported as skipped or reverted rather than
  passed. Concepts adapt `Yeachan-Heo/oh-my-claudecode` (MIT), reconstructed
  in OMH wording.

- **Facts survive compaction, and a new session hears what memory did since
  your last session.** The compaction brief asked the model to extract durable
  material from messages that, by the time it was served, were gone. It now
  says the turns were replaced by a summary and points at the heading where
  Hermes' summary keeps the user's preferences, constraints and important
  decisions ("Constraints & Preferences"). It asks for one
  `omh_memory(action="capture")` call per fact that should hold in later
  sessions and was not already captured in this conversation (a held fact
  answers `already_remembered`). "Key Decisions" is left out because it holds
  task-scoped technical decisions. `on_pre_compress` still returns only the
  system blocks: Hermes hands that text to its summarizer as source material,
  not instructions, so OMH asks the summarizer for nothing, and it stays a
  best-effort (API v1) pre-compress provider. The first pack a prefetch serves
  in a session Hermes started (`initialize`, or its own `reset` switch for
  `/new` and `/reset`) may carry one bounded `<memory_digest>`: records
  remembered, Hermes entries copied intact and freed, records corrected and
  retired. Counts come from record fields and the write and retirement
  journals. The window runs from the later of the last recorded session close
  and the end of the last digest served (both kept in a new
  `memory/session_close.json`, both only moving forward), else the last served
  pack, at most seven days back. A close is written at `shutdown`,
  `on_session_end` (which Hermes also calls at every compression and gateway
  soft-evict) and Hermes' reset. The reported-through mark means rows a
  non-shared digest already reported never come back after a killed or
  overlapping session. That holds even for a session that serves after a
  later-started one, because the mark is read again at render time. A mark more
  than five minutes ahead of the clock is ignored. "Served" means returned to
  Hermes, which may drop or spill the pack, so a mark can cover a digest the
  model never saw. Only nonzero counts are named. A turn-lease reload, a compression, a gateway
  rebuild of the same conversation, and cron or subagent contexts get none. A
  close stamp or receipt that exists but cannot be read means no digest. A
  corrupt stamp or a store fault costs only the digest. On a shared surface
  (the TUI and gateways included) the digest counts only records the
  session's recall lens admits, omits copies, frees and retirements, and names
  no `since`. The digest carries no record text, never lights the recall line,
  and says `journal_at_cap` when the write journal has dropped lines. The
  native write journal also kept only its newest line: its retention filter
  matched the journal's own `content_digest` key and dropped every earlier line
  at each append, so a `removed_entry_demoted` line vanished at the next native
  write. That one key is now exempt (top level, exact spelling, 64 lowercase
  hex), so the journal keeps its newest lines up to its limit again.
  `omh quality-evidence memory` reports `journal_at_cap`, and its freed headline
  says earlier removes may be missing when the journal is at its cap.
  `hermes_epoch` now uses the digest's stamp parser, which treats a 400-digit
  number as no stamp instead of raising.

- **`omh quality-evidence memory` reports what OMH memory did on this
  machine.** The only memory quality surface was `omh memory recall-suite`,
  which runs synthetic fixtures, so nobody could say from real traffic whether
  memory was working. The new command counts, over a window (`--days`, default
  7, or `--since` with an ISO-8601 timestamp or epoch seconds, as in
  `session-usage`), `omh_memory` calls per action and result status and
  Hermes-native `memory` calls per action and outcome from `state.db`
  (read-only, Hermes' `tool_call` wrapper unwrapped), admitted OMH records per
  source and admission state (candidates awaiting review are not records), the
  last prefetch receipt, consolidation briefs per reason family, the native
  write journal's `removed_entry_demoted` counts, and Hermes memory headroom
  per file. A headline is computed from those counts: facts remembered, Hermes
  entries OMH stored a verified copy of (no removal implied), and native
  entries freed after a demotion. Each line names its window and the home its
  count came from. Counts come from structured fields only, never message text.
  A source it could not read exits 3 instead of reading as zero, including a
  directory it may not list (probed by listing it: `Path.exists` reads a
  refused directory as absent and `stat` succeeds on one) and a journal line or
  record file that does not parse.

- **Low-severity leftovers from the #2074–#2080 reviews are tidied.** The
  doctor's loader probe now takes its Hermes code root from the
  `HERMES_PYTHON` override's own tree when that tree holds `hermes_cli`, so
  the interpreter and the code tree it imports come from one install; an
  override tree without a checkout falls back to the home, as before. The
  resolver is renamed `resolve_hermes_code_root` so it no longer shares a
  name with the probe's parameter. `plan` and the `planning` harness now say a
  wrapper's acceptance counts only when it carries the user's answer, and
  `app-debugging` section 6 says the next fix may proceed while a pre-fix
  probe stays not observed, with the probe left open in the record and the
  fix under test counted as failed until the probe is observed, so the
  three-fix stop still fires. The shared plan-acceptance rule is a public name,
  the core-profile gate's history no longer quotes measured byte counts, and
  one fixture continuation line is aligned (#2081).

- **USER.md headroom now raises its own consolidation reason and demote
  rows.** The `headroom_below_floor` reason and the `<demote>` rows read
  MEMORY.md only, so a nearly full USER.md (1341 of 1375 characters on the
  owner machine) never prompted anything. Each Hermes memory file below the
  floor now raises a reason that names it (`headroom_below_floor:USER.md:34<=187`;
  MEMORY.md's string is unchanged at the default cap), so suppression compares each file's own
  string and the brief retires only once no file is below its floor. The brief
  offers up to three rows, largest first, across every file below the floor.
  The floor is proportional to each file's cap (300 at MEMORY.md's default
  2200, 187 at USER.md's 1375), so a small cap cannot be permanently due. A
  USER.md row adds a one-line instruction to keep entries about who the user is
  and how to address them, and `omh doctor` no longer describes a USER.md
  brief with MEMORY.md's numbers.

- **The model maintains OMH memory itself: `omh_memory` gains `recall`,
  `confirm`, `correct` and `retire`.** Capture was the model's only write;
  correcting, confirming, retiring and searching records were operator CLI
  verbs in a package the Hermes process cannot import. Each new action runs
  in-process in the plugin bundle under the lens the memory provider
  publishes for the session at `initialize` (homes, scope allowlist inputs,
  principal context, shared-surface verdict, write permission), read back by
  the tool call's `session_id` and moved when Hermes reassigns the id
  (`on_session_switch` on compression, `/new`, `/reset`, `/resume`, `/branch`;
  a rebind in `prefetch`, as a new conversation, for a turn-lease reload);
  with no lens the tool
  fails closed (shared surface, no writes, and `recall` says the lens is
  unavailable), and cron and subagent sessions are refused as
  `writes_disabled`. A record outside the lens is refused as
  `record_not_in_scope` with nothing written. `recall` is the prefetch
  selector, so it returns records in the order a prefetch serves them.
  `confirm` renews the review deadline the way `omh memory confirm` does and
  counts one use per record per session. `correct` links the corrected fact
  to the old record (`derived_from`, `correction_of`), and the approval that
  admits it -- auto-safe now or an operator's later -- moves the old revision
  to `history/` with `superseded_by` and flips its candidate to `superseded`,
  which approval refuses. `retire` archives with a journal line carrying a
  closed reason (`no_longer_true`, `superseded`, `user_asked`) and the
  session id, retires a live record only after the session was served or
  recalled it, and never deletes. In chat the ranking's usage weight was
  always zero, because only a handoff attachment counted; a prefetch that
  returns a pack now counts `served` in the record's own store, which the
  ranking never reads (it would feed itself), and a model `confirm` counts
  `used` in `usage.json`, which it does. `omh memory status` shows both under
  `recall_usage`. The plugin tool schema ratchet moves 63616 -> 64031.

- **Two Windows CI cleanup flakes are fixed in their fixtures, and a third
  now reports its cause.** Each change follows the traceback in the failed
  run's log, and none changes product behaviour. The observer fixture closes
  every observer with a 120-second margin before removing its directory: the
  room-capacity test closes with 64 live rooms, one locked receipt each, and
  on a Windows runner the 10-second host default did not drain and left the
  worker holding the lock file. The Job Object reaping test starts its leader
  outside the temp dir, whose removal failed on the directory itself after
  every assertion had passed. The release workflow fixture now reports bash's
  exit code and output when the `gh` stub never ran, instead of a bare
  missing `calls.jsonl`. The host unload budget is unchanged (#2069).

- **`omh doctor`'s real-loader probe carries the Hermes code tree.** The
  isolated probe behind `plugin_loader_observed` ran Hermes under a disposable
  `HERMES_HOME` with nothing pointing at the checkout, so Hermes resolved its
  own version as `unknown`, the plugin's `requires_hermes` gate failed closed,
  and a healthy install reported a registration warning that no remediation
  could clear. The doctor now passes the home's own `hermes-agent` checkout, or
  the Hermes root's for a profile home that has none, and the probe puts it on
  `PYTHONPATH`; `HERMES_HOME` stays disposable. A missing code tree
  reports `hermes_code_tree_absent` and a version the host still cannot
  resolve reports `hermes_version_unresolved`, both as not observed rather
  than as a mismatch (#2050).

- **`plan` takes plan acceptance only from the user's answer, as `ralplan`
  does.** Both planning skills now share one acceptance rule: acceptance
  comes from the response status and value the question tool returns, or the
  user's own reply, never from the wording of the question. An acceptance
  question that times out, is dismissed, or returns with no answer leaves the
  plan unaccepted, and is not read as a refusal either. The portable Agent
  Skills `omh-plan` carries the same rule (#2067).

- **`app-debugging` records a moved fault's hypothesis as unresolved.**
  Section 6 of `references/hypothesis-and-race-method.md` now eliminates a
  fix's hypothesis only when the original symptom is still there; when the
  fault moved, nothing contradicts the hypothesis, so it stays unresolved.
  The pre-fix probe for a symptom hidden behind the first runs with the
  section-1 loop when the symptom is intermittent, and a probe that cannot
  run on its own or comes back inconclusive is recorded as not observed and
  leaves the failed-fix count unchanged. A fix whose new symptom the pre-fix
  tree already shows is not counted as failed and is verified under section 7
  once the reproduction passes, instead of being said to hold; the new
  symptom gets its own reproduction record and count (#2057).

- **`loop`'s fence check reads untracked files the ignore rules hide.** Step 3
  of `references/loop-design-review.md` used only `git ls-files --others
  --exclude-standard`, which skips a file excluded through `.gitignore`,
  `.git/info/exclude`, or `core.excludesFile`, so a new test module under a
  fenced directory that patches shared code at import was neither listed nor
  read. The step now also runs `git ls-files --others -- <fenced dirs>`
  without `--exclude-standard`, and reads the files inside a nested repository
  that listing prints as a directory. A test's skip status now comes from the
  acceptance run's own output, compared against the tests the launch run
  skipped, rather than from a collection-only listing that runs nothing; the
  reference names the PowerShell equivalents of `test -e`, `find`, and the
  sha256 tools. Ignored build output under the fence is listed, and a compiled
  or generated file with no matching tracked source fails. The skill body is
  unchanged (#2058).

- **An emoji closer no longer lets a Korean request through memory admission.**
  `omh_memory(action="capture")` already refused a summary ending in a Korean
  request ending followed by closing punctuation or emoji; an emoji carrying a
  variation selector (`실행하세요 ❤️`, `실행하세요 ☺️`) or a keycap
  (`실행하세요 #️⃣`, `실행하세요 1️⃣`) was admitted because U+FE0E, U+FE0F and
  U+20E3 are combining marks. They now count as closers, and a keycap
  sequence is dropped whole; text after the emoji still admits the summary. A
  quoted UI label at the end of a summary (`버튼 라벨은 "저장하세요"`) is still
  refused, the same disclosed limit as other quoted requests. The `ulw-work`
  execution-rulings reference now falls back to `HEAD` when `git stash create`
  prints nothing, so the diff base is defined on a tree whose only changes are
  untracked files (#2068).

- **Tidy the #2049 chain's leftovers.** The model capture path passes
  `MODEL_CAPTURE_SOURCE` instead of repeating its value, so the source the
  admission screen keys on cannot drift from the one the tool sends.
  `ReferenceRegions.masked_spans` is marked diagnostic (only tests read it),
  the apostrophe set uses the `\u2019` escape the rest of the file uses, and
  `skill_record.py` imports in order. The per-file body-ceiling checks for
  `plan`, `ralplan`, `ultrawork`, and `deep-interview` are gone; one test now
  holds the ceiling for every shipped SKILL.md body, including the bespoke
  renders the structure-lint gate never measured:
  `ulw-work` shipped 27,583 bytes, 483 over, and now ships 26,646 because its
  tests-first section keeps the trigger, the iron law, and the pointer while
  the rest stays in `references/tdd-red-green.md`, which already carried all
  of it. The delegated-child route-hint tests move to their own file (#2070).
- **The model moves full Hermes memory into OMH itself.** A new
  `omh_memory(action="demote", entry_sha256=...)` reads one entry from
  Hermes' `MEMORY.md` or `USER.md`, captures it unchanged as a `user-global`
  durable OMH fact under the guards `omh memory demote --stage` holds
  (`redacted_cannot_demote`, `summary_bound_exceeded`, `content_not_intact`,
  `previously_rejected`), and returns `remove_from_hermes` for Hermes' own
  `memory` tool only when the copy is approved (`demoted`) or an approved,
  replay-eligible record already holds the exact entry (`already_covered`:
  its own demotion record, or a durable user-global record with exactly the
  same text). Token similarity never authorizes a removal. When
  MEMORY.md falls below the headroom floor the consolidation brief carries up
  to three `<demote>` rows, stored as file, sha256 prefix and length only and
  previewed from the live Hermes file at render time. Capture and demote
  results carry a suggested `display_line`. The operator path and its
  reference line are unchanged.
- **Hermes memory entries are parsed the way Hermes parses them.** OMH split
  `MEMORY.md`/`USER.md` on a bare `§`, so an entry containing one ("see § 4.2")
  became fragments and every character count missed two characters per
  entry. It now splits and counts on Hermes' full `\n§\n` delimiter (the
  promotion fit check and the eviction plan's shortfall and reclaimable
  figures included) and reads with `utf-8-sig`, so a byte-order mark no
  longer sticks to the first entry.

## 3.0.2 - 2026-10-11

- **`ulw-work` keeps reference-only detail in its references.** The
  per-turn body drops two quality-bar lines that restated
  `references/dependency-topology.md` (the node prompt contract and the
  verification fan-in) for one pointer to it, and the tests-first line now
  points at `references/tdd-red-green.md` instead of restating its contract;
  the external-owner line names `ulw-maestro`'s contract without listing its
  parts. `dependency-topology.md` gains the two clauses only the body carried:
  exact paths in `DELIVERABLE` and `SCOPE`, and a dependency edge never
  standing in for upstream output. The body measures 26,353 bytes against the
  unchanged 27,100-byte ceiling. A quality-bar line can now be declared
  Hermes-only by the reference it points at, and the Agent Skills projection
  drops it; `agent-debug`'s whole-list portable override is gone with no
  change to either projection. The delegated-child route-hint gate and the
  unscreened `hermes_demotion` capture source now say what they do in code and
  are pinned by tests (#2071).
- **`backend` names one authoritative contract per service boundary.**
  `references/service-contract.md` gains a section for boundaries that a
  caller outside the change reads: the prepared contract names the one file
  that defines the boundary, in whichever of OpenAPI, AsyncAPI, protobuf, or
  JSON Schema the repository already keeps, treats mocks and hand-written
  client types as copies of it, and grades a handler that disagrees as a
  contract change. Descriptions, examples,
  extensions, and comments inside a contract are data to validate, never
  instructions; `$ref` resolves only against the schema directories and
  origins the operator approved. Consumers are named first through the existing
  `references/consumer-impact.md`, and a boundary inside one module that
  changes in a single commit is left out. The skill body is unchanged. A new
  `docs/SKILL-SOURCES.md` row watches `affaan-m/everything-claude-code`
  (`skills/contract-first/SKILL.md`) for `backend` (#2049).
- **Memory the model captures cannot be written as an instruction.**
  `omh_memory(action="capture")` now refuses a summary phrased as an order to
  its reader: a second-person modal (`you must`, `you should`, `you need to`,
  `you have to`, `you ought to`) within one clause, or a sentence that closes
  on a Korean request ending (`해줘`, `해 주세요`, `하세요`, `해라`, `하십시오`),
  after NFKC normalization with zero-width characters removed. Fixed greetings
  (`안녕하세요`, `수고하세요`, `고생하세요`) are not requests, and a summary
  opening with `your` is not a cue. Nothing is written, and the result carries
  `reason: instruction_shaped_summary`, the matched cue, and a `next_action`
  that asks for the same fact restated as an observation; there is no review
  step. `procedure` records are exempt, and opening with an imperative verb is
  not a cue. Only the model capture source (`hermes_model`) is screened: L1
  demotion, episode rollup, design-direction promotion, the workflows adapter
  and the `omh memory capture` CLI store the same sentence as before. The rule
  follows an upstream harness's hint admission as a concept only (#2049).
- **`agent-debug` reads a past session as evidence under fixed rules.** A
  new Hermes-only `references/session-forensics.md`, named by one quality-bar
  line, writes the question down (session, turn range, expected, observed, the
  one observable) before the first read and never runs a query on a question
  filled in for the user; opens session stores read-only (`mode=ro`) and never
  changes a session file; bounds every read's length (`substr` in SQL, a
  per-line cap for records) and labels a capped count partial; treats hook
  output, system reminders, OMH context blocks, compaction summaries, and tool
  results as software-written, and a delegated child's user turns as the
  parent agent; reports only figures computed from the session, beside the
  query that produced them, with tool calls counted by distinct
  `tool_call_id`; and shares nothing until the user has reviewed the
  `agent-debug-export` package or approved the exact issue text. It names
  `omh quality-evidence agent-debug` and `session-usage` instead of restating
  them. The portable projection keeps its quality bar without the pointer. A
  new `docs/SKILL-SOURCES.md` row watches `obra/superpowers`
  (`skills/diagnosing-superpowers/SKILL.md`) for `agent-debug` (#2049).
- **`ralplan` counts acceptance only from the user's answer, and
  `deep-interview` keeps an idea's approval to the idea.** A new `ralplan`
  quality-bar line, shared by the Hermes and portable projections, takes plan
  acceptance from the answer the question tool returns or the user's own
  reply, never from how the question was worded; an acceptance question that
  times out, is dismissed, or gets no answer leaves the plan unaccepted, with
  no acceptance recorded, no handoff prepared, and nothing started, and that
  missing answer is not read as a refusal either. `deep-interview`'s interview
  protocol gains one sentence: agreeing to an idea consents to that idea only,
  and a plan, handoff, or code change written later is accepted at its own
  gate. The `ralplan` row for the Sustainable-Use upstream harness (concepts only)
  now lists the question-gate file studied, and a new `docs/SKILL-SOURCES.md`
  row watches `obra/superpowers` (`skills/brainstorming/SKILL.md`) for
  `deep-interview` (#2049).
- **`ulw-work` settles small mid-run questions itself and caps review
  rounds.** A new `references/execution-rulings.md`, named by one
  quality-bar line, lets the coordinator decide a reversible, in-scope detail
  the accepted plan leaves open (a name, an internal structure) and record it
  as one `Ruling: <decision> — <reason> — <cost if wrong>` line in the
  existing goal ledger, then keep working. Irreversible or destructive steps,
  security-sensitive steps, side effects outside the worktree the user has
  not already authorized, and a plan where every way forward is a guess stay
  decisions the user owns, alongside
  the follow-up authority rule and every other stop the skill already has. A
  change gets at most two re-reviews, each by a reviewer that has not seen it
  before; a lane never starts its own reviewer. Evidence is reused per check
  until a diff from the commit recorded with its capture reaches something it
  covers (`observed_tree` stays the identity stamp), with one full
  rerun against the final tree before the closing brief, and a defect outside
  the change's blast radius stays open as a tracked issue instead of passing
  a criterion. The existing `docs/SKILL-SOURCES.md` rows for `ultrawork`
  (`obra/superpowers` and the Sustainable-Use upstream harness, concepts only for
  the latter) now list the additional upstream files studied (#2049).
- **`ulw-work`'s TDD reference checks that a new test guards something before
  it counts.** `references/tdd-red-green.md` now asks four questions before a
  test is written (the behavior it protects, a plausible regression that turns
  it red, why the closest existing test misses that regression, and whether it
  needs a seam no production caller uses), lists shapes of tests that guard
  nothing (a no-assertion probe, a self-comparison, an expected value got by
  calling the code under test, a negative control rejected for an unrelated reason,
  a name that promises more than its inputs exercise), and requires a bug's
  regression test to fail on the code before the fix for that bug's own
  reason. The `ulw-work` body is unchanged; its existing pointer reaches the
  new sections. A new `docs/SKILL-SOURCES.md` row watches
  the Sustainable-Use upstream harness (its test-discipline rule, concepts
  only) for `ultrawork` (#2049).
- **`loop` reviews a loop's design before it launches.** A new
  `references/loop-design-review.md`, named by one quality-bar line, asks for
  a finish line a program can decide, written beside a fence of paths the loop
  may not edit (checked against the diff at judging time); a judge that is not
  the builder; prior human approval before a loop changes its own rules, kept
  separate from memory capture's `approved_auto_safe` admission; and a
  pre-launch check whose open items the model repairs itself where the skill
  allows, asking the user only for a choice that is theirs. The fence check
  is a numbered judging procedure: it diffs the working tree and untracked
  files against a recorded start SHA with renames split, so a moved or
  uncommitted edit to a fenced path still fails, and it checks what those
  listings cannot see directly - `test -e` for files fenced as absent
  (ignored ones included), launch-time sha256 for entries untracked at the
  start or outside the repository, and recorded commits for submodules. A
  retry cap counts failures of one item's acceptance check and then hands over
  to the existing exhaustion ladder, and with no second session to judge, the
  loop stops at its verification gate instead of grading itself. It starts
  after `loopability_assessment/v1` and leaves a scored loop's contract to
  `references/measured-loop-discipline.md`. A new `docs/SKILL-SOURCES.md` row
  watches `affaan-m/everything-claude-code` (`loop-design-check`) for `loop`
  (#2049).
- **`app-debugging` stops after three failed fixes and re-examines the
  architecture instead of trying a fourth.** Only an executed run of the same
  reproduction command counts; a planned run or a different command does not.
  On that run a fix failed when the original symptom persists, or when a new
  symptom appears that the fix caused. Before counting a new symptom, the skill
  checks the pre-fix tree for a fault the original one was hiding; such a fault
  is separate, with its own count, and the fix stands. After a first or second
  failed fix, the root cause is open again and the skill returns to its
  hypotheses. After the third, the skill prepares no fourth fix, names the
  assumptions every fix shared with the observation that would refute each,
  and ends the turn with the next step as a question the user owns. The rule
  is one quality-bar line in the body; the procedure is a new section of the existing
  `references/hypothesis-and-race-method.md`, and a new `docs/SKILL-SOURCES.md`
  row watches `obra/superpowers` (`systematic-debugging`) for `app-debugging`
  (#2049).
- **`plan` surfaces untested inputs before execution, and `ralplan` plans
  for the target state of whoever consumes the change.** When a plan describes
  code changes, `plan` now asks for a `Review Focus` section of at most 5
  requirement-implied inputs or failure modes that no planned test covers,
  each assigned to the owning task that will add its test, keeps each step to
  one action whose outcome can be checked, and runs a proportion check that
  catches implementation leaking into the plan; its completion checklist
  requires the section. `ralplan` names each consumer of the result, their
  current workflow, and the target state before comparing options, records a
  `Success criteria` table (`Criterion | Task | Verification scenario`) that
  extends the acceptance criteria to every target-state difference, and ends
  with a `Target-state coverage` check that turns an unmapped difference into
  a task unless the user excluded it (then it is a recorded non-goal) or it is
  blocked on missing evidence (then it stays an evidence gap). It never
  shrinks scope to an MVP or first phase the user did not request, and sizes
  each task as one `XS`-`XL` band. Both rules reach the portable
  `agent-skills/` projection, and new `docs/SKILL-SOURCES.md` rows watch
  `obra/superpowers` (`writing-plans`) for `plan` and, link-only,
  the Sustainable-Use upstream harness (`ulw-plan`) for `ralplan` (#2049).
- **A workflow name inside a block quote, a relayed line, or a link no longer
  starts that workflow, and a delegated child is not told to start an
  orchestrating engine its brief names.** `> $ulw-work fix the build`,
  `[REPORT] ...`, `planner -> reviewer: $ulw-plan ...` and
  `Reviewer (agent-7) to lead: ...` dispatched or named the quoted workflow,
  and a URL path such as `https://example.com/docs/ulw-plan` drew a route hint
  for it. The routing lexer now masks `>` block-quote lines (a `>` followed by
  a space or the line end, and not by a number; read as diagnostic context but
  never opening the text-transform fast path), relay header lines (a closed
  list of relay tags, and arrows or `(agent-N) to <role>:` senders between
  agent roles only, so `v1 -> v2:`, `Deploy (v2) to staging:` and a person's
  own `[summary]` keep routing) and scheme URLs (ending at a `$`, trailing
  punctuation or an unbalanced bracket; an apostrophe inside the link stays in
  it). A masked link still counts as the request's concrete target. An
  invocation on another line, beside the link, or after a leading link still
  dispatches. A session registered by `subagent_start` no longer receives
  route hint lines or context cards for the orchestrating engines (`ultrawork`,
  `ralplan`, `loop`, `maestro` and the retired engines that fold into
  `ultrawork`); task engines such as `research` and `ultraqa` and every other
  hint are unchanged (#2049).
- **The upstream tracker now watches the superpowers and Sustainable-Use harness
  material shipped skills already adapt.** Five skill credits had no row in
  `docs/SKILL-SOURCES.md`, so upstream could change what OMH adapted and no
  issue would be raised. The `ultrawork` TDD reference and the `code-review`
  dispatch and response references now have `obra/superpowers` rows, and
  `frontend`, `visual-qa`, and `design-quality-gate` have link-only
  rows for the Sustainable-Use upstream harness (Sustainable Use License 1.0, concepts
  only). Each row opens with a null-prior closure receipt. The nine skills
  that credit ECC were compared against ECC and share a posture rather than
  its structure, so they get no row; a note under the table records that and
  the code-level pi-family runtime borrowings. `tests/test_skill_source_attribution_coverage.py`
  fails when a shipped skill credits one of these upstreams with neither a row
  nor a listed reason (#2049).
- **Concurrent TUIs share one fanout scan, and an idle widget polls less.**
  Each open TUI's status widget spawned a fresh reader every 2s, and each
  reader rescanned every fanout record under `coding/fanout` -- the same,
  session-independent answer computed once per TUI per poll -- so reader CPU
  grew with the number of TUIs (#2030). The fanout record is now stored for
  at most 3s under `<omh_home>/runtime/hud-fanout-cache.json` and reused only
  while its key still matches the home, the reader's code, and the lstat of
  every file the scan reads, so a status change is seen on the next poll;
  any cache fault scans directly. The executor-progress projection, whose
  active/stale/expired state is computed at read time, is not cached; it now
  opens event and report logs only for the bindings it keeps. The widget
  doubles its poll interval, up to 8s, while a poll repaints nothing, and
  returns to 2s on any repaint.
- **Spelled-out and vague relative time now routes a memory capture to
  review.** The capture-time relative-time lint caught "3 days ago" and
  "il y a 3 jours" but not "two weeks ago", "a few days ago", "in two
  weeks", "last Monday", "il y a une semaine", "dans quelques jours" or
  "lundi dernier", so the forms people write most often auto-approved under
  auto-safe and aged into a lie (#2048). The quantity slot now takes `one` to
  `ten`, `a few`, `several` and `a couple of` (French `un`/`une` to `dix`,
  `quelques`, `plusieurs`), and a weekday bound to `last`/`next` (French
  `dernier`/`prochain` after it) counts, and so do `recently`/`récemment`
  except as a sort order ("least recently used", "le plus récemment
  modifié"). The anchor stays mandatory, a recurring rule ("the last Friday
  of each month", "le dernier vendredi du mois") stays untouched, and
  `in a`/`in one <unit>` is read as a duration ("built in a day"), so only
  a number or a vague quantifier after `in` counts.
- **A default-store install names `~/.omh` for the plugin, so multiplexed
  processes load it.** Setup and update recorded
  `plugins.entries.omh.settings.omh_home` only when the store was not
  `~/.omh`. A single-profile process reaches `~/.omh` with nothing named, but
  a multiplexed one (a gateway serving several profiles, Desktop `serve`)
  refuses a profile that names no store, so on a Hermes home with several
  profiles the plugin failed to load in every one of them with
  `OMH home is not configured for this profile`, while `omh doctor` passed
  (#2037). Setup and update now record the setting for the default store
  too, in the primary home and in each bot profile that names no store of
  its own; `omh update` backfills an existing install. The plugin's
  resolver is unchanged: a profile that names no store, such as a bot
  created after the last update, is still refused rather than handed
  `~/.omh`. `omh doctor` now warns under `plugin_omh_home_binding` and
  `plugin_omh_home_binding:<profile>` when a home names no store and would
  be refused that way. Behaviour change: as with any other store, the
  recorded setting outranks an `OMH_HOME` exported to Hermes.
- **Past-relative phrases now route a memory capture to review.** The
  capture-time relative-time lint flagged "in 3 weeks" and "yesterday" but not
  "we migrated 3 days ago", "last week", "the other day", "il y a 3 jours" or
  "la semaine dernière", which carry the same hidden anchor (#2031). Each form
  needs a number plus a unit or a "last"/"dernier" bound to a time noun, so
  "the last step" and "le dernier commit" stay auto-approved; French "hier"
  stays out because of German "hier".

- **A preflight the fenced tree failed no longer passes as a host failure.**
  The fence preflight starts `/usr/bin/true` with the unit worktree as its
  working directory, so a unit still running in its own fence could make its
  root unenterable for just that call, and the failure was classified as the
  host's: `--allow-unconfined` then let dispatcher git run unfenced (#2042).
  A failed preflight is now repeated once entering `/` instead of the tree;
  when that passes, the receipt reads `sandbox_preflight_failed_in_tree`, a
  reason the fenced tree caused, and the opt-in is refused. The test that
  every unenforced reason is classified now derives every reason code the
  fence builders can reach rather than two functions' prefixed literals, and
  classifies `worktree_missing` as well.
- **The workspace preflight writes nothing into the unit's git directory.**
  The index-write check wrote its scratch blob, from the dispatcher process,
  into the directory `git rev-parse --absolute-git-dir` named, and on a reused
  worktree the unit can rewrite its `.git` file to name any host directory
  (#2040). The blob now reaches `git hash-object -w --stdin` on stdin, so the
  only writes there are git's own, through the runner that is the unit's
  fence on a reused worktree; a git directory redirected outside the fence's
  write roots fails the check as `git_index_write` instead of being written
  to.
- **Fenced dispatcher git gets no credentials and no network.** Git the
  dispatcher ran in a unit worktree inside a fence (the unit's own since
  #1995, the narrow one #2034 added for `fanout status`, the claim and reuse
  probes and `--diagnostics`) still ran with the operator's whole environment
  and the network allowed, so a `core.fsmonitor`, filter or hook the unit
  planted could read a token the unit itself was denied and send it out
  (#2035). Those calls now run with the network denied and an environment of
  `PATH`, `HOME`, `XDG_CONFIG_HOME`, the locale, the fence's `TMPDIR` and
  `GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, `GIT_NO_LAZY_FETCH=1`;
  every other `GIT_*` is dropped. An unfenced run under `--allow-unconfined`
  gets the same environment with the operator's own
  temporary directory (and, on Windows, the system and profile variables git
  needs to start); it has no fence to deny the network with. Checks run for
  the unit keep the unit's network and environment.
- **Diagnostics analyzers run fenced to their snapshot.** `--diagnostics`
  ran pyright, basedpyright and ruff on the host, with the operator's write
  access and network, against a snapshot of a tree the unit committed, and
  pyright/basedpyright read their configuration from that tree (#2036). Each
  analyzer now runs inside a fence whose only write root is the private
  snapshot directory, with network denied and its temporary directory inside
  the snapshot, and relative or empty `PATH` entries are dropped from its
  environment. A host that cannot prove the fence reports the provider as
  crashed unless the operator passed `--allow-unconfined`, as the
  diagnostics git calls already do. That opt-in now means only "this host
  cannot fence": a fence the fenced tree itself made unprovable (a committed
  `.omh` file, a failed write probe) is refused even with it, for the
  analyzer, the dispatcher's git and the unit fence alike, and every reason a
  fence can go unenforced is classified in one table. Measured on macOS with
  basedpyright 1.39.10 (pyright 1.1.412): a planted `venvPath`/`venv`
  interpreter is never executed, and the PATH interpreter pyright runs drops
  the working directory from `sys.path` before importing anything; a test
  pins both where an analyzer is installed.
- **File activity fails closed on symlink escapes.** `omh quality-evidence
  file-activity` judged workspace containment by a path's spelling only, so a
  symlink inside the workspace that points outside it, such as `linked/notes.md`
  with `linked` leading elsewhere, was listed under its in-workspace spelling
  (#1813). The path's links are now resolved when the query runs, reading link
  metadata only and never a named file, and a path they lead outside the
  workspace is left out and counted under the new `symlink_escape` reason. A
  link that stays inside the workspace keeps its declared spelling, and a
  workspace reached through a link of its own still lists its files.
- **Fanout dispatch no longer exits 0 over a pre-spawn refusal.** A live
  unit refused with `environment_not_ready` (a required child or verification
  capability missing or denied), `executor_not_ready`, or `worktree_failed`
  never spawned, yet carried no failure signal, so `omh coding fanout
  dispatch` and `omh coding run` reported the batch as a success (#2029). The
  refusals now carry a `failure_kind` from the existing closed set
  (`workspace_blocked` for the environment and worktree refusals,
  `binary_missing` for an absent owner CLI, `crash` for any other readiness
  verdict, whose repair card still names the real prerequisite), so the batch
  exits 1. A dry run keeps its exit code. The truthfulness gate now builds
  each refusal from the dispatcher and fails if one maps to 0.
- **Host git no longer runs a unit's planted git configuration.** A unit can
  write its gitdir's `commondir`, and with it the `config` git reads in its
  worktree, so a `core.fsmonitor`, `core.hooksPath` or filter driver it
  planted ran with the operator's write access whenever the dispatcher's own
  git touched that worktree outside the unit's fence (#1999). Measured on
  macOS: a repair attempt's workspace preflight, `fanout status`, and
  `--diagnostics` (`git worktree add` ran the unit's post-checkout hook and
  smudge filter) all fired it. These now run inside a fence whose only write
  root is the worktree: the reused worktree's preflight inside the unit's own
  fence, the claim and capacity-reuse probes and `fanout status` inside a
  narrow one, and diagnostics through a fenced `git archive` the dispatcher
  extracts itself. Where no fence can be proven they do not run unless
  `--allow-unconfined` is passed: `fanout status` gains that flag and
  otherwise reports the resume as `workspace_unfenced`; wrapper status
  surfaces take no opt-in.
- **Memory reads French.** Recall tokenization treated every accented Latin
  letter as a separator, so `déploiement` indexed as `ploiement` and
  `préférence` as `pr` + `rence`; a query typed without accents never
  overlapped, and the `pr` fragment matched unrelated records about PRs
  (#2027). Accented Latin words now index whole, plus an accent-folded form,
  so `deploiement` and `déploiement` find the same record. Cyrillic, Greek and
  other alphabets are unchanged and keep the no-indexable-tokens fallback.
  The admission gates gained French cues for the same categories: prompt
  injection and temporary progress (matched with accents and case folded
  away, each needing two or more words so ordinary narration stays safe), and
  relative-time phrases such as `dans 3 semaines`, `la semaine prochaine`,
  `demain`, and `d'ici vendredi`. Safe French content still auto-approves.
- **Codex starts inside the macOS fanout fence.** Codex CLI reads
  administrator-managed configuration through CFPreferences and stops at
  startup with `Failed to synchronize managed preferences (code -32600)`
  when `CFPreferencesAppSynchronize` returns false (#1996). The Seatbelt
  profile denied every route to the preferences daemon, so the call failed
  inside the fence and succeeded outside it. The fence now allows the two
  `cfprefsd` mach-lookup services and read-only access to its
  `apple.cfprefs.` shared memory; measured on macOS 26.6, all three are
  needed. Preference writes stay refused: the daemon rejects them from a
  client without `user-preference-write`, and a fenced
  `CFPreferencesSetAppValue` or `defaults write` leaves no domain behind.
  No file-write allowance changed. The dispatch diagnostic also retains this
  startup error as a fixed sanitized line, where it used to withhold the
  whole stream as `unknown_output`.
- **Model setup binds aliases on a Hermes custom-provider machine.**
  `hermes auth list` heads a `custom_providers:` entry's pool as
  `custom:<name> (N credentials):`, and the auth parser read only colon-free
  ids, so the gateway's credentials were never observed and every alias
  target was refused as lacking provider auth (#1998). The parser now reads
  that one composed form, and a pool whose `<name>` is still configured
  authorizes both `<name>/<model>` — the spelling Hermes resolves to that
  endpoint — and `custom:<name>/<model>`; a pool left behind by a removed
  entry authorizes neither. A bare `custom/<model>` target, which Hermes
  routes through `model.base_url` rather than a named provider, is refused
  with that reason instead of a missing-auth one, and the provider next
  action asks for the configured name instead of `hermes auth login custom`.
- **Fanout no longer runs a unit unfenced without being told to.** When
  `prepare_fanout_filesystem_confinement` could not prove a write fence (no
  backend on the platform, no trusted bwrap, a failed preflight or probe), the
  receipt said `enforced: false` and nothing read it: `omh coding fanout
  dispatch` and `omh coding run` spawned the owner CLI, and its verification
  commands, with the operator's full write access (#1982). Such a unit is now
  refused before it spawns as `worktree_failed` with `reason_code:
  filesystem_confinement_unavailable` and `failure_kind: workspace_blocked`,
  so the dispatch exits 1; its checks, reproduction command and integration
  checks are failed checks that did not run. `--allow-unconfined` on either
  command runs them unfenced on purpose, records `unconfined_opt_in: true` in
  the receipt, and lists the unit under the summary's new `unconfined_units`.
  This changes Windows, which has no fence (#1357): a Windows dispatch now
  needs `--allow-unconfined`, as does a Linux host without a trusted bwrap.
- **`omh_agent_board` keeps reaching its core after Hermes drops the
  bundle's modules.** Hermes evicts `hermes_plugins.<slug>` and every
  submodule from `sys.modules` on a reload or a failed load while the
  handlers and hooks it registered stay callable. The board tool imported
  its bridge relative to its package on each call, so in that state it
  answered `omh_agent_board_core_unavailable` on a host whose `omh` package
  imported fine, while the tools that bind their siblings at import kept
  working (#1979). The tool and the tool-call hooks now bind the bridge when
  Hermes imports them. An unavailable board also carries a `detail` naming
  the import that failed — the bundle bridge, an incomplete bridge stub, or
  the engine module — where one reason used to cover all three. The same
  call-time imports are gone from the rest of the bundle: `omh_team` (which
  raised `ModuleNotFoundError` in that state, and now names an unimportable
  sibling in `detail`), the `omh_jev_ask` availability check, and the
  memory-governance, engagement-nudge, egress, browser and team-observer
  helpers its callbacks reach. A gate in
  `tests/test_plugin_bundle_standalone.py` reads every function body in the
  bundle and fails on a relative sibling import made at call time.

## 3.0.1 - 2026-10-07

- **The handoff context pack treats project scopes the way it treats thread
  scopes.** `omh memory pack --scope-kind project --scope-ref <identity>`
  for the resolved identity is now the default project pack under its own
  name: no scope filter applies, so the setup, runtime-state, catalog-hint,
  wrapper-session and target snapshots it used to drop are present and the
  conflicts between them are detected the same way; a pack for another
  identity still carries only the records captured under it. A record under
  another project scope — including the unbound `project/default` label
  once the home's identity has resolved — is listed under `excluded_context`
  as `scope_mismatch`, where it used to be skipped without a trace, matching
  how another session's thread record has been listed since #2016.
- **Every shipped skill installs under the Hermes install scanner.**
  `hermes skills install rlaope/oh-my-hermes/skills/omh-routing` was refused
  with `Verdict: DANGEROUS` (#2014): `tools/skills_guard.py` scores a
  sentence by regex, and five sentences in generated skill bodies matched a
  critical or high rule by wording alone — "util-linux's setgid tool",
  "`<dispatch cwd>/.claude/settings.local.json`" (the `>` reads as a shell
  redirect into another agent's settings), "do not tell the user", a
  cryptocurrency name in a routing trigger, and a literal `sudo` in a
  refusal list. Seven directories under `skills/` and one under `agent-skills/`
  scanned `dangerous`. The producers are reworded (never
  the generated files), the routing-signal line skips a trigger that spells
  a scanner-excluded term while the trigger keeps routing
  (`HERMES_SCANNER_EXCLUDED_TERMS` in `catalog_types` is the one list; the
  shortlist sidecar from #2000 reads it too), and
  `tests/test_hermes_install_scan.py` runs the scanner itself — vendored
  verbatim in `tests/_vendor/hermes_skills_guard.py` — over every directory
  under `skills/` and `agent-skills/`, so a wording that trips a critical or
  high rule fails CI before a user hits it.
- **`omh memory pack` scopes reviewed records the way recall does.** The
  reviewed-records snapshot is labelled `project/default` while each record
  carries the scope it was captured under, and the pack's scope filter
  matched labels only — so `--scope-kind thread --scope-ref <session>` and
  `--scope-kind project --scope-ref <identity>` both returned an empty pack,
  while the default project pack carried every session's thread records.
  Records are now matched on their own scope when the label does not match,
  and a thread record travels only with its own `--session-id`; another
  session's thread record is listed in `excluded_context` as
  `scope_mismatch`, the recall pack's reason, instead of being included.
  Snapshots whose items carry no scope (setup, runtime state) still match by
  label. `omh memory inspect --scope-kind … --scope-ref …` reads the same
  filter and now returns the matching records too, inside the
  `project/default`-labelled snapshot.
- **The bundle's store lock retries Windows permission denials.** Windows
  refuses `chmod`, `touch` and `replace` while another process transiently
  holds the file open (WinError 5/32); the control plane's `local_store` and
  the bundle's `memory_store_io` already retried with a jittered backoff,
  but `_awareness_delivery_lock` — the lock every bundle store and, since
  #2012, the memory admission path take — and the delivery ledger's write did
  not. The ledger's `replace` under a concurrent reader is the denial Windows
  produces; the lock's `chmod`/`touch` are wrapped with it so no call on the
  store path is left unguarded (preventive, not observed). All of them now
  go through the same backoff, which has one definition in
  `awareness_delivery.py`; `memory_store_io` and `omh.system.local_store`
  import it instead of carrying copies. POSIX behaviour is unchanged (the
  helper re-raises there).
- **Importing a router module no longer loads the skill renderer.**
  `omh.skills/__init__` imported `packaging` and `render` eagerly, so
  importing any submodule — `routing.intent` imports the dataclass-only
  `skills.catalog_types` — ran the whole render path and, through it, the
  plugin bundle's `awareness`, which imports `routing.intent` back. That
  cycle is what #2013 taught `awareness` to survive; this removes it at the
  root. The seven render-side names (`builtin_skill_templates`,
  `builtin_skill_reference_templates`, `SkillTemplate`,
  `SkillReferenceTemplate`, `router_skill`, `workflow_reference_payload`,
  `workflow_skill`) resolve on first attribute access (PEP 562); every
  `from omh.skills import …` keeps working, `__all__` is unchanged, and the
  catalog names stay eager. `import omh.routing.intent` now loads neither
  `render` nor `awareness`, and importing any `src/` module first no longer
  drops `awareness` into its standalone branch; a fresh-interpreter test
  keeps both properties.
- **The executor-name and coding-delivery phrase groups are defined once.**
  `src/plugin_bundle/omh/executor_cues.py` owns
  `SUBSTRING_NAMED_CODING_AGENT_PHRASES`, `PI_FAMILY_CODING_AGENT_PHRASES`,
  `NAMED_CODING_AGENT_PHRASES`, `CODING_DELIVERY_REQUEST_PHRASES` and
  `CODING_DELIVERY_REQUEST_TOKENS` with their reasoning comments;
  `omh.routing.executor_cues` re-exports them and awareness imports them
  unconditionally. The vendored `ImportError` mirror that the live plugin
  always ran is gone; the parity test is now an identity test plus the
  documented members and absences. Routing is unchanged (428/627).
- **The awareness hint asks the router for its guards per call.** The plugin
  bundle's `awareness.py` bound the router's jit-learn guard, long-document
  guard and the two intent classifiers at import time behind the
  standalone-host `except ImportError`. `routing.policy` imports
  `routing.intent`, which reaches `awareness` through `skills.catalog_types`
  → `skills` → `skills.render`, so any process whose first router import was
  `policy` or `intent` ran those imports against a half-initialised module,
  caught the ImportError as "no router", and kept the bundle's copies for
  the rest of the process — `/loop …` then ranked `workflow-learning` above
  `ulw-loop`. Dozens of control-plane modules produce that process when they
  are the first import; the Windows CI shard that ran `test_candidate_handoff`
  before `test_degradation_signal` was one. The four bindings now resolve
  through `_router_policy_module()` / `_router_intent_module()` on each call,
  as `_user_trigger_pack_route_decision` already did; a host where no router
  module imported at load keeps its standalone copies. A fresh-interpreter
  test pins the `policy`-first order.
- **One memory admission path, called in-process by the tool.** Capture, the
  confinement-scoped duplicate check, the candidate write, auto-safe approval
  and the durability receipt move from `src/workflows/memory.py` into the
  plugin bundle (`memory_admission`, with the store files in
  `memory_store_io`); the control plane keeps every public name as an adapter.
  `omh_memory(action="capture")` calls admission directly instead of locating
  and spawning the installed `omh` console script, so a Hermes session whose
  `omh` is missing, older, or off `PATH` can still remember.
  `omh_cli_unavailable` leaves the tool's status set and a store fault is
  `error` naming the exception class. A before/after run of capture → review →
  approve → status → recall produced identical JSON and store files (modulo
  ids and timestamps). CONTEXT.md gains **Memory admission**. The v1
  scope-snapshot store turned out to have no write path left: its seven
  unreachable update helpers are deleted, inspect / pack / handoff context
  packs were already a read-only projection of reviewed records and
  batch-applied scope items (output unchanged), and INSTALLATION.md no longer
  claims `omh memory apply` previews or writes.

- **Portable overrides live on the skill they replace.** The first table
  moved behind the `SkillRecord` facade: `SkillDefinition` gains
  `portable_overrides` (section → replacement lines), replacing the
  display-name-keyed `PORTABLE_OVERRIDES` table in `catalog_portable.py`, and
  `portable_override_shadows` (section → sha256 of the catalog section the
  override replaces), replacing `tests/fixtures/portable_override_source_digests.json`.
  The #1786 gate — a line added upstream to a shadowed section never reaching
  the portable body — now fails beside the data it protects, naming
  `<skill>::<section>` and printing the digest to paste; a shape test fails
  when an override key is not a definition field or a replacement line is
  missing from the rendered portable body. No generated byte changed.
- **Per-turn text budgets live beside the text they bound.** The primer,
  primer-markdown, workflow-context, role-context and both `pre_llm_call`
  limits — with their full `A -> B: reason` histories — moved from
  `src/maintenance/release.py` to `src/plugin_bundle/omh/turn_budget.py`,
  which also gives the hooks a `render("primer")` seam; `release.py`
  re-exports the names and keeps a pointer where each block was.
  `per_turn_context.budget_report()` / `headroom(slot)` report limit, live
  size, headroom and kind per slot, and the ledger measures the primer
  through the same `render()` the hooks call. No limit value or rendered
  byte changed.
- **The route's prepared query reaches the explicit-invocation checks.**
  `policy.explicit_skill_invocation` and `jev_addressing.jev_addressed_skill`
  accept the chat path's `RoutingQuery` and use it only when its raw text is
  exactly what they would have scored, so a Jev-addressed message prepares its
  text once instead of six times and the bare-first-word check once instead of
  twice; prep-chain runs over the 1,051-message routing corpus fall from 1,365
  to 1,315 with every verdict byte-identical. `tests/test_efficiency.py` reads
  the awareness, capability and body-total limits from the drift ledger
  instead of importing `release.py` constants.

- **One record per skill.** `src/skills/skill_record.py` assembles each
  skill's definition, exposure, harness, portability class and overrides,
  effective routing policy (with the table it came from), next-action label,
  and body/reference renderers into one `SkillRecord`, and
  `project(skill, target)` returns that skill's slice of the managed skill
  tree, the Agent Skills projection, `docs/WORKFLOWS.md`, `docs/ROLES.md`,
  the shortlist sidecar and the capability-family sidecar. `packaging.py`
  reads bodies and references through it — its 13-name if-chain and the
  hand-listed reference producers are data on the record — and every
  generator shares its per-skill unit with `project()`. The record moves no
  data and derives no boundary field from another (the policy boundary, the
  harness guard, the safety rules and the portable override are four
  different fields); every generated artifact and both digest fixtures are
  byte-identical, routing is unchanged at 428/627. CLAUDE.md names the
  record as the source for the skill rows and CONTEXT.md gains **Skill
  record**; data migration per skill follows behind this interface.

- **The live plugin no longer reads `claude-code.md` as a mention of Claude
  Code.** The bundle's awareness route hints carried a vendored copy of
  `contains_boundary_phrase` for standalone hosts, and that copy lacked the
  rule the control plane had gained: punctuation that runs straight into more
  letters or digits (`claude-code.md`, `codex-utils.py`, `claudecode-notes`)
  is a file or hyphenated word, not a mention. Since Hermes loads the bundle
  without the `omh` package, the live plugin always ran the old copy. The
  matcher now lives once in the bundle (`boundary_phrase.py`); the control
  plane imports it from there, and the copy is gone.

- **The router reads one prepared query.** `RoutingQuery`
  (`src/routing/query.py`) holds one message's routing stages — executable,
  scrubbed, routing text, normalized phrase, tokens — built once, with the
  two withheld-skill predicates as methods. `recommend_skills` accepts a
  string or a `RoutingQuery` (the cache stays keyed on the string, a hit
  builds nothing, a miss reuses a passed query), and the router helpers that
  used to spell the four-step prep chain by hand take the value instead. The
  chat path builds the query once per message and threads it through the
  operator fast paths, and the lexical shortlist builds one query instead of
  one per shortlisted skill; prep-chain runs over the routing corpora fall
  from 1,815 to 1,365. Every verdict is unchanged:
  428/428 negative-control and 627/627 interventions, byte-identical.
  `omh recommend`, the `omh_recommend` plugin tool and the MCP bridge now also
  return `route` (`action`, `selected_skill`, `candidate_skill`, `confidence`),
  the chat dispatch decision for the same message; existing keys are
  unchanged and `omh_recommend_result/v1` is not bumped. CONTEXT.md gains
  **Routing query**.
- **One budget ledger.** `src/maintenance/drift.py` is now the only place a
  per-turn or install-footprint budget is compared. `skill_content_smoke`
  used to re-compare eight limits privately — the awareness primer and
  workflow contexts, the role contexts, the capability items — so `omh release
  drift` never reported them; it now reads `drift_report()` for them and
  `omh release drift` lists 30 checks instead of 25 (no limit value changed).
  Each budget carries a kind (`ratchet` | `ceiling`); `derive_ceiling()` is
  the headroom rule as code, replacing the two copies tests kept, and
  `limits()`, `measure()` and `verdict` expose the ledger. The routing-corpus
  totals keep reviewed pins in two places only — the `expected=` values in
  `drift.py` with their reason histories and the two literals at the top of
  `tests/test_routing_precision.py`; `tests/test_cli.py`,
  `tests/test_release_smoke.py` and `tests/test_hermes_ux_quality.py` now
  compare their payloads and `NNN/NNN` strings against
  `build_routing_precision_demo()`, so a new case costs two edits where it
  cost about thirty. CLAUDE.md and CONTEXT.md (**Budget ledger**) describe
  the new shape.
- **The run-record format has one owner.**
  `src/plugin_bundle/omh/run_records.py` defines every run, dispatch and
  receipt file name, every schema version, and the shared progress, profile,
  binding-state, observed-result, receipt-claim and dispatch-status
  vocabularies. The plugin bundle's readers and the control-plane writers
  both import them; until now the bundle, which cannot import `omh.*`, kept
  hand copies (13 constant sets, 12 schema literals in three files each) and
  five parity tests caught drift after it happened — two copies had already
  drifted and six had no test. The parity tests are replaced by
  `tests/test_run_record_format_policy.py`, which fails on any second
  spelling of an owned literal under `src/` and names the constant to
  import. No on-disk format, value or verdict changes; CONTEXT.md gains
  **Run record**.

- **A local-source skill import no longer swallows a nested checkout or
  OMH's own install output.** `omh install --source local` discovers
  `SKILL.md` under the whole source root; a linked worktree left under it
  (its root carries a `.git` FILE, which the `".git" in parts` test never
  saw), a submodule or a clone contributed another revision of the same
  skills, and the project `.omh/skills/` tree — the managed install OUTPUT
  in another layout — did too. Two templates then claimed one install path
  and the second write refused as "local skill differs". Discovery now stops
  at any nested repository root and skips `.omh`; the same source installs
  twice as a no-op. Capture of one fact from two parallel tool calls now
  persists one record: the duplicate check, candidate write and auto-safe
  approval run under a capture lock (without it, 8 of 8 concurrent captures
  persisted). The legacy expiry reader lists with `os.scandir` like the v2
  reader, the open-reminders ledger writes through the shared atomic writer,
  and capture imports the duplicate-summary normalizer from the bundle
  instead of keeping a pinned copy.

- **The memory provider serves its pack in the order Hermes calls its
  hooks.** Hermes runs `on_turn_start` and then `prefetch` inside the same
  turn, and queues the next render only after the turn ends. Since 2026-09-12
  (`2ab7da2ef`) `on_turn_start` blanked the pack to isolate the previous
  principal's lens, so every live `prefetch` returned an empty string: no
  record, no `<memory_consolidation>` brief, no recall line, no prefetch
  receipt — on the owner machine 32 due briefs accumulated with zero
  consolidations observed. The suite stayed green because every provider
  test inserted `queue_prefetch` between the two hooks, an order the host
  never uses. `on_turn_start` now re-renders the pack under the arriving
  turn's principal and for the arriving message (the previous turn's text
  used to be the recall query), and a `prefetch` whose query or principal
  differs from the render re-renders instead of blanking.
  `tests/test_memory_provider_hermes_order.py` drives the provider in the
  host's order and nothing else; five of its six cases are red on the
  previous code.

- **Long-term memory works without an operator.** The store filled only
  when someone typed `omh memory capture` and then `omh memory approve`; on
  the owner machine that was never, across 552 Hermes sessions. Owner
  decision 2026-10-06: the model remembers durable facts itself and nobody
  runs an approval command.
  - `omh_memory(action="capture", summary, record_type, tags, scope,
    retention_class)` is the model's write path. It runs the installed
    `omh memory capture` (console script, `shell=False`, allowlisted child
    environment, 30s timeout) and reports a closed status set:
    `remembered`, `pending_review` with `review_reason`,
    `already_remembered`, `refused`, `omh_cli_unavailable`, `error`, plus
    the durability `receipt_state` the CLI observed on disk and never
    upgrades. `omh memory capture --on-duplicate skip` names the existing
    record and persists nothing; capture output now carries `receipt_state`
    and `review_reason`.
  - The default memory policy is `auto-safe`; `project_memory_policy/v1`
    discloses `mode_source`. A profile that stored the earlier `review-first`
    default without choosing it follows the new default on its next read; a
    mode passed with `--memory-mode` is kept.
  - The `omh-memory-new` and `omh-memory-sync` skills, the always-on
    awareness rail, the dreaming brief, the recommend guidance and the
    wrapper cards tell the model to capture directly, ask one question only
    when scope or durability is ambiguous, and tell the user in one line what
    was remembered, staged, or already kept. Hermes memory keeps short
    pointers and is trimmed only through Hermes' own tool; a brief stays a
    request, never evidence of consolidation.
  - Recall is never silent while active memory exists: when the message
    shares no token with any record, the approved active-tier records are
    served as an unqueried pack would serve them and the pack says so in
    `query_fallback` (mirrored on the prefetch receipt). Reference records
    still need a keyword, archived ones an explicit request, and a partial
    match never falls back. Coding handoff packs follow the same rule. Two
    approved records with the same normalized summary no longer both take a
    slot: the pinned, else newest, else smaller-id record is kept and the
    other is excluded as `duplicate_record` with `duplicate_of`. Retrieval
    corpus `omh-memory-retrieval-fixtures/v3`.
  - Provider state (`dreaming.json`, the brief, the receipt, both journals)
    is written under a lock with an atomic replace, so a CLI and a gateway
    session on one home no longer erase each other's counters (measured
    without the lock: 29–39 of 200 concurrent increments survived). A corrupt
    record or review file, or a directory that cannot be listed, is named on
    the receipt (`store.unreadable_count`, `store.unreadable`,
    `store.store_read_error`) instead of reading as an empty store, and
    every write the provider swallows to protect the turn is counted
    (`write_failures_count`, `last_write_failure`).
  - `omh memory status` carries `last_prefetch`: `never_served` when no
    receipt exists, otherwise when the provider last handed Hermes a pack,
    for which session, and how many records and blocks it rendered — the
    signal that would have shown the month of empty prefetches.

- **The plugin bundle passes Hermes's install scanner again.** The generated
  skill-shortlist sidecar carried the standalone token `monero` from the
  `external-connector-readiness` triggers, and Hermes scans bundled JSON
  with the same critical patterns it applies to code, so
  `hermes plugins validate` reported `dangerous: crypto_mining` and refused
  the catalog install. The token is left out of the BM25 document weights
  and anchors, in the core index and the sidecar alike; the explicit
  `monero gateway` trigger in `recommend.py` still routes that request.
  Measured: "assess the monero gateway connector" still decides `route`,
  with the lexical score 13.8 → 9.7 and the skill still first; `monero`
  alone decides `clarify` before and after. Carried from #1997 by
  @elriclegloire.
- **Git the dispatcher runs in a unit's worktree now runs inside that
  unit's fence.** Git takes its configuration from the worktree it runs in,
  and a fanout unit owns its worktree, so the dispatcher's own git calls
  there were not confined by the fence the unit ran under (#1990). From the
  moment a unit's fence is prepared, the clean-HEAD observation, the
  changed-path listing, the recovery capture and the session workspace
  probes are wrapped in it; a call that cannot be wrapped is not run. With
  no enforced fence nothing changes, since the unit ran unfenced as well.
  - A check resolved after the fence was prepared (a reproduction or
    task-linked command) used to run on the host when the fence did not
    know its executable. It is now fenced by its own PATH, or reported as
    a failed check without running.
  - In a fence without git paths `git add -N` is refused. An untouched
    worktree still reads as unchanged, so a transient failure there is
    retried as before; any other worktree is recorded as unmeasured, with
    a count of tracked paths in place of the path list the host-side
    capture used to give.
  - Still on the host, and why #1990 stays open: the calls before the fence
    is prepared on a reused worktree (workspace preflight, the git-path
    decision, clarification and reuse probes), post-green diagnostics,
    `fanout status`, and the Hermes recovery dispatch.
- **A confined fanout unit can commit in a Git LFS repository.** `git add`
  runs the git-lfs clean filter, which stages through `.git/lfs/tmp` into
  `.git/lfs/objects`; with that directory outside the write fence the filter
  failed and the unit could stage nothing. `lfs` joins the git paths a unit
  in a linked worktree may write, under the same conditions as the others,
  and is created when the repository has none yet. A symlink at `lfs`, or
  planted at the top of `lfs` or `lfs/objects`, adds no git path at all.
  Carried from #1992 by @junsuplee-forjl.
- **Repair briefs stay inside their prompt ceiling for any command text.**
  The brief was JSON with `\uXXXX` escapes, so a failing command written in
  non-ASCII text grew up to sixfold (about 28.5 KB for nine `é` commands at
  the caps) and escaped `UNIT_PROMPT_APPEND_MAX_BYTES`. The brief is now
  written as UTF-8, and each command copy is cut to 512 UTF-8 bytes at a
  character boundary instead of 512 characters. ASCII commands are
  byte-identical to before; nine `é`, Hangul, or emoji commands at the caps
  measure about 5.5 KB, under the `"` worst case of about 10 KB.
- **A flaky say-handler test no longer depends on the wall clock.** The loop
  start test compared two payloads as text, and its `evaluated_at` field
  differed when the two calls straddled a second. It failed CI twice. That
  one field is now normalized before the comparison; every other byte is
  still compared.

- **A confined fanout unit can commit on its own branch.** Under the OS
  write fence a unit in a linked worktree could edit files but not commit:
  its git metadata lives in the shared repository, outside its write root,
  so `git commit` failed on `index.lock` and the dispatcher, which only
  observes a committed HEAD, got nothing. The fence now adds the unit's
  per-worktree gitdir, `objects`, and the `agent` namespace under
  `refs/heads` and `logs/refs/heads`, only when HEAD is the unit's own
  `agent/<unit>` branch in a linked worktree of the dispatching repository.
  Any failed check adds none and the receipt's `git_roots_skip` says why;
  nothing falls back to unconfined. Carried from #1983 by @junsuplee-forjl.
  - A path the unit changes after the fence is prepared no longer becomes
    a grant. Each command used to resolve its write roots and exact-file
    literals again, so a unit could replace one with a symlink and have the
    next confined command (a verification check) write to the symlink's
    target: `hooks/` through a git root, the repository `config` through
    Claude Code's `~/.claude.json` literal, or any directory through the
    worktree and an owner state root. The last two predate the git roots.
    The paths are now resolved once per run, and on macOS a write root's
    own directory entry cannot be renamed or removed from inside the fence.
    A redispatch still resolves again; `docs/FANOUT.md` lists what that
    leaves open.
- **`omh docs workflows --installed` documents only what this machine has.**
  The workflow reference narrows to the skills the local install manifest
  records, with the harnesses those skills name, so a `core`
  profile reads its own catalog instead of the full one. It needs an install
  manifest and refuses `--json` and `--check`; `--output` writes the file.
  Carried from #1984 by @kyzerleo. The same PR's dotted `plugins.enabled:` /
  `skills.external_dirs:` config shapes are not carried: Hermes Agent does
  not read a dotted top-level key, so writing one would report a plugin
  enabled that Hermes never loads.
- **One function assembles every fanout unit prompt.**
  `assemble_unit_prompt()` (`src/coding/unit_prompt_assembly.py`) returns
  the prompt as named blocks in four zones (shared head, unit, tail,
  redispatch append) instead of a string that dispatch then edited. Live
  dispatch, the Hermes recovery lane, `build_unit_prompt`, and both
  benchmark lanes call it; a repair brief, a parent decision, and a retry's
  fresh sidecar path are arguments now. Every existing path is byte-identical
  (840 pinned golden prompts, and product-ab's prompt digests), except the
  change below.
  - The sidecar contract no longer restates when to report
    `process_declined`; the shared head's failure-kind sentence says it, and
    every prompt with the contract carries the head. Sidecar prompts are
    241 B shorter.
  - `UNIT_PROMPT_MAX_BYTES` (8,000 B) now explicitly bounds the dispatch
    prompt, gated over every calibration key with the sidecar contract and
    skill discovery. A repair brief at its own caps (9 commands x 512
    characters) adds about 5.5 KB of plain ASCII and up to about 10 KB for
    characters JSON doubles (`"`, `\`), so it cannot share that ceiling;
    each redispatch section gets its own producer-derived
    `UNIT_PROMPT_APPEND_MAX_BYTES`. Non-ASCII command text is bounded by the
    same ceiling (see the repair-brief entry above).
  - Dispatch rows record `unit_prompt`: block names, byte size, and sha256
    of the prompt sent, never the text.
  - `gpt-6.1-sol-pro` and dated Sol snapshots such as
    `gpt-6.1-sol-2026-09-01` now get the Sol Codex throughput overlay their
    calibration already implied; the overlay reads the contract model id,
    the same identity the calibration lookup uses.
- **The 2026-10-04 prompt audit's measurements are recorded.** All arms ran
  on `claude-fable-5-1` at `xhigh` (Claude Code subscription, 30 instances
  per arm, with same-text repeats).
  - The `claude` family block keeps its place. Against no block it never
    cost more and cut tool calls by about 11%.
  - The shared unit head is measured for the first time. It cuts tool calls
    by about 25–30% at no measurable token cost, so it stays.
  - Removing the parent-clarification block saves nothing measurable, so it
    stays too.
  - The GPT-6.x overrides stay as recorded on 2026-10-02: no measured
    effect either way.
  - The DeepSeek override is unmeasured. It has no subscription route.

- **The live-model benchmark can measure the shared unit head.** Every
  benchmark arm used to send only a calibration paragraph in front of the
  bare benchmark contract, so the head that every dispatched fanout unit
  carries had never been measured. Two new conditions in
  `benchmarks/live-model-tools/v1` cover it.
  - `unit` sends the product's own head (built by
    `shared_unit_preamble_lines()`, not copied), then the `optimized`
    calibration, then a note that the benchmark answer file is the graded
    deliverable, then the task and contract.
  - `unit_lean` drops a declared, named set of head blocks. It starts with
    `PARENT_CLARIFICATION`, the block that also carries the JSON example.
  - Every run record now has a `prompt_digest` of the exact prompt sent and
    a `head_omitted_blocks` field. `bench.py`, `analyze.py`, the run-record
    schema, the fake harness, and the audit all read a single condition list.
  - Offline only so far. No live arm has run.
- **Bedrock Claude ids get the claude family.** `model_family` now reads
  Amazon Bedrock's `anthropic.` vendor segment, with or without a regional
  prefix (`us.anthropic.claude-opus-5-5`), so those ids receive the claude
  calibration instead of the generic one. Before this, every Bedrock Claude
  id classified as `unknown`.

- **Prompt text that repeated itself or a code gate is removed.** An audit
  of every model-facing block (2026-10-04) deleted only text whose every
  receiver already gets the same rule another way.
  - Fanout unit prompts no longer end with the structural-search preference
    sentence; their shared head already says "structural search when
    available, grep otherwise". The coding-delegate capability blocks keep
    it.
  - The `glm`, `deepseek`, and `deepseek-v4.1-flash` composer blocks no
    longer repeat the prompt-cache rule. `omh coding composition-guide`
    prints `PROMPT_CACHE_COMPOSITION_PROTOCOL` beside every composer block,
    and `build_unit_prompt` places the shared head first.
  - The `grok` composer block no longer asks for overlap and cycle checks
    before recording a contract; `fanout prepare` and `validate` refuse to
    record one that fails them.
  - The Claude Sonnet 5.5 subagent and composer overrides are removed.
    The 2026-10-02 run could not tell the subagent override from the family
    block, the composer override was the family block byte for byte, and no
    shipped slot reached either. Sonnet 5.5 now takes the `claude` family
    blocks.

- **GPT-6.1 Sol and Claude Sonnet 5.5 placements are measured.** Each was
  run on its subscription route against `benchmarks/live-model-tools/v1`
  (30 instances per arm, with a same-text repeat for drift). Full tables are
  in the benchmark README; the summary is in MODEL_OPTI.md.
  - GPT-6.1 Sol solves the same instances as GPT-6 Sol with 14% fewer tool
    calls and about 8% fewer tokens, so the #1975 slot swap holds. Its
    Astra-text override shows no measurable effect against the `gpt` family
    block.
  - The Sonnet 5.5 override's vendor-reported cost cut does not reproduce on
    this corpus, because run-to-run drift (about 10%) exceeds any difference.
  - Both overrides stay, recorded as unproven. Neither measured worse.

- **Named custom providers route through delegation.** A provider id such
  as `custom:cli-proxy`, the form Hermes gives a named custom provider, was
  refused as an unsupported mapping by the route writer, the route reader,
  and every routing document. A colon is now admitted when an alphanumeric
  character follows it, so `custom:cli-proxy` and tagged model ids such as
  `qwen3:8b` validate. `custom: x`, `custom:`, and `a::b` are still
  refused, as is any token over 128 characters. A reasoning effort stays a
  bare word. `omh model-chains set` reads the text after the last colon as
  the effort only when it names one, so `custom:cli-proxy:xhigh` splits
  once and `qwen3:8b` stays a model id. Linked-provider detection keeps its narrower grammar. (#1976, thanks
  @mazzy89)

- **GPT-6.1 Sol, Claude Sonnet 5.5, and Grok Build 0.1 are registered, and
  four stale price rows are corrected.** A sweep of every shipped family
  against vendor docs and the Hermes upstream catalog (2026-10-01) found
  three models OMH did not register.
  - GPT-6.1 Sol (`gpt-6.1-sol`, released 2026-09-29) takes every slot
    GPT-6 Sol held, at the effort each slot carried: `deep` head `high`,
    the shared last resort `medium`, the main-role suggestion `high`, and
    every Maestro Codex row (owner decision). GPT-6 Sol leaves the shipped
    chains and stays recognized, priced, and provider-mapped. 6.1 Sol has
    no `none` rung, so `off` and `minimal` are raised to `low` on record;
    the five Maestro Codex rows that named no effort now name `medium`,
    because the Codex client's default for 6.1 Sol is `low` and leaving
    the effort unset would have lowered them silently. `gpt-6.1-sol-pro` is
    a declared pro-mode projection. Price 2/10 with cached input at 5% of
    input. The calibration is GPT-6 Astra's override text, byte for byte:
    the vendor's Codex client gives 6.1 Sol Astra's base prompt.
    Editorial and unmeasured for 6.1 Sol.
  - Claude Sonnet 5.5 (`claude-sonnet-5-5`, released 2026-09-28) gets an
    exact contract. Its declared spellings are the Bedrock id and
    OpenRouter's dotted id. A no-thinking rung is raised to `low`, because
    `disabled` is HTTP 400 on this model, and `omh_delegate_route` refuses
    that rung for it. It is priced at 2/10. It joins no chain (owner
    decision). Its high-effort block adds one clause to the Claude block:
    once the checks pass, start no further review rounds and no reviewer
    sub-agents. Anthropic measured that instruction at `max` effort as
    cutting session cost by about a third with no change in quality.
    It is unmeasured in OMH.
  - Grok Build 0.1 (`grok-build-0.1`) takes the `x_platform_data` slot.
    xAI retired Grok Code Fast on 2026-05-15 and lists `grok-code-fast-1`,
    `grok-code-fast`, and `grok-code-fast-1-0825` as Build 0.1 aliases, so
    on xAI's API the slot already ran it. Both ids are now priced at the
    Build 0.1 list rate of 1/2, with cached input at a fifth of input; the
    old 0.2/1.5 rate under-reported runs on xAI's API after the reroute.
  - Corrected list prices: Kimi K3 0.6/2.5 → 3/15 (it was the K2-era rate);
    Kimi K3 Ultrafast 0.3/1.25 → 3/15, carrying the base rate because
    Moonshot publishes no tier rate; Gemini 3.1 Pro 1.25/10 → 2/12 (it was
    Gemini 2.5 Pro's rate).

- **Update takes back a bot profile's store setting once its `.env` names
  one.** Setup and update give a storeless bot profile
  `plugins.entries.omh.settings.omh_home` under a non-default primary store
  (#1967). If `OMH_HOME` was added to the profile's `.env` afterwards, that
  setting outranked it and the profile kept binding the primary's store.
  Setup and update now remove the setting when the profile's `.env` names
  `OMH_HOME` and the value is still the one OMH's write record says it
  wrote, clear that record entry, and report the removed value per profile
  (`omh_home_reclaimed` in the profile row, and a line in the human output).
  A setting OMH did not write, or one changed by hand since, is kept.
  `omh doctor` adds a warning under `plugin_omh_home_binding:<profile>` when
  a setting OMH did not write outranks the profile's `.env` `OMH_HOME`; it
  never blocks. (#1973)

- **The file-operation, coding-handoff, and review workflows cite
  `session_file_activity/v1`.** `workspace-file-operator` names it inside
  `file_observation_manifest/v1`, and `maestro` and `code-review` name it for
  carrying a Hermes session's file lineage into a handoff or scoping a review.
  Each citation gives the command and keeps the receipt's boundary: it is not
  file-content, diff, test, review, CI, or merge evidence. A new test proves
  profile isolation: two Hermes homes sharing a workspace, a session id, and a
  call id each read only their own `state.db`, including `latest` and the
  CLI under `HERMES_HOME`. Containment stays lexical, so a symlink inside the
  workspace that points outside shows its in-workspace spelling; resolving
  links would stat named files, which the receipt never does. (#1813)

- **Windows fanout dispatch stays unconfined, now as a measured finding.**
  Both native ways to give `omh coding fanout dispatch` a write fence on
  Windows without a dependency were built and run on the Windows CI runner,
  and neither holds the contract. A write-restricted token refuses writes
  outside the unit root but also denies the child its own default-security
  named pipes, so Node's piped `child_process` fails with `EPERM`. That is
  how every coding owner CLI runs its tools. Low integrity keeps the pipes
  working, but any Low process on the host can write every Low-labelled root,
  including another unit's worktree and `AppData\LocalLow`, and owner state
  would have to be labelled Low for good. Behaviour does not change: Windows
  still dispatches unconfined and records
  `no_os_confinement_backend_on_this_platform`. `docs/FANOUT.md` records what
  was measured and what was not. (#1357)

- **Bot profiles under a non-default primary OMH home bind the primary's
  store.** `omh setup --omh-home X` recorded `plugins.entries.omh.settings.omh_home`
  in the primary Hermes home only, so a bot profile that named no store of its
  own had a plugin binding `~/.omh` while its managed skills, widget and skin
  came from X (#1967). Setup and update now give such a profile the same
  setting, but only when it has neither its own `settings.omh_home` nor
  `OMH_HOME` in its `.env`: a profile that chose a store keeps it, and with a
  default primary no profile config changes. `omh uninstall` takes back only
  the setting OMH wrote, and `omh doctor` warns with
  `plugin_omh_home_binding:<profile>` for each profile still naming no store.

- **A blocked research source leaves a typed `research_source_recovery/v1`
  record.** `research` (and the portable `ulw-research`) already tried the
  host's blocked-page recovery once for a 403, 429, paywall, WAF, or bot-wall
  source (#1907). That rule is now a contract in
  `src/workflows/research_source_recovery.py`: one planner maps each failure
  class to exactly one step (cite the direct retrieval, one
  `blocked-page-recovery` handoff, or an unresolved gap naming
  `authentication_required`, `unsupported_failure_class`,
  `missing_capability`, `budget_exhausted`, or `recovery_failed`), the
  record keeps the canonical URL, failure class, route, retrieval time,
  evidence class, outcome, and residual uncertainty, and a run that hands
  the same source to recovery twice is refused as a retry loop. A live page
  and a historical capture stay separate classes. The skill line also names
  a spent retrieval budget as a gap reason. OMH still fetches nothing. (#1527)


- **`agent-debug` produces a bounded, cited incident report, and sharing it
  is a separate reviewed action.** `omh quality-evidence agent-debug` now
  selects one session by full id, `latest`, or a prefix that names exactly
  one (an ambiguous prefix is refused, never guessed), reads a supplied JSON
  Lines session record as well as `state.db` with `record:line` citations,
  narrows to a turn range, and reads within row and byte budgets that skip an
  oversized cell or line without holding it. On top of the cited report it
  builds `agent_failure_capture/v1`, `agent_failure_pattern_hypothesis/v1`
  (at least two competing hypotheses with typed evidence for and against,
  ruled out only by an absence in a complete reading) and
  `contained_recovery_action/v1` (proposed, never executed), and binds a
  fanout dispatch-summary receipt only when it carries the session, run,
  unit, configuration and freshness identities. The new
  `agent-debug-export` re-checks every cited reference against the source,
  redacts and leak-scans the package, and writes it only with
  `--confirm-export`. Requests about a looping, repeating, drifting,
  context-losing or unexpectedly costly agent run now route to `agent-debug`.
  `docs/HARNESS_QUALITY.md` shows an evidence-backed and an unavailable
  example rendered from the test fixture. (#1799)

- **`omh update` no longer drops the full-only skills a core install kept.**
  A staged update renders the skill pack into a new, empty generation and then
  moves `current` to it. The installer decided what to refresh from that empty
  directory alone, so on a `core` profile it wrote only the core skills, and
  every full-only skill the install had kept, such as the nine ULW engines,
  disappeared on the next update. The refresh set now also includes the skills
  the active generation serves. A plain core install is unchanged, and
  narrowing an install is still only done by
  `omh skill-profile reconcile --to core`. (#1963, contributed by
  @anhtahaylove)

- **`omh setup --omh-home X` binds the plugin to X.** The plugin loaded in
  a Hermes home resolves its store from that home's
  `plugins.entries.omh.settings.omh_home`, then the Hermes process's
  `OMH_HOME`, then `~/.omh`, and setup wrote none of the first. So an install
  at any store other than `~/.omh` had a plugin that read another install's
  manifest and wrote its runtime state to `~/.omh` unless Hermes was started
  with `OMH_HOME` exported (#1960). Setup and update now record the setting
  when X is not `~/.omh`; a default install's config is byte-identical to
  before. A value already there is never replaced (a profile's store stays
  its own choice, #1679; profiles that chose none are covered above), and
  `omh uninstall` removes the setting while it still names the store it
  wrote. `omh doctor` gains a `plugin_omh_home_binding` warning when the
  plugin in the Hermes home would bind a different store than the one
  doctor checked. Behaviour change: once the setting is recorded, an
  exported `OMH_HOME` no longer overrides it for that Hermes home, because
  the setting outranks the environment. Re-running setup with another
  `--omh-home` does not move it either (the write is unset-only); to switch
  stores, remove or edit `plugins.entries.omh.settings.omh_home` in the
  Hermes home's `config.yaml` and run setup with the new `--omh-home`, or
  `omh uninstall` from the old store first.
  doctor checked.
- **MODEL_OPTI.md records which chat models keep a non-English persona's
  language after an OMH skill loads.** On a Korean persona,
  `deepseek-v4.1-flash-ultrafast` flipped the reply after an OMH
  `skill_view` (fewer than 20 Hangul characters in its narration) in 16 of
  20 samples, against 3 of 20 with no skill; 15 of the 16 were English
  narrations. `kimi-k3`, `deepseek-v4-pro` and `glm-5.3-ultrafast` held: 0,
  1 and 0 English narrations with the skill loaded. glm's pre-registered
  flip counts (8/20 and 7/20) are short Korean lines and tool-call-only
  replies, which the DeepSeek-marker splitter cannot separate. Six
  prompt-level wording levers were measured against the Flash model and
  none passed its pre-registered rule, so the guidance is a host model
  choice, not an OMH calibration. Docs only.

- **OMH's reply rule says the persona owns the voice, progress updates
  included.** The awareness rail and every generated skill's tail said to
  reply "in the host's own voice" and named nothing that voice covers. On a
  casual-register Korean persona (`deepseek-v4.1-flash-ultrafast` on Slack
  with interim messages on) the final answer kept the persona while 13 of 17
  interim progress lines in one session came out in English. The line now
  says the host's `SOUL.md` persona owns the reply language, tone, speech
  level, and sentence endings, progress updates included; where the persona
  sets no language, the reply uses the one the user wrote in; OMH shapes
  structure and content only. The rail reference's host-voice section says
  the same and adds that a skill's report shape never justifies switching
  language or register. Nothing new is injected per turn: the compact rail
  line changes in place (1241 -> 1434 chars, paid once per session in the
  system-prompt section).

- **The per-turn route hint names only skills this install holds.** On a
  `--core` install the `[OMH Route Hint]` block and the "Skills that may fit
  this request" line ranked the whole catalog, so they told the model to
  `skill_view` skills that were not on disk (`selected=workflow-learning`,
  `omh-content-operator`). The plugin now reads the installed set from the
  install manifest, cached on its mtime, and leaves out every catalog skill
  the manifest does not record. A hint whose selected workflow is missing is
  dropped and the next ranked hint becomes `selected=`; with none left, no
  route block is sent. A full install, or a home whose manifest cannot be
  read, renders the same bytes as before. `omh doctor` gains a
  `route_hint_skills` warning that names the skills a hint could still send
  that are not on disk. (#1954)
- **`install.ps1` resolves the latest release on Windows PowerShell 5.1
  again.** On 5.1 the no-redirect `HEAD` to `/releases/latest` can throw a
  `NullReferenceException`, and that exception has no `Response`. The error
  handler read `$_.Exception.Response` directly, which is a terminating error
  under `Set-StrictMode -Version 3.0`. The installer therefore stopped with
  "The property 'Response' cannot be found on this object" before printing
  anything. The handler now reads that property through a guarded accessor.
  When no `Location` comes back, the installer follows the redirect and reads
  the final URL: `ResponseUri` on 5.1, `RequestMessage.RequestUri` on
  PowerShell 7. The same tag check applies to that URL. If both requests fail,
  the "could not resolve the latest release" diagnostic prints as before.
  Windows CI runs the new behavioural cases and their pre-fix mutation under
  both hosts. (#1953)
- **The installer's interpreter-selection test no longer depends on the host's
  Pythons.** Its `PATH` kept `/usr/bin`, and `install.sh` probes `python3.14`
  and `python3.13` by name before `python3.12`. On a host that ships
  `/usr/bin/python3.14` (Fedora 44), that interpreter was chosen ahead of the
  stubs and the case failed, also on an unmodified main. The test now puts only
  its stubs and a fixed list of linked system tools on `PATH`, and leaves out
  both `/usr/bin` and any host `uv`. The assertion is unchanged, and
  `install.sh` is unchanged. Reported by @awss1i in #1955.

- **The product A/B gate no longer judges a candidate by tests that were
  already failing.** The task-linked selection now drops every module that is
  not green on an untouched checkout at the merge base. This is the same
  verdict the corpus demands of the regression set. The record lists dropped
  modules under `red_at_merge_base_test_paths`. Before this, 10 of 40 tasks
  selected a module that was red before any change, so the gate could send a
  correct run to repair. The pull request's own test files stay excluded as
  target tests. The corpus and its digest are unchanged. (#1896)
- **A fanout dispatch that found a unit busy exits 75, not 0.** When another
  dispatch holds a unit's repair loop, `omh coding fanout dispatch` skips the
  unit as `repair_in_flight` and spawns nothing for it. That run used to exit
  0, so a wrapper reading only the status could not tell "busy, nothing done"
  from success. It now exits 75 (`EX_TEMPFAIL`, retry later), also when other
  units in the batch completed. A failed or blocked unit still exits 1 and an
  interrupt still exits 130; both outrank the busy code. `already_completed`
  and `not_selected` skips still exit 0. (#1932)
- **The `codestral` calibration block now has a live measurement.** It was
  one of four family blocks marked "live benchmark validation pending". Four
  arms of 30 evaluation instances on `codestral-2508` at `high` (two without
  the block, two with it) show no measurable effect either way: 9 / 60
  passes with the block against 5 / 60 without, and +1,607 tokens per task,
  bootstrap CI95 [−2,451, +5,788]. The block is kept, and the
  `MODEL_OPTI.md` section now records the numbers, including that the rule
  written before the first three arms failed narrowly and a pooled rule was
  added before the fourth. `mistral`, `llama` and `solar` stay pending.
  The benchmark's pairing test now checks that the calibration block is the
  only difference between the two prompts; before, extra text before or
  after the block, or a changed separator, still passed it. (#1056)
- **English one-word replies now decline the route question.** The
  `one_word_reply` verdict accepted only the engine-entry approval
  vocabulary, which holds one English word (`lgtm`) against thirteen Korean
  entries, so `yes`, `sure`, `yep`, `nope`, `nah`, `cool` and `proceed` kept a
  question with nothing to decide and the shadow decline rate undercounted
  English turns. A separate English reply list (go-ahead, refusal,
  acknowledgement) now counts when it is the whole message, punctuation
  folded. It only moves the shadow record: the engine-entry approval gate and
  every route payload are unchanged. `stop` stays out because its question
  offers `cancel` and `loop`, and one-word workflow requests (`test`, `fix`,
  `ship`, `refactor`) are still asked. (#1938)
- **The product A/B corpus digests no longer depend on local Git settings.**
  Test-diff hashes are now taken from a fixed diff format: full object IDs,
  no color, no external diff, and fixed context and algorithm. Before this,
  Git 2.55's longer abbreviations or a local `core.abbrev` changed the hashed
  text, and the pinned-corpus tests failed on those machines while CI passed.
  The corpus digest moved to `9b5ff901ebcb`, re-derived from the same pinned
  commits; task text and validator blobs are unchanged. Records under the
  old digest must not be combined with new ones. (#1917, #1948, contributed
  by @jbaehova)
- **New regression tests for the route-question sink and fanout repair.**
  - Recording a route question does not change the payload.
  - `off` mode records the question before withholding it.
  - An in-flight repair skip keeps the earlier dispatch entry and resumes as
    not attempted.
  - Repeated identical checks pair with their own failures in order.

  (#1938, #1932, #1946, #1947, contributed by @jbaehova)

- **The plugin declares a Hermes floor, not a window.** `requires_hermes` is
  now `">=0.21.1"`, and the in-process admission gate reads the same value, so
  a new Hermes minor release no longer skips or refuses the plugin. Hosts older
  than 0.21.1 are still refused before registration.
- **`omh_gather_evidence` runs only inside the host working directory.**
  `project_root` (and so `workdir`) must resolve to the host's working
  directory or a path inside it, symlinks included. After a `-m unittest`
  prefix only reporting flags (`-v`, `-q`, `-f`, `-b`, `-c`, `--locals`,
  `-k PATTERN`) may follow, so `discover`, `-s`, `-t`, `-p`, and model-named
  modules are refused; `git diff` refuses `--output`, `--ext-diff`,
  `--textconv`, and `--no-index`. The `uv run` prefixes are gone from the
  shipped allowlist, because `uv run` syncs and builds the project environment
  before the named command starts.

- **The Ultra-Skills section shows how to use the `ulw-` workflows.** Every
  README (en/ko/ja/zh) and the site now carry a recommended set of prompts
  typed at the Hermes prompt: `ulw-interview` or `ulw-plan` to shape the work,
  `ulw-work` to run the accepted plan, `ulw-loop` to finish against a named
  gate, and a `ulw-maestro` prompt that dispatches one unit to Claude Code and
  one to Codex. A real Hermes TUI capture of a `ulw-plan` answer (target
  dependency graph and lane order), Slack-thread illustrations carrying the
  real reply of a `ulw-interview` first round and a real `ulw-work` run (one
  row per lane with its routed category and model, marked with the model
  vendor glyphs from `model_vendor_glyphs`), and a labelled `ulw-maestro`
  illustration sit beside them. The generated inventory regions are
  unchanged.

## 3.0.0 - 2026-09-29

Highlights of this major release (details in the entries below):

- **Work that finishes.** A todo item closes only on a recorded result
  (#1928), a fanout unit repairs itself in its own worktree until its checks
  pass or its budget is spent (#1929), and a unit's "done" is held to the tests
  its own changes reach (#1876).
- **Teammates on Hermes' runtime.** `omh_team` runs a checked delegate team
  from an accepted plan: owners, dependencies, and a verification command per
  task, with a result only on observed evidence (#1931).
- **Replies in the host's voice.** OMH's record vocabulary stays out of the
  reply, while orchestration decisions (team split, routing, goal, blocked
  reason) carry one plain sentence (#1930, #1837, #1851), and the reply rules
  are linted against real sessions (#1848).
- **Hermes Desktop.** The bundle ships the Desktop half, with an OMH pane and
  status item (#1856, #1864).
- **Routing and skills.** Dispatch only on strong evidence with a lexical
  shortlist otherwise (#1879, #1880, #1891), a measured reach gate for every
  installable skill (#1875), and new skills for app debugging, git workflow,
  relational databases, security events, release cuts, IaC, data pipelines,
  model fine-tuning, mobile release, and internal audit.
- **Models.** Claude Opus 5.5, GPT-6 Luna, and GPT-6 Sol onboarded (#1833,
  #1841); OMH can ask Jev itself when the user names it (#1844).

- **`omh_jev_ask` no longer refuses every call with `consent_not_observed`
  when the person named Jev.** Hermes loads the OMH bundle twice in one
  process: once as a plugin, and again as the memory provider that
  `omh setup` enables. The hooks that record the person's request came from
  the first copy, while the tool could come from the second. The tool
  therefore read consent state that no hook had written. Both copies now
  share one consent state. The turn binding is unchanged: a request is still
  consent only for the turn that made it. (#1939)

- **Plugin reinstalls no longer delete files you added to the plugin
  directory.** `omh setup` now refuses to replace
  `$HERMES_HOME/plugins/omh/` when it holds entries absent from the installed
  OMH manifest, and it names them. `omh update` leaves that tree in place,
  prints why the plugin refresh was skipped, and continues its other updates.
  `--force` still replaces the tree. Replacement runs in a private per-run
  transaction directory, so an existing `.omh.previous` or `.omh.installing`
  sibling is never cleared. After the original tree is moved aside it is
  checked again, so additions or edits made while the new tree was staged
  cause a refusal and a restore. If the rollback itself fails, the error names
  the retained backup. Bytecode caches for managed sources do not block a
  refresh, including caches written by Hermes' own Python when that is a
  different version from omh's; on a machine where the two differ, treating
  those as additions would have skipped every plugin refresh. (#1933,
  contributed by @junjuny0227)

- **The route question says which mode recorded it, what it would have
  declined, which answers contradict themselves, and how it reads against your
  own traffic.**
  - **Mode.** The mode is read from `<omh_home>/routing/route-question.json`
    (`off` or `shadow`, default `shadow`). A config that exists but cannot be
    read, parsed, or understood reports `unknown` with its reason, never the
    default; `on` is not available yet and reads the same way.
  - **Shadow and off.** In `shadow` every negative-control payload is
    byte-identical to the payload built with the mode seam removed. `off`
    withholds the question on every surface.
  - **Where routes are recorded.** Every answer record carries `mode` and
    `mode_source`, and so do the two route records. `omh chat route --record`
    writes a routing record for every turn. A recorded wrapper session
    (`omh_interact` by default) writes a `route_question_observed` session
    event on each turn that built a question. Interactions without a session
    record no route.
  - **Decline verdict.** Each route record carries the decline predicate's
    verdict: `acknowledgement`, `one_word_reply` (a listed approval word such
    as `lgtm`, never a one-word request), `no_candidate` or
    `single_candidate`. In `shadow` the question is still asked; the verdict
    is recorded so its rate is readable.
  - **Invalid answers.** An answer whose Choice probabilities omit an offered
    option, do not sum to one, or do not peak at the chosen option is recorded
    as `invalid_answer` and counts as no opinion. This applies in
    `omh_route_answer` and in the corpus scorer. `coverage_checked` says
    whether the options were at hand.
  - **Report.** `omh chat route-questions report` joins answers to the newest
    route with the same `message_sha256` from either record. It reports
    decline, invalid-answer and agreement rates as reported rates, plus a
    per-turn cost over a declared turn shape that the report names as not
    measured by OMH.

- **Internal-control testing has an owner: `omh-internal-audit`.** "is this a
  significant deficiency or a material weakness", "reperform the bank
  reconciliation control for march" and "how many samples do we need to test
  a daily control for icfr" used to get a direct answer or a question led by
  an unrelated skill. They now dispatch to a skill that derives the grade
  instead of asserting it:
  - `control_under_test/v1` and `sample_design/v1` define the population,
    check its completeness, and size the sample from the control's frequency;
  - `evidence_request/v1` and `reperformance_record/v1` separate evidence
    obtained from evidence described and re-perform each item;
  - `deficiency_severity_grade/v1` shows the stated likelihood, magnitude
    against materiality and compensating controls beside the grade, and
    withholds the grade when one is missing.

  The sample-size table, the evidence hierarchy and the severity decision
  table load on demand from `references/control-audit-method.md`. The Red
  Sox, a lack of internal control over snacking, factory quality control and
  a bridge's material weakness stay away. OMH reads no ledger and signs off
  nothing (#1569).

- **Store releases have an owner: `omh-mobile-release`.** "we are shipping
  3.2 to the app store and google play next week", "our testflight build is
  stuck in beta review" and "set up code signing and provisioning profiles for
  the ios release" used to ask a question led by `connector-operator` or
  `code-review`, or dispatched to `github-event-ops`. They now dispatch to a
  skill whose outputs are the gates the stores enforce:
  - `signing_plan/v1` names every certificate, profile and key with its expiry
    and holder, never the secret;
  - `privacy_declaration_check/v1` compares the privacy manifest and the
    Play data safety form against the SDKs the build ships;
  - `beta_channel_plan/v1`, `staged_rollout_plan/v1` and `hotfix_plan/v1`
    plan the TestFlight or Play beta, the halt thresholds for each rollout
    step, and the higher build number that replaces a bad one, because a
    store release cannot be rolled back.

  The per-platform gates, the halt thresholds and the hotfix steps load on
  demand from `references/mobile-release-method.md`. A phone's store app, a
  gift card and a Kafka broker keystore stay away; a staged rollout of an API
  stays on `release-cut` and watching a deploy stays on `deploy-and-monitor`.
  OMH builds, signs and submits nothing (#1568).

- **Fine-tuning a model has an owner: `omh-model-finetuning`.** "sft vs dpo
  for our summarization model", "should we fine-tune a model or is prompting
  enough" and "train a lora adapter on our internal docs" used to ask a
  question led by `context-budget-review`, `model-setup` or
  `curriculum-design`. They now dispatch to a skill whose first output is
  whether to train at all:
  - `finetune_decision/v1` measures the untuned model and the cheaper fixes
    on a held-out eval and returns `do_not_finetune` when prompting or
    retrieval closes the gap, before any training step;
  - `training_method_choice/v1` picks SFT, DPO or RLVR from the shape of the
    data and names the method's failure mode;
  - `training_data_plan/v1`, `baseline_comparison/v1` and
    `checkpoint_promotion_gate/v1` draw the held-out split before training,
    run the same eval on the untuned baseline and each candidate, and promote
    only a checkpoint that beats the baseline.

  The decision ladder, the method table, the data checklist and the promotion
  procedure load on demand from `references/finetuning-method.md`. An email's
  wording, a hiring process, a data protection officer and a LoRa radio stay
  away, and learning from an OMH run stays on `workflow-learning`. OMH trains
  nothing and runs no eval (#1567).

- **`omh coding fanout dispatch` keeps a unit going until its checks pass
  or its repair budget is spent.** A unit may declare `max_repair_attempts`
  (0 to 3, off by default). When the dispatcher runs the unit's declared checks
  and sees one exit nonzero, it re-dispatches the same executor in the same
  worktree, keeping the prior commits, with a repair brief. The brief names the
  failing commands and their exit codes; no output text is included. The loop
  stops only when every check is observed passing, or when the budget is spent.
  A spent budget records the unit `blocked` with `repair_budget_exhausted` and
  the last failing check, and the batch exits 1. A timed-out check, a
  reproduction unit's expected failure and an executor's own "checks passed"
  never trigger a repair. Attempts are journaled as `repair_attempt_started` /
  `repair_attempt_observed`, so a later dispatch continues the count instead
  of resetting it, and `fanout show` / `fanout brief` report the count and the
  stop reason. A contract without the field freezes and dispatches exactly as
  before.
  Separately, a dispatch whose declared checks were observed failing now
  exits 1 even without a repair budget; it used to exit 0 because the
  unit's process had exited 0.
- **OMH's own words stay out of the reply, and its decisions are said
  plainly.** The end-of-turn sentence for a turn that started remote work
  and armed nothing no longer opens with `[OMH]` or says "armed": it now
  reads "This session has stopped: the remote work it started will not wake
  it when it finishes, so send a message to pick it back up.", in the
  reply's own language. The language is read from the reply text with code
  blocks and inline code removed: a script counts through a run of two of
  its characters, its characters (weighed two Latin letters each) must carry
  at least as much as the Latin letters, so an English reply quoting a Korean
  sentence stays English, and a non-Latin reply takes Hangul before kana
  before Han; a kanji-only Japanese reply reads as Chinese. The OS locale is
  never consulted; Korean, Japanese and Chinese copy ships in the plugin
  bundle and anything else gets English. Four tools now add a `say`
  field to a successful result, one plain English sentence about the
  decision they just recorded, and their descriptions ask the model to relay
  it once in the user's language and its own words: `omh_delegate_route`
  names the model a part will run on (its display name, and what the
  category is for when that reads as a kind of work, never the category id),
  and has its own sentence when no chosen model is left; `omh_todo` states
  the plan and when it counts as complete on `set`, names a step and its
  recorded reason when an `advance` blocks it (or says it was skipped when
  the step is done with a reason), and says in plain words why a
  step marked done still counts as open, never the reason code; `omh_loop`
  states the goal and its criteria on `start` and what the loop waits on for
  an `external_wait`; `omh_agent_board` says which teammate a prepared role
  lane sets up. Reads, errors, refusals and contended writes carry no
  `say`, and every other result field is unchanged. The reply lint
  (`omh quality-evidence reply-lint`) now also catches every `[OMH ...]`
  head OMH writes, 90 `omh_`-prefixed schema ids, 14 record ids
  (`unspecified-high` and the other non-word categories, `no_evidence` and
  the other evidence codes, `done_unverified`, `exhausted_to_inherit`, the
  repair loop's blocked reasons), `route_question`, `coding fanout dispatch`,
  and the result keys `evidence_boundary` and `claim_boundary`, while
  markdown and reference links, a person's own `route_question(q)` call,
  `/v1` URLs, unprefixed version ids and ordinary words stay clean; the common rail's vocabulary line now
  lists the same words and a test keeps the two in step. Fan-out narration
  for `delegate_task` is not included: the host dispatches that tool outside
  the only hook that can annotate a result.

- **Helper lanes can be held to their own check: `omh_team`.** An accepted
  plan whose lanes each carry a check command can now run as a team of
  in-session `delegate_task` helpers where a lane counts as done only when OMH
  runs that lane's command itself and sees it exit 0 -- never on a helper's
  summary.
  - `team_start` binds to this session's accepted `omh_todo` plan: the plan's
    reference must match, and every check command must be written in an
    accepted item as ``check: `<command>` ``, exactly. A command that is only
    mentioned in the plan binds nothing. The host then asks the person to
    approve the exact command list; where nobody can answer, and in a cron
    run, the start is refused. Commands are frozen from that point.
  - A check command refuses, anywhere in argv: shells, `env` and `xargs`;
    inline program text (`python -c`, `-Ic`, `perl -e`, `node -e`, `deno
    eval`); `git -c` / `-C` / `alias.` / `core.` and git verbs that move a
    remote or rewrite the checkout; forge CLIs; `sudo`; network tools;
    package install and publish; and `rm` / `mv` / `chmod` / `chown` / `dd`.
    Every command then also passes Hermes' own hardline floor and the
    person's `approvals.deny` rules, at start and again before it runs; when
    that floor cannot be reached, nothing runs.
  - The record on disk is not trusted to run anything. Which command lists a
    person approved, and which checks OMH ran, live only in the Hermes
    process: `team_reconcile` refuses a team whose commands were not approved
    since Hermes started, and a stored pass this process did not observe is
    checked again. After a restart, `team_start` with the same parts asks the
    person again and every earlier pass is re-earned.
  - The host's own `subagent_start` / `subagent_stop` callbacks tell the team
    which helpers are out, and `team_reconcile` checks nothing until every one
    is back. A failing check (spends a try) returns a fix-up entry carrying
    only `{command, exit_code}`; a check that could not run cleanly (timeout,
    not found, killed by a signal, missing workspace, a workspace outside git,
    files changed while it ran) spends nothing. One `team_reconcile` runs at
    most two checks, each leased just before it runs. A lane starts only when
    every lane it depends on has passed.
  - The team stops only at `done` (every lane passed) or `blocked` with a
    reason, such as `repair_budget_exhausted` with the last check.
    `max_repair_attempts` defaults to 2 and is capped at 3. Checks time out at
    ten minutes.
  - `team_status` gives per-lane state, tries used, the last check, the
    conversation's cost, and the plain caveat that a check runs code helpers
    wrote as the person's own user with the real home folder. Accepted lanes
    carry `{kind: team_check, ref: <team>/<unit>/attempt-<n>/check}` for the
    matching todo item.
  - The record keeps a bounded list (newest 64) of renderable team events --
    `started`, `finished`, `check_passed`, `check_failed`, `repairing`,
    `blocked`, `done` -- each with a monotonic `seq`, the part's title as the
    teammate, one plain summary line and a reference into the record.
    `team_reconcile` and `team_status` return the events newer than the
    caller's `since_seq`.

  `omh_agent_board` is unchanged, pinned byte for byte by a fixture captured
  before this change. Board (kanban) lanes are not yet checked by `omh_team`.
  Hermes answers the approval itself under `--yolo`, `approvals.mode: off`
  or a cron `approve` mode; the command policy and Hermes' floor still apply
  there, but no person has read the list.

- **A plan item marked done now closes only on a recorded result.** The
  continuation rule stopped a plan once every item said done, so a run could
  mark an item done over a failed command, or tick several items off one
  command, and end its own loop. The `omh_todo` tool now binds every item
  itself and ignores any binding the writer sends. An item's window opens at
  its own last transition (declared, pending to active, out of done). At the
  done write it takes `done_at` and the latest `terminal`, `write_file` or
  `patch` call inside its window that no other item holds. The call is read
  from the session's own Hermes `state.db` (`mode=ro`, rewound rows ignored,
  bounded at the done write) and stored as a typed `evidence` reference
  `{kind, ref}`, with kinds `tool_call`, `file_write`, `pr`, `ci_run` and
  `team_check`. A failed binding is sticky across a reopen. A binding a `set`
  drops by a rename, a split or a removal is kept on the plan as
  `dropped_bindings`, and while it is a failure no item opened after the drop
  closes until one passes a command of its own. An item is also failed while
  the latest call before its done mark that no other item holds failed, and a
  file write does not close an item over a failing command in its window.
  Items that share a text pair with the stored items in order.
  `omh runtime todo set --items-json` refuses the binding fields.
  - **When an item closes.** The stop criterion reads that record, never the
    item's text. `tool_call` closes on a recorded `exit_code` of 0 inside the
    window; `file_write` closes on a landed write or a successful patch (#1922's
    outcome rules). An item with no reference closes when its window recorded
    no command and the session's last call before it did not fail, so a
    conversational item is not held open.
  - **When it stays open.** Any other done item is `done_unverified` and still
    open. The turn-end directive and the per-turn plan line name it in plain
    words, and the tool result carries its reason code (`no_evidence`,
    `evidence_failed`, `evidence_unresolved`, `evidence_unreadable`). An
    unreadable store is reported but never closes an item and never drives the
    loop.
  - **How to close it.** Mark the item done again after a passing command, or
    give it a `blocked_reason`.
  - **What is not resolved yet.** `pr`, `ci_run` and `team_check` are accepted
    but resolve nothing, since OMH makes no network call.
  - **What time cannot prevent.** Binding is by time, not content. `clear`
    removes the plan with its dropped bindings, and with two items active at
    once a pass or a failure can be bound to the wrong one. Both are stated in
    `docs/HARNESS_QUALITY.md`.
  - **What does not change.** Items done before this change, CLI writes and
    hand edits carry no binding and count as done as before. A no-op
    re-advance is not a write, so it cannot buy another turn-end nudge. The
    `omh_todo` schema is unchanged, and the new `done_unverified_plan`
    per-turn scenario sits under the existing limit.

- **Data pipeline work has an owner: `omh-data-pipelines`.** "our airflow etl
  backfill is producing duplicate events", "replay the last three days of
  kafka events into the warehouse without double counting", "the dbt model
  changed its schema, what breaks downstream" and "make this spark job
  idempotent so a rerun does not duplicate rows" used to ask a question led by
  `github-event-ops`, `backend` or `github-issue-intake`. They now dispatch to
  a skill whose idempotency and replay are outputs of their own:
  - `idempotency_contract/v1` names the key that makes a rerun safe and what
    happens to a row written twice;
  - `replay_backfill_plan/v1` bounds the window and targets and writes
    through that contract, so a second run changes nothing;
  - `lineage_map/v1`, `schema_change_impact/v1` and `data_quality_gate/v1`
    name the downstream readers, what breaks for each, and the observed
    checks a load must pass before readers see it.

  The idempotency patterns, the schema compatibility table, the replay
  procedure and the quality checks load on demand from
  `references/pipeline-method.md`. A team backfilling a position, a family
  lineage, duplicate calendar events and "sync my memory" stay away. OMH runs
  no job and queries no warehouse (#1565).

- **Routing reads the file a request names, not only its words.** A skill
  may declare `path_globs`; when the request names a matching path and uses
  one of the skill's own trigger words, the skill gains a path score.
  "review the change to infra/network/main.tf before we apply it" and "apply
  the change in charts/payments/values.yaml to staging first" now dispatch to
  `iac-change` without the word "terraform" or "helm" carrying them. A path
  named in passing ("I saved my grocery list as main.tf, what should I cook
  tonight") adds nothing. Only `iac-change` declares globs (`*.tf`,
  `*.tfvars`, `*.tofu`, `charts/**`, `k8s/**`, `kustomization.yaml`,
  `pulumi.*.yaml`), so every other skill routes exactly as before (#1716).

- **Infrastructure-as-code changes have an owner: `omh-iac-change`.**
  "terraform plan shows drift in the kubernetes cluster, stage the apply"
  used to ask a question led by `plan`; a Helm chart values change, a Pulumi
  preview with replacements and a Terraform cost estimate had no owner at all.
  They now dispatch to a skill that reads six named outputs from the saved
  plan, not from the code diff:
  - `drift_assessment/v1` separates drift already present from the change;
  - `blast_radius/v1` lists every replacement and destroy, and a stateful one
    waits for explicit approval;
  - `cost_delta/v1` is observed or marked unestimated, never zero;
  - `staged_apply_plan/v1`, `health_gate/v1` and `rollback_plan/v1` give
    every stage a promoting signal and a way back, and apply only the reviewed
    saved plan.

  The per-tool drift, plan, health and rollback commands for Terraform and
  OpenTofu, Pulumi, CloudFormation, Kubernetes and Helm load on demand from
  `references/iac-change-method.md`. Application releases stay where they
  were: shipping a new app version to a cluster and watching it is
  `deploy-and-monitor`, and cutting or rolling back a release is
  `release-cut`. OMH applies nothing (#1566).

- **A version bump reaches the upgrade plan, and "safe to merge" is a
  call-site verdict.** "dependabot bumped express 4.18 to 5.0, safe to merge",
  "upgrade react from 18 to 19" and "upgrade python from 3.11 to 3.13" used to
  ask a question led by `verification-gate`, `frontend-refactor` or
  `native-debugging`, and a bump that arrived as an opened PR dispatched to
  `github-event-ops`. They now dispatch to `refactor-plan`, which already owned
  dependency upgrades:
  - a spoken version jump counts only with an upgrade verb, two version
    numbers and a word of software, so "upgrade my iphone from 14 to 16" and
    "the price bumped from 10 to 12" stay away;
  - a bump that carries a CVE, a security advisory or a leaked secret stays an
    event for `security-event-response`;
  - the plan is not ready, and the bump is not safe to merge, while any
    breaking change lacks its call sites in this repository (or an observed
    empty search) or any stage lacks its rollback. The table and the
    per-stage rollbacks are in `references/dependency-upgrade.md`.

  `github-event-ops`, `security-event-response` and `refactor-plan` each name
  the other side of the dependabot split (#1712, #1694).

- **Which files a Hermes session touched is now answerable:
  `omh quality-evidence file-activity --hermes-session <id|latest>`.** A
  tool-call count could not say which files a run read, wrote, or patched.
  The new command reads one session's `read_file`, `write_file`, and `patch`
  calls from Hermes' `state.db` (read-only) at query time and lists each
  workspace file with its operation, the outcome Hermes recorded
  (`succeeded`, `failed`, or `unknown`, from the result's own fields, never
  its wording), and first/last time. Every file of a V4A patch is listed.
  Paths are workspace-relative; a path outside the workspace is counted by
  reason and never shown. The list is bounded by `--max-files`, and
  truncation is reported. Plain text by default, `session_file_activity/v1`
  with `--json`. OMH keeps no new store and records nothing during the
  session (#1813).

- **`agent-debug` has a report it can cite: `omh quality-evidence agent-debug`.**
  The skill declared `agent_debug_report/v1` and nothing produced one, so a
  plausible story about a looping run read the same as a diagnosis.
  `omh quality-evidence agent-debug --hermes-session <id|latest>` now reads
  one session from Hermes' `state.db` (`mode=ro`, through the same open and
  session resolution the reply lint and session-usage report use) and
  reports four finding kinds derived from record fields only:
  - `tool_error`: a non-zero `exit_code`, `success: false`, or a non-empty
    `error` in the tool result's JSON;
  - `identical_retry_after_error`: the same tool called next with
    byte-identical canonical arguments after an error;
  - `background_without_notify`: a started process (`pid`) whose result
    recorded `notify_on_complete` not true;
  - `compaction_boundary`: a `_compressed_summary` row.

  Each finding cites session, message and tool-call ids, tool name, error
  class, exit code and timestamps, and quotes no prompt or tool output. A
  validator refuses a finding without the citation its kind needs, a
  citation naming another session, and any key outside the closed citation
  shape. Calls count once per distinct `tool_call_id`, so a compaction's
  re-persisted rows do not double up, and a kind whose column this Hermes
  build lacks is listed `unavailable` rather than clean. Plain text by
  default, `--json` for the payload; the `agent-debug` skill now points at
  the command (#1799, first slice).

- **The repo's agent instruction file has an owner: `omh-agent-instructions`.**
  "set up AGENTS.md", "update our CLAUDE.md" and "write an AGENTS.md for this
  repo" used to ask a question led by `rules-distill` or `memory-sync`. They
  now dispatch to a skill that writes and keeps current what an agent cannot
  derive from the code:
  - every instruction file and the agent that reads it are listed first, and
    the closest file wins;
  - every command written into the file is marked verified with its observed
    run, or unverified;
  - updates replace only the text between `<!-- omh:agent-instructions:begin -->`
    and `<!-- omh:agent-instructions:end -->`, so hand-written sections stay
    byte-for-byte;
  - counts, line numbers and anything else the code already states are
    refused, with the command or file that derives them written instead.

  The file table, the marker convention, the section order and the "what
  never goes in" table load on demand from
  `references/instruction-file-method.md`. Distilling lessons into AGENTS.md
  rule candidates stays with `rules-distill`, and each skill names the other.
  A question about what a CLAUDE.md says is not a request to write one, so a
  bare file name is not boosted (#1713).

- **Deciding and undoing a release has an owner: `omh-release-cut`.** "cut a
  release and tag it", "roll back the last deploy" and "set up a canary for
  this service" used to ask a question led by `img-summary`,
  `deploy-and-monitor` or `ops-observability-card`. They now dispatch to a
  skill that plans the release with its rollback decided before it is needed:
  - what goes in, what is held back, and the version derived from the change
    classes come first;
  - the cut freezes the release branch until the tag is pushed, then passes
    the approval gate, publishes, and curates the notes;
  - every rollout stage promotes on a named health signal, not a clock;
  - `release_readiness_verdict/v1` reads ready only with a named rollback
    trigger and the exact command that performs it.

  The cut sequence, the rollout stage table and rollback by mechanism load on
  demand from `references/release-and-rollback-method.md`. Watching a rollout
  that is already running stays with `deploy-and-monitor`, and each skill
  names the other. OMH prepares; the host or CI tags, publishes, deploys and
  rolls back. "cut a release", "canary" and "release candidate" keep this
  route only beside a word of shipping software, so a band's album and a pet
  canary stay out (#1693).

- **Security events on shipped code have an owner:
  `omh-security-event-response`.** "triage this CVE in our dependency tree",
  "we committed a secret, what now" and "is this dependency's license OK for
  us" used to ask a question led by `feedback-triage`,
  `provider-profile-posture` or `idea-to-deploy`. They now dispatch to a skill
  that responds to the event:
  - the event kind and its exposure window come first;
  - severity is called from the reachable path, not the version number;
  - for a leaked secret, the rotation and the old credential's observed
    rejection come before any history rewrite;
  - `event_closure_verdict/v1` reads closed only when the rotation or the
    fixed version is observed, and names each step still prepared.

  The per-event containment order, the severity adjustment and the license
  obligation table load on demand from
  `references/event-containment-order.md`. A dependabot security advisory is
  an event even when it arrives as an opened PR, so it reaches this skill
  instead of the `github-event-ops` card; a dependabot version bump with no
  advisory is not an event and stays out. `security-safety-review` keeps a
  planned rotation with no exposure, and each skill names the other. OMH never
  scans, contacts a registry, or rotates a credential. "security advisory",
  "leaked secret" and "license ok" keep this route only beside a word of code,
  so a travel advisory and a driver's licence stay out (#1694).

- **Relational database work has an owner: `omh-relational-db`.** An online
  migration on a 200M-row table, a seq-scanning query that needs an index,
  N+1 queries from an endpoint, and when to shard all used to ask a question
  led by `backend`, `ultraperf` or `agent-board`. They now dispatch to a skill
  that plans the database change with the checks that prove it safe to run:
  - engine, version and table sizes come first;
  - an index is proposed only against an observed query plan, with its size
    and write cost;
  - every online migration step carries the lock it takes, its
    `lock_timeout`, its batch size and its rollback;
  - `migration_readiness_verdict/v1` reads ready only when no step lacks lock
    behaviour or a rollback.

  The per-engine lock tables (PostgreSQL lock modes by statement, MySQL
  online DDL), the expand/backfill/switch/contract order, index-type
  selection, N+1 detection and the partition-or-shard projection load on
  demand from `references/engine-lock-tables.md`. `backend` keeps
  `schema_migration_plan/v1` for a service change, and each skill names the
  other. OMH never connects to a database. "what index", "alter table",
  "took a lock" and "need to shard" keep this route only beside a database
  word, so an index fund and a kitchen table stay out. "ALTER TABLE took a
  lock during deploy" on its own is a report with no ask. It stays a direct
  answer while the plugin route hint names the skill, and the same sentence
  with an ask dispatches (#1692).

- **Git branch repair has an owner: `omh-git-workflow`.** "resolve this merge
  conflict", "bisect to find which commit broke it" and "clean up this
  branch's history before review" used to ask a question led by `memory-sync`,
  `github-event-ops` or `code-review`. They now dispatch to a skill that first
  inventories what is already pushed: each branch's local head, its remote head,
  and whether others may have fetched it. It then orders the conflict
  resolution, the bisect, or the rewrite, with a recovery point in front of
  every step that rewrites history. Every force-push in the plan uses
  `--force-with-lease`. Counted and generated files in a conflict are
  re-derived from their producer, never picked. The conflict, bisect,
  rewrite, stacked-branch and shared-checkout procedures load on demand from
  `references/git-repair-method.md`. "bisect", "force push", "cherry-pick" and
  "resolve the conflict" keep this route only beside a repository word, so an
  angle, a car in the snow, an orchard and two teams in conflict stay out
  (#1695).

- **Commit messages and PR bodies have an author: `omh-commit-pr-authoring`.**
  "write the commit message" and "draft the PR body" used to ask a question
  led by `backend` or `content-operator`. They now dispatch to a skill that reads
  the repository's own PR template and recent log first, builds an evidence
  ledger of every command as observed or not_observed, and drafts the text
  from it. `Tested:` lists only rows observed to run; everything prepared,
  planned, or skipped goes under `Not-tested:`, and no wording promotes a
  row. OMH drafts the text only, and never commits, pushes, or opens the PR.
  The PR phrases keep this route only beside a code word, so "a PR
  description of our product launch for the press release" stays out
  (#1711).

- **Application-code debugging has an owner: `omh-app-debugging`.** A wrong
  value, a flaky test, or a lost update in a Python or TypeScript service
  used to dispatch to an execution lane that skipped the diagnosis ("a test
  fails one run in five in CI" went to `command-operator`, "two workers
  write the same row, one update is lost" to `ultrawork`), because the three
  debugging skills each scoped this case out. The new skill records an
  observed reproduction with its hit rate first, writes at least three
  competing hypotheses on distinct axes, orders observations cheapest first
  by which hypotheses each eliminates, and keeps `fix_handoff/v1` blocked
  until `reproduction_record/v1` reads observed. The hypothesis table,
  flaky-test tactics and race patterns load on demand from
  `references/hypothesis-and-race-method.md`. `native-debugging` and
  `build-failure-triage` each name the boundary back. "Root cause", "race
  condition" and "update is lost" keep this route only beside a word of the
  code being debugged, so "the root cause of my back pain" and "my phone
  update is lost" stay out (#1709).

- **A debugging-shaped fanout now holds its edit units until the dispatcher
  has watched the failure reproduce.** A split declares itself
  debugging-shaped with a `kind: "reproduction"` unit carrying a
  `reproduction_command`; the request text is never read. Every other unit
  must reach that unit through `depends_on`, or the freeze is refused. Under
  `--run-verification` the dispatcher runs the command in the reproduction
  unit's worktree and records a `fanout_reproduction/v1` receipt. Only an
  observed nonzero exit (`failure_reproduced`, `observed_by: dispatcher`)
  admits the dependents. A dry-run plan, an unrequested run, a command that
  could not start or timed out, and an observed exit 0 (the failure did not
  reproduce) all keep them `blocked_by_dependency` with the reason
  `reproduction_not_observed`. The verdict is journaled as
  `reproduction_failure_observed`, so a later dispatch that skips the
  completed reproduction unit reads it instead of re-running it. A split
  without a reproduction unit freezes and dispatches exactly as before.
  Closes #1699.
- **A coding handoff now carries the project's codegraph, and the codegraph
  ranks files by structure.** When a handoff is built with a project root and
  that project stores a codegraph artifact (`omh codegraph build --write`), the
  handoff carries a `handoff_context_pack/v1` derived from it: up to twelve
  repo-relative focus files, each a `source: omh_codegraph` item with the new
  `static_analysis_hint` truth level, and the handoff's input manifest lists
  them. A caller-supplied context pack still wins, a project without an
  artifact gets byte-identical output (50 payload digests across five messages,
  five executor targets, and with and without a project root match
  `origin/main`), and an artifact that is corrupt or of another schema is
  named in `codegraph_context_not_attached` rather than read as absent. The
  ranking behind both `omh codegraph handoff` and the pack is now a
  personalized PageRank over the scanner's internal import edges, restarted at
  the files that match the task (terms weighted by how few files carry them)
  and at files already in play, so a module the task's files depend on
  outranks a leaf that only shares a word with the task. It is deterministic:
  fixed damping, iteration cap and tolerance, ties broken by path.
  `omh codegraph handoff` gains `--changed <paths...>` to seed the walk, and
  its JSON gains `changed_paths`; focus-symbol ranking is unchanged. Closes
  #1696.
- **Visual QA can now cite a host's browser motion capture for the exact
  condition it recorded.** `visual-qa` has always asked for
  `motion_interaction_capture/v1` when transitions or interactive states are
  in scope, but OMH had no way to accept one. `omh web-qa observation motion
  import` (agent/operator) now admits a host's metadata-only
  `host_motion_capture_receipt/v1` against one planned matrix cell. The
  receipt carries the recording digest, media type, size, duration, and frame
  count, the producer's requested and observed settings, and optional
  contact-sheet tiles that each name the recording digest. It stores a
  `motion_interaction_capture/v1` record under
  `.omh/web-visual-qa/motion-captures/<run_id>/` and never any media bytes.
  The import is refused, with one named reason, when the lineage differs from
  the plan cell, the revision isn't the checkout's `HEAD`, a tile or the sheet
  names another recording, a digest is malformed, the media type is
  unsupported, a bound is exceeded, a key names a path, or the metadata
  carries secrets. Re-importing the same receipt writes nothing, and a new
  digest or cell gets a new identity. `motion gate` cites a record only for
  its own run, revision, round, route, state, viewport, and browser, and it
  can hold a run's verdict or lower it to `BLOCK` but never raise it to
  `PASS`. Issue #1801.

- **`omh doctor` no longer tells you to rename a shared lifecycle hook.**
  When OMH and another Hermes plugin both subscribe to an event such as
  `pre_llm_call`, `pre_tool_call` or `on_session_end`, the
  `identity_conflicts` check still lists it as a warning, but its next action
  now says what is true: Hermes lets any number of plugins subscribe to one
  event, so nothing needs to change, and the other callback is worth a look
  only if its effect clashes with OMH's (both rewrite the same tool call, or
  both inject context). The doctor line reads "subscribed to by" rather than
  "claimed by", and the claim boundary says a shared hook has no winner to
  resolve. Next actions are now composed per kind: a contested tool name
  still blocks and leads with the rename-or-uninstall repair, and a contested
  skill directory keeps its own. The `identity_conflict_report/v1` schema,
  its severities and its `precedence` values are unchanged. Reported by
  @ComBba in #1902.

- **A turn that started remote work, was told nothing would wake it, and
  armed nothing anyway now ends by saying the session has stopped.** The
  plugin registers the optional `transform_llm_output` hook, which Hermes
  fires once per turn after the tool loop. It appends one sentence to the
  final response only when this turn's unarmed-wait directive (#1738) was
  delivered and a fresh read of `processes.json` still shows no live
  notifying background process for the session. It reads those records,
  never the response text, so a response that says it is waiting cannot
  trigger it, and a turn that armed a watcher, made no remote call, or whose
  records cannot be read passes through unchanged. The sentence is shown to
  the person and not added to the model's context: Hermes saves the
  transcript before this hook runs. This closes the end-of-turn half of
  #1721. Arming a watcher at that point is still impossible, because the
  hook cannot re-enter the turn loop.
- **`achievements` and `wiki` answer with their own chat card.** A request
  that dispatched to either skill, such as "show my badge progress for this
  month" or "help me build a wiki out of my project notes", got the generic
  "I know which workflow should handle this" acknowledgement, because neither
  had a routing policy of its own: `achievements` fell to the observability
  default (`refresh_status`) and `wiki` to the knowledge default
  (`prepare_memory_review`). Each now has a policy and a workflow card:
  `achievements_summary` (`show_achievements_summary`,
  `hermes_achievements_observation/v1`) summarizes unlocked badges, tiers,
  recent unlocks and next-tier progress from the local artifacts only, and
  `wiki_blueprint` (`prepare_wiki_blueprint`, `wiki_blueprint/v1`) sizes a
  wiki to its readers and maintainer or prepares destination-aware notes for
  an existing store. Both sentences are now intervention cases, so natural
  skill reach goes from 121 to 123 of 130 and both skills leave the
  unreached baseline.

- **Re-running only a sharded run's failed jobs now reconciles.** After
  "Re-run failed jobs", `aggregate` could read the earlier attempt's red
  shard result instead of the re-run's green one. Both attempts shared one
  artifact name, and `download-artifact` keeps the same-name artifact with the
  highest ID, which is not the newest (run 36302750878). Shard and quarantine
  results now carry `github.run_attempt` in the artifact name, the file name
  and the result JSON (`run.py --attempt`). `aggregate.py` reconciles each
  shard's newest attempt and prints the results it superseded. It stays
  fail-closed: a shard with no result in any attempt is red, two results for
  one shard in one attempt are red, and a stale green can never hide a fresh
  red (#1894).
- **A final-review lane now records whether it saw the author's context,
  and an inherited one cannot pass as independent review (#1698).** Every
  lane observation carries a required `context_provenance`,
  `fresh_from_diff` or `inherited_from_author`; an observation without it
  is refused at construction. The wave assesses an `inherited_from_author`
  lane, or a lane that completed with no provenance recorded, as `BLOCK`
  with `refused_field: context_provenance` beside the blocking lens.
  `execute_final_review_wave` takes the executor's declared provenance, and
  a runner result may declare its own. The built-in Hermes adapter declares
  `fresh_from_diff`, and each fan-out `final_review_records` row carries the
  field. Declaring provenance is not evidence that a review ran: a prepared
  lane stays `prepared_not_executed`.
- **Deep research tries one recovery before calling a blocked source a
  gap (#1527).** When a source answers HTTP 403, HTTP 429, a paywall, or a
  WAF or bot wall, the `research` skill now loads Hermes' bundled
  `blocked-page-recovery` skill once for that source when it is available,
  and never retries the same URL in a loop. An archive or cached copy it
  returns is cited as a dated historical capture, never as the live page.
  When the skill is missing, recovery fails, or the source needs a login or
  payment, the run names the retrieval gap with that reason, as before. The
  portable `agent-skills/ulw-research` body carries the same rule against
  the host's own recovery capability and does not name the Hermes skill.

- **A skill's trigger phrase used in its everyday sense no longer reaches the
  skill.** Nine sentences measured in #1899 carried a skill's own phrase whole
  and dispatched it, or led a clarify with it: "my phone had a silent failure
  of the alarm", "how many harness sessions does a sled dog need", "what is a
  weekly status review in a school parent meeting", "is a camera gate at the
  driveway worth installing", "habits that keep your skill health up as a
  pianist", "summarize the independent perspectives in this essay", "what is
  media input on an old VCR", "how do I cancel my gym membership" and "how
  long does it take to become a doctor". A tenth, "cancel my netflix
  subscription", dispatched `cancel` through the leading-name path. The
  router now keeps one table of these phrases, `EVERYDAY_SENSE_PHRASES` in
  `routing/policy.py`, with the lane words that mark each skill's sense. A
  skill withdraws when its phrase comes with other content and none of that
  content is a lane word. The phrase on its own ("silent failures", "cancel",
  "doctor") still routes as before, and an explicit invocation always wins.
  Catalog scoring, the operator-surface fast path, the harness-session guard,
  the bare leading name and the clarify shortlist all check the same table. Ten negative controls pin the sentences and ten
  intervention cases pin the lane sense of each phrase. Every case already
  in both corpora routes exactly as before, and `omh demo skill-reach` still
  reports 123/130 skills reached.
- **The cost receipt now counts Hermes kanban workers the conversation
  started.** `omh_cost_receipt/v1` gains a fourth source, `kanban_workers`.
  A worker run belongs to the conversation when its task's `tasks.session_id`
  (the originating session Hermes stamps at creation, inherited by a worker's
  follow-up tasks) is one of the conversation's sessions. The worker's spend
  is read from the session it stamped on its run
  (`task_runs.metadata.worker_session_id`), with that session's continuations
  and delegates, in the state.db of the profile the run was claimed for.
  Every board is read, the default one and each named one, read-only. The
  same honesty rules hold: priced usage, unpriced tokens and missing records
  stay apart. A worker that ran without stamping its session (crashed, or
  still running) is listed as missing, never as zero and never matched by
  timing or title. A session the delegate walk already summed is not counted
  again. The receipt names the boards it read and says when there is no board
  or one could not be read. "Hermes kanban workers" leaves the not-covered
  list; tasks created from the CLI or dashboard, which record no originating
  session, take its place.
- **The routing corpora now prove natural reach for 33 more skills and a
  negative control for every installable skill.** `omh demo skill-reach`
  (#1875) listed 35 skills whose own non-name trigger dispatches but that no
  intervention case reached without naming them, and 17 skills that no
  negative control entered. Thirty-three intervention cases, each a user's
  request built around one of the skill's own triggers, and seventeen
  negative controls, each using a skill's vocabulary in an unrelated sense
  (a Jev skill through a person named Jev), close all but two of those gaps
  without changing a trigger or the router. Natural reach goes from 88/130 to
  121/130 skills and negative-control coverage from 113/130 to 130/130.
  `achievements` and `wiki` stay listed: every dispatch to them answers with
  the generic `ack` chat response, which the intervention evaluator rejects,
  so no case can pass until they get their own response surface. The seven
  addressed-only skills (`meta-router` and the six `jev-*` skills) stay as
  they were.

- **A prepared coding handoff can carry a machine-checkable
  `handoff_contract/v1`, and its postconditions' exit statuses, not the
  report's wording, decide verification (#1715).** Before this, a handoff's
  acceptance criteria and verification were prose. Whether the executor met
  them was a matter of reading its report. Now `--handoff-contract
  contract.json` on `omh coding delegate` and `omh coding lifecycle start`
  attaches typed inputs, postcondition commands (compiled through
  `verification_plan/v1`), an optional output shape, and forbidden actions to
  the Codex, prompt-only, and runtime handoff schemas. The handoff is refused,
  with the offender named, when a declared input is unused or a template
  variable is undeclared. Forbidden actions and postcondition commands appear
  in the executor prompt's Don't and Test sections, not in the routing
  metadata. `omh coding lifecycle verify --postcondition-exit ID=STATUS`
  records integer exit statuses into `handoff_contract_receipt/v1`. On a
  contracted run, verification is observed only when every postcondition has
  exit status `0`. `--completion-status completed`, a wrapper
  `verification_observed` flag, or a word such as `passed` cannot promote it,
  and a contract that was never run says so. OMH still executes none of the
  commands. Handoffs without a declaration are byte-identical to before.
- **A cadence phrase in a report, or a command to fix a product defect, no
  longer dispatches a confident wrong skill (#1892).** `every morning` and
  `every day` are `automation-blueprint`'s own trigger phrases, and the
  own-phrase rule dispatched on them in any sentence: "every morning I drink
  coffee ..." opened a scheduled-ops blueprint. A phrase made only of a
  frequency and its time now counts as own-phrase evidence only when the
  message reads as a request: a request frame (`can you`, `remind me`,
  `I want`), a main clause after the cadence that opens on its verb, or a
  clause about a thing (`the report`, `our snapshot`) that carries a
  directive modal (`should`, `needs to`) or a passive of a delivery verb
  (`gets sent`) in its main clause, before any subordinator (`that`,
  `until`, `because`) or reporting verb (`says`, `thinks`). A clause about a person (`every morning I ...`) reads as a
  report even with a modal (`I should really ...`). Separately, the feedback-triage guard's weakest branch
  (a product noun beside a defect noun, no reporter) read "fix the null
  pointer crash in the checkout service" as a customer report and dispatched
  triage on trust earned by its reporter-shaped branches; that branch no
  longer fires when the message's command verb is an edit verb. Both now ask:
  the first with `automation-blueprint` first, the second with a coding skill
  first. Recurring requests ("every morning check release risk and tell me on
  Slack ...") and defect reports ("the checkout page crashes on submit")
  still dispatch, and so do subject-initial and passive scheduling requests
  ("every morning the report should go to Slack", "every morning our
  dashboard snapshot gets sent to leadership"). Sixteen negative controls and
  ten intervention cases pin both sides; no existing corpus case moved. Known
  limit: a thing-subject habit with a modal ("every morning my dog needs to
  go out") still dispatches, as on main; separating it needs noun vocabulary.
- **A routing guard dispatches on its own only when its measured record is
  at least 3 right per wrong, unless demoting it breaks a quality floor.**
  `GUARD_DISPATCH_TRUST` now reads each guard's record as the dispatched
  winner on the tuning set. Eight measured guards under 3:1 become
  context-only (browser, coding-handoff status, workspace file, deliverable
  package, scheduled ops, voice, research brief, ops observability). Nine
  more under 3:1 stay trusted because demoting them breaks a product quality
  floor (routing accuracy, known-lanes baseline, grounded score, route-hint
  alignment, chat-card and common-request coverage, the ulw-equivalence
  digests) or removes no measured wrong dispatch; each reason names which.
  Guards never measured keep their shape label. No predicate or vocabulary
  changed; a context-only guard still boosts and reorders the field, and its
  winner asks with itself first on the shortlist. On the tuning set
  (in-sample, English, n=390) wrong dispatch falls from 7.9% to 5.9%; the
  intended skill is dispatched or first on the shortlist at the same 37.7%,
  and on the shortlist at 71.3% (69.7% before). The owner's held-out set was
  not read for this change. Canonical coding requests keep dispatching to
  `ultrawork`. 7 intervention cases and 18 unit-test rows are re-pinned to a
  clarify, each with the intended skill first. `browser-operator` keeps
  natural reach through a new case on its own phrase ("run a playwright task
  ..."), paired with a negative control.
- **The awareness section registers once per plugin manager, without a warning
  on every session.** `register()` runs on both the plugin loader and the
  memory-provider loader, so the `omh.awareness` system-prompt section was
  offered twice per process; Hermes rejected the second and its memory-provider
  collector logged `failed to register_system_prompt_section ... already
  registered by plugin 'omh'` on every session init. The plugin now checks the
  context's own manager (per `HERMES_HOME`, so each profile of a multiplex
  gateway still registers its own) and skips a section that manager already
  holds. The check reads Hermes internals; if they change, the duplicate attempt
  and its warning come back and nothing else does. Reported and first fixed by
  @kssd in #1887.

- **Korean work requests get a skill candidate line too.** The per-turn line
  ranked ASCII words only, so an all-Korean request never got one. The
  generated shortlist index now also carries the syllable bigrams of the
  Hangul triggers the catalog already has (no trigger was added; the frozen
  per-skill Korean counts do not move), ranked with the same BM25 constants
  and admitted on their own floor: anchor bigrams in two words of the
  message, or one rare word at a high score. A message the ASCII ranking
  admits keeps its line. The awareness primer now scopes OMH skills by the
  work signal instead of listing everyday topics (weather, prices, travel),
  a list that also described real requests such as an exchange rate for an
  invoice; two openings get back what Korean requests to them are about
  (`omh-image-cards` names meeting notes, `omh-live-info` a rate or local
  time a work task needs). Measured live (deepseek-v4.1-flash-ultrafast, one
  Hermes turn per message, own sets written for this change): Korean work
  requests loaded the intended skill 85.6% of the time over two runs
  (81.2/90.0) against 71.9% on main (72.5/71.2); 0 of 40 everyday Korean and
  0 of 20 everyday English messages loaded an OMH skill on either side (one
  run); English work stayed at 81.2% on both sides (80.0/82.5).
- **CI runs the Windows unit tests in four shards.** Each of the two
  `test-windows` shards ran about 7,200 tests in roughly 35 minutes, against
  about 13 minutes for a Linux shard, so Windows set the wall clock of every
  run. The `plan` job now also writes `plan-windows.json`, a 4-shard plan over
  the same inventory, timing history and quarantine; the Linux lanes keep their
  2-shard `plan.json`. `aggregate.py`
  takes `--lane-plan LANE=PATH`, checks each lane against the plan that lane
  ran, and fails when a lane plan covers different tests or a different
  quarantine, or when any shard of a lane's own plan is missing. The planner
  also seeds two known loads before balancing: a declared `--shard0-offset`
  for the non-test gates shard 0 runs (90 s on Windows, 25 s on Linux, from
  measured step medians), and the serial quarantine's duration on the last
  shard. The quarantine now runs in its own process after each lane's last
  shard instead of in three separate `test-quarantine` jobs, which queued for
  10 to 17 minutes under the 20-concurrent-job cap. A run now has 12 jobs
  (was 13 before this change).
  A new main push now cancels the main run it supersedes, as a new pull
  request push already did: in the 7 days to 2026-09-26, 32 of 86 main runs
  were superseded before they finished, at ~140 job-minutes each. A red main
  is then attributed to a range of merges; the tip run still tests all of
  them. The Linux `test` lane runs Python 3.11 only on a pull request, and
  3.11 plus 3.13 (in place of 3.12) on a main push or a `workflow_dispatch`,
  which the workflow now accepts; Windows stays on 3.12. No failed run in
  those 7 days was red only on Linux 3.12, while a 3.13-only defect had
  merged green (fixed by 13696e5d). `aggregate.py --event` requires exactly
  the lanes that event runs and fails when one is missing. A pull request run
  has 10 jobs, a main run 12.

- **A test shard can run in N worker processes.** `tools/test_sharding/run.py
  --workers N` hands a shard's test modules to N `-P` interpreters, each with
  its own temp root, and merges their outcomes into the same result JSON; a
  worker that dies turns every test it had not reported into an error. N=1 is
  the unchanged serial path and the quarantine stays serial. The first N=2
  run surfaced a latent order leak, not a parallelism defect:
  `mock.patch.dict(sys.modules, ...)` drops the modules a block first imports
  but leaves the parent package's attribute, so a later test got two copies
  of `document_chunk_plan` and its patch missed. The serial runner imports
  every test module before running any, which hid it. Every `sys.modules`
  patch in `tests/` now goes through `tests/_module_patch.py`, and
  `tests/test_module_patch_policy.py` fails on one that does not. The TUI
  widget test harnesses no longer call `process.exit`: the widget's first HUD
  read is a python child in the test's temp directory, and exiting under it
  left the child holding the directory on Windows (WinError 32 at cleanup).
- **Hermes turns name the skills a work request may fit.** On a turn whose
  request reads as work, the plugin adds one line naming up to three
  installed skills with the situation each serves, and the model may load
  one with `skill_view`. The candidates come from the same BM25 ranking the
  router's shortlist uses, shipped to the plugin as a generated index
  (`omh docs skill-shortlist`, checked byte-for-byte). The line needs a
  catalog-rare word from a skill's own situations or triggers, and stays
  away from greetings, factual questions, jokes, recommendations, personal
  advice, a workflow the person named, and messages with no ASCII words. A
  session sees the same candidate set once. The awareness primer also says
  which requests OMH skills are for. Measured on a live model (GPT-6 Luna,
  one Hermes turn per message, one run per arm), the intended skill loaded
  for 90% of a 150-request work set (78% on main). The everyday target was
  missed: 32.5% of an 80-message everyday set still loaded an OMH skill
  (38.8% on main), against a 10% target. Most of those loads had no
  candidate line; the model picked the skill from the host's skill index.
  Requests written without ASCII words got no line here; Korean ones now do
  (see the entry above).
- **Shortlist first: the router dispatches only on strong evidence and
  otherwise hands Hermes the shortlist.** A confident score dispatches only
  on an explicit or named invocation, the winner's own trigger phrase (unless
  another skill said an equal phrase), or a trusted intent guard.
  The pinned canonical requests without a phrase of their own ("the CI build
  is failing on main", "review PR 1234", "deploy the app to production") ask,
  with the intended skill first on the shortlist, for Hermes or the user to
  confirm; paraphrases of them ("restyle the settings screen", "look over this
  merge request") are not guaranteed the same order. Every guard is classified in
  `GUARD_DISPATCH_TRUST`, trusted only where its predicate is intent-shaped
  and its measured record supports it; guard fast paths answer to the same
  table. Everything else -- trigger tokens, a one-word name, a context-only
  guard -- clarifies with reason `weak_dispatch_evidence`. The clarify
  carries up to four candidates: the declined winner first, scored skills
  with evidence of their own, then a BM25 ranking over each skill's name,
  triggers, situations, description, and use_when. The clarify card tells the
  model to pick the workflow whose situation matches, naming each by the
  situation its description opens on; `route_question` asks the same
  shortlist. Guards and fast paths that fired on a word used in passing were
  narrowed with vocabulary-level rules and negative cases (failure-outcome
  words, check verbs, a cadence of a frequency word before a time, code-unit
  nouns, own-skill inventory questions, system memory, bare verb names before
  a plain noun), and single words that only mean a skill inside its phrase
  are held back so they stop deciding which skill leads the shortlist. Measured in-sample on the 501-message tuning set these rules
  were checked against: wrong dispatch 30.9% -> 9.8%, intended skill
  dispatched or shortlisted 34.3% -> 62.7% (English: 7.9% and 69.5%). On the
  owner's held-out English set, before the follow-up that removed
  tuning-probe wording from the predicates, wrong dispatch went 40.4% ->
  25.3% and reach 43.2% -> 62.2%; the reach target of 85% is not met.

- **Every installable skill is checked for routing reach, and a skill the
  corpora never reach fails CI by name.** `omh demo skill-reach` (operators
  and agents) projects the two routing-precision corpora per skill on the
  deciding surface: intervention cases that dispatch to it without an explicit
  invocation, cases that reach it only when addressed, and negative controls
  that enter its territory and stay unrouted. `tests/test_skill_reach.py`
  fails naming each skill with no natural dispatch case or no negative
  control, unless it is in a shrink-only baseline whose reason is re-measured
  on every run: `corpus_gap` holds only while one of the skill's own non-name
  triggers dispatches to it, and `addressed_by_design` (the `/omh` sigil and
  the Jev skills) only while an addressed case reaches it and no non-name
  trigger does. A baseline entry for a skill that became reachable fails too.
  Measured at landing: 130 installable skills, 88 with natural positive reach
  and 42 without (35 corpus gaps, 7 addressed by design); 113 with a negative
  control and 17 without. A case where the router asks with the skill first
  is shown as `shortlist_first_cases` and not counted as reach. No trigger
  or routing behavior changed.
- **A fanout unit's "done" can include the tests its own changes reach.** A
  unit may declare `task_linked_test_runner` (for example
  `PYTHONPATH=tests python -m unittest`). Under `--run-verification` the
  dispatcher reads the committed diff it observed, selects every test module
  that directly imports a changed file through the local codegraph, and runs
  the runner on them as one more dispatcher-observed check, so its exit status
  decides the unit the way every declared check does; the prompt's criterion
  names the same rule. A failing check now records `unit_state_reason:
  verification_failed` instead of `verification_not_observed`, and an earlier
  attempt's journaled pass no longer outlives a failure in the current one. A
  change no test imports adds nothing, and an unreadable diff fails closed. The
  product A/B bench's gate runs the same rule over the candidate's diff (the
  task's own test files excluded), so it no longer only re-runs the criteria
  the model already ran green.
- **`omh update` says what changed for you.** After the new generation is
  installed, the update prints a short "What changed for you" block: skills
  added (with what each is for), removed, or given new instructions; skills
  that now pick up different requests (the trigger phrases gained or lost);
  and the model chains on this machine whose shipped default moved, shaped by
  this machine's providers -- or "your own chain for it still applies" where
  the user overrides that category. The comparison reads only OMH's own
  records (the managed manifest's per-skill checksums and a new
  `runtime/update-baseline.json`), so a user's config edits never appear as
  an OMH change. A first install says there is nothing to compare, and an
  update that changed nothing prints nothing. The note is kept at
  `runtime/update-change-note.json`, and `omh_status` returns it as
  `last_update_change_note`, so asking Hermes "what changed in OMH?" answers
  from the record; nothing is added to the per-turn context. English by
  default; `--language` / `OMH_LANG` localize it.
- **Asking "how much did this task cost?" in chat gets a receipt.**
  `omh_run_summary` now returns a `cost_receipt` (`omh_cost_receipt/v1`) that
  sums the calling conversation's recorded spend: its session rows and
  compression continuations, every delegated Hermes child below it, and fanout
  units that recorded the conversation as their origin. `omh coding fanout
  dispatch` stamps that origin (`origin_session_id`) from the
  `HERMES_SESSION_ID` Hermes gives terminal commands. Observed cost, usage with
  no recorded price, and records with no usage stay apart; nothing is
  estimated, and every receipt names what it does not cover. Operators get the
  same text from `omh quality-evidence cost-receipt --session <id>` (`--json`
  for the payload).
- **"Continue what I was doing" works across Hermes surfaces.** A new
  read-only plugin tool, `omh_resume`, returns the person's recent OMH work
  from their other sessions in the same profile: the plan todo each session
  declared (last 24 hours) and the completion checkpoints it froze (last 30
  days), joined to Hermes' own session rows for the surface, timing, tool-call
  count, repository name and branch. Plain text is the default rendering, in
  the `text` field. Who counts as the same person comes only from `state.db`:
  every local surface (`cli`, `tui`, `desktop`, `acp`) is the profile's user,
  and a chat-platform user counts only in a direct message (`source` +
  `user_id`, `chat_type` `dm`), so one Slack user never sees another's plan,
  the local user never sees theirs, and a group channel or thread, where
  anyone can ask and everyone reads the answer, is refused. Hermes
  records no link between a platform user and the local user, so that
  crossing is not made; a surface that names no person (webhook, cron, a
  delegated subagent session) is shown nothing. A session another profile's `state.db` lists is never read,
  even when the profiles share one OMH home. Metadata only: no session title,
  activity description, deferral reason or transcript. Nothing is added to
  `pre_llm_call` or the primer; the tool schema raises
  `PLUGIN_TOOL_SCHEMA_CHAR_LIMIT` 59258 -> 60678.

- **The plugin admits a Hermes git checkout by the release it resolves, not
  the install stamp's placeholder.** Released Hermes through 0.21.5 hard-codes
  `hermes_cli.__version__`; hermes-agent main now serves it from the install
  stamp only, so a checkout without one -- a source install, and the
  plugin-catalog CI that clones Hermes to run `hermes plugins validate` --
  reports `0.0.0`, and OMH refused to register there. The bundle now reads
  `hermes_cli.version_info.get_version_info().base_version` when the host has
  it, the value Hermes' own `requires_hermes` gate compares, and falls back to
  `__version__` on released hosts. An unsupported or unknown release is still
  refused.

- **Skill descriptions open on the user's situation.** Hermes shows a model
  each skill's name and the first 57 characters of its description; on the
  previous catalog half of those windows began "Hermes ..." and most spent
  characters on the word "workflow". Every installable description now reads
  "<situation the user is in>: <what the skill produces>" (for example
  "Remember a fact for future sessions: ..."), and no two skills share a
  three-word opening. `SkillDefinition` gains `situations`, 5-10 plain English
  phrases per skill in the words a user would use; the lexical shortlist
  reads it and nothing scores or renders it. Routing results on both
  precision corpora are unchanged.
- **Skill openings name the work context a model needs to tell them from
  private life.** Many situation openings also described private life: a
  weekend plan, a personal budget, a performance review, a book club
  meeting. A live model loaded them for everyday chat. 26 openings now put
  the work context inside the visible window, for example "Company hiring or
  HR process to structure", "Upcoming work meeting that lacks an agenda" and
  "Support ticket your team must answer or escalate". On a 120-message
  everyday-chat set (GPT-6 Luna, one Hermes turn each, two runs per side),
  the share that loaded an OMH skill fell from 69% to 44%. That is still far
  above the 10% target. `omh-live-info` alone accounts for about 19 of
  those loads, whatever its opening says. On a 130-request work set the
  intended skill loaded in 67.0% of runs, against 70.8% on main.
  Routing results on both precision corpora are unchanged.
- **The plugin bundle passes `hermes plugins validate`, and a plugin Hermes
  installed is left to Hermes.** The Hermes install scanner read the dict-key
  constant `PRIVATE_TOKEN = "__omh_egress_attempt_token"` as a hardcoded
  secret (`dangerous`), which fails a curated-catalog entry; it is now
  `PRIVATE_ARGUMENT_KEY`, and a test applies the scanner's own
  `hardcoded_secret` pattern to every bundle file. `omh setup` and
  `omh update` read Hermes' install records (`plugins/.install-metadata.json`,
  the `.hermes-catalog.json` sidecar): a `plugins/omh` that
  `hermes plugins install` wrote, and OMH did not write after it, is reported
  as host-managed and not overwritten, `--force` included, while skills and
  config are still managed, and a bot profile's row says `host_managed`
  instead of `refreshed`. `omh uninstall` keeps that tree, `--force`
  included, and names `hermes plugins remove omh`. `omh doctor` reports it as
  installed by Hermes, says whether its files match the installed OMH
  package, and reports a hook whose bytes differ from the package's reviewed
  digest as version skew (a warning naming `hermes plugins update omh`), not
  tampering; the hook-integrity record is read only by doctor, so nothing
  changed at runtime. A directory with neither OMH's manifest nor a Hermes
  record is still refused.
  The documented install is unchanged.
- **The OMH awareness primer now lives in the session's system prompt, not in
  the first user message.** Hermes 0.20.2 (tag v2026.8.16) added
  `register_system_prompt_section`: text rendered once per new session and
  frozen into its system prompt. Every Hermes the plugin admits (0.21.1 and
  later) has it. The plugin registers the primer (1,044 chars, the same text
  for every session) as the `omh.awareness` section, under the host's
  4,000-char per-section cap. `pre_llm_call` no longer carries it for a
  session the section rendered for. Before, the primer went into the fenced
  user-message context on the first turn and again after a compaction dropped
  it. A session keeps the old per-turn path, and can carry the primer twice,
  unless its own first turn confirms the section: a routed background-review
  fork renders under its parent's session id, so a render alone is not
  trusted, and a fork runs with the parent's history, so its turn is never a
  first turn. The fallback cases: a host without the API or a section the
  host refuses; an unconfirmed record (a parent resumed after a restart whose
  first review fork renders the section); a
  session resumed after a restart, where the host restores the section
  without calling the plugin; a legacy compaction that rotates the session
  id, where Hermes rebuilds the prompt before assigning the new id
  (`conversation_compression.py`); and an id evicted from the plugin's
  1,024-session record (least recently used first). "Never zero" has two
  stated gaps: a section the host drops past its shared budget (below), and
  a review fork of a parent with no history at all, which would pass as a
  first turn. The largest measured `pre_llm_call` context on a
  section host drops from 6,260 to 5,214 chars
  (`PRE_LLM_CALL_CONTEXT_CHAR_LIMIT`); the fallback keeps its own gate at
  6,260 (`PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT`, scenario
  `all_surfaces_without_section`). Everything else the hook sends depends on
  the turn and stays where it was. Every prompt Hermes builds now carries the
  primer, including `hermes prompt-size` inspection builds and routed
  background-review forks. `omh doctor` counts a section delivery once per
  session, on the first `pre_llm_call` that leaves the primer to a confirmed
  section,
  so a working install does not read as zero deliveries; a render with no
  turn behind it (prompt-size, a review fork) counts nothing, and an install
  with neither still warns. Known limit: Hermes renders sections in sorted-id
  order against an 8,000-char budget shared by every plugin, so a plugin whose
  id sorts before `omh.awareness` spends it first; a section dropped past that
  budget is dropped after rendering, with no signal a plugin can read. Such a
  session gets no primer (the host logs a warning) and is still counted as
  delivered.

- **The product A/B lane measures honestly where it contradicted itself.**
  `benchmarks/product-ab/v1` gave the OMH arm a file scope (`src/`, `tests/`)
  that forbade the completion file its own contract required, and one model
  declined two of five tasks over that conflict without a tool call; the scope
  now names the file and `doctor` fails when it stops doing so. Each
  verification criterion is rendered by the function that builds the gate's
  argv, so the model reads `PYTHONPATH=tests python3 -m unittest …` rather
  than a command that failed as written. The transport filter is derived from
  a sentinel check, so a criterion the protocol adds before the unit's checks
  is no longer dropped silently. Records (`omh_product_ab_run/v2`) say the gate
  never runs the hidden validator and passes on an untouched checkout; the
  gate reads the restored regression modules the grader reads; the report
  counts absent and blocked claims per arm, prints the gate disclosure under
  the table, lists PR-914 as a known corpus defect, and records unreported
  usage as `null` rather than `0.0`. Both arms now read one sentence resolving
  "commit what passes" against "do not commit". No `src/` change.

- **Cached-input calls on GLM 5.3 (and its Ultrafast tier) now price at the
  vendor's own cache-hit ratio instead of the generic tenth.** `glm-5.3` and
  `glm-5.3-ultrafast` were priced in `APPROX_PRICE_PER_MTOK` but absent from
  `APPROX_CACHE_READ_RATIO`, so a cached-input token on either id fell
  through to the 0.1 default. Z.ai lists GLM 5.3 cached input at $0.26
  against $1.4 input, and GLM-5.3-Flash cached input at $0.03 against $0.15
  input (docs.z.ai pricing, read 2026-09-24); both `glm-5.3` and
  `glm-5.3-ultrafast` now carry the 0.26/1.4 ratio (rounded to 0.186, at the
  same precision as the neighbouring Fable and DeepSeek rows), and
  `glm-5.3-flash` carries the exact 0.03/0.15 ratio (0.2). No routing or
  list-price change.

- **Claude Opus 5.5 in the shared last resort now names `medium` effort
  (editorial, unmeasured).** The `last_resort.any` entry carried no effort,
  so fanout dispatch passed no effort flag (claude-code `--effort`, codex
  `model_reasoning_effort`) and the executor CLI's own default applied, and a
  prepared route carried none. It now names `medium`, which reaches fanout
  dispatch and prepared routes; the Hermes `delegate_task` path is unchanged.
  Anthropic's Opus 5.5 guidance is to set effort explicitly
  (https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5.md),
  and `medium` is the rung Opus 5.5 already carries in `unspecified-high` and
  `capable`. No calibration block fires at `medium`; the vendor order is
  unchanged. Named follow-up: bench arm O4 (Opus 5.5 at `medium` on
  `benchmarks/live-model-tools/v1`).

- **Opus 5.5 subagent block and GPT-6 Luna's `low` placement are now
  measured (2026-09-24).** `MODEL_OPTI.md` records two new benchmark
  results, both from `.omc/research/opus55-luna-bench-2026-09-24/`: the
  Claude subagent calibration block on Opus 5.5 at `xhigh` costs +4,023
  tokens/task over no block, within its own +5,439 same-text drift, at the
  same 18/30 pass rate — kept, though `xhigh` is not a shipped Opus 5.5
  setting; and OMH's `low` effort for `gpt-6-luna` costs +13.9% more tokens
  than the vendor-default `medium` for the same 15/30 pass rate and the same
  list price, so `low` saves nothing measured on this corpus. A third arm
  shows the `gpt-5.6-luna` → `gpt-6-luna` generation swap at `low` dropping
  pass from 18 to 15 (not significant, all three losses in `PREDICATE`) for
  a 67% list-cost cut; `gpt-6-luna` stays in the `quick` and `simple-work`
  chain slots (owner decision), with `PREDICATE` flagged as a known weakness
  to re-check on a larger corpus. No routing, pricing, or contract change.
  Correction (2026-09-24, observed from the run transcripts): the three
  `PREDICATE` losses are a `kind` vocabulary mismatch, not a search miss —
  every `gpt-6-luna` run found the functions and wrote a task-derived `kind`
  label where the grader expects `function`. Named follow-up: bench arm L6
  (`gpt-6-luna` at `low` on the three `PREDICATE` tasks with the `kind`
  vocabulary stated).

- **Runs on the GLM 5.3 and DeepSeek V4.1 Flash Ultrafast tiers now report a
  cost.** `glm-5.3-ultrafast` and `deepseek-v4.1-flash-ultrafast` are served
  by an OpenAI-compatible gateway next to the base ids the shipped chains
  name, but neither appeared in the plugin's price table, so a machine-level
  chain override naming one reported no cost at all. Neither vendor publishes
  a separate rate for the tier, so each row carries its base model's
  documented list price rather than an invented discount: GLM 5.3 at 1.4 / 4.4
  per million tokens (docs.z.ai), V4.1 Flash at the peak 0.30 / 1.20 with its
  0.02 cache-hit ratio (api-docs.deepseek.com). `docs/MODEL-ONBOARDING.md` §5
  now states that rule. Neither tier gains a provider-family row, a contract
  row, or a shipped-chain slot, so provider verdicts stay unknown. Because the
  interview offers a member's `-ultrafast` variant only when that id is
  priced, `omh model-chains interview` now also offers `glm-5.3-ultrafast` for
  chains that name `glm-5.3`.

- **Adding an ordinary skill no longer forces a raise of the skill-body
  budget.** `full_profile_skill_body_chars`, the install footprint of every
  `full` `SKILL.md` body, was a zero-slack ratchet that each new skill had to
  raise to the exact value it measured, and it could not see growth in what
  reaches every request. It is now a ceiling with standing headroom: the
  producer-measured total (1,044,180 chars) plus 10%, rounded up to the next
  50,000, which is 1,150,000 and holds about thirteen average bodies. A test
  keeps the ceiling equal to that derivation. The per-request budgets (skill
  index, tool schemas, `pre_llm_call` context) stay zero-slack ratchets, and
  the per-skill body ceiling in the structure lint is unchanged. A new budget,
  `full_profile_skill_body_repeated_chars`, bounds text repeated verbatim
  across bodies (104,214 chars measured, 9.98%) by the same policy, rounded up
  to the next 10,000: 120,000. Every lane member carries renderer-stamped rail
  sections, so an ordinary new skill adds about 1,450 repeated chars and the
  headroom holds about ten of them, while a skill that copies another's own
  sections or a rail sentence stamped into every body still fails. Both
  measurements are floors as well: a change that shrinks either figure lowers
  its measurement and ceiling in the same commit.

- **`omh_capabilities` answers with the summary when no action is given.** The
  default was `export`, the full capability manifest (over 800k characters),
  which Hermes writes to a file, showing the model only a short preview.
  `action=export` still returns it when asked for by name, and a call that
  names only a `section` still gets that export section. The `omh_todo` and
  `omh_loop` tool schemas drop prose that restated another field or explained
  a rule rather than stating it (7,752 and 7,230 chars, from 9,827 and 7,812);
  every parameter, enum, required field and stop/continue rule is kept. The
  longer phase, `blocked_reason`/`deferred_reason` and checkpoint explanations
  are in the `todo-checklist` skill's references.
  `plugin_tool_schema_chars` ratchets from 57,968 to 55,468.

- **The release budgets now watch what can reach the model on every request.**
  `omh release drift` gains four ratchets, each measured by a producer: the
  full-profile skill index Hermes renders (`skill_index_chars`, 10,894 chars,
  one line per skill with the description cut to Hermes's 60 characters, plus a
  100-char per-line ceiling), the plugin bundle's registered tool schemas
  (`plugin_tool_schema_chars`, 57,968 chars across 19 tools, measured by running
  the bundle's own `register()` against a recording context; an eager ceiling,
  paid on every request only when Hermes's `tools.tool_search` is off, since
  under its default bridge the plugin tools are deferred behind a listing), and
  the largest fenced `pre_llm_call` context over a named scenario set
  (`pre_llm_call_context_chars_max`, 6,260 chars when a routed first turn, a
  role marker, an active workflow and a full running-work board coincide; the
  parts no scenario seeds are listed beside the producer). The
  skill-body total keeps its value and its enforcement and is relabelled for
  what it is: the install footprint, each body loaded on demand. The wording
  that called a skill body "always loaded" is corrected in the installer
  warning, `omh setup --core` help, `docs skill-context-cost`, the doctor
  skill-weight advisory, the structure-lint ceiling message, the adding-a-skill
  guide and the installation guide: a body costs about 8k chars per load and
  stays in history until compaction; only its index line rides every request.
  A new structure-lint rule, `SKILL_INDEX_OPENING_DISTINCT`, fails when two
  installable skills open their visible description with the same three words
  (casefolded, punctuation around a word ignored); the two groups that do
  today ("Hermes adaptation for", "Policy overlay for") are recorded with
  reasons rather than rewritten here.

- **GPT-6 Sol takes every shipped slot both GPT-5.6 tiers held.** `gpt-6-sol`
  replaces `gpt-5.6-sol` in the shared last-resort order (at `medium`) and in
  the Codex Maestro rows, and replaces `gpt-5.6-terra` at the head of `deep`
  and in the `main` role suggestion (both at `high`), in both lanes. The
  Codex `deep` chain is now Sol alone at `high`. The Codex options gain a
  Sol row, and both GPT-5.6 rows stay with their ladders unchanged, so an
  explicit `--model gpt-5.6-sol` or `--model gpt-5.6-terra` override still
  has its effort adjudicated; the 5.6 Sol label no longer claims to be the
  Codex CLI default (the served Codex catalog ranks Astra first). Every slot
  keeps its previous effort. Both GPT-5.6 ids leave the shipped chains and
  stay recognized, priced, and provider-mapped; GPT-5.6 Sol's 2026-09-11
  frontier-slot retirement is widened to every shipped chain. Terra has no
  GPT-6 counterpart, and the Codex client repository's model catalog names
  Sol as the upgrade for both 5.6 tiers (the served catalog does not push it
  yet); Sol's list price ($2 / $10) is at or below Terra's on every
  documented rate. The placement is editorial and unmeasured; the 5.6 Sol vs
  6 Sol pair at `medium`, the Terra vs Sol pair at `high`, and `main` at its
  effort are the follow-up.

  `gpt-6-sol` gains an exact contract read from the vendor's pages: the
  route sends a no-reasoning request as `none`, its documented rung, whether
  it was spelled `none` or `off`, and raises `minimal` to `low`. The Codex
  client's ladder is recorded beside the API ladder without `none` and
  without the Codex-only `ultra` rung, which no OMH ladder or chain names. No
  calibration text changed: Sol receives the GPT family block until a
  measured pair argues for an exact one, and the Codex Sol prompt's sentence
  telling the model to continue without ending the turn is not imported.
  The `gpt_sol_codex_handoff` overlay keeps applying to GPT-6 Sol as a Codex
  main agent, now pinned by a test that names it.

- **OMH can ask Jev itself, when the user asks for it (#1795).** A new
  `omh_jev_ask` plugin tool sends typed questions (yes/no, pick-one, scored) to
  Jev with the user's own key and returns probabilities, and six
  default-installed skills use it: `omh-jev-ask`, `omh-jev-route` (answers an
  undecidable route question and records it as `answered_by: omh_jev_ask`),
  `omh-jev-failure-triage`, `omh-jev-review-gate`, `omh-jev-action-check`, and
  `omh-jev-done-check`. The last four call versioned presets whose rule ladders
  run in OMH code and can only add a hold, a flag, or an objection; a failed
  ask is labelled `not_answered:<status>` and never reads as Jev's answer. This
  is the second scoped exception to "OMH makes no network calls", and it is
  narrow on purpose: the tool opens no socket unless the person's own message
  for that turn names Jev (`consent_not_observed` otherwise; text the host adds,
  such as a quoted reply to the bot's own offer, channel history, an image
  description, an inlined attachment, or a file or page an `@`-reference
  pulled in, does not count, and a reply or channel-history turn that also
  carries an `@`-reference expansion does not consent at all, since a quote
  can spell the expansion's header line; only an allowlisted
  platform a person types into can consent, never a webhook, API, cron,
  subagent, batch, single-query, or kanban-worker turn; on a messaging
  platform only the first line of the message counts and a photo or file
  caption or a voice message does not, because Hermes merges other senders'
  text and clips into the first sender's message -- a native-vision turn, which reaches the hook as a
  content list with image parts, counts as a media turn by its parts; in a
  shared chat only the participant who opened the session can, and a session
  a compaction started names no owner; and the consent is bound to its own
  turn, so a background fork of the session cannot spend it, and while a
  fork's call overlaps the main turn's, neither is sent). A forwarded
  message, a WeCom quote, or a forwarded voice transcript reads as the
  forwarding user's own words, since no chat app marks a forward, and after
  `/new` or a `/stop` whoever speaks first owns the next session's consent;
  both are documented in the skills' rail. The gate cannot tell a bot from a
  person, since the host's bot flag never reaches `pre_llm_call`, so on a
  profile that admits bot messages a bot's words consent like a person's;
  that residual is documented too. A credential in a field name or a
  question id is refused like one in a value, and so is any 8-character piece
  of either configured route key, in any case and with whitespace removed. Only a
  `TYPESAFE_API_KEY` enables it by itself (the OpenRouter route also needs
  `{"openrouter_route": true}` in `<omh_home>/jev/settings.json`, a local-trust
  opt-in), the route table is two fixed HTTPS hosts, redirects are refused,
  only 429, 503, and 529 are retried (any other 5xx and every timeout, a
  gateway's 504 or 524 included, may have been billed and are reported), the
  deadline bounds each read as well as the connect, and no key, `state`,
  question text, or reply is stored; any 8-character piece of a key echoed
  back by the server, in any case or JSON-escaped, is scrubbed from every path,
  and an echo that spaces the key's characters apart blanks the whole excerpt.
  An `answered_by: omh_jev_ask` record is accepted only for an ask this OMH
  process itself sent and Jev answered, never on a ledger row alone, and only
  with the request text, from which the question is re-derived: the ask must
  have sent exactly that question, and a verified digest refuses a Choice
  outside its options whoever answered. The skills
  declare `requires_tools: [omh_jev_ask]`, so Hermes leaves them out of the
  skill index where the tool is not registered (code-read, not observed live),
  for callers that pass a tool set; a caller that passes none shows them.
  Routing reaches a Jev skill only when a message addresses Jev ("ask jev",
  "use jev", "have jev", a skill name in its invocation form); sentences that
  only mention Jev, decline it, name it among options, or explicitly invoke a
  different OMH skill keep their owner, pinned by new corpus cases. `omh doctor`'s `plugin_jev_sidekick`
  line now also reports the tool's route by variable name, its ledger, and what
  it sends. No live Jev call was made; every wire fact is documented, not
  observed.

- **Setup and execution guidance now agree with their existing boundaries.**
  Setup workflows use secure native or user-side credential entry and redacted
  approval previews instead of requesting secrets in chat or promising that
  chat input is never retained. Maestro distinguishes choosing an executor
  from authorizing it to run, while an explicit owner-and-execute request can
  supply both without a second confirmation. Ultrawork excludes conflicting
  parallel writers, not its supported single-owner or ordered execution modes.
  These are generated-guidance corrections; no routing, dispatch mechanism,
  public skill name, configuration option or runtime permission gate changes.

- **The Claude subagent calibration no longer tells the model to keep
  working.** The high-effort `claude` block said "No one is watching this
  unit in real time: proceed on every reversible action inside the boundary
  without asking, and if your last paragraph is a plan, a question, or a
  promise, do that work now", which breaks the rule that no calibration
  sentence may push the model to keep working. That sentence is removed and
  nothing else in the block changes. Measured on `og` /
  `anthropic/claude-fable-5-1` at `xhigh` over the 30-instance evaluation
  split of `benchmarks/live-model-tools/v1`: 18 / 30 before and after, the
  same instances, and 2,641,559 harness tokens against 2,760,212 and
  2,955,008 for two runs of the old text. The per-instance delta against
  their mean is −7,202, CI95 [−15,422, −47]. The composer block loses its
  two sentences of the same kind, "keep working while delegated units run"
  and "If your closing paragraph is a dispatch you could run, run it before
  closing"; that deletion is unmeasured, because the benchmark runs one agent
  with no fanout and never reaches the composer path (#1836 tracks one).

- **The Jev plugin posture follows the `hermes-jev` rename to `nerve`, and
  knows `jev-curator`.** An open upstream catalog change (hermes-agent #119045,
  read at its head on 2026-09-23, not merged) renames the community plugin
  `hermes-jev` to `nerve` and its `jev_*` tools to `nerve_*`. Once that lands,
  neither signal OMH classified on would fire -- the name was not in the table
  and the tools no longer carry the `jev_` prefix -- so `plugin_jev_sidekick`
  would report the plugin absent and the `jev_plugin` answerer rung would
  disappear from route questions. `nerve` is now a known record, labelled as
  read from the open PR, and its `nerve_` prefix counts as Jev-class for that
  name alone; another plugin's `nerve_` tool does not classify that plugin. The observed
  tier, which sees a dispatched tool name without its plugin, counts only the
  exact `nerve_` names the entry declares. `hermes-jev` stays known for
  machines that have not updated. `jev-curator` (plugin-catalog, added
  2026-09-21) now reports `known: true` with its catalog disclosure instead of
  `known: false`. The routing-questions benchmark README says how an operator
  drives an installed Jev plugin over the exported corpus to produce an
  external arm; OMH still never calls one.

- **Claude Opus 5.5 and GPT-6 Luna take their predecessors' shipped slots.**
  `claude-opus-5-5` replaces `claude-opus-5` in `unspecified-high`,
  `unspecified-low`, `capable`, the `main` role suggestion, and the shared
  last-resort order, and `gpt-6-luna` replaces `gpt-5.6-luna` in `quick` and
  `simple-work`, each at the same position and effort. The Claude vendor order
  stays Fable 5.1 before Opus. Both superseded ids leave the shipped chains and
  stay recognized, priced, and provider-mapped, so a machine whose provider
  serves only the older id keeps it with `omh model-chains set`. The placement
  is editorial and unmeasured; the old-vs-new pairs are the follow-up.

  Both ids gain exact contracts read from the vendors' pages, the first for a
  Claude model: Luna's route sends a no-reasoning request as `none`, its
  documented rung, whether it was spelled `none` or `off`, and
  `omh coding model-route` raises a no-thinking request for Opus 5.5 to
  `low` because the API rejects disabling thinking, which
  `omh_delegate_route` now refuses for it as it does for Fable. The Hermes
  lane's named-model branch now applies every exact contract's floor, so GPT-6
  Astra asked for `off`, `none`, or `minimal` there is raised to `low` on
  record, as the catalog lane already did. New price
  rows follow the documented lists, and three stale GPT-5.6 rows are
  corrected to the vendor pages: Luna to $0.20 / $1.20, Terra to $2 / $12,
  and Sol to $4 / $20, which OpenAI labels promotional through at least
  2026-11-21 with no later price published. No calibration text
  changed: neither shipped placement reaches the subagent high-effort tier,
  and the Claude blocks stay byte-stable.

  The loop itself was corrected where it contradicted its own rule. The
  `model-optimization` skill still told a runner that an older generation
  stays as fall-through; it now states the superseded-generation rule and the
  four source labels. The shared-final-order sentences in the installation,
  architecture, and model-routing docs are now checked against the catalog,
  and each retirement records its own decision date and is checked out of both
  lanes. The Maestro docs note that Claude Code's `opus` alias reaches Opus 5.5
  only from v2.1.280 and resolves to Opus 4.6 on Microsoft Foundry.

- **A stop now ends the turn with the next action offered, not with a
  refusal.** Runs on the executing engines closed with sentences like "I will
  not merge or force-push here": the follow-up authority rule said to describe
  a follow-up and wait for approval, but not how to close, and the closing
  brief rule listed "follow-up declarations" among the bookkeeping not to
  narrate, so the model stated what it would not do and the person saw no
  next move. The follow-up authority rule now ends the turn by naming the next
  action and asking whether to take it, as one question carrying the choices
  the user has; the closing brief rule ends a boundary stop with that offered
  action and states what was left undone as the option it leaves open; every
  generated skill's tail carries the same sentence beside its stop condition,
  and the common rail has a Turn Ending section with the before-and-after.
  The wrapper copy for the file-lookup and direct-answer states is reordered
  in every locale so it ends on the action rather than on "does not start an
  OMH workflow". The per-skill byte ceiling moves 26,000 -> 26,500 for
  `ultrawork`, with the reason at the entry.


- **A Hermes child now receives its prompt.** `omh coding hermes-child
  dispatch` spawned `hermes --oneshot -` and wrote the prompt to stdin, but
  Hermes' `-z/--oneshot` takes the prompt as its positional value and reads no
  stdin, so the child answered the literal prompt `-` with a greeting, exited
  0, and billed the routed model for it. The child is now
  `hermes chat --query-file - --quiet`, the one Hermes transport that reads a
  prompt from stdin; the prompt still never enters argv, and `--quiet` keeps
  a completed turn's stdout to the final response as `-z` did. A start Hermes
  refuses before the turn, because the child sees no provider, now prints
  Hermes' first-run guidance on stdout and exits 1 where `-z` printed one
  stderr line; the child's exit code and the literal verdict tags are what
  callers read, so that text is a failed dispatch, never a result. Hermes
  writes its `--usage-file` report for `-z` alone, so the observation's
  `usage` is empty on this transport rather than a number it did not measure;
  paired-run, final-review, and the live-model-tools isolated-child arm reuse
  the same child and inherit both changes, and the docs of each say so. The
  test fakes now model the real CLI (`--oneshot` reads argv, never stdin), so
  the old argv fails the suite instead of passing it (#1824).

- **Setup no longer writes a `plugins.enabled` Hermes cannot read.** A config
  carrying `enabled: '[]'` is a string to YAML and no plugins to Hermes, and
  setup inserted `    - omh` under it, which YAML refuses (`did not find
  expected key`); the same insert under `enabled: null` or a plain word folds
  the item into the string, so Hermes loaded nothing and said nothing. Setup
  now classifies the value first: a null or a quoted `[]` carries no member and
  is normalized to a block list, an inline list is expanded as before, and any
  other scalar stops setup with the file untouched and `hermes plugins enable
  omh` named as the repair. The line reader stops attributing items under a
  scalar to the key, and `omh doctor` reports a file already in that state as
  the file it is rather than as an enabled plugin. A new
  `hermes_config_plugins_enabled` check carries the same sentence setup
  refuses with, so a home where setup stopped before installing the bundle
  still names the cause instead of only its side effects (#1825).

- **A board readback is now measured after it is serialized, and is no longer
  run through diff padding.** The ceiling that keeps `kanban_show`,
  `kanban_list` and `kanban_attachments` inside the context budget was applied
  to the record before it became JSON, so a board whose text needed escaping
  crossed the budget by whatever the escaping added. It is measured on the
  bytes the host actually receives, and a readback that is cut says so, with
  the fields it dropped named rather than silently absent.

  The same records were also passing through the diff band-padding path, which
  splits on line boundaries and writes literal newlines back. A board carrying
  a Unicode line separator therefore split inside a JSON string and came back
  as invalid JSON. Kanban records are excluded from that padding, which is what
  the padding was always for: diffs, not structured results.


- **An engagement nudge now counts what a tool call did, not that it was
  made.** The counters behind the plan and delegation nudges were incremented
  from the fact of a watched tool call, so a write that the host refused, a
  patch that applied nothing, and a write that landed all moved the same
  threshold by the same amount. `_mutation_effect` now classifies a file
  mutation as `landed`, `partial` or `unknown` from the same two facts Hermes'
  own `file_mutation_result_landed` reads, and only `landed` advances the
  threshold; the other two are counted under their own fields so the difference
  stays readable rather than disappearing.

  The read side gains the same distinction. A pre-dispatch refusal is not
  search effort, so a `blocked` status no longer bumps the direct-read counter,
  and a call whose arguments could not be fingerprinted is declined by name as
  `unknown_read_identity` rather than counted as a new distinct read.

  The classification runs at two seams because one is not enough on the real
  host: the executor suppresses the inner post-tool hook for a delegated call
  while `transform_tool_result` still fires inside it, so a design that watched
  only the post hook would have seen nothing for exactly the calls a delegation
  nudge is about.


- **Accepted native work can be resumed from a bounded scope checkpoint, with
  durable verification, review and QA declarations.** `omh_todo` adds
  `checkpoint`, `record` and `recall`; no new engine or router state lookup is
  introduced. A checkpoint freezes the owning session's accepted todo items
  and separately records rejected ideas. Later sessions in the same profile
  and logical project can read it without changing a checklist or resuming work.
  Result rows preserve claimed source, revision/environment, findings and
  existing `verification_receipt/v1` references without turning a model claim
  into an observed result. Missing, stale, malformed and declared-empty sources
  remain distinct. Storage is capped; full stores refuse rather than evict.
  Existing close/verification/review/QA guidance now exposes this callable path
  to Hermes model selection, without adding language-specific triggers or a
  mandatory story template. Offline native fixtures cover registry, bridge,
  lifecycle, storage and the composed #1794 approval boundary; live semantic
  model adoption remains untested. No edit approval, receipt issuer, CI
  observer, merge authority or new task execution runtime is added.

- **Hermes replies under OMH are written in the user's words and the host's
  own voice.** People were reading OMH's record vocabulary back in chat ("this
  is an evidence-bounded surface", "prepared_not_observed", "wrapper",
  "handoff", "evidence boundary"), and nothing told the model that those terms
  belong to records and tool calls rather than to the sentence a person reads,
  or that the host's `SOUL.md` owns the voice. Every generated skill's tail now
  says so in one sentence, the common rail gains a Reply Language And Host
  Voice section with plain substitutes ("prepared, not run yet", "not checked",
  "handing the coding work to X", "this shows X and does not show Y") and the
  rule that awareness lines, route hints, and first-response shapes are
  instructions never quoted to the user, both awareness primers carry the same
  line, the closing brief rule leads "in the user's words", and the shared
  purpose line of the operator skills ("a structured, evidence-bounded OMH
  operating surface instead of ad hoc narration") becomes "a structured,
  checkable answer instead of an improvised one". Budgets move with the reason
  at each entry: the compact primer 900 -> 1,050, the markdown primer
  3,210 -> 3,400, the per-skill ceiling 26,500 -> 26,800, and the full-profile
  ratchets re-derived from their producers.
- **A hand-written portable override now learns when the catalog section it
  replaces has moved.** `PORTABLE_OVERRIDES` (12 skills, 28 sections) replaces
  catalog sections wholesale for the Agent Skills projection, which is the
  right mechanism -- a Hermes-shaped line has to be rewritten by a person -- but
  no test read the table, so a line added to an overridden section was absent
  from `agent-skills/<skill>/SKILL.md` with every gate green and nothing
  recording that a decision was owed. `docs agent-skills --check` cannot see it:
  it compares shipped bytes against a projection that already applied the
  override, so it agrees with the override by construction. Two producers in
  `src/skills/catalog_portable.py` now report a sha256 per replaced catalog
  section and the entries that no longer resolve, pinned by
  `tests/fixtures/portable_override_source_digests.json` and asserted in
  `tests/test_agent_skills_projection.py`. A moved section fails naming the
  `<skill>::<section>` entries, so the author re-reads that decision instead of
  diffing 28 tuples; re-pinning without editing the override is the valid
  outcome that records a deliberate choice not to mirror a line. The failure for
  an entry that stops resolving carries its reason, because the two halves
  behave differently at projection time: a dropped skill is looked up by display
  name and silently misses, while a renamed section raises an `AttributeError`
  out of rendering that names only the field. No override text and no projected
  byte changes.

- **A bounded Kanban readback no longer contradicts itself.** The label line is
  the first thing a model reads, and it printed a bare 64-character prefix of an
  oversized task id while the JSON beside it listed that same id under
  `omitted_fields` -- the second identity `docs/KANBAN-READBACK-CEILING.md`
  promises is never manufactured. Label values now carry `...[truncated by omh]`
  inside the 64-character cut, and a field the projection omitted is named
  `<omitted: too long>` rather than quoted as a prefix of itself, with the
  `kanban_show` label read off the projected records instead of the originals.
  A row list that is not a list of objects is reported as one: it is named in
  the new `omh_readback.malformed_rows` and in the label (`tasks not read
  (malformed row list)`), it is not counted as dropped, and a projection leaves
  the key out rather than writing `[]`, which rendered 62 host rows as an empty
  board under a `0 of 0 tasks shown` label. A `kanban_show` whose `runs` cannot
  be read says so instead of reading as a task that never ran; an empty list and
  an explicit `null` stay ordinary absence. Both projection tiers are now
  measured after rendering rather than the core one being returned unmeasured,
  and a core projection that does not fit falls to an identity tier
  (`projection = "identities_only"`: root `ok`/`error`/`task_id`, the task's id
  and status, the latest run's id/outcome/status, no rows) whose size is fixed
  by its field sets rather than by the input -- measured at 3,556 characters
  against the 24,000 ceiling at the worst escaping the 256-character scalar cap
  admits. The row-drop accounting gains its own tests: the tracked size no
  longer subtracts a list separator for the last row, which put it below the
  payload it stands for, and the dropped prefix leaves in one slice rather than
  one `pop(0)` per row. None of this is reachable from the shapes the pinned
  Hermes host emits today; it is the last-resort path the ceiling falls back to.

- **A `plugins` node written on its key line no longer reads as "nothing is
  enabled".** `plugin_enablement` entered Hermes' `plugins` node on one
  condition, a top-level line whose text was exactly `plugins:`, so the flow
  mapping `plugins: {enabled: [hermes-jev]}` and a `plugins:` line carrying a
  comment both left the same empty lists a config enabling nothing leaves.
  Every caller then stated "not enabled" about a plugin the host loads. One
  classifier now answers for that node and the reader follows both forms
  Hermes loads; a corpus of fourteen readable nodes is pinned against the
  answers Hermes' own PyYAML gives them. A node outside those forms -- an
  alias, an anchored block, a repeated key, a file YAML refuses -- reports
  unread rather than empty: `omh doctor` returns `plugin_enabled_in_hermes`
  as an unobserved warning naming the node instead of telling the operator to
  enable a plugin that is already on, and the uninstall report says
  `plugins.enabled` was kept rather than absent. Setup gains one refusal to
  match the remover, which already declines every `plugins` node that is not
  the plain block: it used to find no `plugins:` line under a flow mapping and
  append a second top-level `plugins:` block, and a duplicate top-level key
  resolves to its last value, so the operator's own list was dropped with no
  error anywhere. The plugin bundle's routing-tier reader is unchanged and
  still under-reads the flow form by one tier; it cannot import the core
  reader, and it states no enablement.
- **A reply lint turns the reply rules into checkable evidence.**
  `omh quality-evidence reply-lint` reads the sentence a person read (a file,
  stdin, or the trailing replies of a Hermes session, opened read-only) and
  reports `record_term_leak` (the rail's record vocabulary plus the Korean
  renderings read in live replies, `표면` and `레인`), `awareness_line_quoted`
  (`[OMH Awareness]`, `Boundary:`, `Route hint:` lines), `refusal_closer` (the
  closing paragraph declares what will not be done and offers no question), and
  `decision_without_question`. A term the user named is carved out, only the
  closing paragraph decides the closing findings, and a finding exits 1. The
  `reply_lint/v1` payload carries its own claim boundary: a clean result is not
  evidence that the reply was correct or in the host's own voice.

- **Wrapper cards now say what they hold and what they leave out, in the
  reader's own words.** All 79 `ChatCopy` headline/body entries in the
  localized card table are rewritten across their seven locales (en, ko, ja,
  zh, es, fr, de): no first-person voice competing with the host's `SOUL.md`,
  no OMH record vocabulary (`workflow`, `picker`, `handoff`, `lane`,
  `wrapper`, `observed`, `prepared`), and each evidence limit stated as "this
  shows X and does not show Y" instead of as a refusal to claim. The two cards
  whose bodies were instructions addressed to Hermes rather than sentences for
  the reader -- the file-or-text lookup and the direct answer -- now describe
  what the card does and what the reader can supply, and both now reach an
  English reader at all: their English body came from the router's constant
  fallback clarification, so the sentence Discord and Slack printed was
  "Answer this as a file or text lookup..." rather than any card copy. Those
  two cards render their copy in every locale now, and the Hermes-facing
  instruction keeps the `routing_instruction` and route-explanation fields it
  already had. `card_copy_voice_violations` re-derives both rules from the
  table itself, so a card added later is checked without anyone enrolling it:
  run against the
  table as it stood before this change it reports 173 violations spread over
  all twelve cards and all seven locales, and none after. The first-person
  half is a regression list rather than a grammar checker, and says so at the
  list: four of the seven languages drop the subject pronoun, so what gives
  the speaker away is a verb inflection, and no short list of inflections is
  complete. Two headlines change on the wire and their pins move with them:
  the direct-answer card reads "This can be answered directly in the chat."
  and the research card "Source-backed research can ground this.".
  Wrapper-facing text produced elsewhere -- the operating-brief cards and
  inline headlines in `omh.wrapper.contract`, the session ladder in
  `omh.wrapper.sessions` -- is outside this change and still carries the
  shapes the new rule rejects. The routing-inertness fixture is re-pinned
  with the rewritten headlines: 103 of its 237 pinned rows move and
  `observed.plain_headline` is the only field that differs on any of them,
  so `observed_digest` moves for the first time without a verdict moving.
  That corrects a claim beside it -- the projection was described as carrying
  only the router's output, and it also carries the card's headline and
  boundary, which a card picks after the route.
- **`observed_check_results/v1` is declared once, and every surface renders
  it.** `verification-gate` stated the row's shape twice in its own body and
  the two disagreed: a quality-bar line asking for command/source, freshness,
  exit status and scope, and an artifact expectation asking for command,
  timestamp/source, exit status, summary and a stale-output flag. `omh-wiki`'s
  handover table named two of the fields, and a fourth restatement was written
  before review caught it. Nothing could fail, because nothing was derived; a
  consumer recorded whichever copy it read, and the field that went missing was
  freshness, the gate's own guard against reporting a stale output as evidence.
  `src/evidence/observed_check_results.py` is now the one declaration. The
  reconciliation keeps both disputed fields rather than picking a list: `scope`
  (what that run covered) and `summary` (what the output said) both stay,
  `freshness` is the single name for what was freshness on one line and a
  stale-output flag on the other, and `source` becomes a field of its own,
  because the same command proves different things run in this checkout, in a
  CI job, and in a person's report. Each field a reader cannot infer renders
  with its meaning beside it, so a surface quoting the row cannot quote a name
  without its definition. The gate's artifact expectation, its quality-bar line
  (which now points at that expectation instead of listing the fields a second
  time), the `omh-wiki` and `todo-checklist` handover tables, and `ulw-qa`'s
  manual test guide all render from it. `tests/test_observed_check_results.py`
  scans every rendered body and reference that names the row, fails a line that
  enumerates the fields without rendering them, and runs the two drifted lines
  through that same scan to show it fires. Budgets move with the reason at each
  entry: the full capability section 422,817 -> 422,908 and the full-profile
  skill bodies 1,029,426 -> 1,029,724, both re-derived from their producers.
- **Session usage shows which Hermes surfaces OMH actually reaches.**
  `omh quality-evidence session-usage` reads Hermes' own `state.db` read-only
  and reports, per `sessions.source` tag (`tui`, `cli`, `desktop`, `oneshot`,
  ...), sessions, tool calls, `omh_*` tool calls, sessions with at least one,
  `skill_view` loads and OMH skill loads, with the per-name breakdowns. Every
  count is over distinct `tool_call_id` per session, because a compaction
  re-persists tool rows under new ids; the OMH-skill signal is the catalog's
  `[omh] ` description prefix in the `skill_view` result rather than the
  `omh-` display name, since the `ulw-*` skills are OMH skills too, and a
  name-only result (a reference-file load, a compaction placeholder) counts
  when it names a catalog skill. Archived and hidden sessions are included,
  `--since` takes an ISO-8601 timestamp or epoch seconds, `--source` keeps
  one surface (`(none)` the untagged sessions), and an empty window exits 0
  as an observation while a missing database exits 2. The `session_usage/v1`
  payload carries its own claim boundary: it is not execution, review, CI, or
  merge evidence. `reply-lint --hermes-session` gains the same `--source`
  filter: `latest` resolves to the most recent session with that tag, an
  explicit id whose tag differs or cannot be checked is an error rather than
  a silently ignored flag, and the payload records `source_filter`.
- **The plugin bundle ships a Hermes Desktop half.** The OMH status line and
  plan todo rendered only in the modern TUI, through the widget Hermes Desktop
  does not load; the app's extension point is a unified plugin package. The
  bundle now carries `dashboard/plugin_api.py`, which Hermes' web server
  imports by path inside the gateway process and mounts at
  `/api/plugins/omh/hud` while `omh` is in its `plugins.enabled` (the
  registration `omh setup` and `omh update` write); it answers with the same
  `omh_hud/v1` payload the widget renders, read for the gateway's own Hermes
  home and the session the app names, a reader failure as a 200 error record
  the pane can label rather than a raise it could not tell from a transport
  failure, and concurrent first polls share one load under a lock. Beside it,
  `desktop/plugin.js` is an uncompiled ESM plugin written for the app's
  disk-plugin loader: it polls that route every 5 s while the gateway is open
  and draws the payload as a structured `omh` pane and a compact status-bar
  item (see the entry below), never a value the reader did not produce; it
  ships off, as the app requires of unified-package halves, and the switch is
  under Capabilities -> Plugins. `dashboard/manifest.json` is also read by the
  browser dashboard (`hermes dashboard`), which registers a tab for every
  manifest, so it is marked `tab.hidden` and the browser dashboard gets no
  `omh` tab. Observed: a live `hermes serve` logged the mount and answered 200
  on the route, and node drove the renderer file with the SDK shims replaced
  by recording fakes, and the built Hermes Desktop app, launched against an
  isolated home with the renderer file placed by hand as a standalone disk
  plugin, showed `[omh] vunknown | plugin:ready | coding-agent:not-selected`
  in its status bar; the app's own copy into `desktop-plugins/omh/` and the
  rendered pane are by construction from Hermes' loader source, not observed.
  `pyproject.toml` ships the three files (the backend as a `dashboard`
  subpackage, the renderer file as package data, so no Python package marker
  lands in the folder the app copies), `omh update` refreshes them through the
  existing bundle manifest, and `omh doctor` gains a non-blocking
  `plugin_desktop_half` check that warns an older bundle toward `omh update`
  and never claims the half is enabled.
- **A Hermes home registered at the pre-pointer skills path is migrated to
  the generation pointer instead of keeping both.** A bot profile registered
  at `~/.omh/skills` before the command install moved to its shared
  generation pointer was carried forward by `omh update`, which added the
  pointer beside the older entry and retired nothing. Hermes refuses a bare
  skill name that resolves to two different files across
  `skills.external_dirs`, and every generation refresh made the two copies
  differ, so after each update every OMH skill present in both failed to
  load by name in that bot (#1857; on the owner machine `profiles/miku`
  recorded `Ambiguous skill name 'omh-model-setup'`). `_apply_result` run
  from the installer-managed command now retires every other OMH-managed
  entry in the same config write that registers the pointer, so the home
  ends registered at exactly one managed path. Entries are matched by real
  path, the rule Hermes resolves them by and the one the readers below
  count by, so an older entry spelled through `~`, a trailing slash or a
  symlink is retired too rather than reported as an ambiguity `omh update`
  could never clear. A directory the person registered themselves is never
  touched, a home naming no managed directory stays opted out, and a
  command that is not the installer-managed one (a checkout, a pip or uv
  tool install) stays additive and never retires the pointer, so it cannot
  move a machine backwards. The apply step and every profile row carry
  `registration` (`migrated`, `added`, `unchanged`) with the entries
  retired, and update prints one line per home that moved. `omh doctor`
  gains `external_dir_ambiguity` for the primary home and one row per
  affected bot profile: a warning naming both paths and the consequence,
  counting only directories present on disk (Hermes skips a missing one),
  with `run \`omh update\`` promoted to doctor's headline next action.
  Update re-reads every home after the write and prints the same sentence
  as a warning line for one it could not retire; that residual state does
  not move the update's exit code. The pre-pointer copy on disk is not
  deleted: no manifest records it, and on a managed install it backs the
  always-retained `bootstrap-legacy` generation (the self-update rollback
  target), which only `omh uninstall` collects. Doctor reports it as
  unregistered but retained (`external_dir_unregistered_copy`) and calls
  it safe to delete, with its directory mtime, only when no home registers
  it and no generation links it. Update also names the gateways whose last
  recorded start precedes this update, from Hermes' own files: a
  `gateway.pid` record for the home plus a `gateway-starts.log` last start
  earlier than the bundle manifest's `installed_at` (rewritten by every
  update) prints `Hermes gateway for <home>: last recorded start <ISO>
  precedes this bundle's install (<ISO>); run \`hermes [--profile <name>]
  gateway restart\``. The pid record's `start_time` is Hermes' PID-reuse
  fingerprint (psutil `create_time() * 100` on macOS, `/proc/<pid>/stat`
  field 22 on Linux), never a wall clock, and is pinned as not read; a
  ledger line that is not a finite positive number, or bytes that are not
  UTF-8, yield no hint rather than a traceback. No signal, no process
  listing, no subprocess.
- **The Hermes Desktop pane draws the HUD the way the TUI widget does, in the
  app's own language.** The first pane dumped `display.widget_lines` and
  `display.todo_lines` as monospace text: no colour, wrapped mid-token, and
  no word on which model any agent ran, which the owner set beside the
  modern-TUI widget and rejected. `desktop/plugin.js` now renders the
  structured payload: a header with the `⚚ OMH` mark, the version badge and
  the widget's state label (`ready`, `3 agents · 2 running · 1 blocked`); the
  main session's model and usage from the app's own state (the payload names
  a model only per subagent row); the widget's header chips (repeat guard,
  board counts, `dispatcher not observed`, open tools, yolo, summed tokens)
  as badges (the parallel-shot badge among them); a full-width hairline;
  a PLAN section (`PLAN`, the title, `done/total`, a progress bar, the TUI's
  eight-item window with earlier/later folds, each phase as its own bold
  header row with its own `done/total` -- the current phase in the label
  colour -- and its items hanging under it behind a left rule: `●`/`✓`/`○`
  glyph, the text wrapping under its own start, done items struck through,
  `waiting: …`/`skipped: …` in warn and `unchanged …` in quaternary each on
  their own line); a hairline; an AGENTS section that up to 480 px of pane
  width stacks three lines per agent (state glyph, `sub`/`bot`/`main` tag,
  8-char id, the action title on one line with an absolute path shortened
  to `…/last/two` and the full text in a tooltip; the route identity in the
  widget's own shapes -- `category:architect(model:effort)`,
  `inherit(model:effort)`, `(codex/maestro model)`, `kanban/assignee` -- with
  the state word; elapsed · tokens · cost) and past it lays the same cells
  out as one aligned grid under a row of column labels, 26 px rows with an
  alternating band; rate, `cache N%`, ctx, `turn N (M tools)` and fallback
  live in the row's tooltip; the plan column is capped at 640 px; the DAG block
  while a graph is active; and a quiet footer notice: a reader error record
  replaces the body with it, a transport failure keeps the last payload
  under it.
  The status-bar item is compact -- `⚚ 3 agents · 2 running · 1 blocked ·
  3/6`, `⚚ ready` when idle, the detail in its tooltip -- and reveals the
  pane on click; it renders nothing before the first answer, like the Kanban
  count. Every colour is a theme token through a stylesheet the plugin
  appends on register and removes on dispose (Tailwind never scans a disk
  plugin), and the mono cells (ids, route identity, chips, version badge)
  name the app's bundled JetBrains Mono ahead of the theme's mono stack;
  the route identity wraps only at its grammar's seams, never
  inside a model name; the formatters (`tokenCountText`, `elapsedText`,
  `costSegmentText`, `routeIdentity`, `hudStateLabel`) are the widget's,
  ported and pinned against its examples; the poll keeps the previous answer
  while refetching. Observed: node drove the file with the SDK, React and
  JSX shims replaced by recording fakes, and the built Hermes Desktop app,
  launched against an isolated home whose recorded session held a six-item
  plan declared for it, one running delegation child seeded from the
  recorded one, and a two-task board another teammate had placed there,
  showed the structured pane at 330, 667 and 900 px and the status-bar
  count with no boundary error.
- **The README and site demos show an ultrawork run on both surfaces.** The
  Hermes Desktop tile now plays a real session: the prompt goes in, the plan is
  declared, three lanes fan out, and the OMH pane lists each lane's route
  (`category:writing(kimi-k3:medium)`, `category:deep(gpt-6-sol:medium)`,
  `category:capable(claude-fable-5-1:medium)`) beside two `bot` rows the
  kanban board dispatched to a bot profile. The Hermes CLI tile plays the same
  prompt in the modern TUI, with the `[Plan]` dock above and the HUD rows below.
  The site's CLI card, which played `omh setup`, now plays the TUI run, and
  its Desktop card plays the new Desktop session; the `omh setup` video files
  under `site/assets/` are removed since nothing referenced them any more.
  Captions on both surfaces (and their ko/ja/zh strings) say what the clips
  show. The clips were recorded on 2026-09-25 against an isolated Hermes home
  with the owner's provider; the Fable and Sol routes in the Desktop clip were
  chosen by the category chains and then re-dispatched on the served model,
  which the session narrates on screen.
- **A Hermes child on the chat transport reports its tokens and cost again.**
  Since #1830 the child spawned by `omh coding hermes-child dispatch` runs as
  `hermes chat --query-file - --quiet`, and Hermes writes its `--usage-file`
  report for `-z/--oneshot` alone, so the observation carried `usage: {}` and
  paired-run cells and `--final-review` lenses showed no tokens or cost. The
  numbers were never lost: every API call of the turn queues its token deltas,
  priced cost, `cost_status` and `cost_source` into the child's `sessions` row
  of `HERMES_HOME/state.db`, drained when the turn finalizes and again when
  the quiet CLI exits, and the dispatcher hands each child a disposable home of
  its own. After the child exits and before that home is removed, the
  dispatcher now reads every `sessions` row there, read-only, and sums them
  into the `-z` report's vocabulary (`input_tokens`, `output_tokens`,
  cache and reasoning counts, `total_tokens`, `api_calls`, `model`,
  `provider`, `estimated_cost_usd`, `cost_status`, `cost_source`), which the
  observation builder already turns into `tokens`, `cost_usd`, `cost_status`
  and `cost_source`. `--format stream-json` was measured and not chosen: its
  terminal record carries tokens but no cost, and every tool result of the
  turn would land on stdout ahead of it. The prompt still never enters argv,
  nothing beyond the final response is read from stdout, and `usage` stays
  empty, never zero, when the ledger records no API call or the file is
  missing, not a database, or shaped differently; text columns are bounded
  and screened the way the removed usage-file reader screened them. The
  coupling is recorded in `CONTEXT.md` (Host surfaces OMH reads) beside the
  lease registry. The test fakes now leave a real SQLite `sessions` row in
  the disposable home, so the dispatch suite proves the numbers travel end to
  end and the CLI observation carries them (#1831).

- **`omh codegraph tests --changed <paths...>` names the tests a change
  reaches.** Picking "the smallest test that proves the claim" was left to
  judgment, and this repo's own notes record a hand-picked subset missing a
  gate four times in one session. The new subcommand walks the
  `imports_internal` edges the codegraph scanner already builds backwards from
  each changed path and lists every `test*.py` module under a tests directory
  that those recorded edges reach, with the import distance, as text or
  `--json` (`codegraph_test_selection/v1`). A changed package `__init__.py` is
  credited with the importers of every scanned file under its directory, since
  importing any of them executes the `__init__` and the scanner records no
  edge for that. A module nothing imports is reported as such rather than
  expanded into the whole suite; a non-Python, directory, deleted, or
  unscanned path is classified, not dropped; each entry keeps the caller's
  spelling with the resolved path beside it, naming a symlink or case-variant
  spelling; the non-test files in the closure and the scanner's own warnings
  are listed so a hub explains a wide selection and an unparseable test is not
  silently absent. Exit status is 0 whenever the graph builds and every path
  resolves inside the repository. Every payload carries a fixed `blind_spots`
  block (dynamic imports, fixtures loaded by path, generated artifacts gated
  by byte comparison, helpers importable only through an extra `PYTHONPATH`
  root, package roots that extend `__path__`, spawned commands, non-Python
  changes) and a `claim_boundary` saying the subset is a starting point and
  never a substitute for the full suite. Pure traversal: nothing is imported,
  executed, or spawned. `docs/CODEGRAPH.md` now lists OMH's own `omh codegraph`
  subcommands and is linked from the README, so it leaves the navigation
  exemption list. Deriving a fanout unit's `verification_commands` from its
  `file_scope` through this selection is a named follow-up (#1697).
- **A diagnostic request queued behind a busy provider no longer holds a
  global execution slot while it waits.** `DiagnosticExecutionEngine._observe`
  took the global slot before the provider slot, so when two overlapping
  requests both reached pyright first, the two global slots were held by one
  pyright runner and one pyright waiter and ruff could not start although
  nothing ran in its place. The engine now takes the provider slot first, so a
  global slot is only ever held by a runner that is executing. This is the
  fault behind the bounded-execution test that failed three times and was
  answered each time with a wider deadline (#1599, #1755, then at 60s on
  Linux): the overlap it waits for is now guaranteed rather than scheduled, a
  new test forces the interleaving that hung, the deadline is unchanged, and a
  failure reports the observed `active` map instead of `False is not true`;
  it also releases the runners on failure, so a broken engine reports at one
  deadline rather than after every queued runner has waited out its own
  (#1790). Observed: with the interleaving forced, the previous order hung to
  the deadline 3/3 with `active={'pyright': 1}` and the new order overlapped
  5/5; the unmodified test, run 30 times on a loaded macOS host, failed once
  before the change (360s, the same traceback as CI) and the new test against the
  previous order failed 1/1 at the deadline naming the observation.

- **A verdict one session declares can be read by a later one, from the
  command line, as the declaration it is.** `verification-gate` was told to
  issue `claim_verdict/v1` as PASS, HOLD or BLOCK and never where it goes; the
  completion store #1818 added (`omh_todo action=record` / `recall`,
  `native_completion/v1`) is that place, and the wrapper guidance for
  `verification-gate`, `code-review` and `ultraqa` now names it in one shared
  sentence, so a model that reaches a verdict, a ranked finding set or a QA
  result is told to persist it under the scope checkpoint with its
  `claimed_evidence_state` kept as written; `code-review`'s policy is derived
  from the review category's entry plus that sentence, never a pasted copy.
  Nothing read that store from outside a Hermes session;
  `omh runtime verdict show [--session] [--checkpoint] [--revision
  --environment]` does, through one reader in the store module. Its
  `native_completion_read/v1` payload carries `standing: model_declaration`
  and the claim boundary at the top level on every status and keeps every row
  at `standing: model_declaration`, `observed: false`; separates a store that is
  `absent` from one that is `empty` from one that is `present`; and reports
  each kind as `absent`, `stale`, `declared_no_findings` or
  `declared_findings`, so no record and a record that declared nothing found
  never read alike. Freshness is judged only against a binding the reader
  states -- `current` or `stale` for that exact revision and environment
  inside the 30-day cap, with the `completion` projection beside it -- and is
  `unbound` with no completion judgment when none is stated; a half binding
  is refused. A store that cannot be read is `malformed` and exits 1; a
  missing one exits 0. The tool's `recall` renders through the same
  projection unchanged. `docs/HARNESS_QUALITY.md` gains a Declared Verdicts
  section and `CONTEXT.md` a Completion dossier entry. Observed: one handler
  session wrote a PASS claimed observed, a HOLD with one finding claimed
  prepared and a QA PASS, then cleared its plan; the CLI read them bound and
  unbound with the claimed states intact, and a second session's `recall`
  agreed with the bound read field for field (#1782).

## 2.0.5 - 2026-09-22

- **The cut now asks for the site rebuild its own push cannot start.** A cut
  pushes with `GITHUB_TOKEN`, and GitHub does not create workflow runs from
  events that token caused. Pages listens for a push to main touching
  `site/**`, and the version bump always rewrites `site/index.html` and
  `site/i18n.js` — so the one push that changes the advertised version was
  the one push Pages never saw. Observed on the v2.0.4 cut: `Distribution
  Release`, dispatched explicitly, was the only run on that commit, with no
  Pages run and no CI push run beside it.

  The public badge therefore kept the previous version until some later merge
  happened to touch a path Pages watches, which left the page advertising a
  release as the last surface still naming the one before it. The cut now
  dispatches `pages.yml` next to the distribution dispatch it already makes
  for the same reason. No new permission — the job already holds
  `actions: write`. That step carries `continue-on-error: true`: by the time
  it runs the tag, the release and the distribution dispatch have all
  happened, and a site rebuild that fails for a reason of its own must not
  repaint a finished cut as a failed one. It still goes red on its own row.
  The distribution dispatch above is deliberately not treated this way —
  if that one fails nothing publishes, and red is true.

- **A release body is now bounded by what the surface it is published to
  accepts.** The 2.0.4 cut tagged and pushed, ran its gates green, and then
  failed at publication: `HTTP 422 Validation Failed / body is too long
  (maximum is 125000 characters)` against a 228,212-byte section. Nothing was
  released, and the npm and Homebrew steps after it were skipped, so the
  version existed as a tag with no installable artifact. The bound that
  existed, `MAX_NOTES_BYTES`, is 262,144 — twice the limit of the surface the
  artifact is published to, which is not a bound at all, and it grew more
  likely to fire with every release that shipped more work than the last.

  `omh release notes` now trims an oversized section to whole entries plus one
  trailer stating how many it kept, how many remain, and where they are; a
  section already inside the bound is returned byte for byte, so an ordinary
  release publishes exactly its authored notes as before. The CHANGELOG stays
  the record and is never rewritten — the bounded body is a view of it. The
  length is counted in UTF-16 code units rather than code points, because
  GitHub says "characters" without saying which and the UTF-16 count is the
  larger of the two readings. A single entry that cannot fit raises rather
  than truncating inside it, since half a sentence published as a whole claim
  is worse than a refusal a person can act on.

- **A route OMH cannot decide now carries the question it could not answer,
  and an answer to it can be recorded and measured.** When the deterministic
  router reaches an undecidable route -- a script its trigger tables do not
  cover, a near-tie between two candidates, or a low-confidence score -- it
  already hands the shortlist to model selection. It now also types that
  shortlist as a question: one relative Choice over the candidates plus `none`,
  and one absolute yes/no per candidate, built by the same builder the routing
  corpora are exported with, from the handoff's own candidates so the two
  cannot name different shortlists. `omh chat route`, `omh chat interact`, `omh
  chat route-hint` (as a new top-level key of `chat_route_hint/v1`) and the
  `omh_interact` plugin tool carry it. `omh_recommend`, `omh_context` and the
  awareness rail do not, and that is a statement about wiring rather than
  policy: those three build their own payload from the awareness hint and never
  see the core route.

  Nothing about the route changes. A decidable route carries no question at
  all, an unanswered question leaves the deterministic route in force, and a
  recorded answer does not re-route anything either. What an answer is FOR is
  measurement: `omh_route_answer` writes one `route_question_answer/v1` per
  session and question under the OMH home, embedding the same
  `routing_question_answers/v1` row that `omh chat route-questions score
  --answers <dir>` already reads, so an answerer is scored against OMH's own
  corpora instead of writing into a ledger nothing reads. An answer whose
  digest names a different question is refused rather than recorded, because a
  record joined to the wrong question measures the wrong thing.

  The record names the request it answers for, not only the question. It
  carries `message_sha256` over the raw request and repeats it on the embedded
  row, so a row read out of a JSONL file still identifies its own request and a
  scorer can join on it. A caller sends the request and OMH derives the hash,
  or sends the hash when the text is not at hand; sending both with different
  values is refused, because they name different requests and choosing one
  would record the answer against a request nobody meant.

  `confidence_source` is derived from who answered, never taken as an argument
  and never called calibrated: `self_reported` when the host model answered
  about itself, `answerer_declared` when a plugin reported a number OMH did not
  observe. OMH sees only which answerer the caller named -- not the request,
  not the response, not whether anything was called at all -- and a field
  asserting a vendor's calibration would be a claim about a model written from
  a tool argument.

  The answerer ladder reports what could answer the question on this machine,
  one provable tier at a time: a Jev-class plugin whose manifest declares a
  `jev_` tool is `installed`, one Hermes' own config also enables is `enabled`,
  and one whose tool has reached dispatch here at least once is `observed`.
  That last tier is a durable timestamp in the burst ledger rather than a scan
  of it, because the entry ring holds 200 calls and a scan would report a
  plugin as never used after 200 unrelated ones. Every tier under-claims by
  construction: a config shape the bundle's reader cannot follow reports
  `installed` rather than `enabled`, and an unreadable plugins directory drops
  the rung instead of inventing one.

  The ladder is a report and never a recommendation. No text OMH injects into a
  turn names a third-party tool, and no rail was added for this: OMH warning
  about a plugin's egress in `omh doctor` while nominating it in the prompt
  would be the same product saying two things. A test pins that the prompt
  context is byte-identical to the awareness text it was always built from.

  One rollout note: the HUD reads its required tool list from the bundle's own
  `PROVIDED_TOOLS`, so an install that has not run `omh update` will report the
  new tool as missing until it does.


- **The cases that gate OMH's router are now questions anything can answer, so
  a second opinion can be measured on the same ground.** `omh chat
  route-questions export` projects both shipped routing corpora into typed
  questions: one relative Choice over the router's own candidate shortlist plus
  `none`, and one absolute yes/no per candidate. The two are deliberately
  separate questions. The Choice picks WHICH workflow and always returns one of
  its options, which is why `none` has to be one of them; each yes/no decides
  WHETHER that one workflow is what the request asks for, answerable without
  reference to the others. An answerer may pick a candidate and still say no to
  every fit, and the scorer reports that as it stands rather than repairing it.

  `omh chat route-questions score` reads answers and always includes the
  deterministic arm, so no arm is ever reported alone. It takes a JSONL file of
  `routing_question_answers/v1` rows or a directory of `route_question_answer/v1`
  records, which join a corpus item by question digest. A malformed row is
  counted and named by its line, never dropped: an arm that answered badly and
  an arm that did not answer are different results, and only one of them may be
  excluded from a denominator. Every rate is a `reported_rate` payload naming
  what it divided, so an arm with nothing to score reports `percent: null`
  rather than a confident zero.

  The deterministic arm's verdicts are the routing-precision corpus's own, read
  through two new accessors rather than re-derived. That is the whole load-
  bearing decision here. `clarify` with a named candidate is a PASS in the
  negative corpus -- the router asks one question instead of opening a workflow,
  picker, or handoff -- and the EXPECTED intervention in the positive one, so a
  single re-invented predicate cannot serve both. A measured draft that used one
  reported the shipped router as over-routing on more than a third of the
  negative controls, on a corpus this repository gates at zero, which would have
  put two OMH surfaces on record disagreeing about OMH's own router with the
  benchmark holding the wrong number. A test
  now pins the projection against `build_routing_precision_demo` case by case,
  and shows the pin failing when the verdict is replaced. That corpus's pass
  verdict on each case is also read rather than only carried: a score report
  fails by name when the corpus records a case the routing-precision gate
  fails, so a report cannot read clean while the gate reads red.

  A recorded answer joins back to its question by digest, and the digest names
  the request rather than the shortlist it produced. A digest over the question
  block alone is shared by every request the router shortlists the same way,
  which on these corpora is most of them, so a reader joining by digest would
  have scored an answer against whatever the first case behind it expected --
  an arm that answered correctly recorded as having hijacked a negative
  control. The digest covers the request and its candidates, and where a digest
  still reaches more than one case, which is where the two corpora record the
  same request verbatim, the record is reported as ambiguous and scored against
  none of them.

  The message is the join key, and the digest reports the shortlist. A question
  digest covers the candidate list as well as the request, and the candidate
  list is cut per surface -- a route hint asks about two candidates where a
  full route asks about three -- so the same request asked on two surfaces
  produces two digests and a digest-only join would drop the answer. A recorded
  answer joins by message first; the digest then says whether the shortlist was
  the same one, reported per answer as `digest_match` and counted per arm as
  `digest_mismatch`. A mismatch is scored, because the answer is about that
  request; it is reported, because an arm asked about a shorter list was not
  asked quite the same question.

  A corpus question is now built from the same place a live route builds one.
  A live route attaches a question only where it could not decide, and it
  builds it from the undecidable route's candidate handoff; the projection read
  the route's public recommendations instead, which drop each candidate's
  description and carry the route's prose reason rather than the handoff's
  machine codes. The two questions therefore never shared a digest, and an
  answer recorded on a live route scored as having answered nothing. Both sides
  now call one builder with one set of inputs. The cases a live route never
  questions -- the ones it decided -- still carry a question for the offline
  arms, and an arm answering recorded live routes is denominated on the
  undecidable cases alone, with the rest named `not_live_joinable` in each
  rate's excluded list rather than counted as questions it failed to answer.

  An answers file is written by a model or by whoever ran an external arm, so
  it is read as untrusted input. Every file is bounded before it is read whole,
  every string that reaches a report line is stripped of control characters and
  capped, because a report is an artifact somebody attaches to a PR and an
  embedded newline in an arm name forges a line in it. A row claiming the
  reserved `deterministic` arm name is refused by name rather than merged into
  a tally the report then replaces.

  No routing case was added. The projection reads the two tuples and adds
  nothing to either, because their lengths are pinned across several test files
  and a benchmark is not a reason to move a gate. The expected answer for each case
  comes from the case's own record, including the one intervention case whose
  correct answer is to open nothing and the clarify cases that pin no candidate;
  both map to `none`, which the corpora say and the projection does not decide.

  `benchmarks/routing-questions/v1` is the lane. It answers batches through
  `omh coding hermes-child dispatch --confirm-dispatch`, with the prompt on
  stdin and the answers collected from a file the prompt names, because that
  boundary reports usage metadata and never model text. It is offline by
  default and refuses a live run without `--allow-paid-live`,
  `--max-paid-calls` and `--confirm`, with a second refusal inside the library
  so importing it and calling a harmless-sounding function cannot spend
  anything. It never imports `omh`: the lane measures the product a person
  installed, through its executable, not the checkout it happens to sit in. The
  arm that runs the operator's own authenticated Hermes rather than the
  isolated child has its process directory and its `TERMINAL_CWD` both pinned
  to the batch workspace, so a model with the file toolset resolves relative
  paths there and not in the checkout the lane was launched from. Answers are
  written as each batch returns, so a run that stops partway keeps every answer
  it has already paid for, and a model-written row is narrowed to the
  documented answer keys before it is persisted. No live arm has been run, and
  running one is an operator's call.


- **`omh doctor` now says which Jev-class plugins a machine holds, and what
  each one's catalog entry declares.** Jev (TypeSafe System One) is a
  non-generative decision model: it answers typed questions and cannot write
  code, so OMH never routes it and never calls it. Community Hermes plugins do
  call it, and several ask for hooks the OMH bridge also registers — most
  sharply `pre_llm_call`, where OMH injects its route hint while a Jev skill
  router nominates a skill, so one message can reach the model carrying two
  nominations. Nothing in the CLI said that was happening.

  The new `plugin_jev_sidekick` check is appended on every run, in both
  branches: a machine with no signal reports `optional: no Jev-class plugin
  installed`, and a machine with one reports the tier reached — installed,
  enabled, or credential name present — plus one note per plugin naming the
  tools and hooks its manifest declares, the hooks it shares with the OMH
  bridge, and, verbatim, whatever its catalog entry discloses about what
  leaves the machine. Every note says "declares" and carries the artifact and
  date OMH read it from, because a catalog description is its author's
  statement and a `plugin.yaml` is whoever installed it: neither is evidence
  that the plugin ran or that any request left the machine. `omh doctor
  --json` carries the full `jev_sidekick_posture/v1` payload.

  Three local reads and nothing else: the plugin directories under
  `$HERMES_HOME/plugins`, Hermes' `plugins.enabled` list, and the variable
  NAMES in `$HERMES_HOME/.env`. Manifests go through the existing bounded
  subset reader, so a construct it does not model is reported as unread
  rather than guessed at — an unread `provides_hooks` leaves the hook overlap
  unestablished, which the check says instead of reporting no overlap, and an
  unread plugin directory stops the check from reporting absence at all. The
  credential scan reaches its names through a new `allowed` parameter on
  `env_key_names` rather than by enrolling them in `HERMES_ENV_KEY_PROVIDERS`,
  which feeds provider entitlements and would reorder mixture chains around a
  model that can never be a chain member. No value is read, anywhere.

  A read that did not happen is reported as itself everywhere, not only for
  hooks. Enablement is `enabled`, `not enabled`, or `unknown` with the reason
  attached: Hermes' `plugins` node written as a flow mapping is valid YAML
  Hermes loads and a form the shared block reader walks past, and it produces
  the same empty list a config that enables nothing produces, so the check
  says which of the two it read rather than asserting the commoner one. A
  manifest that declares a name OMH could not read is classified on its
  `jev_` tools alone, because the directory name is then a guess and a guess
  that lands on a catalog entry would attach that maintainer's verbatim
  egress disclosure to this install.

  Everything the sweep reads is bounded and untrusted. A symlinked
  `plugin.yaml` is refused and named for the reason the symlinked-directory
  guard already states, the manifest cap is taken at the read rather than
  from a preceding `stat` that a zero-length file walks past, Hermes' config
  is bounded like the manifests beside it, and a directory name — which
  passes no reader and is chosen by whoever created the directory — is
  stripped of control characters and length-capped before it reaches a
  payload field or a report line an operator pastes elsewhere.

  `ok` stays `True` in every branch, including the warning one: a third-party
  plugin an operator installed deliberately is not an OMH install failure and
  must not flip the doctor exit code. The next action is built from the
  branches that fired and names the `.env` path OMH read rather than a
  default spelling of it, and it describes an overlap as the declaration it
  is: the bridge registers eight hooks, only one of which is the nomination
  surface, so what a shared hook supports is "declares the same hook OMH
  registers" and not a sentence about what the plugin does. The check groups
  into `optional_surfaces` by its `plugin_` prefix. `Check` gains an optional
  `detail` payload, `None` for every check that carries no structured
  finding, so `observed` keeps its one meaning as a boolean.


- **OMH now recognizes a model class it cannot route coding work to, and
  refuses that work by name instead of preparing it.** TypeSafe's Jev answers
  a typed Choice, Score, or Noul over options the caller supplies and its own
  jaggedness page states it "is not trained to generate text". Until now
  `jev-1.13.0` fell to family `unknown`, inherited generic prompt discipline,
  and would have been routed an implementation unit like any other id, with
  the failure arriving from the provider rather than from OMH.

  The class is `model_class()`, read off the family, with `generative` as the
  default so every model the catalog has never met routes exactly as it did
  before. `non_generative` is refused at each surface that would hand a model
  work to write: `omh coding model-route --model jev…` answers
  `status: model_refused` and prepares no model, no effort, and no chain;
  `omh model-chains set` exits 2 and writes nothing; the operator
  category-maestro config rejects such an entry by name on read and on write;
  and a chain entry that reaches the resolver anyway, from a hand-edited chain
  document or an operator recommendation document, is skipped with a record
  naming the class while the next generative entry takes the head — on the
  catalog lane and on the Hermes editorial lane alike. The refusal of a
  requested id is decided before any catalog is consulted, so neither lane
  can route around it.

  This narrows one stated invariant and the docstring that carried it moved
  in the same commit: an explicitly requested model still wins over every
  catalog and is still never adjudicated on quality, but it is now refused
  when its class cannot do the work at all. The refusal payload carries a
  `refusal` record with the id and the kind, so a JSON consumer never parses
  a sentence to learn what happened, and the key is present only on a refused
  route, leaving every payload that routes today byte-identical.

  Recognition is the rest of the onboarding, done honestly rather than
  skipped. `jev-1.13.0` is an exact contract read from docs.typesafe.ai on
  2026-09-21, with `jev-latest` and `jev-preview` as declared alias rows
  because both move on the next release. It carries no effort ladder, and
  `model_class`, `question_types`, `max_choice_options`, and `rate_limits`
  are optional keys that do not move `model_contract/v1`, on the same terms
  `served_ids` and `limits_note` joined it. `max_output_tokens` is `0` rather
  than absent: output is typed answers billed at zero, which is also why the
  price row is `(0.042, 0.0)` — a zero is a published rate, and a missing row
  would make every run on the model report no cost at all. The bare word
  `jev` is recognized as a family, because TypeSafe sends it in the `model`
  field and a gateway spells it `typesafe/jev`, but it inherits no contract:
  no vendor page describes that spelling. Both classifier surfaces read the
  bare word the same way, so a dynamic workflow spec that names `jev`
  describes a model target rather than an agent.

  The coverage dimensions that stay `missing` for reasons of this class are
  `effort`, `category_projection`, and `provider_eligibility`, and a test pins
  that reading. `effort` is missing because there is no effort parameter;
  `category_projection` and `provider_eligibility` are missing because the
  model is in no shipped chain, which is the decision rather than an
  oversight. The only levers that would turn them green are an invented rung,
  an invented chain entry, or an `intentional_exclusion` row that would claim
  OMH deliberately does not cover a model it does cover. The same row also
  reports `data_handling` as `missing`, which is not about this model —
  every contracted model in the catalog reads the same way — and reports
  `calibration` as `covered` through the generic fallback, which records that
  the generic discipline applies rather than claiming a model that takes no
  prompt was calibrated.


- **The HUD route label drops its parent-equality token.** A lane the tool
  routed to the model the parent session itself runs rendered as
  `category:deep(deepseek-flash:high =parent)`. The token said the dispatch
  cost what the parent costs, but it compared the model named on the row
  against the parent's model, which no row on that screen shows — so the
  reader could not check the claim against anything in front of them, and on
  the owner's `deep` chain, whose head IS the session's model, it rode every
  child row. The lane now reads `category:deep(deepseek-flash:high)`: the
  category names the lane, the parentheses name the model that ran, and the
  state tokens that remain (`fallback`, `inherit`) each name an EVENT in the
  route rather than a comparison. Nothing about which model ran is lost —
  that was always the model name itself. The `read_omh_hud` payload still
  reports `same_as_parent` for a caller that holds both models; the widget no
  longer reads it, and the widget-pack gate now pins that absence.


- **A planning run that starts editing now asks the person first, instead of
  being told not to.** Give `ralplan` a prompt with implementation intent
  folded in — "ralplan implement the refactor now and open the PR" — and it
  implements. Its skill has refused that in prose since it shipped: one line
  routes a full delivery cycle to `ultrawork`, a worked example is built from
  that exact sentence and answers "stop at the reviewed plan", and a third
  says to start a follow-on engine "only on the user's explicit go-ahead".
  Routing is not what failed either; measured on
  `build_chat_interaction_payload`, the sentence dispatches to `ralplan` at
  score 12 with `next_action: present_plan`. The message reaches the right
  skill and the skill's own rule is then read past, so a fourth sentence was
  not the fix.

  `plan_stage_gate` is the enforcement that was missing. A planning run stamps
  its checklist `plan_stage: awaiting_acceptance` when it declares it
  (`omh_todo`, a new closed-vocabulary field on `omh_todo/v1`), and while that
  holds, a `write_file` or `patch` in the owning session is escalated from
  `pre_tool_call` to the host's human-approval gate. That gate is the only
  directive the hook offers that a model cannot decline — `block` becomes a
  tool result, and one measured session read 185 host refusals and repeated
  the call anyway, while `approve` is resolved by
  `tools/approval.py::request_tool_approval` and never returns to the model as
  text at all. It is also, literally, somewhere to put the question, and the
  question is the feature: *this session declared a plan and has not recorded
  you accepting it, and this call edits a file. Approving implements now;
  denying stops at the reviewed plan.*

  Nothing reads anybody's prose. Two fields decide it — the stamp, and the
  plan projection's own `established` verdict, reused rather than re-derived
  so the gate cannot disagree with the HUD about whose plan a record is or
  when it went stale. This repository has already paid for the alternative:
  the plan's stop criterion used to be matched out of item text and read
  "verify the retry is not blocked on the session limit" as blocked while
  missing "waiting on the owner's review", wrong in both directions on
  ordinary input. The guard against its return is a mutation table rather than
  an assertion about today's wording: the same call is made twice over records
  whose every word argues the opposite of what the field says, and the verdict
  follows the field.

  The approval gate is the strongest thing OMH can do to a person's turn, so
  every state the records cannot settle is silence. No record, a record this
  session does not own, a stale one, a finished plan, an unreadable home, a
  stamp this build cannot classify, a call the host named no session for, and
  every tool that is not one of the host's two file-mutating ones all return
  nothing — the discipline #1738 landed for the unarmed-wait directive,
  applied to a stronger action.

  Ownership is asked separately from freshness, and the separation is a
  correction rather than a flourish. The renderer's `established` verdict
  does not answer "whose plan is this": its identity rule reads an
  unattributable plan as BELONGING, deliberately, so a real checklist is
  never hidden from its owner on missing evidence. A gate that stops a
  person's turn needs the opposite default — and a home-wide stamped record,
  which the chat writer produces whenever the host names no session on the
  same call that carries the stamp, projects as `established` for every
  session id that asks. Reusing the renderer's verdict as ownership armed
  this gate for three unrelated sessions under review. The projection now
  states the raw fact, `own_record`, decided after transport ids are
  translated to durable keys so a comparison of raw ids cannot refuse a
  record the session does own; the gate reads that first. A stamped record
  with no owner is unattributable by construction, and refusing it loses
  nothing. Absence of the field is unknown rather than "not accepted",
  so a delivery checklist, a CLI write, and a record predating the field are
  all ungated; reading absence the other way would put this in front of every
  edit anyone makes with a todo list open.

  **An unattended run is not gated at all, and that is a decision rather than
  an oversight.** `request_tool_approval` fails CLOSED with no person present,
  so escalating on `hermes chat -q`, a webhook, or a delegated child would not
  ask anything — it would refuse the edit with the host's wording for a rule
  nobody can answer, which is how a gate meant to protect a person becomes the
  reason their automation stopped. The predicate is the one the repeat guard's
  stage two already uses, and the fallback is deliberately not the repeat
  guard's `block`: a loop that keeps running is worse than one that is
  stopped, while a session doing ordinary work is not. Cron is the stated
  exception and cannot be closed from a plugin — `HERMES_CRON_SESSION` is a
  ContextVar, never a process variable — so a cron turn reads as attended; at
  the `approvals.cron_mode` default of `deny` the edit is refused with the
  host's wording, and only a cron job that both stamps the field and then
  edits files reaches it at all.

  The `[a]lways` allowlist grain is set explicitly to the constant
  `omh_plan_stage_edit`, and the reason is not the one `request_tool_approval`
  documents for itself. That function hashes the reason into a key when it is
  given none, but a plugin directive never reaches that branch —
  `_resolve_block_from_details` calls it as `rule_key or tool_name` — so an
  omitted key is the TOOL name, and what a person's `[a]lways` would store is
  `plugin_rule:write_file`. That grain is wrong twice: it re-asks at the next
  `patch` what a `write_file` prompt already settled, and being named after
  the tool rather than the rule it would permanently allowlist that tool for
  every OMH rule that ever escalates it, including ones that do not exist yet.
  A key carrying the session, the file, or a digest of the plan would instead
  leave a dead entry in their own `command_allowlist` per session, or re-prompt
  somebody who had already answered. One line in their config, visible and
  removable, covering both file-mutating tools with one answer.

  Two honest limits. The stamp is written by the run, at declaration time, so
  a planning run that never stamps is not gated — the enforcement binds once
  the record exists, and what makes that worth building is that stamping
  happens at the compliant start of the run rather than at the tempted middle
  of it. And a run can record `accepted` without being told to; that is a
  deliberate, recorded declaration in a record a reviewer can read, which is
  what the prose rule never produced.
## 2.0.4 - 2026-09-21

- **A prepared route now names the session that prepared it, so the HUD label
  it exists to upgrade finally reaches the HUD.** `omh_delegate_route` records
  every route it writes in `~/.omh/routing/route-provenance.json`, and the
  reader uses that record to say a lane was ROUTED to the parent's own model
  rather than merely inheriting it — the shape the owner's `deep` chain
  produces, since its head is the model the session itself runs. The reader
  threw the whole history away in session scope, on the correct observation
  that a record carrying no owner cannot be claimed by one conversation. The
  TUI widget always reads session-scoped, so the upgrade had never once fired
  on screen: three children observably routed to `deep` rendered as
  `inherit(deepseek-flash:high)`, twenty seconds after the record that said
  otherwise.

  The row's LABEL came back the same way, from the one source that can prove
  it. The title column renders a dispatch goal, and it had been reading the
  host manifest — which names no session, so session scope drops it and the
  row went out blank beside its id. A child's first user row is inside that
  child's own session, so attributing it is a primary key rather than a
  timestamp guess, and the sentence is the same sentence: the manifest's
  `goal` IS the dispatch prompt, so nothing new in kind reaches the screen.
  The manifest stays unattributable and stays dropped; the fallback never
  outranks a goal that was attributed.

  The fix is the owner the record was missing, not a scope exemption. The
  tool handler already reads the dispatching session from the host keyword
  (`host_session_id(kwargs)`, the durable id `state.db` names) to scope the
  route-restore baseline, and now stamps the same id on the provenance
  record; session scope filters the history by that owner using the same
  conversation set it already selects children with, so a record another
  conversation prepared still cannot label this one's lanes.

  The field is additive-optional inside `delegation_route_provenance/v1` and
  the schema version does not move, on the same terms `session_ref` and
  `deferred_reason` joined `omh_todo/v1`: the key is written only when
  non-empty, so a writer that cannot name its session produces the record it
  produced before, and a reader that predates the field ignores it. Bumping
  the version would have been the harmful choice — every existing reader
  discards a document whose `schema_version` it does not recognise, so a
  rollback would lose the global-scope labels that work today. An ownerless
  record stays unclaimed in session scope, which is exactly what it did
  before, so no install gets a worse label than it has; global scope is
  unchanged and still reads every record, because it makes no ownership
  claim about the children it lists either. A malformed owner refuses its
  record like any other malformed field, which the loader turns into "no
  provenance" — provenance only ever upgrades a label and still never gates
  routing.

- **A change nobody can prove with a command now has a page for the guide a
  person follows instead.** `VI. Manual test guide` is a phase of the
  `code-story` plan template, and the repository owned that artifact only for
  RENDERED surfaces: `omh-visual-qa` covers listing pages, states, and
  viewports and scopes out everything else on purpose. A CLI flag, a
  migration, a config change, a daemon restart, an install on a real machine
  — none of those had a page saying what to write. The new
  `skills/ulw-qa/references/manual-test-guide.md` is that page, reached from
  one `ultraqa` quality-bar line, because `ultraqa`'s declared subject is
  test scenarios and its required inputs (changed behavior, acceptance
  criteria, known risk areas) are already the guide's inputs.

  The rule the page is built around is the one the tree already held in one
  place and nowhere else: `skills/ulw-work/references/tdd-red-green.md`
  refuses manual testing as a way to close a tests-first lane, because a
  manual check leaves no output to paste and no command to rerun. A manual
  test guide is a handover artifact and never evidence — a finished guide is
  `prepared_not_observed`, and only a run moves anything out of that state.
  Stated in `verification-gate` vocabulary so there is one vocabulary and not
  two: a written step is a `verification_matrix/v1` row with no result, and a
  person who runs it can supply an `observed_check_results/v1` row. The page
  does not restate that row's fields — it renders `verification-gate`'s own
  declaration of them, because three places in the repository already
  enumerate that row in prose and no two agree, and the field a fourth copy
  would most likely lose is freshness, which is precisely the field a manual
  run most needs and most often loses. A report of "looks fine" supplies none
  of the fields and meets the refusal the gate already applies to `works as
  expected`. The row is also where the evidence stops: OMH persists no
  verification output (#1782), so it lives in the session and nowhere else,
  the same thing `handover-artifacts.md` marks with its "Held where" column.
  `done` on the phase therefore says the guide exists, never that anyone
  followed it, and a claim citing it earns HOLD or BLOCK with the manual
  checks listed not-run.

  What the page carries beyond the boundary: the four-field step shape
  (setup, do, expect, broken — `broken` meaning the near-miss, the wrong
  result that reads like the right one), a closed list of four reasons a step
  may stay manual at all, so a step that could have been a test is named as
  one rather than accumulating in a document somebody re-runs by hand every
  release, and the `enumerate, do not sample` rule generalized off
  `visual-qa`. Sources follow `omh-wiki/references/handover-artifacts.md`
  rather than restating it: the plan record is the only one that outlives the
  session.

  `tests/test_manual_test_guide_reference.py` holds what is machine-checkable
  — the body pointer and the reference exist together, the named artifacts
  survive a rewrite, the row shape is still the gate's live declaration, the
  page points at the source table instead of copying a paragraph of it, and
  neither the page nor `tdd-red-green.md` can delete the refusal they share.
  Two limits are stated rather than implied, in the test's own docstring as
  well as here: the rule's wording is prose and no gate checks it, and the
  shared-refusal test is deletion-only — a rewrite that keeps the word
  `unobserved` and reverses the sentence around it passes, because catching
  that needs a matcher over prose and this repository does not match prose.

- **Closing a story has an owner.** The `code-story` plan template stamps ten
  phases and the last of them, `X. Close`, was the only one nothing answered
  for. `verification-gate` owns the evidence a claim needs BEFORE completion
  or merge; `todo-checklist` says a done mark is a declaration;
  `github-event-ops` labels an issue and never closes one. Nobody owned the
  act of closing.

  It belongs to `todo-checklist` now, through
  `references/closing-a-story.md`, because a close judgement that reads
  records can read the plan record and nothing else.
  `observed_check_results/v1` and `claim_verdict/v1` are instruction text:
  nothing writes them, nothing reads them, there is no store, and the same
  holds for ranked review findings and QA pass/fail. So the page is scoped to
  what survives -- `state`, `phase` and `blocked_reason` under
  `$OMH_HOME/runtime/todos/<session key>.json` -- and its source table is
  rendered from the same `HANDOVER_RECORD_SOURCES` the `wiki` handover page
  uses, so the two cannot come to disagree about which of the four is a
  record. A verdict still in this conversation is cited as a declared output
  of this session, never as something the next reader can go back to.

  What the page will not let a close claim is the part worth reading twice.
  Every phase `done` means every phase was DECLARED done; a phase `done`
  carrying a `blocked_reason` was skipped on purpose and the template refuses
  to let it leave the list; no `blocked_reason` anywhere means nothing was
  RECORDED as blocked, which is not evidence that nothing was. Landing the
  change happens outside OMH, which makes no network calls and never watches
  anything merge, so a close report names who observed the merge commit or
  the CI conclusion, or says it has none.

  **A run reaches the page through the phase template, not by asking in
  plain words, and that gap is open.** A chat trigger was built, measured and
  withdrawn. Built from `close`, `story` and a finishing word as an unordered
  token set, it dispatched nine sentences at high confidence that have
  nothing to do with a plan -- a bedtime story, a closing ceremony, a
  newspaper layout, a Jira ticket, an incident -- including two that were its
  own negative controls with one word added. As a closed phrase list it still
  matched inside "close the story book", because `phrase_is_spoken` enforces
  a right edge only for single-word phrases. And it missed four of the six
  natural phrasings of the real request, `close this story` among them. A
  trigger that is simultaneously too wide and too narrow is measuring the
  wrong thing, so none of it shipped. The measured corpus, and the two
  reasons reading a record instead cannot be the discriminator either, are
  filed as #1789.

- **The bare word `close` no longer names an accounting workflow.** A
  multi-word trigger is also scored as its separate tokens, so
  `finance-analysis`'s phrase "month-end close" handed it `close` -- a
  connection, a modal, a file handle, an estimate near a number -- and made
  it the top candidate on every sentence containing the word, including
  "close this story, it is done" at a score of 4. The token is held back now.

  An accounting request that spells the cue is untouched: "month-end close"
  is a domain trigger worth +54 through `domain:`, and the three phrasings
  carrying it hold at 54. An accounting request that does not spell it loses
  the 3 points the loose token was giving it -- "variance analysis for the
  monthly close" keeps its dispatch at 9, but "we need to close the books for
  September" and "reconcile the ledger before the close" lose the top slot in
  a clarify, and two more drop from medium to low. No accounting sentence
  lost a dispatch, which is why this is priced as acceptable rather than
  described as untouched.

- **The gate that catches a skill body change now says which body changed.**
  Editing a skill body moves a pinned sha256 in
  `tests/fixtures/agent_skills_hermes_digests.json`, and until now the failure
  was a bare dict compare over 124 keys: `Diff is 11220 characters long`, the
  elided preview lining up two unrelated skills because the produced dict is
  in catalog order and the fixture is sorted, and the edited skill's name
  nowhere on screen. It now reports `moved=[...] added=[...] removed=[...]`
  and says to re-derive the fixture sorted-key in the same commit.

  The reason this matters is that no other gate sees a body change at all.
  The ten `docs ... --check` gates compare a producer against its generated
  file, so they find DRIFT; an intended body edit moves both sides together
  and every one of them stays green. That is correct behaviour for a drift
  gate and is not a gap in them — the digest fixture is a pin, and it fired
  exactly as it should. What was missing was that the pin was undocumented in
  both places a person doing this work looks, `CLAUDE.md` and
  `docs/ADDING-A-SKILL.md`, and that its failure named nothing. Both are now
  written down, with the distinction between a drift gate and a pin stated
  where it is needed.

- **Interactive `omh setup` now asks whether OMH should watch for its own
  updates, so the capability stops being invisible.** `omh update-check set
  --mode off|notify|auto` has shipped for a while and runs from the launch
  path, but the only way to find it was to already know its name. The wizard
  now asks once, as its last question — every other group configures how the
  assistant behaves, this one configures how the install maintains itself,
  and the apply phase right after it is the answer's first reader
  (`_release_source_commit_for_state` returns early while the mode is `off`,
  so an opt-in recorded here is in effect for the same run).

  The shipped default is unchanged. `off` is the pre-selected option, read
  from `DEFAULT_UPDATE_CHECK_MODE` rather than written beside it as a
  literal, so Enter through the wizard lands exactly where `--yes` lands and
  cannot drift from it: pressing Enter must not be how a machine starts
  making network requests. `--yes`, `--json`, `--no-interactive`, and every
  run without a terminal never see the question and write nothing at all —
  the key stays absent, which is what keeps it askable later.

  Asked once, then never again, including when the answer was `off`. That
  needed a distinction `read_update_check_policy` cannot make: it normalizes
  an absent record to the shipped `off`, so "never asked" and "answered off"
  come back identical and a predicate reading it would re-ask on every
  interactive run forever. The new `update_check_policy_recorded()` reads the
  stored record instead, which is the only place the two differ, and every
  answer — `off` included — is written, so the record is the answer rather
  than the deviation from the default. A corrupt or hand-edited value reads
  as unanswered, matching what the policy reader already does with it.

  The question states both consequences it is asking consent for, in all four
  languages: `notify` and `auto` each contact GitHub at most once per 24-hour
  interval, and `auto` additionally runs `omh update`. The policy lives at
  `$OMH_HOME/setup-profile.json`, inside OMH's own home, so the default `omh
  uninstall` — which removes that home — takes it back with everything else;
  nothing is left under a host-owned root for uninstall to reverse
  explicitly.

- **The three artifacts that close a long piece of work — a deep guide, an
  ELI5 pass, and a quiz — now have written guidance, on `wiki`.** A coverage
  pass over all 124 shipped skills found these late stages unowned: `docs`
  says outright that it is not a generic documentation writer, and
  `materials-package` routes code documentation away to "the docs/wiki
  workflow", which leaves the wiki half of that pointer as the only live
  destination. `paper-learning` already had the level vocabulary and a
  coverage ledger, but its input is a supplied paper, not the change you just
  shipped. Nothing at all matched `quiz`, `flashcard`, or `exam`.

  The load-bearing rule in the new `wiki/references/handover-artifacts.md` is
  that all three are assembled from what is readable, never from what you
  remember. By the time they get written the early reasoning is out of
  context — compaction took it — and a model asked to explain a decision it
  can no longer see reconstructs a fluent, diff-consistent, invented one that
  nothing downstream can tell from the real reason. This is the rule the
  repository already applies to stop criteria, one stage later —
  `blocked_reason` exists as a field because inferring it from item text was
  wrong in both directions.

  What "readable" means is stated per source, because only one of the four is
  a record. The plan record is persisted under
  `$OMH_HOME/runtime/todos/<session key>.json` and read with
  `omh runtime todo show`: it carries `state`, `phase`, and `blocked_reason`,
  and it outlives the session. The verification, review, and QA names —
  `observed_check_results/v1`, `claim_verdict/v1`, ranked findings, pass/fail
  evidence — are declared outputs that OMH asks a model to produce and
  stores nowhere, so they live in the session's own context and are subject
  to the same compaction as the reasoning above. The page says so in a "held
  where" column rather than presenting four equal records, and tells the
  writer to record which sources were actually readable instead of
  reconstructing what is gone.

  The quiz is a completeness check on the deep guide, not a study aid, and
  its admission rule is what keeps it from degenerating into "what does this
  PR do": **every question cites one record entry, and a question that cannot
  cite one is not written.** Only three entry kinds qualify — a review
  finding, a failed check, or a `blocked_reason` — because each is a record
  of something that actually went wrong or was actually decided. A question
  the deep guide cannot answer is a hole in the deep guide, which is what the
  quiz is for. The rule's reach is stated too: only a `blocked_reason` can be
  cited durably, because only the plan record survives the session.

  An empty quiz does not claim a clean run. With three sources unstored,
  `omh_todo` opt-in, and another session's record unlinked after a day, zero
  entries is the ordinary outcome, so the quiz reports a basis drawn from
  `HANDOVER_QUIZ_BASIS` — modelled on `PAPER_LEARNING_SOURCE_STATES`, next
  door to the level vocabulary it already borrows — where "could not read it"
  and "read it and found nothing" stay different answers. Only
  `sources_read_no_entries` says anything about the change itself.

  The guidance is a reference file, so it loads on demand and costs the
  always-loaded skill pack nothing; only the pointer section on `wiki`'s body
  is paid for, and `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` moves by that section
  alone. The ELI5 pass is written at level `very_easy`, reusing
  `paper-learning`'s word rather than coining a second name for one idea, and
  `tests/test_handover_artifacts.py` re-derives every citation from the
  surface that declares it — the todo validator for the plan-record fields,
  each skill's own declared outputs for the rest. A citation also names a
  word its own declaration must carry, so swapping
  `observed_check_results/v1` for the sibling `verification_matrix/v1` fails
  rather than quietly turning observed into prepared, and the quiz's table of
  admissible entries is generated from a closed producer so no hand-written
  row can admit a source nothing declares.

- **A code story now has a shape OMH ships, and a stage it does not do stays
  on the list.** `omh_todo` takes a new optional `template`, whose
  one value is `code-story`: send it with `action=set` and the plan is
  declared with the ten phases of a code story — `I. Story`, `II. Implement`,
  `III. Review`, `IV. QA`, `V. Fix`, `VI. Manual test guide`,
  `VII. Deep guide`, `VIII. ELI5`, `IX. Quiz`, `X. Close` — in delivery
  order, one pending item each. The phases come out of the new
  `todo_templates` module rather than out of whatever the model invents that
  day, and the name is stored on the record (`template`) and projected into
  the HUD payload, so "is this a story plan" is a field a reader reads rather
  than phase labels matched back out of prose.

  The stamp is enforcement, not decoration. Every later write to a stamped
  record — a whole-list `set`, or a single-item `advance`, which now carries
  the stored name back through the same builder — is held to the same
  coverage: all ten phases present, each first appearing in template order,
  every item inside one of them. A phase this change does not need therefore
  cannot leave the list; dropping it is refused by name. The way to not do a
  phase is to carry it as `state=done` with a `blocked_reason` saying why it
  does not apply. That reason is a convention the tool description and the
  refusal text ask for, not a rule any validator can hold — a phase that was
  genuinely worked is also `done` with no reason, so what the record enforces
  is the phase's presence and nothing more. `done` rather than a fourth item
  state, for the reason the store recorded when it chose a `blocked_reason`
  field over a `blocked` state: the counts, the projection and the widget
  keep reading three states. `done` is also the only state that lets the plan
  finish — a `pending` item carrying a reason is the plan's own stop
  criterion and would halt the run at the skipped phase with every later
  phase unreached.

  A skipped phase now says so on the surfaces a person reads. The checklist
  row opens its recorded reason with `skipped:` instead of `waiting:` when
  the item is closed — nobody is waiting on a phase nobody will do — and the
  HUD payload carries a derived `counts.skipped`, the items that are `done`
  and carry a reason. Both plan headers name it: a running story reads
  `Todo · story   5/10 (3 skipped)` and a finished one
  `Todo · story ✓ 6/10 (4 skipped)` rather than `✓ 10/10`. That mattered
  because the finished panel drops every item row: the reasons disappeared at
  exactly the moment anyone would look for them, and the number asserted ten
  phases of work for a six-phase story. Only the finished line subtracts —
  the running header's numerator sits above item rows a person can count, so
  it keeps `done` — and the clause is on both so the step between them is
  something the reader has been watching rather than something that appears
  at the end. Nothing new is written to disk and no item state was added: the
  count is derived from two fields the item already has, and a plan with no
  skips renders both headers exactly as before.

  A stamped plan that runs out of item budget is told which bound it hit. The
  template declares ten of the twenty items `omh_todo` allows, so ten are left
  for work of the plan's own; the twenty-first is refused rather than
  truncated, nothing partial lands, and the refusal now appends the arithmetic
  a caller cannot do for itself — what the template holds, what is left, and
  that nothing was written. A plan that named no template reads the plain
  `todo items are capped at 20` it always read.

  Nothing detects a story from what a person typed. The declaration is the
  `template` argument on the call and nothing else, so a one-line question
  gets no phases, and a plan declared without the field is byte-identical to
  what this store wrote before the field existed — the additive-optional
  contract `session_ref` and `deferred_reason` already follow.
  `tests/test_story_template.py` pins the stamp, the coverage refusals, the
  skip, the unchanged plain write, and that an older reader still gets every
  field it knew.

- **The setup keyboard menus stop throwing away keys you pressed while the
  menu was redrawing, and read a whole keypress instead of its first three
  bytes.** `_read_tui_key()` called `tty.setraw(fd)`, whose default is
  `TCSAFLUSH` — the same call as `TCSADRAIN` except that it also DISCARDS
  input not yet read. Because it ran once per keypress rather than once per
  menu, every read began by destroying whatever had been typed in the
  meantime. Measured on a pty: a Down arrow queued before the read survives
  `TCSANOW` and `TCSADRAIN`, and is gone after `TCSAFLUSH`. Nothing wanted
  that flush — discarding on entry is a technique for dropping a terminal's
  unsolicited reply, and setup never queries the terminal, so the entry mode
  is now `TCSADRAIN`, which differs from the old one in exactly the discard
  and in nothing else, including where it can block.

  The two halves had to ship together, because fixing the flush alone makes a
  worse bug reachable. The read took a fixed two characters after an ESC, so
  a keypress longer than three bytes — a modified arrow such as Ctrl+Left
  (`ESC [ 1 ; 5 D`), a mouse report — left its tail in the queue. The flush
  used to destroy that tail. Without the flush and without this second fix,
  the tail is read as separate keypresses, and measured on a pty the menu
  then sees `;`, then `5` — which is a menu choice, so one Ctrl+Left silently
  selects option 5 and returns — and then leaks `D` onto the next prompt.
  `_read_escape_tail()` now consumes a CSI through its final byte (`@`–`~`)
  and an SS3 through its one byte, so no fragment of a keypress can arrive as
  another. A complete sequence always starts with ESC and so can never equal
  a single-character menu choice: the silent selection is unreachable by
  construction rather than merely unlikely.

  Reading to a terminator needs a bound, and a hang in an installer prompt is
  worse than the bug being fixed, so there are two. The tail reads use
  `VMIN=0`/`VTIME=1`, so a lone Esc — a real key — returns after a tenth of a
  second instead of waiting forever for a sequence that is not coming (the
  old fixed two-character read hung there). The CSI loop also stops at 16
  characters, past every sequence a keyboard sends, so an unterminated
  parameter run cannot hold it. `tests/test_setup_keyboard_input.py` drives
  all of this against a real pty; the existing menu tests patch
  `_read_tui_key` and so could never see any of it.

- **Arrow keys pressed into a free-text setup prompt are no longer answered,
  scolded, and echoed back as raw escape bytes.** The provider question runs
  an arrow-key multi-select and then asks "Add another provider by name
  (Enter to skip)" as free text. An operator who kept pressing the arrows had
  their escape sequences returned by `input()` as if typed, and the observed
  line read `? Add another provider by name (Enter to skip) []: ^[[B^[[A^[[B^[[
  is already recorded or is not a plain identifier; skipped.` Nothing was
  typed, so nothing should have been rejected -- and printing the raw
  sequences back sends control codes to the terminal and makes the message
  unreadable.

  `_ask`, the primitive under every free-text prompt in setup, now strips
  terminal control input before trimming whitespace: complete CSI
  (`ESC [ … final`) and SS3 (`ESC O x`) sequences, a sequence the submitting
  Enter cut short (the reported line ended `^[[`, and dropping only its ESC
  leaves `[` standing as an answer), and any remaining C0/C1 control
  character or DEL. A line of nothing but arrow keys therefore reads as
  empty, which every call site already treats as Enter, and no caller can
  echo a control byte back because none reaches it. The fix sits at the
  primitive rather than at the one prompt that was reported, so the yes/no
  fallback and both menu fallbacks get it too. `readline` was not imported to
  make the arrows editable: it is absent on stock Windows Python and would
  change the editing model of every prompt in setup.

  The rejection message is also split in two. `provider_add_rejected` ORed
  two different reasons, so it could not tell an operator which had happened,
  and only one of them is worth retyping. A duplicate now gets
  `provider_add_duplicate` ("already recorded"), a malformed id keeps
  `provider_add_rejected` and now names what a plain identifier is. Both keys
  are present in all four language tables (en/ko/ja/zh).
- **Uninstall no longer leaves the sections it created behind as empty keys.**
  On an install made before the write record existed, `omh uninstall` reversed
  the keys it can attribute without a record and left

  ```yaml
  skills:
    external_dirs:

  plugins:
  ```

  in the person's `config.yaml`. Two causes, both of them about WHEN a
  container is read. The scope decides which containers OMH may drop by asking
  which ones it emptied, and it asked on text from which uninstall had already
  stripped the managed skills directories -- so `skills.external_dirs` read as
  a container the person kept empty and was spared. And the candidate set was
  fixed before the removals ran, so `plugins:`, which becomes childless only
  once `plugins.enabled:` is gone, was never a candidate at all.

  The baseline is now the config as it stood before the uninstall removed
  anything, and the candidate set is every managed container at once: the
  removal pass already re-reads the text after each deletion and works deepest
  first, so a parent leaves with its last child in the same pass.

  Which container OMH may drop is answered by the write record where there is
  one, and only guessed where there is not. The two are not equal, and the gap
  costs a person a key: a container they already had, EMPTY, before setup, and
  which setup then filled, has children at uninstall time — so "was it empty
  before?" says no and the guess concludes OMH created it. `containers_created`
  says otherwise and is right. An install with a record therefore consults the
  record alone; the guess is what the no-record lane has, and its
  by-construction argument holds for what it covers.

  That also repairs two containers the previous behaviour already lost on a
  recorded install: a pre-existing empty `memory:`, and a pre-existing empty
  nested `display:` / `sections:`. Both now round-trip byte-exactly, as
  `skills:`, `display:` and `plugins:` continue to.

  `omh uninstall --registration-only` drops the section its registration was
  the only occupant of, by the same rule and reading the same record, and
  keeps everything else it kept before. `docs/INSTALLATION.md` said that scope
  "removes the registration and nothing else"; it now says what it does.
- **The universal installer picks a Python the wheel can be installed into.**
  Reported from a second machine: `curl ... install.sh | sh` created the virtual
  environment out of `/usr/bin/python3`, and pip then refused with `Package
  'oh-my-hermes' requires a different Python: 3.9.6 not in '>=3.11'`. The venv
  was left behind, no `omh` command existed, and the next line the person typed
  was `omh setup` into `command not found`. install.sh checked only that its
  interpreter EXISTED -- `install.ps1` had probed the version since it shipped,
  and said in its own docstring that install.sh had no such probe.

  It has one now, and the same floor the wheel declares. The search runs
  `python3` first, then the versioned commands newest-first, which is the order
  `packaging/npm/lib/python.js` already used so the two distribution surfaces
  land on the same interpreter; then the places an interpreter hides when it is
  not first on PATH, which is the macOS case exactly: Homebrew, python.org
  frameworks, pyenv and uv. A candidate is accepted on what it reports, not on
  where it was found, and the report has to be one line that is only a version
  -- a wrapper that prints a banner first is refused rather than read past. An
  interpreter named in `OMH_PYTHON` stays the only candidate, because the
  variable exists for a person who knows something the search does not.

  With nothing found and `uv` already on the machine, the installer has uv
  install Python 3.12, shows uv's own output while it does, and then runs its
  own search again rather than asking `uv python find` — that command resolves
  a PROJECT environment first and is cwd-dependent, and `curl … | sh` runs
  wherever the person is standing, so from a checkout it answers that
  checkout's `.venv`. A `.venv` reports a supported version and would sail
  through the probe, and as the BASE of OMH's environment it is strictly worse
  than the interpreter uv was just asked for: rebuild that project and `omh`
  breaks. `--managed-python` does not reliably prevent it either, measured on
  uv 0.12.5. The search instead reads uv's managed directory from
  `uv python dir`, which is cwd-independent and also finds interpreters on a
  machine where `UV_PYTHON_INSTALL_DIR` or `XDG_DATA_HOME` has moved it.
  Downloading a language runtime is a kind of side effect this script has never
  had, so it is announced before it starts and `OMH_PROVISION_PYTHON=0`
  declines it without having to name an interpreter instead. `install.ps1`
  gains the same last resort and honors the same variable — the two installers
  are one documented interface and a parity gate holds them to it — and asks uv
  for its interpreters BY PATH (`uv python list --managed-python
  --only-installed`), so neither script needs to know where uv puts them on
  either platform.

  With neither, it stops before creating anything and names every version it
  did find, and says so differently when the interpreter was one the person
  named: a path that is not there reports "was not found" rather than a verdict
  on the version of a file that does not exist. Interpreter resolution runs
  before the release lookup, so a machine with no usable Python and an
  unreachable GitHub gets the interpreter diagnosis rather than a release
  error. Every run prints the interpreter it chose.

- **The interactive setup wizard says where you are in the questions.** The
  apply phase has narrated itself since it shipped (`[1/5] Installing OMH
  workflows...`); the question phase that runs before it printed a header and
  then fired the display question, the coding-delegation question and the
  provider list back to back with nothing between them. Each question group
  now carries the same `[k/n] <what this decides>` heading in the same style,
  localized in all four languages.

  The total is derived, not declared. Several groups skip themselves -- a
  config that is already TUI plus an OMH skin, no external coding CLI on PATH,
  nothing to offer as a provider, no terminal, no `--with-mcp` -- so a fixed
  `[1/5]` would over-count on most machines. Each group's "will I ask?"
  condition is now a named predicate that the group itself returns early on,
  and the wizard builds the list of groups that will speak before printing the
  first heading. A group that stays silent gets no number and the numbering
  stays contiguous. No question's wording, order, default, or behaviour
  changed, and non-interactive runs (`--yes`, `--json`, no terminal) print
  none of it.

  The heading renders through the apply phase's own `_HumanProgress.step`, so
  the line is identical, but without its 40ms settle. That settle makes a line
  readable when more output lands on top of it at once; a heading over a
  question is followed by a prompt that waits for a person, and `_read_tui_key`
  flushes the input queue on every read (#1778), so delay added before a menu's
  first read is a window in which a keypress is silently discarded.

- **The HUD header stops naming the scope when the rows already carry it.**
  The state label had a word in front of it -- `[this chat]`, `[global]`, or
  `[this chat + global]` -- written before the activity rows had tags of their
  own. They have had them since the board lanes landed: `[sub]` for a delegate
  child, `[bot]` for a board worker. The entry for that work recorded that
  "the header line still states the scope"; that no longer holds. On a
  session-only list the header word repeated what every row below it already
  said, and it did so in 12 cells of a `truncate-end` line where a segment's
  position is its priority.

  The header now carries one marker for one fact: `[global] ` when rows from
  outside this conversation are in the list, and nothing when they are not. An
  entirely unowned list and a mixed one read the same deliberately -- what the
  header owes the reader is that the totals beside it are not all theirs, and
  which row belongs to whom is the rows' own job. It is the word the DAG block
  has always used for the same fact, so the HUD now has one vocabulary for it
  rather than two. A payload naming no scope still says nothing, unless a
  Maestro row is itself global: absence is not a scope and does not become a
  claim here.

  `⚚ [OMH] v2.0.3 │ [this chat] 9 done` now reads `⚚ [OMH] v2.0.3 │ 9 done`.
  Measured on one busy header (version, repeat chip, board counts, cost, ctx,
  open tool calls, yolo) rendered through the shipped widget: at 80 columns
  the session line used to cut after `repeat x8 cycle-of-2 blocked` and now
  reaches `· board 1q`, and the mixed line used to cut mid-chip at
  `cycle-of-` and now clears the chip and its separator. At 120 columns the
  session line's open-tool-call segment (`• 2 tools · 41s`) fits whole where
  it was cut. The global line is unchanged at every width.

- **The delegation nudge counts distinct searches, and its budget survives a
  plugin-host restart.** It watched `search_files` and fired at five direct
  reads, counting CALLS -- so five different greps and one grep five times
  were the same event to it. In session `20260919_140745_db409e` the model
  issued 203 `search_files` calls, the large majority identical; the nudge
  spent its whole budget of two on the loop, said "delegate this", and was
  silent for the remaining ~180 calls. The session's actual problem was that
  it was repeating one search that returned nothing, and the only OMH
  mechanism watching searches had no way to know.

  The threshold now counts distinct `(tool, argument digest)` pairs, using the
  digest the repeat guard already computes for the same call at
  `pre_tool_call` rather than a second hashing path. Five identical searches
  do not fire it; five different ones still do; the pinned negative at four is
  unmoved; a hundred repeats followed by a real search pass still has its full
  budget. The text says "different search/read calls", because the number in
  it changed meaning.

  The budget also stops refilling itself. `MAX_ENGAGEMENT_NUDGES` is two per
  kind per SESSION and the counter lived in a per-PROCESS map, so a restart
  handed the session a fresh one: `db409e` received four delegation nudges in
  a 2+2 split bracketing a mid-session `omh update`, and `8da9b8` received
  three. The two counters that bound the spend and the two latches that end it
  are now written to a session-keyed store under the OMH home, read back once
  per session, under the same 64-row LRU bound the process map uses. The work
  counters stay in the process on purpose: losing them across a restart delays
  a nudge and never adds one, and persisting them would put a file write on
  every watched tool call rather than on the handful that spend something.

  What the data says about this nudge, stated because it bears on whether the
  budget is worth defending: across 140 intervention-to-next-assistant pairs
  in the 2026-09-19 audit, none was followed by an OMH tool call, including
  the eight delegation nudges. The one intervention with a visible effect is
  the route hint (`skill_view` follows it 37 times in 60). It is kept because
  a distinct-search pass is the case it was written for and that case was
  never actually reached before this change. Whether prose that changes
  nothing earns 668 characters a session is a product decision and is not
  taken here.

- **The HUD can tell forty different tool calls from the same call forty
  times.** The activity segment counts calls in flight, which is progress,
  and a loop is the opposite situation wearing the same number. Session
  `20260919_140745_db409e` issued 203 `search_files` calls, 185 of them
  refused by the host's own guard, for a pattern matching nothing in the
  repository; the person noticed only because the transcript's tool-call
  panel happened to be expanded. Collapsed, that panel is one chevron line
  reading `Tool calls (203)`, and the HUD was the only place left to see it.

  The status line and the TUI dock header now carry `repeat xN` whenever the
  repeat guard has a cycle for the reading session: muted while the guard is
  only watching, `repeat xN blocked` in the warn tone once it has actually
  refused a call, and `repeat xN approval` in the error tone once it has
  stopped answering the model and is asking a person. A cycle longer than one
  call says so (`repeat x8 cycle-of-2`), because the same call eight times
  and a pair of calls four times over are different things to look at.

  Three properties make the row trustworthy rather than decorative. It is
  scoped to the reading session, resolved the same way the plan block
  resolves it, so two sessions sharing one OMH home never add up. It rides
  the poll's existing ledger read -- one read already backed the parallel
  shot and the liveness block, and now backs this too -- so the two-second
  reader takes no new lock and no new file open; measured at the 64-session
  ceiling, the projection costs 0.006 to 0.018 ms more and the whole HUD read
  is unchanged inside noise. And the stage is the one the GATE recorded:
  `escalation_can_reach_a_person` reads process-global maps that the widget's
  freshly spawned interpreter does not have, where it would answer "attended"
  for every session, so `pre_tool_call` writes its own answer onto the row
  and the reader takes that. A row with no recorded answer withholds the
  escalation stage rather than assuming it.

  Metadata only, and narrower than the ledger: the projection is given no
  tool name and no argument digest, so the row says that a call repeated and
  never what it was. Asserted against the serialized payload with a sentinel
  in the arguments and in the results.

- **The per-turn fanout scan stops growing with the machine's history, a
  dropped ledger tick is counted, and an unchanged approval-bypass flag is no
  longer rewritten on every hook call.** Three costs on the path every turn
  and every tool call takes, measured together because they share a harness.

  `pre_llm_call` read the fanout root twice -- the running-work board and the
  unacknowledged-dispatch reminder -- and the board opened four JSON files for
  every fanout directory the machine had ever created. Nothing prunes that
  root, so the cost only ever grew: 0.8 ms on a fresh home, 147 ms on one with
  a thousand fanouts. Both readers now keep the eight most recently active
  directories and open only those, which takes the same turn to 7.2 ms at a
  thousand and 2.0 ms at the dozen a working home has.

  The bound is by recency and not by name, which matters more than it looks: a
  fanout id is `fanout-<sha256(goal)[:12]>`, a content hash carrying no order
  at all, so sorting the names and slicing would have kept an arbitrary eight
  of a thousand and silently dropped running units. The running-work board
  orders by when a fanout's in-flight markers last changed, because that is the
  stamp its own question moves; the dispatch reminder keeps ordering by when a
  summary was written. The board reports how many directories the bound passed
  over, so a truncated scan cannot read as a complete one. Pruning that root is
  still nothing's job, and a bounded scan is what makes that survivable rather
  than fixed.

  The tool-bursts ledger's three writers are best-effort and must stay that way
  -- a hook that raised would vanish into the host's own try/except-and-log
  wrapper -- but the lock's `TimeoutError` is an `OSError`, so a write lost to
  contention left no trace at all. An entry left open then read identically
  whether the call was still running or its close had been dropped. The swallow
  is unchanged in width; what it now does before returning is count the drop,
  classified as a lock timeout or a write error, folded into the ledger by the
  next write that does take the lock and reported beside the liveness it
  bounds. Measured: eight concurrent writers lose nothing at all, twenty-four
  lose 477 of 9,648 writes, and the counter reads back 477. It is a lower bound
  by construction, and says so.

  `record_approval_bypass` took a lock, wrote a temp file and renamed it on
  every hook call -- twice per tool call, once per turn -- for a boolean that
  changes when a person presses Shift+Tab. It now writes only when the
  observation is news: 0.201 ms to 0.020 ms. The timestamp is load-bearing in
  exactly one place, the six-hour staleness cut in `latest_approval_bypass`, so
  an unchanged value is still refreshed every half hour and can never age into
  that cut while the hooks are still observing it. No other reader reads the
  stamp: the widget renders the state and the flag, and the permission
  rehearsal reads the same two.
- **Three shipped skills can be reached by the phrasing a person uses.** Each
  lost its own home turf for a different reason, and an unreachable skill is
  always-loaded context nobody can spend.

  `live-incident-response` shipped for #1563 and lost the sentence it exists
  for. `we have an incident open right now, the checkout API is down`
  dispatched to `browser-operator` at 48, with the incident lane third at 7.
  The browser guard fires on a context token plus an action token, and both
  sets are ordinary English: `checkout` names a payment page and also the
  service that takes payments, `open` opens a tab and also describes an
  incident that has not been closed. A guard boost of 42 cannot be outscored
  by trigger evidence, so the ordering is the only place this can be decided:
  a message declaring a live incident now blocks that guard, the way a visual
  QA request already does. The skill also carried `open incident` but not
  `incident open`, the order people say it in.

  `inference-serving` never surfaced for `serve a 7B model at 50 requests per
  second`. It carries `serve this model` and `serve the model`, and a person
  names the size, which puts it between the two words. The rule is now a
  serving verb plus a model noun, with the model on the object side of the
  verb: `serve a 7B model` matches and `which model should we use to serve
  our support customers` does not. A blocker list could not hold that second
  shape, for the same reason the trigger could not hold the first.

  `refactor-plan` was dropped before any trigger could score on `this 900
  line function needs to be broken up`. It offers itself only when the
  message carries restructuring vocabulary AND planning vocabulary, and a
  decided refactor described the way people describe one uses neither word.
  Split vocabulary now stands in for the restructuring half, the way the
  dependency-upgrade phrases already do, and it needs a unit of software
  beside it so that a crowd broken up by police is not a refactor.

  Each row gains a positive case and each generic word it introduces gains a
  negative control: the negative corpus grows from 277 to 280 cases and the
  positive corpus from 425 to 429, both at zero overroutes and zero missed
  interventions. Twelve sentences using `serve`, `function`, `down`, `open`,
  `incident`, `broken up`, and `split` in an unrelated sense score
  identically before and after.

- **One bad byte in a profile config no longer blocks every tool call in the
  home.** `pre_tool_call` resolves the session's store before anything else,
  and every binding fault except a session no profile owns came back as
  `action: block`. Fault injection confirmed all four shapes: an unresolvable
  variable in the configured home, a blank home, a NUL in the path, and a bad
  Hermes home. In a native host that path re-validates the profile
  `config.yaml` on every call, and the installed host validator raises on a
  config carrying a control character. It raises on every call, for as long
  as the byte is there, so the cost of one such byte was every tool of every
  session in that home. (Separately measured, on the healthy path: that
  validator is an uncached YAML parse costing 0.417 ms per tool call against
  a real 3,463-byte config.) It has never fired in practice:
  the block message appears zero times across the whole history of both of
  the owner's `state.db` files. It is fixed because the failure, when it
  comes, is total.

  The veto's recorded reason was that a rules file may exist in the named
  store and may be blocking this very tool. That reasoning does not survive
  the case one level down. When the store DOES resolve and the rules file
  cannot be read -- malformed, permission-denied, or raising something the
  gate never anticipated -- the call is allowed, every time. That is
  `toolcall_rules`' documented fail-open contract, and the rule-gate handler
  added alongside the doctor hot-path checks rejected blocking on a rule-gate
  failure by name. So OMH allowed the case where it knew exactly which rules
  file it had failed to read, and refused the case where it could not locate
  one at all: the harsher response to the weaker signal.

  Every binding fault on `pre_tool_call` now degrades, the posture the other
  hooks already took. A rules file that loads and matches still blocks, with
  its own message, so what the narrowing removes is the veto that fired when
  there was no rules file to consult, not the one a person wrote. The
  trade-off is restated at the handler rather than dropped: while a home
  cannot bind, no tool call in it is checked against that person's rules.
  That window is real, it is the same window a malformed rules file already
  opens, and it is not a defence against an actor who can write the profile
  config in the first place.

  On this hook the degraded call is silent, which is worth saying rather than
  glossing. Nothing is written to a store, because a binding fault means
  there is no store to write to. The returned payload is not a record
  either: Hermes reads a `pre_tool_call` result's `action` and skips every
  other shape, and a hook result's context text is read on the `pre_llm_call`
  path only. Two things do still surface the same fault. `pre_llm_call`
  returns the same degradation and its context IS injected into the turn,
  once per turn, and it now names the exception type -- the only thing left
  separating a session no profile owns from a store that was named and could
  not be read. And for the config-fault class the host reports itself, with a
  backup copy of the broken file and a stderr warning naming the parse error
  and its position.

  No retry: of the writers that can leave that config unreadable, only a
  person's editor saving in place is transient, and Hermes and OMH both
  replace the file atomically and cannot produce the state at all.

- **One discipline for every OMH write of Hermes' `config.yaml`.** OMH wrote
  that file from two families that did not know about each other. The
  delegation route writer read, compared a file signature and replaced
  atomically, and since #1737 held a lock; `write_config` rewrote the whole
  file with no lock and no compare, reached by `omh setup`, `omh theme`,
  `omh memory`, self-update's external-dirs registration and
  `system/targets`. One of those could read the file, have a route land, and
  write back its stale copy. The route was erased, and the restore record
  then saw a value it had not written and dropped the person's baseline as a
  foreign edit. Before #1737 that needed somebody running a CLI command
  during a routed dispatch; with restores running at turn and session
  boundaries the window is met far more often.

  Every one of the seven call sites now goes through `update_config`, which
  reads, runs the caller's mutation against the text it just read, checks the
  signature again immediately before the replace, retries when the file
  moved, and refuses rather than writing after three rounds. The retry is
  what keeps both updates: the second attempt derives its change from the
  other writer's file. Where the OMH home is known and exists the CLI takes
  the SAME lock the route writer holds, so the two families serialize instead
  of merely detecting each other. `system/targets` is the one place that may
  write a config belonging to a Hermes home this invocation is not bound to,
  and there the signature compare stands alone; it is marked as such.

  The replacement also carries the destination's file mode, which the old
  path did not: a rename installs the temp file's mode, so a config somebody
  had chmodded to 0600 widened on every OMH write. The mode is read before
  the temp file exists, which is also what leaves nothing but the rename
  between the signature check and the replace.

  `--dry-run` takes no lock. A preview writes nothing, so it has nothing to
  serialize against, and taking the lock regardless made a read-only command
  create a `routing/` directory and a lock file inside it, force that
  directory to 0700, and acquire a five-second wait plus a way to exit 2.

  Four source-derived gates keep the discipline from drifting back. They fail
  on a bare `write_config` call anywhere in `src/`, on a renamed import of it,
  on a write whose destination expression names `hermes_config_path` and goes
  to `atomic_write_text`, `write_text` or `open` a level lower, and on a
  mutation that never names the text it was handed. The third sees the
  spelling every write in this repo uses at the point of the call; a path
  bound to a local first needs dataflow, not a name, and stays a reviewer's
  job. That last one is not hypothetical: converting
  `cmd_uninstall` reintroduced exactly that shape and it passed every other
  test. It is also the limit of what a syntactic gate can do -- a mutation
  that mentions its argument and still returns precomputed bytes is the same
  lost update and is indistinguishable from a correct one, so the tests say
  so rather than implying otherwise.

  A refusal now names its own cause. An unreadable or symlinked config raises
  `ConfigUnwritable`, a real race raises `ConfigConcurrentUpdate` and a
  mutation that times out raises `ConfigMutationFailed`, all under one
  `ConfigWriteRefused`; before, a permission error surfaced as an exception
  whose name claimed a race that had not happened.

  A symlinked `config.yaml` is refused before the read, on every round,
  rather than left to the reader. The reader refuses one by opening with
  `O_NOFOLLOW` and catching the error, and `os.O_NOFOLLOW` is Unix-only: on
  Windows the flag is a no-op, so the open followed the link and the refusal
  never fired. The compare's two sides then stopped describing one file --
  the read stamps `fstat` on the followed descriptor, the guard stamps
  `lstat` on the path -- so every round mismatched and the command failed
  with "kept changing during 3 update attempts" instead of naming the
  symlink. Only the final component is checked: the temp file is created in
  the config's own directory and renamed within it, so a symlinked parent
  cannot produce the link-destruction this prevents, and people do symlink
  dotfile directories.

- **`omh uninstall` now reverses every `config.yaml` key setup wrote, not one
  of seven.** Setup's apply step writes `skills.external_dirs`,
  `auxiliary.compression.fallback_chain`, `plugins.enabled`,
  `display.interface`, `display.skin`, `display.sections` and
  `memory.provider`. Uninstall reversed the registration and left the rest, so
  a machine kept `plugins.enabled: - omh` and `memory.provider: omh` naming a
  bundle that was gone.

  Observed against Hermes 0.21.3 in a temp home with the bundle removed: a
  leftover `memory.provider: omh` makes agent init call
  `load_memory_provider("omh")`, get nothing, and then look the provider up
  in the plugin catalogue before warning that it is neither installed nor in
  it; `hermes doctor` reports it as `omh plugin not found`. The lookup is
  cached for six hours per home and skipped when
  `security.allow_lazy_installs` is off, so the recurring cost is the
  warning rather than a request per start. The stale `plugins.enabled` entry
  and `display.skin: omh` are silent -- discovery simply never finds them.

  Setup now records what it added, as the difference between the reading
  before its pass and the reading after it, which is the same test #1750
  applied to `display.sections`. Uninstall reverses a key only while the
  current value is still the recorded one, so somebody who moved
  `memory.provider` to honcho keeps honcho and the report names the key it
  left alone. A value consent let OMH migrate them off -- `display.interface`
  and `display.skin` are the only two -- is put back rather than removed.

  Installs made before the record get the honest subset. `display.skin: omh`,
  `plugins.enabled` containing `omh` and `memory.provider: omh` name OMH by
  construction and are reversed. `display.interface: tui`, the
  `display.sections` children and the compression fallback chain are values a
  person can legitimately hold, so they are kept and the uninstall output
  says which and why.

  `--registration-only` keeps its narrow meaning and reverses nothing else.
  `--dry-run` lists every key it would reverse and leaves the file
  byte-identical.

  The record is keyed by config path, because every Hermes bot profile
  shares the primary's OMH home and one `omh setup` therefore writes the
  same `runtime/state.json` once per home. A single slot would end the run
  holding the last profile's record, and the primary -- the home somebody is
  most likely to uninstall -- would silently fall back to the no-record
  subset.

  Bot profiles are reversed the same way the primary is, and through the
  same function, because setup writes the same seven keys to each of them
  (`_sync_hermes_profiles` calls the apply pass once per profile home). A
  profile that still holds a key is reported as `partially_cleared` with the
  keys named, rather than as `cleared` over a config that still says `omh`.

  Every remover now takes the same refusal its forward writer takes. The
  display removers always did; the memory, plugin and compression removers
  took none of it, and two of those shapes were not merely untouched. On a
  config carrying both a dotted `memory.provider: omh` and a `memory:`
  block, the owner check read the dotted value and the mutator then deleted
  the block's `provider: honcho`, leaving OMH's marker and losing the
  person's provider. On a config with `enabled: &plist`, the display path
  refused over the anchor while the plugin path emptied the list the anchor
  names, so every `*plist` alias resolved to null. A quoted inline
  `plugins.enabled` is also left alone now, because the list parser splits on
  commas before it strips quotes and `["a,b", omh]` would come back as two
  entries.

  A row's status is read off the config rather than matched against its own
  English message. The old substring test reported a key that was present
  and deliberately untouched as "nothing here", and coupled the
  absent/kept distinction to the wording of six messages. The case that
  separates the two: OMH wrote `display.sections.tools`, the person deleted
  that line, and the remover answers "no display.sections child to remove",
  which reads like absence about a key the config still carries.

- **A skill whose name is an ordinary English word no longer claims every
  sentence that happens to spell it.** `pods stuck in CrashLoopBackOff after
  helm upgrade` dispatched to the `loop` goal engine at high confidence, in
  English and in Korean; `a user asked us to delete all their data` reached
  the external-advisor `ask` skill; `should I hire a backend engineer or a
  DevOps person first` reached the `backend` coding lane. A wrong confident
  dispatch is worse than a question, because the person gets a goal engine
  for a Kubernetes problem and has no reason to suspect the router.

  Two mechanisms, both now closed. Matching was plain containment, so a name
  fired INSIDE a longer word -- `loop` in `CrashLoopBackOff`, `ask` in
  `asked`. Trigger and name matching go through `phrase_is_spoken`, which
  rejects a match that starts or continues mid-word. Its two edges differ on
  purpose: a phrase that starts mid-word is never the phrase, while a
  multi-word phrase extended on the right is the same phrase inflected, so
  `attack scenarios` still matches the `attack scenario` trigger and `asked`
  still does not match `ask`. The left-edge test is ASCII-only because
  Japanese and Chinese are written without spaces.

  Separately, one occurrence of a one-word name was credited four times: the
  `name:` phrase at +5, the identically-spelled trigger phrase at +6, that
  trigger's token at +3, and the same token again from the metadata fold at
  +1. Fifteen points for one word clears the high-confidence bar on its own,
  and four labels in the evidence list read as four independent findings when
  they are one. The three duplicates are dropped; the word scores once, as
  the name it is, which is worth a clarifying question rather than a
  dispatch. Every invocation form is untouched: `$loop`, a leading `loop`,
  `use omh loop`, and `use the loop skill` all still dispatch, and so does a
  Korean particle welded to the name (`loop로`), which marks the token as the
  name rather than the English word.

  Three lanes had been carried by that inflation and now have the phrasing a
  person actually types: `plan` gains "make a plan", "write a plan", and
  "write the plan"; `frontend` gains the locative "in / on / to the
  frontend"; and `deep-interview` trades its bare `interview` trigger -- every
  hiring loop and user study in the language -- for "interview me". The verbs
  `make` and `write`, and two ordinary words `research` reached only through
  complete phrases (`before`, `open`), are held to whole-phrase-only scoring.

  Measured on the deciding surface over the 94-ask survey in the issue: 41
  dispatch / 43 clarify / 10 fallback becomes 35 / 48 / 11. Nine asks moved.
  Six were the wrong confident dispatches above; one was corrected in place
  (`review this terraform plan before I apply it` now reaches `code-review`,
  not the planning workflow); two were clarifications whose top candidate
  changed once a substring artifact stopped scoring. One previously correct
  dispatch became a clarification that still names the same workflow. The
  negative-control corpus grows from 265 to 277 cases and the
  positive-intervention corpus from 424 to 425, both at zero overroutes and
  zero missed interventions.

  The always-loaded skill-body budget rises from 977,649 to 977,773
  characters for the six added trigger phrases.

- **Fourteen skills stop telling the model to record a coding handoff for work
  that is not coding.** A skill body rendered "Preferred harness for this
  skill: `coding-handling`" and an `omh runtime record --harness
  coding-handling` command whenever the catalog had never assigned that skill
  a harness, because the renderer read `primary_harness_for_skill`, whose
  fallback exists so that routing, validation, and the structure lint always
  get a harness that resolves. Nineteen skills reached it that way, among them
  `achievements`, `buzz`, `capability-toggle`, `live-incident-response`,
  `meta-router`, `running-work-board`, and `todo-checklist`. The line sits in
  always-loaded context, so every one of those sessions carried a coding
  instruction for a skill that reads badges or shows a checklist.

  A skill the catalog declares no harness for now renders neither the line nor
  the command. `omh runtime record` requires `--harness`, so the alternative
  to omitting both is naming a harness nobody chose; saying nothing is the one
  answer that cannot be wrong. The renderer reads `declared_primary_harness`,
  which reports the absence instead of hiding it, and the routing fallback is
  left where its consumers still need it.

  Five of the nineteen genuinely are coding skills and now say so in the
  catalog rather than inheriting it: `backend`, `frontend-refactor`,
  `maestro`, `native-debugging`, and `rust`. Each is filed under the
  `delegate_coding_and_ship` capability family and does work the
  `coding-handling` harness names for itself -- write, modify, debug,
  refactor. Their rendered bodies are byte-identical; what changed is that a
  value nobody declared became one someone did. Three more that the family
  also files under coding were left undeclared on purpose, because a second
  harness competes for each and the catalog does not say which wins:
  `application-threat-model`, `llm-app-dev`, and `tech-debt-audit`.

  The always-loaded skill-body budget falls from 979,758 to 977,649
  characters.

- **A long line in a diff no longer makes every short line pay for it.** The
  full-width diff band pads painted `+`/`-` lines with trailing spaces out to
  the block's widest line, and that padded string is the tool result, so the
  spaces are read by the model as well as painted on screen. `MAX_BAND_CELLS`
  caps the band at 160 cells, but under the cap the widest line still sets it
  for everything else. A 3,310-char patch result with 118 short lines and one
  152-cell line became 18,682 chars, 5.6 times its own size, in whitespace.

  Padding is now bounded by `MAX_BAND_PADDING_RATIO`: it may not exceed the
  diff's own length in characters, so the transform can never more than double
  what it is handed. Over the budget the band steps down to the widest painted
  line whose padding fits, and the lines above it keep the unpadded right edge
  the cap already leaves on an outlier. The band only ever lands on a width
  some line actually has, because a band between two of them covers no line
  the lower one misses -- which is why the case above recovers to 3,562 chars,
  1.08x, rather than merely stopping at the budget.

  The band is a cell width, since that is what makes the rectangle uniform on
  screen, but the budget is characters, since that is what the result costs.
  Padding is spaces, one character and one cell each, so the spend is the same
  number in either unit; only the diff it is measured against differs, and a
  double-width line is two cells per character. A cell-denominated budget
  would therefore bound nothing the result is billed in: a CJK-heavy diff
  reaches 2.28x in characters under one.

  Diffs whose padding already fits the budget are untouched, byte for byte.
  Across 1,853 per-file diffs from this repository's last 300 commits, 1,531
  render identically and 322 lose padding, for 2.27 million fewer characters
  of trailing space in total. None loses its band entirely.

- **Seven skills gain the mechanism they only gestured at, for the cost of one
  line each.** `verification-gate` named which commands count as evidence and
  never mapped requirement to task to evidence. `deep-interview` asked one
  question at a time with no taxonomy to prioritise against and nowhere to
  write the answers. `ultrawork` split work into disjoint lanes and shipped no
  file-ownership manifest, the artifact that stops two lanes editing one file.
  `code-review` ran a single bug-first pass. `todo-checklist` tracked work and
  could not review whether requirements were fit to build from. `ai-slop-cleaner`
  was deletion-first for code and carried nothing for prose. `plan` had no place
  to put a rule that is not up for renegotiation.

  Each now carries a reference file with the procedure: stable `FR-###`/`SC-###`
  ids and a requirement-to-task-to-evidence map with a metrics block; a ten-category
  ambiguity taxonomy scored Clear/Partial/Missing with a five-question cap and a
  write-back target; a stream manifest with explicit file lists, a named owner for
  each shared interface, and a four-step overlap ladder whose last rung is that two
  streams never edit one file concurrently; five review lenses run as separate
  passes, including a verification-gap lens that asks whether anything would go red
  if the changed behaviour broke; a requirements-quality checklist whose generator
  may not tick its own boxes; a prose lexicon whose word tiers keep a wordiness fix
  from reading as an authorship accusation; and a project constitution where a
  conflict with a MUST principle is resolved by changing the plan.

  Reference files are measured outside `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT`, so
  the always-loaded cost is seven pointer lines: 978,380 to 979,758 characters,
  against a pre-retirement level of 992,659. The `ultrawork` pointer is the
  terse one deliberately -- that body had 89 bytes of headroom under the
  per-skill ceiling, and shortening a pointer was cheaper than raising a second
  ratchet.

  Every mechanism is reconstructed in OMH's own vocabulary from a studied
  upstream, each registered in `docs/SKILL-SOURCES.md` with the commit read and
  its closure receipt: github/spec-kit, automazeio/ccpm, wshobson/agents, and
  bmad-code-org/BMAD-METHOD, all MIT. Nothing here needs a model judge inside
  OMH, a network index, or ownership of the working tree; a coverage map is
  something a model fills and a person or CI checks, never evidence by itself.
- **What keeping a plan costs: one item per write, and a shorter block per
  turn.** Two costs measured against the real hooks. Ticking one item cost a
  whole-list write: `action=set` was `omh_todo`'s only write, so a ten-step
  plan paid one declaration plus ten re-sends of every item's text, state and
  phase, about 1.5 KB of arguments per advance and one chance per advance to
  drop or reword an item nobody meant to touch. And the per-turn plan block
  restated the drive in full on every turn for the life of a plan; a
  one-character message in the owner's own history carried 854 characters of
  it.

  `action=advance` changes one item's state: the item number, the start of
  that item's current text as a guard, and the new state, with
  `blocked_reason` riding along and `deferred_reason` behaving exactly as it
  does on a `set`. The reference is an index plus a guard rather than an id,
  because the record has no item id and needs none for anything else, and
  because what a bare index cannot do is refuse when the list moved
  underneath it -- a guard that no longer describes the text at that position
  is refused rather than applied. Out-of-range, a finished plan, an absent
  record, a bad state and a guard mismatch are each refused with the field
  named, and a refused call leaves the record byte-identical.

  It is the same write by a narrower route, and that is a test rather than a
  claim: a plan walked entirely through `advance` produces a record byte-equal
  to the same plan walked through `set`, under a fixed clock. There is one
  validator, one stamp and one schema, because the new path rebuilds the item
  list and hands it to `build_todo_record` like every other write. Every
  reader of "the plan changed" -- the reconciliation turn budget, the HUD's
  unchanged duration, the turn-end nudge budget -- sees it as it sees a `set`.
  The read-modify-write this introduced is serialized by a per-record lock
  that `set` now takes too, so a whole-list write can no longer be overwritten
  by a list read before it. It is the bundle's existing two-backend lock, the
  one `tool_bursts`, `approval_bypass` and `memory_open_reminders` already
  take, with the wait it allows made a parameter rather than a constant: that
  lock's own default is sized for telemetry that would rather drop a counter
  than delay a turn, and a plan write is the opposite trade. A copy here
  would have been the bundle's third, which is the shape that let a Windows
  host once take no lock at all while reading as though it had one.

  That is a new way for `set` to fail, and it did not have one before: it
  wrote through `os.replace` and took no lock. A writer that waits more than
  two seconds for the record is refused with `"status": "contended"` and an
  error naming the record, saying the write did not happen and to send the
  same call again. It is not `invalid_todo`, and the separate status is the
  point: a writer told its payload was invalid rewrites the list it just
  sent, which is the whole-list rewrite this change exists to stop, while the
  right response to a busy record is the identical call. The record is
  untouched either way, `TodoContendedError` subclasses `TodoStoreError` so
  every caller written before the lock still catches it, and `omh runtime
  todo set` reports the same status and still exits 1. Nothing counts or
  surfaces refusals: no reader has anywhere to put one.

  The block was then measured sentence by sentence for what each one does, and
  three places said one thing twice: the drive's premise and its imperative
  were two sentences for one ask, its stop criterion re-stated "an answer does
  not discharge the turn" one clause after the drive said it, the stall
  framing ended with the drive repeated, and "either finish the remaining
  items or say which stay open and why" is what the drive already asks, so it
  moved to the budgeted half of the reconciliation rule. Nothing was deleted
  from the full rule to move it. Per turn, driving `pre_llm_call` against a
  temp home: the drive variant falls from 694 to 654 characters on the turns
  that carry the full rule and from 541 to 435 after, the stalled variant from
  887 to 807 and from 734 to 588, and a 40-turn session with one plan pays
  18,057 characters instead of 22,099 on the drive variant and 24,177 instead
  of 29,819 on the stalled one. The answer-first and deferred rules were
  measured and left alone; the reasons are recorded beside them. What may not
  be shortened away is pinned per variant and past the budget: the drive
  clause and its stop criterion where the plan drives, the message ordering
  and the record-first way back where it does not.

- **OMH no longer routes on rows no person wrote.** Hermes opens turns for
  rows it writes itself -- a background process finishing, an async
  delegation batch, a model switch -- and each arrives as a `role="user"` row
  carrying real text. OMH's awareness rail and route hint read that text as a
  request. Measured in the owner's `state.db`: 282 of 1,869 user rows are
  host-synthesized, 259 of them `async_delegation_complete`, and 272 of the
  282 match the awareness vocabulary. One background-process notice drew
  `intent=meta_discussion; selected=workflow-learning` with 3,297 characters
  of routing behind it.

  On a turn the host opened for itself there is no request, so `pre_llm_call`
  now derives one value -- the message read AS a request -- and gives every
  routing surface absence on such a turn: no `[OMH Route Hint]`, no awareness
  vocabulary match, no structured route hint in the context brief, and the
  per-fingerprint claim ledger is not spent. That last one is the tail of the
  bug rather than its bulk: the ledger holds one route per session, so a
  claim spent on a notice silences the same hint later, when a person
  actually asks for it.

  The discriminator is `display_kind`, the record field Hermes stamps when
  the row is written, and never wording. `steer` is input typed for the
  renderer and routes exactly as an untyped row does; an absent or unreadable
  row keeps today's behaviour, because a plugin that cannot tell who wrote
  must not start claiming the host did. Measured on a completion-notice turn
  by driving the real hook: 3,484 characters before and 798 after for a
  `process_complete` notice, 3,852 before and 798 after for an async
  delegation batch. The identical text on an untyped row is unchanged at
  3,656 and 4,024.

  What is deliberately untouched is everything that reads the turn as an
  event rather than a request -- the plan drive, the dispatch outcome lines,
  the active-workflow line, the role marker -- because a completion notice is
  exactly the turn on which those matter. The first-turn primer is unchanged
  too, including when the opening row is a notice: Hermes computes
  `is_first_turn` as "no prior history", so withholding the primer there
  would drop it for the whole session rather than defer it, and the host
  replays it in `api_content` for the person's later turns anyway.

  The predicate #1739 introduced moved from `todo_reconciliation` to a
  neutral `turn_authorship` module, since a routing surface importing "who
  opened this turn" from the plan-checklist module reads wrong. The old
  import surface is re-exported unchanged.

- **A turn that starts remote work and arms nothing is told so, before it
  ends.** A Hermes session cannot wake itself: exactly two things start a
  turn, a person's message and the host's background-process completion
  notice. So "waiting for CI" is a real wait only when the turn armed a
  background process that exits when CI does. Measured on the reporter's own
  session history, of 48 turn endings that mentioned CI or a deploy and a
  wait, one had armed a waiter and was woken by it; the longest idle gap was
  168 minutes.

  A `terminal` call whose command starts work on a remote now gets a directive
  on its own result when nothing is armed. It names two honest exits and picks
  neither: arm the wait as a background process with `notify_on_complete=true`
  so Hermes delivers the completion notice and resumes the session, or tell
  the person plainly that this session has stopped and what they need to come
  back for. It says not to poll in the foreground, because OMH's repeat-call
  guard escalates a foreground poll to a human gate. A second sentence covers
  the other stall in the report: a command held at the human approval gate did
  not run, and a session cannot approve on anyone's behalf.

  Neither trigger reads the model's prose. "This turn started remote work" is
  the command the model passed to a tool with a schema, matched line by line
  on executable plus subcommand tokens after a shell-aware split, so a
  multi-line script counts while `git push --help`, `echo git push` and a
  heredoc body carrying the words are all misses. "Nothing is armed" is two
  host records: `processes.json` for liveness, since it carries only live
  processes and names each one's spawning session, and the background spawn's
  own tool result for whether a live process will notify at all. It takes two
  because Hermes writes the process checkpoint during the spawn and sets the
  notification fields afterwards, so the most recently armed process is
  always recorded without them. Anything the two cannot settle answers
  "unknown" and the directive stays silent: this may decline to speak, but it
  must never tell a session that armed something that it did not. A delegated
  child is never nudged, because it does not report to "the person" and the
  host says its watcher would not reach its parent.

  It is deliberately small and deliberately conditional, because it lands on
  very nearly every successful push: at the moment a push returns, a session
  has almost never armed anything yet. So the obligation is phrased as "if
  this turn will wait on that work", and a session observed arming a
  notifying background process, from its own tool arguments or from the
  process record, stops being reminded how. The directive is 436 characters
  and the approval sentence 233.

  The issue proposed acting in `pre_verify`, and that hook cannot reach the
  turn that matters. Hermes gates it on the turn having changed files and
  feeds that set from `write_file` and `patch` only, so a turn that pushes and
  opens a pull request has changed nothing and never reaches it. The directive
  rides `transform_tool_result` instead, which fires for every tool and lands
  while the model is still inside the turn loop, so both exits are reachable.
  At most one directive per turn per cause, latched on the host's own turn id.

- **The branded TUI collapses the transcript, and doctor names what bounds a
  runaway loop.** Two halves of the same question: whether a person can see a
  run going wrong.

  Hermes renders every tool call and every thinking block expanded. On a long
  run each call becomes its own row, the prompt scrolls out of sight, and the
  transcript is a wall. OMH's branded-TUI choice already set two display keys
  under one default-Yes confirmation, and `display.sections` now rides the
  same consent: `thinking`, `tools` and `subagents` collapsed, under the same
  rules as the other two. Only from the confirmation or `--yes`, never on a
  noncanonical YAML shape, and `--dry-run` never persists. Narrower than the
  other two in one way: every section key is unset-only, so an explicit
  `display.sections.tools: expanded` survives while the other two are still
  added. `collapsed` is not `hidden` -- counts stay visible and a click
  expands. The prompt's trigger is unchanged, so an install already branded
  before this existed takes the third key through `--yes` rather than being
  re-asked. What setup wrote is recorded in the apply result, so
  `omh uninstall` can reverse it later without guessing which values were the
  person's own.

  `omh doctor` gains two advisories in the read-only lane, which reports and
  never rewrites. The first names `agent.max_turns` when it is at or above
  200, the point where the turn budget rather than the host's loop detector
  is what a repeat loop runs into. It fires on Hermes' own default of 500,
  and says so, because the measured loop reached 409 tool calls under exactly
  that value. The second names `tool_loop_guardrails.hard_stop_enabled` when
  it is false or unset, which is the host default on an attended platform: in
  that state Hermes' loop detector only appends a note, and the model ignored
  185 of them in the measured session. Turning it on halts the turn at
  `no_progress_block_after`. OMH changes neither key.

- **`omh doctor` stops warning about work nobody can do, and starts seeing
  the tool-call hot path.** Two truthfulness defects on the same surface.

  The memory-consolidation warning could never clear. When Hermes' memory pack
  is over its headroom floor and nothing in it is provably redundant --
  measured on the owner machine at 14 entries, 67 chars of headroom against a
  floor of 300, `reclaimable_chars: 0`, no duplicate clusters -- the planner
  has nothing to propose and OMH cannot write Hermes memory by design. Doctor
  still said consolidation was "due" on every run, and a standing warning is
  how people learn to skip doctor. That state now reports what it is: the pack
  is full, nothing can be reclaimed automatically, and the move that does
  exist is shortening or removing an entry through Hermes' own memory tool. It
  no longer counts as a warning. A brief with a duplicate cluster keeps
  today's wording and today's severity, because there is a consolidation to
  run.

  Doctor could not see the tool-call hot path at all. A `toolcall-rules.json`
  is how somebody tells OMH to block a tool call, and the enforcing hook fails
  open: a wrong `schema_version` refuses the WHOLE document, a bad regex drops
  one rule, and either way nothing is reported. Doctor now runs the same
  validator `omh ops toolcall-rules-validate` runs, against the store it
  already inspects, and names the file, the loaded and skipped counts, and the
  first error. No rules file stays silent -- the file's presence is the
  opt-in. Doctor also reads the plugin host observation journal it already has
  and names a hook whose recorded calls did not come back observed.

  Inside `pre_tool_call`, the rule gate gained its own handler. A failure
  while evaluating somebody's rules used to escape to Hermes, which appends
  nothing, logs one WARNING and then DEBUG only -- so the person's blocks
  stopped running and nothing said so. The call is still allowed, which is the
  module's documented fail-open contract and avoids the #1674 shape where one
  broken state refuses every tool call in every session. What changes is that
  it is no longer silent: the failure is counted where doctor reads it, and
  doctor names the tool, the exception's type, and the fact that the call was
  allowed. The exception's message is deliberately not stored: it is free
  text from whatever raised, so it can quote the person's own rule pattern or
  a tool argument, and that ledger is metadata-only.

- **A delegation route now has a way back, so one lane's model stops being
  every later session's default.** `omh_delegate_route` writes
  `delegation.model` / `provider` / `reasoning_effort` into `config.yaml`
  because Hermes re-reads those keys per dispatch. Nothing put them back.
  Clearing was a sentence in the tool description rather than something the
  code did, so on the machine this was measured on, 28 of 32 recorded routes
  were never cleared and a route written for one lane two days earlier was
  what every delegation inherited -- including sessions that never called the
  tool.

  OMH now records, under the same lock as the route write, what the three
  keys held the first time it wrote over values it did not write. A key the
  file did not carry is recorded by being absent, so putting the baseline
  back removes the key rather than writing an empty string. The baseline is
  captured once and survives later routes; only a person's own edit between
  two routes re-captures it, because at that moment OMH is again writing over
  a value it did not write.

  A route is turn-local, and deliberately so. `on_session_end` is not a
  session boundary: Hermes fires it once per message from the turn
  finalizer. "Route the next dispatch" is a turn-local intent and a
  `delegate_task` is dispatched inside the turn that set the route. The
  recorded scope is the task rather than the turn because the host gives a
  plugin tool `task_id` but never `turn_id`.

  What a task is differs by flow, and both are ordinary. In TUI and CLI the
  host mints a fresh task per turn, so the scope is the turn; a restore that
  does not happen at its own turn end is then not retried until the next
  session start. On every gateway platform -- Slack, Discord, Telegram,
  Feishu, the API server -- `task_id` is the session id, so the scope is the
  session, a route survives later turns of it, and a missed restore is
  retried by the next turn end. That is the majority flow on the machine
  this was measured on.

  A recorded task decides on its own, without also requiring the session.
  That is what carries a restore through a compression split: the host
  reassigns the session id mid-turn when it splits a long transcript, and
  those long fan-out turns are the ones that route, while the task id is the
  same value at the tool and at the turn end on both sides of the split.

  Turn scope makes a leak short and bounded rather than impossible. A lock
  the turn end could not take within its budget leaves the route, as does a
  session killed mid-task; both then wait for the next session start and the
  liveness bound.

  Three paths put the previous values back: `action=clear`, the end of the
  task that wrote the route, and the start of a later session when the
  writing session is gone. Chain exhaustion restores the baseline instead of
  clearing. `action=fallback` legitimately runs a turn after the route was
  written, because a child that dies on HTTP 400 is reported later, so it
  now recovers its chain position from the route provenance record rather
  than from the live keys. Every restore is gated on the same recorded
  value, never on wording: OMH compares the file's current three keys with
  what it recorded writing, and a value someone else set is reported and
  left alone.

  The baseline is what the PERSON had, which is not the same as what the
  file holds. On the machine this issue came from the file already held a
  leaked OMH route, and capturing that as the baseline would have made the
  most expensive model in the chain a permanent restore target. Every route
  OMH writes is already recorded in `route-provenance.json`, so a candidate
  baseline that exactly matches the newest such record is recognised as
  OMH's own leftover and recorded as "keys absent" instead, with
  `baseline_origin` saying which of the two it was. Two consequences are
  stated rather than glossed: a person who pins by hand exactly the model,
  provider and effort OMH last wrote is indistinguishable from that leftover
  and their pin will not come back, and when provenance is missing or
  unreadable the check cannot run at all, which is reported as its own note
  instead of quietly falling back. The record also names the `config.yaml`
  it describes, because two Hermes profiles may share one OMH home and a
  record that named no file let one profile act on the other's route.

  The same provenance comparison now guards two more places. `action=fallback`
  reads the live keys as its chain position only when OMH can prove it wrote
  them, because after a turn-end restore those keys hold the person's own
  pinned model: reading that as the position made one failed lane report a
  whole exhausted chain, skip the candidate that would have worked, and then
  delete the pin. And the clear at the end of an exhausted chain will not
  remove a value OMH cannot prove it wrote.

  What comes back is the previous VALUES, not the previous bytes: the writer
  normalises quoting, emits the three keys in a fixed order, and drops an
  inline comment sitting on one of those lines. Every other byte is
  untouched.

  The session-start path exists because a session killed mid-task never
  reaches the turn end. It restores only a route whose recorded writer is not a
  live session, asked of that writer's own `state.db` row -- not of the
  live-TUI list, which is scoped to "which session is a person looking at"
  and so omits every writer on another surface by construction. Most writers
  are on another surface: on the owner's routing profile every route comes
  from a `slack` or `subagent` session, and the default home already has
  `desktop` routes beside its TUI ones.

  Only a row the host closed is an observation that the writer is gone. A row
  the host never closed -- what a killed TUI and most gateway sessions leave
  behind -- is not, so the route's own age decides instead, bounded at six
  hours. Each verdict is named so a reader can tell an observation from a
  bound. The cost is stated: a route left by a killed session can outlive it
  by up to six hours. That is the accepted side of the trade, because
  restoring under a live writer sends that writer's next child to the wrong
  model. Nothing available shortens it -- the host's lease registry records
  which surfaces are open, not whether their processes are alive. Turn scope
  makes it a narrow path: it now covers only a session killed mid-task.

  OMH registers `on_session_start` for this; it is the host's own first-turn
  lifecycle callback, bounded and fail-open.

  The turn-end restore is on the hot path of every turn of every session,
  including each delegated child's, so the case with nothing to restore
  costs one `stat` with no lock and no database read.

  Two sessions routing at once is ordinary on one machine, so the whole
  read-through-replace is inside the plugin's existing file lock. A writer
  that cannot take it returns a refusal the tool surfaces and never reports
  `routed`. The interleave that motivated the recorded writer -- A routes, B
  routes over it, A ends -- leaves B's route in place and B's session end
  restores the user's own baseline.

  A machine that already carries a route written before this change has no
  baseline record. OMH cannot know what those keys held, so the automatic
  paths report `no_baseline_recorded` and change nothing. An explicit
  `action=clear` still removes the keys, which is what it did before and the
  only way to settle a route nothing recorded.

- **`omh --resume <id>` works, and the terminal now names the `omh` way
  back.** Bare `omh` is documented as the same door as `hermes`, but the door
  opened one way only: the parser rejected `omh --resume <id>` as an invalid
  choice, and the one resume hint on screen when the TUI exited named the
  other binary, `hermes --tui --resume <id>`. Someone who came in through
  `omh` was told to come back through `hermes`.

  Three Hermes session flags now pass through on the bare launch --
  `-r/--resume`, `-c/--continue` and `-p/--profile` -- each value forwarded as
  its own argv element, in one fixed order, with nothing else added. No
  top-level OMH option claimed those short forms, so they carry over
  unchanged. Which terminal opens is still Hermes' `display.interface`
  decision: the launch has never forced `--tui` and still does not. Combining
  one of the three with a subcommand is an error that names the flag, because
  a dropped `-p` would run that subcommand against a profile the person
  believes they selected.

  After a clean exit, OMH prints one copyable line, `omh --resume <id>`, or
  `omh -p <profile> --resume <id>` when a profile was passed, since a profile
  has its own `state.db`. Hermes' own epilogue still prints first; suppressing
  it would mean capturing the child's stdout, which would break the TUI.

  OMH cannot read the id Hermes used -- Hermes creates its active-session file
  with `mkstemp` and unlinks it before returning -- so the id comes from the
  state database the TUI just wrote to. The TUI gateway stamps
  `sessions.ended_at` as the child exits when it owns the session's lifecycle,
  and the launch knows when its child started and stopped. Only the id and the
  columns that choose it are read: no title, no message content, no cwd, and
  cwd is not a filter either, because `hermes --resume` restores the session's
  own directory.

  The whole contract is when it declines, since this runs after the session
  has already ended and a wrong id is worse than no line. Nothing is printed
  when no TUI session ended inside the child's window, when the newest one did
  not end close to the child's exit, when a second session ended within the
  same tolerance (two terminals closing together), when the session holds no
  messages, when the database is missing, locked, corrupt or foreign, or on
  any exit code other than 0 and 130. A gateway-owned session is never ended
  by the TUI, so it produces no candidate and no line, which is the right
  outcome rather than a gap.
- **Three skills that were strict subsets of a stronger sibling now retire
  into it, and the always-loaded budget ratchets down instead of up.**
  `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` sat at exactly its own limit, so every
  new skill and every strengthened body needed a raise before it could land.
  Three of the installed skills were doing a job their sibling already did
  and more: `performance-goal` produced the same outputs as `ultraperf` minus
  the baseline record, the ranked hypotheses and the regression gate;
  `best-practice-research` answered the same question as `web-research` with
  three untyped outputs instead of two named schemas; and `autoresearch-goal`
  was a validator-gated wrapper around what `research` already does with a
  reference and six schemas. Each pair cost two always-loaded bodies for one
  job.

  The three are retired, not deleted, using the shape the four folded ULW
  engines already use: the contract stays in the catalog as a workflow
  reference, the body stops rendering, a stale label or tap path fails with a
  named migration error pointing at the target home, doctor reports a
  leftover install, and rollback is a one-row edit. What differs is where the
  intent went. An engine retired into a capability inside `ulw-work`; these
  retire into a whole sibling skill, so the migration error names the target
  home rather than a capability id, and the cue vocabulary folds into the
  target's own trigger table instead of routing through the engine alias
  resolver. That resolver returns an unconditional high-confidence dispatch
  on a contained cue, which is right for a distinctive engine name and wrong
  for a bare word like `benchmark`; folded triggers compete in ordinary
  scoring instead.

  Nothing anyone types stops working. Every trigger of the three still
  dispatches, now to the target home, and the two bare metric nouns another
  workflow already owned (`latency` to the observability card, `throughput`
  to the agent ops review) keep that owner. The negative-control corpus still
  reports zero over-routes with three new controls added for the everyday
  words the fold moved.

  The budget is ratcheted DOWN to the new measured value: the full-profile
  skill body from 992,659 to 978,380 characters, the full capability section
  from 430,308 to 422,526, and the standalone capability section from 120,089
  to 117,254. Installable skills go from 127 to 124.

- **OMH's per-turn context now arrives fenced, and stops over-asserting.**
  Hermes concatenates whatever `pre_llm_call` returns onto the API copy of the
  USER message (`compose_user_api_content`, `agent/turn_context.py`) with no
  role separation and no marker, so up to 6,678 characters of OMH imperatives
  were delivered as a continuation of what the person wrote. Hermes already
  fences its own memory channel for exactly this reason; OMH now does the
  same. Everything it injects goes inside `<omh-context>`, behind a note
  saying the block is automated OMH context rather than the person's words and
  that their message outranks it -- including the dispatch outcome lines and
  the running-work rows, which carry no `[OMH ...]` head of their own and so
  could never have been covered by a per-producer convention. A turn OMH has
  nothing to say on still injects exactly zero characters.

  The fence is sanitized, not merely wrapped. Most of what goes inside is text
  OMH did not author -- todo item text the model wrote, dispatch refs,
  workflow and lane names, role markdown, route-hint fields derived from the
  person's own message -- and a part carrying `</omh-context>` would close the
  fence early and hand everything after it to the model as the person's words
  again, reachable by whatever writes a todo item. Any `omh-context` tag is
  removed from the body first, matching the tolerance of the host's own
  `sanitize_context` (either tag, any case, whitespace inside the brackets).
  Stripped rather than escaped, because nothing un-escapes it and Hermes
  replays this turn's injection verbatim on every later turn. Removals are
  tallied in process for diagnostics; they are not a call failure, so they do
  not enter the degradation lane, whose claim boundary would then be false.

  Six rules that over-asserted were rewritten with it. `TODO_ANSWER_FIRST_RULE`
  now offers the record before the resume ("either record an omh_todo
  `deferred_reason`, if they steered the work elsewhere, or resume the plan"),
  because the gate that selects it is presence-only by design, so "stop,
  forget the plan" and "carry on" reach the identical sentence and resume-first
  made arguing the default reply to someone who had just said stop. Both
  options and the stop criterion are unchanged. On a turn that variant is
  selected the dispatch block is introduced as coming after the answer and the
  continuation-claim finding is held back entirely, so one obligation claims
  the turn instead of three. That finding no longer says "announced a
  continuation but nothing resumed ... A promise to continue is not a
  continuation" -- a verdict it delivered on ordinary narration like
  "continuing to read the router tests" -- and instead names the records that
  hold, with the count, and asks for the next step or a plain statement that
  the work is stopped and why. The delegation nudge stops saying "keep working
  while it runs", which was wrong about both tools it names: measured on
  hermes-agent 0.21.3, `omh_delegate_route` writes routing keys for the next
  dispatch and runs nothing, while `delegate_task` is always backgrounded for
  a top-level model call and the host's own schema says never to wait or poll
  on it. And the answer-first rule now needs a person, not merely a message.
  Hermes opens turns with rows it writes itself -- a background process
  finishing, an async delegation batch, a model switch, a crash-recovery note
  -- each a `role="user"` row carrying real text, so presence alone read them
  as somebody writing and the model was told to answer a person who did not
  exist. Measured in the owner's store: 282 of 1,869 user rows. The
  discriminator is the row's `display_kind`, which Hermes stamps at turn start
  and already uses for the same question in `split_user_originated_turn` and
  in the /rewind and /undo listing; absent or `steer` is a person, anything
  else is the host. A record field, never wording.

  And the plan line gains the off-switch every other injection already had.
  Code-mode latches once per session, engagement nudges cap at two, the board
  card claims once, the route hint claims per fingerprint, the repeat streak
  expires, dispatch outcomes age out; the 357-character reconciliation rule
  fired on every turn for as long as a plan existed. It now spends a
  three-turn budget per plan record and drops to its first clause after that,
  returning in full on every write to the record -- which is when a completion
  claim is most likely, since the model has just marked something done. Both
  inputs are records: the plan's own `updated_at` and a per-session turn count
  beside the other bounded maps in `hooks/nudge_budget`. A caller that is not
  a turn renders the rule whole and records nothing.

  Measured over 40 turns with one open plan, by driving the real hook rather
  than multiplying one turn: 29,259 characters before against 28,358 after
  when nothing writes the plan, and 62,229 against 57,491 on a session also
  carrying two unacknowledged dispatches. The fence costs 119 characters on
  every turn that injects anything and the budget returns 153 once it spends,
  so a session whose plan is written every other turn never reaches the saving
  and pays the fence in full -- 34,019 against 29,259. That trade is stated
  rather than tuned away: the marker is the fix for the root cause and its
  cost is per-turn by construction, because a fence explained only on the
  first turn would survive until a compaction dropped that turn.

  The decay is a small part of that plan block, not most of it: the block runs
  about 850 characters on a one-character message and the three-turn budget
  returns 153 of them. The rest is the drive wording, which this change leaves
  alone deliberately. Refs #1730, which stays open for that remainder and for
  the `omh_todo` single-item update.

  Nothing here claims to change what a model does. Every figure is a
  measurement of what the model is TOLD.

- **A question asked mid-plan is now answered before the plan resumes.**
  While an `omh_todo` plan has open items, every turn's context carried
  `TODO_CONTINUATION_RULE`, whose stop criterion ends "not when a turn has
  produced an answer". On a turn someone opened with a message that is the
  wrong sentence: it tells the model that answering does not discharge the
  turn, so the ask gets a cursory agreement and the session returns to its own
  next item. The observed run agreed that something "could be a model-level
  issue" having checked nothing, pivoted to "how shall we proceed?", and when
  challenged offered to fact-check if it were asked a second time.

  The per-turn line now reads one structural fact about the turn -- whether an
  inbound message opened it -- and carries `TODO_ANSWER_FIRST_RULE` in place
  of the drive when one did: answer it completely in this turn, investigate
  rather than defer, never agree with a claim you have not checked, then
  either record a `deferred_reason` or resume the plan (the entry above
  reorders those two branches, which shipped the other way round here).
  The drive is reordered, not dropped, which is what keeps this inside the
  stop-criterion contract rather than back at an observe-only reminder.

  That fact is an identity, not an interpretation. Hermes invokes
  `pre_llm_call` exactly once per turn, from `build_turn_context`, with the
  message that started it, and a turn the session drove onward by itself never
  re-enters that hook at all -- the host appends the `pre_verify` directive as
  a synthetic user-role row and re-enters the same turn loop. Nothing OMH
  wrote can arrive as this message, so presence is the whole test: two
  messages that mean opposite things produce the identical line, a blank or
  non-string message is absence, a host-labelled tracker event is an event and
  not someone writing, and a host that passes no message renders what it
  rendered before, byte for byte.

  Precedence is pinned alongside it. A recorded `deferred_reason` still wins
  over the message, being the more specific statement and the one that names
  what was asked for instead; a blocked next item still vetoes the deferral;
  and the stall observation goes with the drive, since "if nothing is blocking
  it, move it" would re-add in the same breath the ask this branch removes.
  The turn-end directive is unchanged and deliberately ungated: it fires after
  the answer it is handed as `final_response` exists, which is the moment the
  new rule itself asks the plan to resume, and Hermes passes it no message it
  could gate on.

- **The rule that keeps a retracted failure from outranking a live
  cancellation is now held by a test.** Runtime recap ranks the two terminal
  event groups by severity rather than arrival, so a `cancelled` appended
  after a `failed` does not erase the failure. That much was pinned. The case
  that keeps severity honest was not: a failure since retracted -- a second
  `failed` record written `not_observed` -- must yield to a live cancellation.
  The code gets this right only because per-type selection runs before the
  severity comparison, and nothing recorded that the two rules compose in one
  order and not the other. A change that compared the groups first, or that
  read `not_observed` as an absent record rather than a record, would have
  flipped it with every existing case green (#1554).

- **A Windows diagnostic-owner test no longer lets tempdir teardown replace
  the verdict it exists to report.** In
  `tests/test_local_diagnostic_process_cleanup.py`, both tests asserted their
  outcome after their `TemporaryDirectory` block had already closed, so a
  `PermissionError` from a still-exiting child holding the directory open
  came back as the whole failure and hid whether cleanup actually verified
  (#1644). Both tests now assert inside the `with` block, and
  `WindowsJobObjectOwner` records which of its two waits did not resolve --
  the Job Object never reporting empty, or the process handle not reporting
  exit once it did -- on a new `termination_diagnostic` attribute the test
  surfaces in its failure message, with no change to what `terminate()`
  returns. Separately, `_await_empty_job`'s 1.0s deadline was a correctness
  bound sized like a performance budget on a shared runner, the same class of
  defect as #1599/#1604; it is now its own named constant,
  `_JOB_EMPTY_DEADLINE_SECONDS = 30`. The Windows path itself is unverified
  from this change -- macOS cannot reach `WindowsJobObjectOwner` at all.

- **`omh ops plugin-risk-audit` can now bind its hook classification to the
  Hermes you would enable the plugin on.** The hook-semantics mapping is pinned
  to one host revision and the audit published that range, but it had no input
  or result field for the host an operator is actually running. A plugin on a
  newer or older Hermes still came back `classification_status: classified`,
  and the public documentation told the reader to compare the two versions by
  hand — so the one safety condition the audit describes sat outside the
  machine-readable verdict (#1597).

  `--hermes-version <x.y.z>` states the host; `--hermes-install <dir>` names
  one local installation and reads the `__version__` its version module
  declares. The two are mutually exclusive, so nothing ranks one host claim
  over another, and neither is inferred: the plugin's own `requires_hermes`
  says what the package asks for and is never read as an observation of an
  environment. Reading an installation goes through the bounded seam the TUI
  preflight already used, now shared rather than copied. It is a file read —
  Hermes is not imported, its binary is not run, no subprocess is spawned, no
  socket is opened, and no installation is discovered by scanning.

  `declared_hooks.host_contract.inspected_host` reports the version that was
  established, the method it came from, and one of four compatibilities.
  `incompatible` and `unreadable` hold the verdict at
  `classification_status: unknown` and put `undetermined_hook_contract` in
  `summary.risk_categories`, so a mapping that was never read against your host
  cannot render as an established contract. `not_observed` is the default when
  no host is named and is not a pass: the audit says so in a diagnostic
  whenever the plugin declares hooks. An explicit request that yielded nothing
  stays distinguishable from never having asked, because the method names the
  source that was selected either way.

  The three claims stay apart. A manifest that parsed cleanly keeps its
  `declaration_status`, its per-hook rows and its effects while the overall
  decision is held, and the declared range and the inspected host are separate
  fields that are tested not to substitute for one another. No operator path,
  installation path, or version string that failed to parse reaches the result.
  `hermes_host_execution` and `hermes_plugin_admission` join `not_observed`,
  because a compatible mapping is static pre-enable evidence and never proof
  that the host would admit, load, register or run the plugin.

- **`omh ops plugin-risk-audit` now says whether a plugin can replace its own
  installed code.** The audit reported dependencies, dynamic execution, hook
  capability, network requests, committed secrets and process execution as six
  independent categories, so an operator saw ordinary network and process
  findings without being told the package may also carry a second
  software-update authority beside the host's pinned plugin update path, with
  different pinning, rollback, consent and review guarantees (#1546).

  The result now carries a `self_update` block composed from signals the scan
  already collects rather than a parallel scanner: the file's own
  `network_request` category supplies retrieval, a write, copy, rename or
  replace call beside a code or manifest target name supplies replacement, and
  an archive unpacked or a self-directed upgrade command in a file that also
  spawns a process supply the remaining legs. Three named compositions classify
  `detected` and the matched one is reported, so the result says which signals
  produced the verdict. Neither ordinary leg passes alone, which is why an API
  client writing a cache file and a code generator with no network do not
  compose it. Retrieval beside dynamic execution is `needs_review`, because
  retrieved bytes can become code without a write to settle it either way. Both
  verdicts reach `summary.risk_categories`, as `self_update_or_code_replacement`
  and `undetermined_self_update_path`, so a wrapper reading only the summary
  cannot see a package with an unsettled replacement path as a clean one.
  Integrity verification is recorded under `mitigating_signals` and never turns
  a finding into a safe verdict.

  The scan stays what it was: bounded static text from one explicitly named
  local directory, with import, registration, execution, dependency
  installation and network access still `not_observed`, joined now by
  `plugin_code_replacement` and `plugin_self_update_execution`. No file name,
  remote target or matched source reaches the result; `signal_file_counts` is
  the bounded stand-in, because a file name is plugin-authored text. Absence is
  reported as absence of a match rather than absence of risk, in the block's own
  diagnostics and in the claim boundary. `docs/PLUGIN-SELF-UPDATE-AUDIT.md` is
  the public account of the signals, the compositions, the three states, and the
  two shapes worth knowing before acting on a result.

- **A plan item that records why it cannot proceed now says so on the
  checklist.** `blocked_reason` had one consumer, the turn-end continuation
  directive, which reads it and stops nudging. Nothing rendered it, so the
  person watching the TUI saw the item sitting in `active` with no sign it was
  waiting on anything -- which reads as stuck, the exact reading the stall
  finding exists to prevent (#1553). Both row-rendering surfaces now carry the
  reason: the text HUD line appends `(waiting: <reason>)`, and the TUI plan
  panel adds the same clause in its warn tone, ahead of the `(unchanged …)`
  hint on a row that carries both, because the reason is what explains the
  age. It renders on whatever row holds the field rather than on a chosen item
  state.

  The store's 200-character cap is not a row width, so each surface cuts the
  reason at 48 characters, the ellipsis included, and the panel gives back
  exactly the width the clause needs from the item text so that a long text
  cannot push the clause off the row. Truncation stays a render concern: the
  stop criterion and the projected `blocked_reason` field are untouched, and a
  recorded reason remains a declaration -- never evidence that something is
  actually blocking.

- **A coding CLI installed under a sensitive directory no longer dispatches
  without a write fence.** Fanout screened its sandbox read roots with
  `read_roots_are_safe`, while every fanout spawn passes
  `allow_broad_file_read=True`, which makes both backends ignore those roots
  for reads. The screen could therefore narrow nothing, and its one remaining
  effect was to answer a sensitive read root by leaving the run unconfined: an
  owner CLI at `~/.claude/local/claude`, a standard Claude Code install
  location, put `.claude` into a read root and the dispatch lost its write
  fence while still reading the whole host tree. The more sensitive the
  executable's location, the less confined the run (#1602).

  The fanout lane no longer runs that screen, with the reason recorded at the
  code, and its confinement receipt now says outright that reads are not part
  of the boundary it attests, so the record still states what was and was not
  confined. The strict cross-harness-adapter lane, where the same screen does
  narrow reads, is unchanged and still refuses an unsafe read root; the
  `~/.claude/local` shape is pinned there as a refusal. The fanout
  data-boundary row no longer names `read_roots_are_safe` as an enforcer,
  which moves the safety-profile revision.

- **A tool call the model has already made four times in a row is now
  refused, not just warned about.** A Hermes session searching a repo called
  `search_files` with one identical pattern more than 180 times in a row,
  identical arguments every time, each returning in ~0.0s. The tool itself
  printed `BLOCKED: You have run this exact search N times in a row` into the
  result, and the model read that and issued the same call again. The session
  burned its budget and never started the work it was asked to do. A warning
  inside a tool result is advice; the loop ends only when something refuses.

- **A tool call a session keeps repeating is now refused, and then put to
  the person.** Measured session 20260919_140745_db409e, 409 tool calls and
  2.12M input tokens: 203 `search_files` calls with identical arguments, 185
  of them refused by Hermes' own guard with its counter escalating past 99,
  and the model issued the same call again every time. The same session then
  repeated one `read_file` region 100+ times against the host's second guard.
  The session burned its budget and never started the work it was asked to
  do. So the loop is not a search quirk, and a refusal message is something
  this model demonstrably reads and ignores.

  `pre_tool_call` now counts consecutive identical calls per session, keyed by
  tool and by a digest of the arguments, and intervenes in two stages. Stage
  one, at the 8th identical call, returns a block directive whose message
  becomes the tool result. Stage two, after four of those blocks have been
  ignored, returns an approve directive instead, which Hermes routes to the
  same human-approval gate as a dangerous shell command; the host documents
  that gate as one the model cannot skip, and in a context with no human to
  ask it fails closed. The escalation carries an explicit
  `omh_repeat:<tool>:<digest>` rule key, so a person who answers "always" is
  answering about exactly that one call rather than about a key that changes
  with every prompt.

  Eight and twelve, not four, for two reasons. Hermes already refuses a
  repeated `search_files` at the 4th identical call, so a second refusal at
  that point is the same message in another voice; engaging four calls later
  engages on evidence the host's refusal did not produce, namely that it was
  ignored. The binding reason is the other one: an identical repeated call is
  not always a loop. Polling is the legitimate case, since `terminal` running
  `gh pr checks <n>` back to back while waiting on CI has byte-identical
  arguments every time, and OMH cannot tell it from a loop because the digest
  covers arguments and this code never sees a result. So the ladder leaves
  room for a poll: a short one passes under 8, a long one reaches a person at
  12 who can answer "always", and the digest-scoped rule key is what makes
  that answer cover exactly that poll and nothing else.

  Stage one is not a stronger mechanism than the host's, and the code says so:
  a block becomes the tool result exactly as the host's error did, and a model
  that ignores one can ignore the other. Four ignored blocks is where that
  stops being a model recovering and starts being a refusal nobody is reading,
  and the only response in the host's contract that a model cannot answer by
  itself is the person.

  Both messages say only what was measured, which is the arguments. Neither
  claims the results were the same or that another call cannot differ: that
  would be false for a status poll, for `web_search`, and for `read_file` on a
  file another process is writing, and OMH has no way to know. The host's
  guard can say "the file has NOT changed" because it sits inside the tool;
  this sits outside it. The block message says the call has been issued that
  many times with these arguments, says OMH compares arguments and not
  results, and then branches: if the same thing keeps coming back, including
  nothing, then what is being looked for is not there under that name, so read
  the file directly or list what it does define; if something is being waited
  on, do other work between checks instead of re-issuing the call back to
  back. It also never says "you already have this information", the host's
  wording, which was false in the measured case because the pattern named
  functions that do not exist.

  The guard clears itself. One call with different arguments or to a different
  tool resets both counters to nothing, and a streak whose last call is more
  than five minutes old stops counting. Calls that dispatched and calls this
  guard intercepted are counted in separate fields, which is also what makes
  stage two reachable at all: once stage one starts refusing, no further call
  runs, so a count of calls would freeze and only a count of ignored refusals
  can escalate. A reader function exposes both, and the stage, for a later HUD
  surface without changing what is stored.

  Telling a loop from a poll by digesting results is deliberately not built
  here; it is the right next step and is filed separately.

  Identifying a repeat needs the arguments, and the ledger still never holds
  them: they are canonicalized, capped at 8 KiB and stored as a 16-character
  BLAKE2b digest that says only "identical" or "different", which keeps the
  record inside the plugin's `privacy: metadata_only` contract. No argument
  text reaches the ledger, the block message, the approval prompt, or the rule
  key. Every path out of the positive case allows the call: no session id, no
  digest, an unreadable ledger, a malformed row, or a binding fault. That
  matters most at stage two, where an escalation in an unattended session
  waits for a human and then fails closed, and #1674 is what an over-broad
  `pre_tool_call` veto already cost once.

  What this does not claim: that the loop ends. Stage one is a refusal with
  the same mechanism as the two host refusals this model ignored 185 and 100+
  times. Stage two takes the decision away from the model, but no live Hermes
  session was run here, so the prompt rendering and a person's deny ending a
  real loop are untested.

- **`/omh-model` and the `omh` CLI now edit the store a bot profile
  dispatches from.** A Hermes bot profile may select its own OMH store with
  `plugins.entries.omh.settings.omh_home`, and its native plugin resolves that
  setting before any environment value. The two other surfaces that show "the
  chains" did not: the TUI widget forced `OMH_HOME` (or `~/.omh`) into every
  reader and writer it spawned, and the standalone CLI read the environment
  and never the file, even under `--hermes-home <profile>`. So a chain set
  from a Desktop bot chat landed in the profile's store and took effect there,
  while `/omh-model` in that bot's TUI and `omh model-chains show` read
  `~/.omh` and reported every category as `default` -- and a save from the
  picker went to a file the profile never read (#1679).

  The standalone lane now reads the same setting from the Hermes home's own
  `config.yaml` (by text scan, the block shape Hermes writes, last duplicate
  winning), then the legacy `OMH_HOME`, then `~/.omh`; an explicit
  `--omh-home` still wins. An inline `plugins:` section that names no
  `omh_home` reads as absent. A blank or null setting, an inline section
  that does name it, an alias or merge key it could be inherited through, a
  leaf a YAML loader would not hand back as one string, a tab-indented file,
  and a `$VAR` other than `$HERMES_HOME`/`$HOME` are binding errors rather
  than a substitute store -- the last because this lane has no secret scope
  to verify a variable against, where the native lane does. The widget names
  no store and lets the bundle resolve it from the Hermes home it names. The
  installer's profile sync keeps naming the primary's store for the managed
  skills, widget and skin every profile shares; the registration-only
  opt-out and the one-time legacy migration still find a registration
  written at the default store when the home has since selected its own.

  Two smaller things made the symptom unreadable and are fixed alongside: an
  override document the reader rejects (`invalid: …`) rendered in both
  pickers as twelve `default` rows with no warning, and now gets one row
  saying the file is there and why it is not in effect; and the TUI picker
  showed the file it edits only while a change was pending, and now shows it
  always.

- **A gateway session that no profile owns is no longer vetoed out of every
  tool call.** On a Hermes gateway with `multiplex_profiles` on, a session that
  reaches OMH with no home override is one OMH refuses to attribute to any
  profile -- it will not guess a store, and that refusal is correct. What was
  wrong is what `pre_tool_call` did with it: it returned `action: block`, so
  every tool call in every such session came back "OMH runtime binding
  unavailable; tool rules could not be checked", while TUI sessions and
  explicitly routed profiles kept working. The reporter measured 72 blocked
  calls in a day across their IM and cron sessions and confirmed the sessions
  recover as soon as the hook stops vetoing (#1674).

  The veto exists to protect user-authored toolcall rules, and those are opt-in
  by the presence of a file inside the session's own store. A session with no
  store has no rules file to leave unread, so the veto was protecting nothing
  and ending the session instead. That distinction is now carried by the signal
  rather than guessed by the handler: the two refusals that name no store raise
  `UnattributableSessionError`, and `pre_tool_call` degrades on it exactly as
  `post_tool_call` and `pre_llm_call` already did. Every other binding fault
  keeps the veto, because each of them named a store first -- a malformed
  setting, an unresolvable path, an unverified owner, a config read that failed
  -- and a rules file may be sitting in it.

  Profile isolation is untouched. Which sessions bind and which are refused is
  the same before and after; only the refused session's tool calls stop being
  vetoed. The narrower report that a configured `omh_home` cannot rescue this
  shape is real and left open: the refusal does precede the configured home, by
  design, and changing that is a profile-binding decision rather than a
  hook-posture one.

- **Each Hermes TUI's plan-todo panel now renders its own session's checklist,
  not the most recently active one's.** Reported with screenshots (#1672): with
  two TUIs open, both panels showed the same plan and whichever TUI moved last
  won both -- one session mid-run on that plan, the other on an unrelated
  topic, under a byte-identical header. Writes were already one record per
  declaring session; reads were not. The widget names its session from the
  host's per-TUI active-session file, which on `session.create` holds the
  gateway transport id (`ebe3eaaa`) while records and `state.db` rows are keyed
  on the durable session key (`20260917_132533_8da9b8`) -- a name no row or
  record carries, so the reference resolved to nothing and a fallback re-read
  with no identity at all, which answers with the most recently active TUI row.
  The two names meet in the host's own active-session lease registry
  (`$HERMES_HOME/runtime/active_sessions.json`), which records the durable key
  as `session_id` and the transport id as `metadata.live_session_id` against
  one lease, so a reference matching no live row is now resolved there before
  being taken at face value and a created TUI reads its own plan. The
  most-recently-active fallback is gone: an unpaired reference keeps its own
  identity and falls back to the home-wide record under the gates already in
  place, never to another session's record. Only `surface: 'tui'` leases
  answer. Because the host claims a lease on a session's first real turn rather
  than at creation, a TUI nobody has prompted in is named by no entry -- and
  has declared no plan either, so its panel is empty for the same reason. Read
  only, and no Hermes change: `session.create` does already return the durable
  key next to the transport id, so the host could write it into the file
  instead, but OMH does not patch Hermes and the registry answers the same
  question from our own side.

- **The three sibling engines can now put their own lanes on the board
  `ulw-work` learned in the entry below.** A `loop` iteration still died with
  the session: the chain of assess, act, verify, decide had no shape on the
  board, so a loop that had to survive a session end either stayed in-session
  and was lost, or went to the board as unordered rows a new session could
  only resume from memory. `ultraqa` had no way to run a destructive probe
  anywhere but the main workspace, and `ralplan` produced accepted lanes that
  `ultrawork` had to re-plan into node prompts before it could prepare a row.
  Each engine now carries one always-loaded clause, and for the two engines
  that go to the board the method lives in a reference outside the body
  budget. `ulw-loop/references/board-iteration.md` chains each iteration as a
  builder row whose `parents` is the previous verifier and a verifier row
  whose `parents` is its builder, so the board itself enforces builder,
  verifier, next builder and nothing runs out of order; a stop the constraint
  assessment owes the user is a `needs_input` block with the reason, never a
  silent retry, and a new session resumes from one `kanban_list` and one
  `kanban_show` per changed row, continuing from the last `done` verifier
  rather than from memory. There is no goal-mode root row, because the loop's
  real gate is the in-session verification it already requires.
  `ulw-qa/references/board-fanin.md` runs each adversarial scenario
  as its own probe row in a Hermes-owned worktree with a runtime budget, fans
  every probe into exactly one fixer row whose `parents` is all of them so it
  is promoted only after every probe reports, re-verifies through the native
  review lane (`request_review`, and `request_changes` with the reason on a
  failed re-check; a review claim is not merge evidence), returns findings only
  through the bounded, labelled readback as the worker's own report, and names
  the preserved worktree as the cleanup receipt. `ralplan` gains no reference
  and no board: its accepted plan now lists every lane in node-prompt shape
  (`TASK`, `DELIVERABLE`, `SCOPE`, `VERIFY`, `STOP WHEN`) with `depends_on`
  per lane, so `ultrawork` can prepare rows from the plan without re-planning
  while planning itself stays a bounded in-session lane. The create recipe,
  the main-session-only rule, the readback bounds, the provenance words, and
  the role table are not repeated; both references point at
  `ulw-work/references/kanban-lane.md`. No trigger changed, so the routing
  corpus is unchanged.
- **A ulw-work lane can now outlive the chat session, and the HUD shows it
  beside the delegate_task rows.** Until now every parallel lane was a
  `delegate_task` child: a daemon thread inside the TUI process that `/new`,
  a session end, or `kill -9` took with it, that Hermes marked `unknown` and
  never resumed, and that no second session could see. The Hermes Kanban
  board already had everything a durable lane needs (rows in `kanban.db`,
  parent edges that promote a child when every parent is `done`, a gateway
  dispatcher that claims a `ready` row and spawns the assignee profile as a
  detached OS process, a per-task worktree, a `session_id` stamp on rows an
  agent created), and OMH already had the prepare-only path to it,
  `omh_agent_board`. What was missing was the lane vocabulary on that path
  and any way to see the result. The prepared durable `create` now admits
  the per-task overlay the dispatcher reads — `body`, `skills`,
  `workspace_kind`, `workspace_path`, `priority`, `max_runtime_seconds` —
  each bounded before the host schema is consulted, with `parents` declared
  on the create itself because the dispatcher can claim a parentless
  `ready` row within one tick. The role is a contract rather than an
  instruction: a create that states `lane_role` has that lane's skill and
  workspace filled in from the role, and a verifier or reviewer declaring no
  parents is refused instead of landing as a fan-in row the dispatcher can
  claim before its inputs exist. OMH still executes nothing: the Hermes loop
  invokes the prepared `kanban_create`, the gateway runs the worker, and a
  board `done` is written as the worker's completion claim, never as
  verification, CI, review, or merge evidence.

  The HUD reads the board read-only through a bundle-local reader that
  resolves the board the way Hermes does (`HERMES_KANBAN_HOME`, the current
  board slug, the Hermes root with `profiles/<name>` stripped) and projects
  each open task as a lane row in the same activity list as the native
  rows, tagged `[bot]` where a delegate child reads `[sub]` (bold, three
  cells, in place of the per-row `[global]` / `[this chat]` scope word; the
  header line still states the scope), identified as `kanban/<assignee>(<model>:<effort>)` in the same
  shape as the native `category:name(model:effort)` and rendered as one
  accent-toned line, with a static dot for `queued`, a warn bang for a worker whose
  heartbeat stopped, and the native status word in the tail. The figures on
  that line are the worker's own: the board records no usage at all, so the
  model, turns, tool calls, tokens and cost are read from the worker's
  session in the assignee profile's `state.db` and summed the way the native
  rows sum them, so one token column means one thing down the whole list.
  Three rules link them, all matches on recorded fields: the
  `worker_session_id` a worker stamps onto its run the first time it calls
  `kanban_complete` or `kanban_request_review`; before that, the session
  whose title Hermes derived from the dispatcher's own opening prompt,
  `work kanban task <id>`, inside that run's dispatch window, which is what
  tells two workers one tick spawned apart; and failing both, the single
  kanban-source session opened inside the window. A window two untitled
  sessions answer identifies neither, so the
  row keeps the board's own facts and a blank token column rather than a
  borrowed figure. The header
  gains `board Nq Nr Nb` while the board holds lanes and `dispatcher not
  observed` when `ready` rows have waited past the dispatch window with no
  worker or claim anywhere — the one board fault the HUD can see, named as
  a verdict rather than a failure. A session that created board lanes is
  told once, on its next first turn, how many are still open.

  Board readback was the claim that did not survive review: `kanban_show`
  returns every run and comment uncapped, the message gate never sees a
  tool result, and the bridge discards the text. So a third annotating
  pass in `transform_tool_result` now bounds `kanban_show`,
  `kanban_list`, and `kanban_attachments` results per field and in total,
  drops the oldest comments and runs first while keeping the latest run,
  and prefixes one label line whose confidence words are a hand mirror of
  `src/evidence/labels.py`: a completed run is `reported done`, never
  observed or verified. The ultrawork body carries one clause pointing at
  `references/kanban-lane.md` (25,911 bytes by the structure lint's own
  measure, 11 over the 25,900 ceiling, ratcheted to 26,000 with the dated
  reason); the recipe, the
  main-session-only rule (delegate_task children never see `kanban_*`), the
  readback discipline, the provenance words, and the role table — profile
  is the permission envelope, role is the `skills` pin plus body plus model
  pin on the create, specialist titles are lane titles only — live in that
  reference, outside the budget. `docs/AGENT-BOARD.md` records the operator
  preconditions the board needs and OMH cannot create: the `kanban` toolset
  enabled for the platform plus a fresh chat, `hermes kanban init`, a
  running gateway with `kanban.dispatch_in_gateway`, an existing assignee
  profile with the lane's skills installed.
- **The plugin bundle no longer needs the `omh` package to load, and the
  tool-call hooks no longer die when a bundle module fails to.** Reported with
  a reproduction by @tonalenar (#1623): with `memory.provider: omh`, Hermes
  loads the copied bundle a second time as a memory provider and that lane
  execs every top-level `*.py` eagerly. Three modules -- `agent_board_bridge`,
  `activity_observer`, `native_activity_observer` -- imported `omh.*` at module
  scope, which cannot resolve from Hermes' interpreter under the documented
  `uv tool install` / `pip install --user` layouts, and Hermes keeps the
  half-initialized module in `sys.modules`. The lazy `from ..agent_board_bridge
  import pre_agent_board` in the hooks then failed on the NAME rather than the
  module, so `error.name` was the bundle's own dotted path and never `omh`: the
  guard re-raised, and every tool call logged a hook warning while the bridge
  was dead anyway. The three modules now guard those imports the way the rest
  of the bundle already did and report the absence where the feature is
  entered -- `omh_agent_board` answers `omh_agent_board_core_unavailable`, the
  board hooks stand down instead of refusing native `kanban_*` calls they have
  no prepared request for, and the observer raises at construction, which
  `register` turns into the existing `observer_setup_failed` status. The
  engines themselves stay in the `omh` package: a copy in the bundle would be a
  second set of rules for the same receipts. The report's first suggested fix,
  widening the guard to `except ImportError` while keeping the `omh.*` name
  check, was measured against the cached-stub case and does not hold -- the
  name is still not `omh`, so the hook would still re-raise; its own
  alternative, taking the bridge by attribute and skipping when it is absent,
  is what shipped. The gate that should have caught all of this loaded one
  module, `awareness`, so its real subject was whatever `awareness` happened to
  pull in; `tests/test_plugin_bundle_standalone.py` now imports every module
  under `src/plugin_bundle/omh/` with `omh` blocked and derives that list from
  the directory.

- **A sibling cell no longer reads the receipt integrity key while it is
  still empty.** One OMH home holds one key and every run directory under it
  signs with that key, so `load_or_create_observation_key` was reached
  concurrently: `execute_paired_run_plan` submits a wave's cells to a
  `ThreadPoolExecutor`, and the lock each cell holds is a
  `BoundedSemaphore(global_concurrency)` admitting N holders, not a mutex, so
  two cells on different executors and providers ran the function at the same
  moment. The key was created with `O_CREAT|O_EXCL` and filled by a separate
  `os.write`, so between those two calls the key path existed at length zero
  and a second caller read it short. What reached the reader was not a partial
  key but `Hermes child observation integrity key is invalid` -- a message
  naming the key when the key was whole and the reader had merely arrived
  mid-write, which is the wrong diagnosis rather than only the wrong timing.
  The key is now drawn into a private temporary file in the same directory and
  published with `os.link`, so the key name appears only once it already holds
  all 32 bytes. `os.link` was chosen over the `os.rename`/`os.replace` the
  issue proposed because those publish atomically but overwrite: two creators
  would each install a different key, and the one that had already signed a
  receipt would stop verifying. `os.link` fails with `FileExistsError` for
  every creator but the first, which is the same single-creator election
  `O_EXCL` made on the key path itself, and the losers then read the key that
  actually landed. A retry loop on a short read was rejected: it converts a
  race into a slower race and leaves the failure mode intact. The two faults
  that shared the `is invalid` message are now separate -- a key that cannot be
  read says so, and a key of the wrong size reports the size it read, which
  post-fix can only mean the file itself is damaged.

- **There is now a skill for the plan checklist itself, for people who are not
  running a delivery engine.** `omh_todo` is registered on every session, and
  until now nothing in the skill surface named it: 131 skills, none with `todo`
  in the name, and 2 of 126 rendered bodies mentioning the tool at all — both
  delivery engines. A user who wanted a checklist went looking for `/omh-todo`
  and found nothing. `omh-todo-checklist` answers that, in an ordinary session,
  with the body carrying only what is wrong to discover late: items are
  declarations and never execution evidence, exactly one item stays active, and
  `action=set` replaces the whole list so a partial write silently drops what it
  leaves out. The shaping rules, the `blocked_reason` versus `deferred_reason`
  distinction — an item that cannot proceed, versus a person steering the
  session elsewhere — and the guidance on when a checklist is not worth
  declaring live in an on-demand reference, outside the always-loaded budget.

  It is not called `omh-todo`, and the reason is measured. A one-word name
  matches any sentence containing that word through the scorer's `name:` credit,
  and `todo` is among the commonest words in a coding session. A two-word name
  needs both words, which is what makes holding the bare token in
  `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` sufficient rather than decorative. Typing
  `/omh-todo` still finds it, because Hermes slash completion is prefix-based.
  Holding the tokens then cost the complete phrases their edge — "declare a plan
  checklist" routed to the planning workflow — so the phrases that name the
  checklist carry an explicit-phrase boost, with the bare nouns `todo` and
  `checklist` deliberately excluded from it.

  `docs/ADDING-A-SKILL.md` gained the two required surfaces it was missing.
  Without a `_WORKFLOW_OPERATIONS_CHAT_CARDS` entry a new skill has no card of
  its own; without `_DIRECT_WORKFLOW_SKILLS` membership the router selects it
  correctly and then renders a generic plan card, which reads as a routing bug
  and is not one. It also gained the rule that a `do_not_use_when` line must not
  repeat the deferring skill's own trigger vocabulary — otherwise the sentence
  written to send work to a sibling makes the deferrer outrank it.
- **`ulw plan` reaches the plan engine.** `docs/INSTALLATION.md` tells users to
  invoke a workflow as `ulw work …`, and only the hyphenated label routed: `ulw`
  on its own is an `ultrawork` trigger at score 12, so it took the whole request
  and the second word was never read. `ulw plan` reached `ultrawork`, `ulw qa`
  did too, and `ulw research` likewise -- the opposite of what the reader asked
  for, with nothing on the reply to say so. Routing now joins `ulw <suffix>`
  into the label it means before matching, for suffixes the catalog actually
  renders as a `ulw-` skill; every spaced form now routes exactly where its
  hyphenated twin does. `ulw` alone still means the delivery engine, and a
  second word that is not a rendered label is left alone rather than joined
  into a skill name that does not exist. Both halves are pinned in
  `ROUTING_INTERVENTION_CASES`, because a join measured only on what it fixes
  is "improved" until it swallows every sentence starting with those three
  letters.

- **The gate against hidden dynamic imports was matching nothing at all.**
  INVARIANT 1 of the handoff safety contract claimed to forbid reaching a
  module by name, on the grounds that a name resolves against the interpreter
  search path and could reach `subprocess` invisibly. It inspected two AST
  shapes, `__import__` as a bare name and `import_module` as an attribute, and
  neither occurs anywhere in `src/`. The spelling this repo actually uses is
  `from importlib import import_module` followed by a bare call, which is an
  `ast.Name` the check never looked at: 15 such calls across 5 files, two of
  them passing a variable rather than a literal. The same mutation — a bare
  `import_module(name)` dropped into an unrelated module — passes on `main` and
  fails now. Issue #1637 asked whether the check's silence about
  `importlib.util.spec_from_file_location` was deliberate scope or a gap, and
  the answer turned out to be that the premise was wrong on both sides. A path
  is not the bounded alternative to a name: `spec_from_file_location` plus
  `exec_module` executes a file that lives outside `src/`, so
  `_source_modules()` never parses it and the loaded file may import whatever
  it likes — which is verbatim what the invariant's own failure message says
  makes a dynamic import dangerous. What actually makes the live call sites
  acceptable is that each confines which module it can reach, and confinement
  is a property of the call site, not of the spelling. So both families are now
  allowlisted the way `subprocess` already was, each entry naming the
  confinement: a closed four-entry literal table, host modules that a wrapper
  declaring no dependency on Hermes cannot import normally, a computed managed
  plugin directory, a `checked_path` root refusal. Coverage extends past
  `spec_from_file_location` to `module_from_spec`, `exec_module`, the
  `SourceFileLoader` and `runpy` spellings, and builtin `exec`/`eval`, so the
  gate does not simply move to the next spelling; what stays deliberately
  uninspected — string indirection, `importlib.reload`, `sys.path` mutation —
  is written down with its reason rather than left to be inferred. Three path
  sites, not the four the issue counted, and one of them is the documentation
  claims prober, which is not a plugin path at all. No path load was reaching a
  spawn capability, and the existing plugin readiness tiers are unchanged; the
  comment in `plugin_pack.py` that justified them dropped its claim that the
  loaded file is hash-pinned, because the doctor tier runs against the
  installed bundle even when the manifest was already recorded invalid.

- **Saying a plan is fine no longer starts the plan again.** `the plan is
  fine, just ship it` dispatched `plan` and emitted a 10,572-character planning
  artifact -- goals, non-goals, decision drivers, options, rejection rationale,
  acceptance criteria -- for a sentence whose content is "yes, go", while
  `the design is fine, just ship it` one word away clarified.
  `ENGINE_ENTRY_CONFIRMATION_RULE` already said an accepted plan is planning
  evidence and not permission; the router contradicted it. It was never a
  `plan` problem: 18 of the catalog's 19 single-word names dispatch on their
  own name in that sentence shape, from `loop` at 45 to `maestro` at 9, because
  a name is at once the skill's name phrase, its phase, its metadata and a
  trigger. The gate keys on the SENTENCE instead of the name, which is what
  makes it finishable -- a list of which catalog names are ordinary words in
  every language the router accepts cannot be completed, and a word missing
  from it would leave the defect live inside a fix that claimed to handle it,
  where an approval phrasing this misses simply leaves today's behaviour. Two
  conditions gate it: the message approves, matched at word boundaries, and the
  winning skill's whole case rests on its own name -- computed by erasing the
  name and re-scoring rather than by listing which evidence labels count.
  Sigilled invocations (`$plan`, `/plan`, `use omh plan`) stay outside it; a
  bare leading name does not, since `plan is fine, ship it` is one article from
  the reported sentence. A compound approval clarifies rather than routing its
  remainder: re-scoring those remainders was measured, and the one that would
  have dispatched confidently is `ultrawork` on "now implement the retry
  handler", which is exactly the automatic continuation the rule forbids.
  English and Korean; Japanese and Chinese are deliberately absent rather than
  guessed at. The corpus gained 8 negative controls and 6 interventions, a case
  shape it had never contained.

- **The briefing now says when there is nothing left to do.** Reported as "할 일
  없다고 유저한테 공지해주는 게 부족함": a finished run announced itself only by
  going quiet. `signal` carried three values and `running` meant both "still
  moving" and "done", so the sole evidence a run was over was that the
  `Remaining:` line had stopped appearing — an absence, which is the one thing
  a glance does not register. A fourth value, `complete`, is withheld until
  every outstanding list the briefing keeps is empty: `pending_gaps` alone is
  not enough, because the runtime ladder reports separately in
  `runtime_milestone_gaps` and a prepared team path can sit at an unobserved
  rung with no progress step pending. The finished state also catches the
  headline's fall-through: those branches learn about a merge only from a
  runtime observation event or a lifecycle token, never from
  `runtime_status["merge"]`, so a run whose every step was complete could still
  be headed "is handling the coding work" — present tense, under a ✅ mark. It
  catches rather than outranks, which is the opposite of the standing rule for
  a stop and deliberate: a stop contradicts those branches, while a finished
  run agrees with them and they say more, so "work is recorded as merged" keeps
  its headline. The `Action:` line reads `none` in that state rather than
  echoing whatever `next_action` was written last, since nothing requires a producer to
  clear it on the way out. The sentence is translated in all seven locales the
  table carries, and an adapter that only knows the original three values keeps
  working: `complete` is the case it previously received as `running`.
- **A chat reply now names the workflow you asked for, in the spelling you can
  type back.** Two separate faults made the first line of a reply disagree with
  the router that produced it.

  The catalog keeps `ralplan`, `ultrawork`, `ultraqa`, `research`, `loop`,
  `maestro`, `context`, `deep-interview` and `ultraperf` as internal keys
  because triggers, capability maps and lifecycle rows are built from them,
  while the installed skills answer to `ulw-plan`, `ulw-work`, `ulw-qa` and so
  on. `public_workflow_identifier` exists to make that swap on the way out and
  its docstring calls itself "the one place" it happens — but the wrapper's
  explanation and usage-trace payloads never called it, so `ralplan` reached
  `label`, `visible_prefix`, `route_recommended_reply`,
  `route_primary_action_label` and `route_primary_action_hint` while
  `why_this_workflow` on the same payload said `ulw-plan`. One reply named the
  same workflow two ways. A `next_action` token that embeds its own skill
  (`prepare_ultraperf_loop`) put the key back into the sentence even after
  every field was corrected, so rendered prose now goes through
  `with_public_skill_names`; the tokens and ids themselves are untouched.

  Separately, a dispatched workflow that answers with the card it starts with
  lost its name entirely. `ultrawork` on a request that names no target keeps
  its plan card by design, and the prefix then read `[omh] plan` — so a user
  who typed `ulw-work` saw no trace of what they asked for, while
  `route.selected_skill` still said `ultrawork` two keys away. The prefix,
  label and `usage_trace.selected_workflow` now name the routed workflow on a
  `dispatch`; `state.selected_workflow` still reports the card that was
  actually rendered, because that is what a consumer reading it has always
  been told.

  `tests/test_public_workflow_name_exposure.py` derives the legacy set from the
  display rule rather than listing it, so a later relabel moves the guard with
  it, and fails if that set is ever empty — a guard over nothing passes without
  proving anything.

- **A minted memory id can no longer read back as a leaked credential.**
  `secrets.token_urlsafe(18)` draws 24 characters from the base64url alphabet,
  so a token occasionally comes out shaped like a real API key — `sk-`, `hf_`,
  `gh[oprsu][_-]`, `AIza`, `xox-` and the separator-split variant all fire, at
  a measured one id in 25,000. When such a token became a block's own
  `review_id`, the admission walk classified the block's own identifier as a
  secret and omitted the approved block from its own render with
  `safety_blocked_in_admission.review_id`. Nothing was lost and nothing said
  so; it surfaced as a CI failure costing a full diagnosis each time it landed.
  `_opaque_id` now redraws until the token classifies safe, and `_validate_block`
  checks the shape of `review_id` rather than only its presence — the guard its
  sibling `_memory_review_path` has had all along. Pinned by forced colliding
  draws, one per firing pattern, taken from real generator output (#1641).

- **OMH now engages on an ordinary prompt, and the trigger is what the model
  does rather than what the user typed.** Four measured causes of one report
  ("거의 todo나 에이전트 호출을 하지 않더라"). The plugin bundle's invocation
  vocabulary had drifted behind the router's: a bare `ulw` was a clean explicit
  dispatch on `public_chat_route_payload` and a zero-length context from
  `awareness_route_hint`, and so were the historical `omh-loop` and
  `omh-research` labels, because the pre-ULW alias was only added inside the
  display-name override branch. The bundle runs in a live session while the
  routing corpora measure `src/routing/`, so every routing test stayed green
  over a dead surface; a parity test now re-derives both vocabularies and fails
  on divergence. A route hint for a workflow whose run *is* a checklist now
  says to declare one — six workflows, not `ulw-context` or `ulw-interview`,
  which are engines that produce one card or one question. Awareness was gated
  on the user's message already containing OMH vocabulary, so six of eight
  ordinary work requests got nothing; the session's first turn now carries the
  primer unconditionally (897 characters, once), deliberately not on a task-size
  test, since the largest request in that set was one of the misses.
  None of that makes a plain session declare a plan, so two behaviour-triggered
  nudges ride `transform_tool_result`: one on the third `write_file`/`patch`
  result with no plan record, one on the fifth direct search/read with nothing
  routed. Both latch off permanently on a record — the plan record, or the tool
  name the host handed the hook — never on a string the model wrote, and both
  are bounded at two per session (worst case 1,418 characters). `subagent_start`
  is registered so a delegated child, which runs under its own session id on a
  seam carrying no agent identity, is never asked to declare its parent's
  checklist. Known boundary shared with #1549: the gate is `write_file`/`patch`,
  not "edited code", so a session that edits through the shell is never nudged.

- **An `ultrawork` run now meets its "declare the plan first" instruction
  before it starts, not after it has finished.** The one sentence telling the
  engine to initialize its phase todo was the sixth bullet of a ninety-line
  list under a heading named `Catalog Metadata`, near the bottom of a
  26,705-byte body — a section a model reads as machine-readable bookkeeping,
  reached only once the run is already underway. Strip that block from
  `skills/ulw-work/SKILL.md` and the word `todo` did not appear anywhere else
  in the document, `Completion Checklist` included; a real run performed the
  whole task with the HUD checklist empty. The directive is unchanged text
  that moved: workflow bodies gained a `## First Steps` section, rendered
  directly under `## Why This Exists` from a new `opening_steps` catalog field,
  and `ultrawork` and `ralplan` carry their todo-initialization there. Each
  also gained one `Completion Checklist` line, because the section a model
  follows to decide it is done covered lane disjointness, ACK, review, CI and
  integration and said nothing about whether a plan was ever declared — so a
  run that declared none still read as complete. The Agent Skills projection
  buried its own host-neutral copy of the same directive in the same place and
  moved with it. The seven remaining `ulw-*` skills are unchanged: six mention
  a todo only through the shared interjection rule, which re-reads one *when
  one is active*, and `ulw-interview` mentions none — a conditional reference
  is not a misplaced instruction, and giving them an obligation they never had
  is a different change.

  Because the cause is structural rather than an authoring slip -- `quality_bar`
  is a `SkillDefinition` field and every field it holds renders under
  `## Catalog Metadata` -- all 126 rendered bodies were then swept for `omh_*`
  directives living only inside that span. It found the same shape twice more,
  and both are now stated where a run decides it is done. `ulw-maestro` is told
  to close with the localized `omh_run_summary` text and its checklist said
  nothing about the close, so a run could end with no summary and nothing in
  the document contradicted it. `ultrawork` is told to route every
  Hermes-native lane with `omh_delegate_route` before dispatch and its
  checklist said nothing about routing, so a run that dispatched every lane
  inherit-labeled passed its own completion contract -- which is the second
  half of the same user report, the run that declared no todo also routed no
  lane. Each is one line restating an obligation the quality bar already
  carried; no new behavior text.

- **The coding status board reports how much a lane did, not only how long it
  ran.** A lane at twelve minutes and two tool calls and a lane at twelve
  minutes and sixty are different situations, and an elapsed time alone reports
  them identically — which is the reading a person has to make when deciding
  whether a quiet lane is working or stuck. `tool_count` was already observed
  and recorded in `ROUTING_METRIC_SIGNAL_KEYS`, and
  `_compact_event_projection` already folded it into the progress event; it had
  no field on the board row to travel in. There is now a `TOOLS` column on the
  aligned board and a `N tool calls` part in the bullet profile.

  Zero and unobserved render differently, deliberately. Zero is a real answer —
  an executor that made no tool calls made none — so an unobserved count shows
  `unknown` rather than `0`, which a reader would take as the executor having
  done nothing. `True` is refused as a count for the same reason it is refused
  elsewhere in this module: it is an `int` in Python and `1 tool call` would be
  a fiction.

- **Each lane on the coding status board now wears its model vendor's glyph.**
  Three running lanes are three rows of near-identical text, and the model is
  the field that differs and the field a reader scans for; a glyph is read
  before the word beside it is. The mapping is per vendor, not per model —
  `claude-opus-5` and `claude-fable-5-1` share 🟠, because eleven glyphs are
  already at the edge of what anyone holds and one per model generation is not.
  The traffic lights are reserved: 🟢 🟡 🔴 mean whether a run needs the reader,
  so a vendor wearing red would read as a stopped lane, and
  `tests/test_model_vendor_glyphs.py` fails if the two sets ever intersect.
  Every glyph is two display cells, also pinned, because a one- or three-cell
  glyph looks fine in bullets and shifts every column after it in the aligned
  block. A model the table has not seen renders ⬜ rather than nothing, since an
  unlabelled row among labelled ones reads as a rendering fault.

  Vendor resolution handles the shapes the board actually carries rather than
  the aliases OMH chooses: a bare product name (`fable-5 high` — Anthropic's
  names arrive without the family prefix), a provider-prefixed id
  (`openrouter/qwen-3.5-coder`, where the vendor is the model's and not the
  gateway's), and a generation-numbered token (`qwen3-coder`, which is why the
  token table is written out instead of matched by prefix). The first two were
  found by existing board tests, not by the new guard, which had been derived
  from the shipped chain table alone.

- **A narrow table keeps its columns on Slack, and provenance stopped taking
  the notification preview.** Messenger profiles turned every markdown table
  into bullets, which is right for a wide one and wrong for the shape people
  actually send — a list of issues or PRs, two or three short columns, which
  reads as a table and loses its alignment as bullets. Limited profiles now
  render such a table as an aligned block inside a code fence, the one shape
  Slack and Telegram keep, and fall back to bullets above three columns, above
  a 56-cell rendered width, or below two data rows. Each limit answers a
  different failure: a wrapped monospace row no longer lines up with the row
  above it, and a fence around a single row costs more than the columns save.
  Rich profiles are unchanged and keep the markdown table.

  Column width is now measured in display cells rather than characters.
  `len("이슈")` is 2 while the string occupies four columns, so padding by
  length is how a Korean or Japanese board comes out ragged inside the fence
  that exists to keep it straight — which the coding status board had been
  doing all along, and `src/commands/setup.py` had been getting right in its
  own copy. `src/system/display_width.py` is now the one home for both.

  Separately, the message gate's five provenance bullets became one line, and
  on limited profiles it follows the body instead of leading it. Five lines of
  "which skill, which model, which prompt" above the answer spend the whole of
  a phone's notification preview on who did the work rather than on what they
  found. The field labels stay: dropping them would leave
  `ulw-goal — active — sha256:…`, where only the digest identifies itself. Rich
  profiles keep the aligned card above the body, where there is room for it.

- **A `providers.<id>` block now says what it serves, and a machine that
  cannot say is told so.** Such a block is the operator's own endpoint behind
  their own `base_url`, and detection recorded every one of them as `gateway`.
  That kind is multi-vendor, so `alias_is_served` counted every alias as served
  and `entitlement_shaped_chain` was a no-op: the chain reordering did nothing
  at all, and `omh model-chains show` said only `Linked Hermes providers:
  custom (config)`, which reads as confirmation that the providers are being
  counted. Free-tier users reach OpenRouter and similar through exactly such a
  block, so the feature was dark for the population whose chains most need
  shaping. Detection now reads the block's `base_url` host, which it already
  parsed to decide whether the endpoint was a local model server: a host that
  is a vendor's documented API endpoint (`ENDPOINT_HOST_FAMILIES` — exact
  hosts, never a substring) carries that vendor's family, so a `custom` block
  pointed at `api.deepseek.com` reorders the chains like a `deepseek` provider.
  An id that already names a family is never overruled by its URL, and a
  private relay of the operator's own stays unresolved rather than being
  renamed after a vendor whose name happens to appear in its URL. For that
  remaining case — a gateway no host can identify — `omh model-chains show`
  says so and names the one way to record what it serves:
  `omh model-chains provider set <id> <kind>` / `clear <id>`. It is the only
  way, measured rather than assumed — a detected `providers.<id>` row arrives
  ticked at the kind detection gave it, re-entering the same id after the list
  is refused as already recorded, and a `--yes`, `--json`, or non-TTY
  `omh setup` asks no provider question at all. It writes the same
  `providers.json`
  through the same validation the interview now also routes through — one
  producer, `write_provider_entitlements` — refuses a kind outside the
  vocabulary by naming the accepted values, refuses to overwrite a record it
  cannot read, and is idempotent. The line is said only when every provider
  resolves to no family and no category actually came out reordered, so a
  machine holding `openrouter` (which does serve every family) and one whose
  routes shape a chain are both left alone; the `--json` payload carries the
  same fact as `unplaced_providers`.

- **`omh doctor` now says when the installed profile cannot reach the workflow
  engines, and names the command that fixes it.** `install_skill_pack` adds
  only what the recorded profile names and otherwise refreshes what is already
  on disk, and none of the nine canonical ULW engines is in
  `CORE_PROFILE_SKILLS` — so on a core install `ulw-work` is in neither set and
  no number of `omh update` runs will ever add it. That ADD/REFRESH rule is
  deliberate and unchanged; what was missing was the consequence, which nothing
  restated after `--core`'s help text stated it at the moment of choosing. A
  user who invoked an engine found nothing and had no way to learn why. The new
  `workflow_engine_reach` entry names the absent engines and the profile on
  record, and points at `omh update --full`. It lives in the read-only advisory
  lane rather than among the doctor checks because core is a legitimate,
  recommended profile — a fact with a consequence, not a health failure — so it
  cannot move the doctor status or exit code. It is derived from which engines
  are absent and never from the profile label, so an install that holds them
  stays silent whatever it recorded.

- **`doctor`'s staleness finding reports what it actually measured.** The
  `skill_freshness` check is a content comparison, and its message printed two
  package versions: on the preview channel, where catalog content moves without
  a version bump, that read `installed by omh 2.0.3, but this omh is 2.0.3` — a
  sentence contradicting itself while asserting a real problem, with nothing in
  it a reader could act on. It now reports catalog revisions, the identifier
  `guidance_projection` already names, so the two checks describe one condition
  in one vocabulary. A revision pair has the same failure mode, so it is
  printed only when there are two revisions to print: a manifest that records
  the current revision over files that do not match it is reported as that
  disagreement rather than as one digest quoted against itself.

- **A load-bearing comment in `guidance_projection` no longer states a false
  reason.** `_projection_state` measures completeness against the install
  manifest rather than the catalog, and justified that by asserting `omh setup`
  installs a core subset by default. The default is `full` and has been for
  some time. The measurement is still right — a user can be on core, and
  catalog-based completeness would then call that correct install missing — so
  the behaviour stands and the reason is now stated without naming a default at
  all. `GuidanceProjectionProfileTests` computes both halves instead.

- **A coding briefing now opens by saying whether it needs you.** The first
  line carries 🔴 / 🟡 / 🟢 — stopped, waiting on you, running — which is what
  a phone notification shows when it shows sixty characters and nothing else.
  The signal is computed from observed state (a standing blocker, then whether
  dispatch was ever observed), never from `next_action`: that token is free
  text from an open set of producers, and whether a reader has to get up must
  not depend on wording someone else chose. It also ships as `signal` in
  `coding_briefing/v1` so an adapter with its own chrome can ask the question
  without parsing a sentence. `headline` now consults the blockers too, so a
  cancelled run can no longer be headed "reported completion" beneath a red
  glyph — the contradiction the previous entry left open. The remaining
  internal tokens left the screen with it: the `Stopped:` / `Remaining:` /
  `Action:` labels are translated, runtime milestone ids are named in words,
  and `next_action` is rendered as what the reader should do
  (`surface_runtime_failure:ci` → "look at the failure on CI"). That last one
  is an open set, so unrecognized values render "check the current status"
  rather than the token — the failure mode being fixed is a token reaching a
  chat bubble, and doing it only for rare values would have made it harder to
  notice rather than rarer. Every identifier stays in the payload for anything
  that parses it. `tests/test_briefing_line_shape.py` sweeps eight run states
  across four locales for twenty-one known internal tokens.

- **The coding briefing stopped printing its own step ids at the reader.**
  `Still missing evidence: workspace_isolation, verification, review, ci` named
  five internal keys; a key is a stable identifier, not a word anyone outside
  this repository knows. Step and blocker names now come from
  `src/catalogs/briefing_vocabulary.py`, which answers in all seven locales
  either locale set can ask for, and `build_coding_briefing` takes a `locale`
  for the rendered lines only — ids, `next_action`, and every machine-readable
  value keep their one spelling so a parser never has to know the reader's
  language. The same module supplies the status board's copy, which had been an
  `if korean:` pair inside the renderer: five of the seven locales could not be
  rendered no matter what a caller passed, and `status_board_messenger_body`
  took no locale at all, hardcoding `korean=False` at each of its three call
  sites — so a messenger board was English regardless of configuration. Both
  now take a locale. The Korean truncation line also gains the unit total it
  alone omitted, which had left a reader to add two numbers to learn how much
  work there was. `tests/test_briefing_vocabulary.py` derives the required keys
  from `_progress_steps` and `_BLOCKER_KINDS` rather than from a list kept
  beside them, and fails on a row that answers fewer locales than a caller can
  ask for. The `Stopped:` and `Not reached yet:` labels themselves are still
  English; they belong with the line structure, not with the names.

- **A stopped coding run no longer reads as an early one.** The coding briefing
  listed everything that had not happened under a single `Still missing
  evidence:` heading, so a step the runtime had failed, blocked, or cancelled
  appeared as one more name beside steps nothing had reached yet — and a reader
  had no way to tell which. The distinction was not recoverable from the
  payload either: `_state` spells an unmet prerequisite `blocked`, and
  `_runtime_event_state` spells an observed runtime failure with the same word,
  while a cancelled milestone reached no briefing surface at all even though
  `build_runtime_observation` had tracked it separately all along.
  `coding_briefing/v1` now carries `blockers[]` beside `pending_gaps[]`, each
  entry naming the step, its kind (`failed`, `blocked`, or `cancelled`), and the
  runtime event behind it, read from the runtime observation rather than
  re-derived from a state word. The rendered lines lead with `Stopped:` and no
  longer repeat a stopped step under what is now `Not reached yet:`, and the
  narrative leads with the stop instead of with what the run is waiting on.
  `pending_gaps[]` keeps its meaning, its ordering, and its consumers; the
  headline still reports the executor's own result and does not yet consult
  `blockers[]`.

- **Fanout's write fence now works on Linux.** `omh coding fanout dispatch`
  confines the owner CLI and its verification commands with `sandbox-exec` on
  macOS, but the Linux `bwrap` path had never run, and on a real host (Fedora
  44, bubblewrap 0.11.0) it never could: its `--tmpfs /` root mounted only each
  executable's directory, so the dynamic loader was missing and even the
  preflight's `/usr/bin/true` failed with `execvp /usr/bin/true: No such file
  or directory`. Every Linux dispatch therefore ran unconfined, recorded as
  `sandbox_preflight_failed`, even with a trusted bwrap installed. The fanout
  layout is now the Linux counterpart of the macOS policy. The host tree is
  mounted read-only, so a write outside the worktree and the owner's state
  fails with `EROFS` instead of landing in a private tmpfs; `/dev` and `/proc`
  are fresh; toolchain `TMPDIR` points into the worktree's ignored
  `.omh/confinement-tmp`; the spawning environment is inherited rather than
  cleared, so per-command verification overrides reach the child; and
  `/run/user/<uid>` is replaced by an empty read-only mount, because from a
  read-only host tree `systemd-run --user touch <path>` otherwise asks the
  user's service manager to write outside the fence. The preflight and the
  probe run under that same layout. macOS keeps its probe policy unchanged and
  the cross-harness adapter lane keeps its strict layout. A Linux host with no
  trusted bwrap now reports `sandbox_backend_unavailable` instead of a failed
  preflight. The real-sandbox tests that ran only on macOS now also run on
  Linux hosts with a working trusted bwrap (and skip elsewhere, including CI),
  four backend-independent tests left the macOS-only class, and the
  `docs/FANOUT.md` note that dispatch provides no filesystem confinement is
  corrected. (#1356)

- **The plugin risk audit says what a declared hook would actually do.**
  `omh ops plugin-risk-audit` reported one aggregate `hermes_hook_capability`
  category decided by a regex holding three hook names, so a policy gate that
  can block a tool and a best-effort observer read identically, and a plugin
  declaring only `post_tool_call` was reported with no hook capability at all.
  The audit now reads a root `plugin.yaml` as structured data and classifies
  every hook it declares against one pinned Hermes contract revision: what the
  host does with the return (policy gate, prompt/context contributor, result
  transformer, lifecycle callback, observer), where the callback runs (bounded,
  caller thread, queued worker), and what a timeout does (fail closed, fail
  open, not applicable). `pre_tool_call` is the only hook whose timeout blocks
  the action; a `pre_verify` gate is bounded and fail-open, so a hung gate lets
  the turn finish -- the distinction the aggregate hid. Nothing is imported,
  registered, installed or executed, so hook registration, execution, timeout
  enforcement and failure handling are each reported `not_observed`, and a
  declaration is never evidence that a hook ran. A manifest the audit could not
  understand -- unreadable, malformed, outside the reader's bounded subset,
  requiring an unsupported host revision, naming a hook the contract does not
  contain, or absent entirely -- reports `undetermined_hook_contract` in the
  summary rather than a clean result. The mapping is a hand-transcribed snapshot
  of Hermes 0.21.1 and cannot detect upstream drift;
  `docs/PLUGIN-HOOK-CONTRACT.md` says so, and says what to do when a hook
  classifies `unknown`.
- **Loop is a native tool, and the CLI now speaks through the same
  service.** `omh_loop` registers one session-bound plugin tool over eight
  workflow-critical lifecycle actions -- `assess`, `start`, `status`,
  `feedback`, `permit`, `run_once`, `goal_driver_observe`, `queue_observe` --
  so Hermes manages one durable `loop_cycle/v2` without assembling shell
  arguments or parsing command output. Every action runs through a new typed
  operation service (`omh.workflows.loop_operations`) whose manifest is the
  only place the Loop action vocabulary exists, and all twenty-two `omh loop`
  subcommands are now adapters over that same service, keeping their flags,
  exit codes, and JSON keys. Tool mutations bind to the configured OMH home
  and the host session id, refuse a caller-named store, and refuse an
  existing-loop write that does not submit the `record_revision` a read
  reported; failures return a stable code from one closed vocabulary. Every
  result carries prepared-versus-observed state: a successful call records an
  OMH transition and never implies dispatch, implementation, review, CI,
  merge readiness, or merge. Operator surfaces (tick, sticky rules, queue
  dispatch and recovery, driver binding and migration, handoffs, narration)
  stay on the CLI, and the Loop skill now names the tool first and the CLI as
  the fallback. Existing installs need `omh update` before the tool appears.
- **Every provider surface says which providers count.** With linked
  providers reordering chains on their own, the surfaces that describe
  providers now tell that truth. `omh doctor` gains a `provider_entitlements`
  check, grouped with `hermes_model_routing` under a new `model_routing`
  group: it names every provider counted with where it was found, the
  `providers.json` and `model-providers.json` statuses, the ids the record
  excludes, and warns (without flipping the exit code) when `providers.json`
  is invalid — its recorded kinds are dropped and any providers it excluded
  count again — or when a route names a provider neither recorded nor
  linked: an alias a chain names sorts behind the served entries of every
  chain naming it, while a dispatch-only route reorders nothing but sends a
  dispatch that pins it to a provider Hermes is not linked to.
  `omh model-chains show` prints the same ignored-record consequence, the
  routes document status when it is invalid, and both kinds of unknown-
  provider route (`routes_path`, `routes_status`, `unserved_routes` in the
  JSON, schema unchanged). Non-interactive `omh setup` (`--yes`,
  `--json`, a non-TTY) reports the counted providers and the record's status
  as an additive `providers` field and a printed line. The CLI picker and
  `/omh-model` show one row when `providers.json` is invalid. The interview
  copy in all four languages no longer claims that skipping keeps the
  built-in order, and two docs pages say "recorded or linked" where they
  framed the record as the only route.
- **A document plan fans out one unit per range.** `omh coding fanout
  prepare --from-document-plan <plan.json>` derives a fanout unit from every
  range of a `document_chunk_plan/v1` file: the unit's title is the plan's
  per-range brief, its file scope is that range's report file, and its new
  optional `input_budget` carries the plan's per-range character budget, a
  token estimate, and the range's `read_file` window as a source range. The
  budget is validated at freeze (bounded, typed, tokens consistent with
  chars, source estimates within the ceiling), rides the frozen unit only
  when declared, and the executor prompt states the ceiling and the ranges
  after the unit's boundary lines. A plan without ranges is refused with
  exit 2 and nothing is frozen; dispatch itself is unchanged and still
  opt-in.
- **Long documents get a chunk plan before they are read.** A new
  `omh_document_plan` plugin tool splits a document larger than one
  `read_file` window into numbered ranges from the numbers Hermes states
  after its first read (page count, `total_lines`, extracted length, an
  outline of section anchors): each range carries a page or character span,
  the sections it covers, an estimated character and token size, the
  `read_file` offset/limit window that reaches it, and a digest, and the
  plan is written to `$OMH_HOME/documents/<plan_id>/plan.json` with a
  covered / next / missing ledger that `mark` advances and `show` re-reads
  after conversation compression. Ranges snap to the outline and to the
  100k-character budget Hermes reads per call, and a plan of more than four
  ranges carries a `delegate_task` brief per range so the reading can fan
  out one child per range. OMH never opens the document: a local file
  contributes only its size and sha256, every count is labelled
  `caller_supplied`, and a covered mark is the caller's statement, not
  observed coverage. The paper-learning skill points to the tool when the
  paper exceeds one window.
- **Paper reading progress survives the session.** The `paper-learning` skill
  promised a `paper_learning_card/v1` under `.omh/paper-learning` "when a
  wrapper or CLI records it", and no command wrote there, so a long paper
  restarted from the abstract every session. `omh paper` is that command:
  `plan` records the card (a local source file is hashed for identity, never
  parsed), `progress <paper_id>` records one explained chunk as covered /
  next / missing plus a short note, `list` and `show` print where reading
  stopped so a resumed session continues from the recorded next section, and
  `validate` checks every card, ledger, and the index cache. The store is
  `$OMH_HOME/paper-learning/<paper_id>/card.json` plus an append-only
  `ledger.jsonl`; page counts, PDF extraction, and explanation correctness
  stay not observed until a host records them.
- **An unresolved memory decays to open, not to a verdict.** A record whose
  outcome is undecided used to be delivered like a settled fact until its
  review deadline, then go `stale` and leave recall — read as decided, then
  forgotten. `omh memory capture --unresolved` / `omh memory approve <id>
  --unresolved` now set `staleness.resolution: open`. Past its review
  deadline an open record is delivered as `open · N days unresolved`
  (pack items carry `resolution` and `resolution_marker`, each pack one
  `unresolved_delivered` count, the provider's record line the same marker)
  instead of being held back; expiry, a changed source, and an unreadable
  source still outrank it, and a non-open record keeps today's verdict byte
  for byte. Only `confirm` or `correct` writes `resolved`, `retire` ends it,
  and nothing else clears it — no timeout, no reminder, no batch confirm. An
  open record always carries a review deadline (durable records and episodes
  included), and `confirm` resolves an open record even when it has none.
  `open_max_days` (default 365, policy tunable) bounds every non-durable open
  record as `expired/unresolved_expired`, and `omh memory retire` names that
  reason so a question that died unanswered reads differently from a fact
  that aged out. The provider asks: one `omh reminder: "<summary>" (<id>)
  has been unresolved for N days — resolved, still open, or drop it?` line
  per pack once the deadline passes, then at most every `open_ask_days`
  (default 14); `omh memory keep-open <id>` is the "still open" answer that
  resets the clock and touches nothing else, `omh memory retire <id>` the
  "drop it" answer. The ask is recorded only when the pack is actually
  served and disclosed in the prefetch receipt (`reminder`) and
  `latest_open_reminder()`. `omh memory status` gains `counts.unresolved`
  and a bounded oldest-first `open_records` list; `omh doctor` warns about
  open records older than half the ceiling. Issue #1528.
- **DeepSeek V4.1 Flash override measured and revised.** On the first day a
  served route existed (`og` added `deepseek/deepseek-flash`), the
  `deepseek-v4.1-flash` high-effort override ran the #1463 five-arm pair on
  `benchmarks/live-model-tools/v1`: pass rate tied within noise, but the
  original wording cost 25% more tokens than the inherited `deepseek` block
  (+21,663 per instance, CI95 [+6,550, +42,944]), re-running checks on tasks
  the model was not going to pass. The two phrases that asked the reply to
  carry "the verification output" and the blocker report "the observed
  output" are gone and the family block's "verify once, and stop" is back;
  the revised block measures at the family block's cost with the fewest tool
  calls and API turns of any arm. Numbers in `MODEL_OPTI.md` and the
  benchmark README; records archived outside git. Closes #1463.
- **The bundled plugin declares its Hermes runtime range.** OMH admits
  Hermes `>=0.21.1,<0.22.0` before plugin registration and rejects unsupported
  hosts with the required and running versions. Missing or invalid declarations
  fail local conformance; release readiness also checks the tested-host matrix.
  Existing installs should run `omh update` to refresh the managed bundle.
- **A very large PDF is read in page ranges, not truncated.** The new
  `long-document-reading` skill owns "summarize this 300-page contract",
  "read this manual", and the bare "summarize this document" (which used to
  land in file packaging): it probes the page count and scanned flags with
  Hermes' built-in `pdf` scripts, plans page ranges sized to the `read_file`
  budget (about 60 pages per 100,000-character call), extracts each range
  with page selection so every claim keeps a page anchor, delegates ranges
  to `delegate_task` children above four, and closes each range with
  covered / next / missing so a compacted or resumed session continues from
  the ledger. `long_document_card/v1` is the metadata contract; page count,
  extraction, scanned-page OCR, and delegation stay unobserved until a tool
  result records them. Papers stay with `paper-learning`, produced files
  with `materials-package`. `docs/LONG-DOCUMENT-READING.md` answers "how do I
  process a very large PDF with Hermes?" in terms of Hermes' measured limits.
- **A document handed to a coding owner is gated like an image.** A PDF or
  office file now reaches the coding-lane media handoff as a declared
  `raw_media:document` (or `local_file_reference:document`) input: files
  attached to an `--event-json` message are declared from their name and
  media type (Discord `attachments`, Slack `files`, Telegram
  `message.document`; bytes, URLs, and names never enter the payload),
  `omh coding delegate --input-representation` declares one explicitly, and
  `omh chat interact` derives the same declaration from its event. The
  decision matches `input_modality_document` route evidence exactly the way
  `input_modality_image` is matched — fresh, `host_observed`, same provider,
  wire model, and endpoint mode — and image evidence never stands in for it.
  Every fail-closed verdict now carries a modality-specific
  `remaining_user_action` and an `alternative_representations` list: for a
  document, `extracted_text` (text Hermes already read out of the file, for
  example with `read_file`) or `ocr_output` with an observed OCR
  transformation; for an image, `ocr_output`; for audio or video,
  `transcript`. Fanout dispatch refusals state that action beside the reason.
  `--transformation-json` supplies the observed-transformation record an
  `ocr_output` or `transcript` handoff needs. The demo decision set gains the
  document path, and the action names no coding owner. Three gaps found in
  review are closed in the same change: the route the evidence is scoped to
  is now real (`omh coding delegate` binds the same resolved Hermes model
  recommendation the chat lane binds, and a recommendation that names no
  endpoint mode binds `default` instead of no route at all), a handoff with
  no resolved provider and wire model reports `route_unresolved` rather than
  asking for evidence of an empty route, a fanout unit any capability gate
  refuses carries `failure_kind: capability_gate` so a batch refused
  entirely exits non-zero (with a `record_capability_evidence_then_redispatch`
  row in the cause-specific recovery table), and every attachment on a
  message is classified, so a PDF listed after any number of text files is
  still declared.
- **Providers linked to Hermes are recognized on their own.** OMH now reads
  which providers Hermes is already linked to — a `hermes auth` login in
  `auth.json` (the pool rows Hermes itself counts, never a credential
  borrowed from another CLI), a `providers:` entry or `model.provider` in
  `config.yaml` (a loopback endpoint left out), an API-key variable name in
  `$HERMES_HOME/.env` — and counts them the way a recorded `providers.json`
  answer counts: chains reorder so served entries lead, `omh model-chains
  show`, the CLI picker, and `/omh-model` list the providers counted with
  where each was found, and `omh_delegate_route` refuses the same
  known-wrong pins. Only ids and variable names are read, never a key or a
  token, and nothing is invoked. The `omh setup` interview offers the same
  rows pre-ticked (a login row says so), its recorded kinds win for an id
  both name, and a linked row you untick is written as `excluded_providers`
  and stops counting; the record is no longer the only way a machine's
  providers reach routing.
- **Model chains get a picker.** Bare `omh model-chains` (alias `omh model`)
  on a terminal opens an arrow-key editor: one row per mixture category with
  its head model, effort bar, origin and whether this machine's providers
  serve it; left/right step the head model through the aliases chains name
  today, `-`/`+` step its effort, `d` restores the shipped default, Enter
  writes through the same validated document `omh model-chains set` writes
  and `q` writes nothing. Off a terminal the bare form prints `show`. The
  chain rules live in the plugin bundle so the Modern-TUI widget can walk the
  same rows.
- **`/omh-model` in the Modern TUI.** The OMH widget registers the same
  picker as a modal app: `/omh-model` opens it over the transcript with the
  keys the CLI picker uses, reads and saves through the installed plugin
  bundle, and shows the written path on save. Hermes' own `/model` keeps its
  name and its job (the session model); the two edit different things. A host
  whose widget SDK lacks the overlay primitives keeps the docks and the CLI
  picker.
- **The HUD says when another model answered.** A delegation child's row now
  carries a `model_attestation` verdict comparing the model the run was routed
  to against the model Hermes recorded as having answered it
  (`session_model_usage.model`, written per call). Nothing compared the two
  before: the row reader preferred the recorded route and never read the
  answering model, which hid a substitution in exactly the case one happened.
  Both sides resolve through the alias table the mixture-category label
  already uses, so a vendor pointer answered by its exact contract id, a base
  answered by a dated snapshot of itself, or two speed tiers of one model read
  as agreement rather than a false alarm — and a newly declared pointer alias
  moves the verdict with no second table to update. `unknown` is a first-class
  verdict: a child that switched models mid-run, one with no usage row, and
  one nothing recorded a request for each say so with the reason, never a
  silent agreement. The payload states the limit it covers — delegation
  children only, since a main session is named by `sessions.model` alone with
  no per-call answering model to attest against.
- **Rehearse an unattended batch against your rules before it starts.**
  `omh ops permission-rehearse --plan <file>` runs the `(tool, args)` pairs a
  cron entry or unattended run intends to issue through the same matcher the
  enforcing `pre_tool_call` hook uses, and returns a per-call table: `refused`
  names the rule that would block the call, and everything else is `unknown`
  with the reason. The third tier is deliberately not claimed — "needs
  approval" lives in Hermes' per-tool approval declarations, which OMH has no
  reader for — so the summary counts `planned`, `refused`, and `unknown` and
  has no allowed bucket an unknown could be folded into. The payload carries
  the observed approval-bypass state alongside, because a rehearsal run under
  an active bypass describes a policy nobody is currently applying, and it
  reports when the rules file is present but defective, because "nothing
  refused" from a policy the hook never loaded is not a green light. The
  rehearsal executes nothing and writes nothing; exit `1` means a planned call
  is refused, `3` that the rules file is defective, and `0` only that no rule
  refuses these calls — never that they are allowed.
- **A configured profile can move to another machine.** `omh setup-profile
  export` serializes this install's `setup_profile/v1` -- coding owner,
  operating model, memory mode, selected categories -- plus the capability
  policy, the recorded MCP host recipe and the Hermes model aliases into one
  local JSON pack with a content-addressed manifest, and `omh setup-profile
  apply --from <pack.json> --apply` writes it back through `omh setup`'s own
  writers. Redaction reuses the `RAW_OR_HIDDEN_KEYS` and `metadata_safety`
  primitives every record store already screens against: a credential-shaped
  value or a machine-local path never enters the artifact, and every field
  withheld is named with its reason rather than dropped in silence. Apply is
  a dry run until `--apply`, reports each field as applied or not applied
  with the reason, refuses a pack from a newer OMH whole rather than writing
  a partial profile, and hands back the exact `omh setup` commands for the
  two surfaces it will not write unasked -- Hermes model aliases, which need
  their own digest-bound confirmation, and the MCP host config, which is
  written only under `--with-mcp`. Transport stays out: export writes a local
  file, apply reads a local file, and moving one between machines is your own
  git or file copy.
- **A wrong memory source now has a blast radius.** `omh memory sources`
  indexes reviewed records by the source recorded on them, and `--source
  <label>` returns that source's records so they can be piped into the
  primitives that already shipped -- `lineage`, `retire`, `prune`, `correct`,
  `recall-suite` -- every one of which takes a record id the operator
  previously had no way to produce. Two record fields are source axes and one
  record can carry both (`source`, the admission channel, and `source_ref`,
  the document the memory was taken from), so a record admitted from two
  sources is indexed under both and reports both under `matched_axes` rather
  than only the first. The report is a read: it quarantines, retires and
  deletes nothing. A record that recorded no source is listed as
  `indeterminate`, never assumed clean, alongside any record file that would
  not parse, and an empty selection names which of the three empties it is
  (`empty_store`, `source_never_recorded`, `no_records_for_source`) because
  they are three different answers. `memory-sync` gains one pointer to a new
  `references/source-recovery.md` carrying the quarantine-first sequence and
  the rule that completion evidence is a recall report over this store showing
  the records absent -- never the retire command's exit code, and never
  `recall-suite`, which seeds its own fixture corpus in a temporary store.
- **The evaluation lane scores the path, checks the corpus, and qualifies the
  judge.** Three gaps let a number out of this lane with nothing behind it.
  `agent-evaluation` scored quality, correctness, time, cost, tool coverage,
  verification and review gaps separately but never the order the run took, so
  a run that reached the right answer by skipping verification scored the same
  as one that did not; it now carries a trajectory dimension scored beside the
  outcome and never folded into one total, asking whether the run searched
  before it asserted, took approval before an irreversible side effect, used an
  available tool instead of guessing, and verified before claiming done.
  `llm-app-dev`'s `references/eval-harness.md` specified the golden-set shape
  but not its hygiene, so a leaking corpus produced a quotable score; it gains
  a corpus-hygiene section covering answer leakage, duplicates and
  near-duplicates, fixtures mutated until a case passes, a holdout contaminated
  by the tuning that chose the threshold, and per-case provenance, with the
  rule that the corpus state is reported above the score and an unchecked set
  is labelled unchecked. The catalog ranked judges below executable checks but
  never said how to qualify one you have no choice but to use, so
  `agent-evaluation`'s `references/self-evaluation-loops.md` gains the
  qualification procedure -- a hand-labeled sample, a blind judge pass with the
  grader model ID pinned, agreement measured against the human labels with a
  chance-corrected statistic beside raw agreement, and every disagreement read
  -- plus the table saying what each agreement band licenses. A judge with no
  measured agreement is unqualified, and that verdict is a safety rule in the
  always-loaded body rather than a reference note, because a judge is used
  while comparing executors and the existing reference pointer fires only for
  self-evaluation.
- **Three reported misroutes reach the skill that owns the question.** A
  filling context window ("context window is almost full, save decisions and
  hand off to a new session") returned the project-terminology workflow at high
  confidence because the message opens with the word `context`, which is that
  workflow's whole name; `context-budget-review`, which owns the must-keep
  pack, the summarization checkpoint plan and the overflow recovery route, did
  not place. The budget sense of `context` -- `window`, `limit`, `compaction`,
  `overflow` alongside the `budget` already carved out -- now stops that word
  carrying explicit-invocation weight, and the lane gains the overflow
  phrasings it had no trigger for. A Korean continuous watch ("계속 감시해줘")
  reached nothing, and so did its English form ("keep watching this", "keep
  monitoring the build"): every phrasing `automation-blueprint` recognised
  named a cadence or the word automation itself, so the intent was missing in
  every language rather than only in Korean, and the English base corpus, the
  `ko.json` pack, and new `ja.json`/`zh.json` entries all ship together. And a
  memory-provider comparison ("compare memory providers on my own data for
  retrieval quality and latency") reached the operations telemetry card,
  because it reads as telemetry word for word, while the skill that declares
  `memory_provider_posture/v1` -- and that `memory-sync` explicitly defers
  provider questions to -- did not place at all; the noun phrase now reaches
  `external-connector-readiness`, its declared owner. Every generic word these
  triggers are built from (`window`, `hand`, `off`, `keep`, `watch`, `monitor`
  and the rest) is held back from its skill's trigger tokens and pinned by a
  negative control in the sense it does not mean, so an ordinary sentence
  routes exactly as it did before.
- **An application threat-model request no longer gets the agent's threat
  surface.** `security-safety-review` emits `threat_surface_map/v1` over the
  AGENT's own prompts, tools, files, dependencies and credentials, so asking
  Hermes to "build a threat model for our payment service architecture" did not
  merely miss -- it would have answered confidently with the wrong artifact
  under a near-identical name. That phrasing returned `deep-interview`,
  `build-failure-triage` and `model-setup`; it now opens the new
  `application-threat-model` workflow, and an agent-surface phrasing still
  opens `security-safety-review`, both pinned in the routing corpora. The
  workflow models a real system: an asset register with a data class and one
  named loss each, trust boundaries stating what crosses and what authenticates
  the crossing, attack scenarios derived per boundary, one decision per scenario
  from a closed vocabulary (mitigate, transfer, accept, eliminate) with an
  owner, and a security test per mitigating control naming the observable that
  fails when the control is removed. Its artifact is `application_threat_model/v1`
  -- it shares no word of structure with `threat_surface_map/v1`, names the
  application as its subject, and is never a surface map. A control is
  `unverified` until observed configuration or a passing test says otherwise,
  the workflow never writes exploit code, and the model is not a scan, a
  penetration test, or a compliance attestation. The six STRIDE prompts, the
  asset/loss table and the per-control test shapes live in
  `references/threat-model-method.md`, measured outside the always-loaded body
  budget.
- **A reviewed skill draft can be installed, through the promotion lifecycle
  that already shipped.** `omh learning skill-draft` produced a draft a person
  could approve and then do nothing with: the boundary said an approved draft
  is "a proposal a person or Hermes Agent `/learn` acts on - never an install".
  One lane over, `omh web-qa promotion` already did exact-byte diff review,
  reviewer-bound approval receipts, a single visibility commit, retained
  generations, rollback, removal and crash-safe retry -- and reached exactly one
  kind of source, because every entry point took a browser `trace_id`. The
  parameter is now a promotion source id and the same seven subcommands are
  mounted a second time as `omh learning promotion ... --source-id sd-<id>`,
  calling the same functions: nothing about the lifecycle was reimplemented, and
  a browser-derived promotion still renders byte-identically, which is why the
  `browser_*` schema names and the receipt's `trace_*` field names were kept
  rather than widened. A draft installs only after `skill-draft review
  --decision approve`, only from this project's own draft store, and only past a
  pattern risk scan of its instruction text that reuses the `plugin-risk-audit`
  detectors and refuses naming the category it matched. A review later changed
  to `revise` or `reject` deactivates the entry it approved on the next
  `status`. `skill_pattern_risk_review/v1`, whose own docstring said its only
  caller was its test file, is now reachable as `omh ops
  skill-pattern-risk-review`; it cites the scan and decides nothing, because a
  clean scan is not an approval. A promotion status meaning the entry is not
  live -- `stale`, `quarantined`, `unverified_managed_state` -- no longer exits
  `0`.

- **Two more pinned fixtures say their own order out loud.** Every committed
  fixture was read against the assertion that consumes it, asking what the
  parse discards. Two maintain an order no assertion could fail:
  `routing_precision_subset_at_c.json` keeps 237 pinned case ids sorted while
  both consumers turn the list into a set, and `ulw_alias_baseline.json` keeps
  84 cue keys sorted while the baseline is compared as a dict -- in each case a
  re-derive in producer order rewrites the whole file, buries the row that
  moved, and passes CI. Both orders are now asserted, and the second also
  pins the `sorted()` inside `ulw_alias_corpus()` that supplies it, since
  removing it makes the cue order hash-dependent without failing anything.
  The rest of the sweep is recorded as not depending on a maintained property:
  hand-authored inputs no producer rewrites, frozen historical captures,
  single-line compact files no diff can bury a change in, and artifacts already
  held byte-exact by an existing gate. (#1615)
- **An incident that is still open now has an owner.** The catalog held every
  piece of live incident work and no skill that ran one: severity and the
  customer reply in `support-operations`, health signals and the rollback gate
  in `deploy-and-monitor`, retrospective synthesis in `reliability-review`,
  readiness in `production-audit`. `support-operations` explicitly routed an
  active incident to `reliability-review`, whose own `use_when` is "review
  incident notes, SLOs, error budgets" -- so the one skill that saw the request
  handed a running outage to a postmortem. Measured on the deciding surface
  (`build_chat_interaction_payload`), "we have a production outage right now,
  declare severity and assign an incident commander" was a clarification with
  no owner, and "the checkout service is down right now, start the incident
  timeline" dispatched to `reliability-review`. The new
  `live-incident-response` workflow owns the open incident end to end: severity
  declared as live state with the observation that set it, a named commander
  plus operations, communications, and scribe, an append-only timeline where a
  correction appends an entry naming the one it corrects and never rewrites it,
  every mitigation marked temporary or permanent with what removes it, recovery
  verified against a named signal at its healthy value rather than inferred
  from a mitigation being applied, and the customer notice drafted. Paging,
  status-page updates, and customer sends are effects OMH cannot perform: they
  route to `connector-operator` and are recorded observed only when the
  connector returns a result, with prepared and observed kept as separate
  states in the record. The boundary closes in every direction rather than one
  -- `reliability-review` and `deploy-and-monitor` each gain their first
  `do_not_use_when` statement pointing back at the live lane, and
  `support-operations`'s single active-incident statement splits so the live
  half reaches the live lane and only the retrospective half stays with the
  review. The method detail (the severity ladder, the four roles, the three
  timeline entry types and their fields, the communication ledger, handover and
  closing) is `skills/omh-live-incident-response/references/incident-command-method.md`,
  measured outside the always-loaded body budget. Seven negative controls pin
  the other senses of "incident", "commander", "severity", "outage",
  "production" and "war room", and eight interventions pin the live phrasings
  plus the three siblings keeping their own requests. (#1563)

- **Sensitive work can be kept off models whose data policy nobody has read.**
  Nothing recorded how a model's provider handles the data sent to it, so the
  only exclusion available was `excluded_providers` at provider granularity and
  a per-machine reorder of `model-chains.json` — neither grounded in a policy.
  `MODEL_CONTRACTS` now carries a `data_handling` axis with two closed
  vocabularies (`training_use`, `retention`) plus the account scope that keeps
  it out of account-level claims, exactly as `rollout` already does: the value
  is the vendor's documented default for the surface the contract was read
  from, and tier, region, and a negotiated agreement move it in both
  directions. `omh model-chains show --sensitive` declares the work sensitive
  as a field — never inferred from message text, which
  `src/quality/safety_preflight.py` forbids outright — and drops every model
  whose contract does not document a permitting default, naming each exclusion
  with its own reason: the policy conflicts, the axis is undeclared, the policy
  was never read, or no contract resolves at all. A model of unknown policy is
  excluded and named, never silently kept and never silently omitted; the
  command exits 1 when a category is left with nothing to route to. Both
  shipped contracts declare the axis as `not_recorded`, because neither
  vendor's data-usage page is among their sources and inventing a value there
  would be the claim this axis exists to stop — so every shipped chain empties
  today, which is the honest state and is now visible rather than assumed. The
  coverage audit reports the axis as its own dimension, derived from the same
  verdict the gate acts on so the two cannot disagree. (#1560)

- **`doctor` now proves the plugin enforces, not only that it registered.**
  The checklist already refused to collapse install, import/register smoke, and
  Hermes runtime load into one claim, but nothing asked the installed bundle to
  decide anything: a plugin that loads, registers every tool and hook, and
  returns `None` for every tool call passed all three tiers. A fourth tier,
  `plugin_enforcement_smoke`, calls the installed bundle's own
  `toolcall_rule_directive` in-process against a temporary rules home and
  reports the decision it got back. Two probes, because one cannot tell
  enforcement from a stuck answer: a scoped probe the rule names must come back
  blocked, an unscoped one must proceed. A bundle that decides neither, or
  blocks both, fails this tier while the import and register tiers keep
  passing, and the report says so in those words. A bundle whose seam cannot be
  reached at all reports `unknown` and still does not pass. The probe is
  harmless by construction rather than by choice of a realistic command: both
  tool names are fabricated, appear in no host and in `PROVIDED_TOOLS`, the
  arguments carry one marker and no path, command, or content, the rule is
  `repeat: always` so no once-per-session claim is consumed, and the rules file
  lives in a temporary directory that is the probe's entire OMH home. (#1561)

- **Two profiles can be checked for isolation instead of discovered to leak.**
  `CONTEXT.md` states "Exactly one home is active per invocation" as an
  invariant and nothing verified it, so a leak between two profiles surfaced as
  behaviour rather than as a finding. `omh doctor --profile-isolation
  '<omh-home>[,<hermes-home>]' '<omh-home>[,<hermes-home>]'` compares two
  profile references across config, cache, plugin state, files, and env, one
  verdict per surface over named artifacts rather than a tree diff. It reports
  a shared path as leaked and names the path, catches the two shapes a string
  comparison misses — two homes symlinked to one target, and one home nested
  inside the other — and reports `unknown`, never `isolated`, for a surface it
  could not inspect, which is what a profile reference with no Hermes home
  produces. The env surface names the ambient `OMH_HOME` or `HERMES_HOME` that
  pins one of the two profiles for every invocation that forgets a flag. Exit 1
  on a leak, 3 when nothing leaked but a surface was not inspected, 0 only when
  every surface was inspected and none leaked. The ordinary `omh doctor` run is
  unchanged: the sub-check fires only for the operators who pass the flag.
  (#1562)
- **A crashed paired-run cell now records what raised it.** `_execute_cell`
  contains an exception so one cell's failure cannot take the matrix down, and
  the containment is correct -- but it discarded the reason. A
  `ReceiptVerificationError` naming a short integrity key reached the caller as
  an opaque CRASHED cell, and the fan-in blocker then described the shape of
  the result (`crashed execution state`) rather than the cause. On #1592 that
  cost a full diagnosis cycle: the first hypothesis drawn from the surviving
  evidence was coherent and wrong. The `except` clauses are unchanged; what
  they record is wider. Every contained failure -- workspace, runner, unexpected
  runner error, and cleanup -- now carries a `PairedRunCrashReason` on the
  outcome, and the fan-in blocker reads `crashed execution state:
  ReceiptVerificationError: Hermes child observation integrity key is invalid`.
  A runner that already crashed owns the cause, so a later cleanup failure does
  not overwrite it. The record reaches a metadata artifact, so it carries a
  bounded exception type and a message that is path-redacted, control-stripped,
  capped at 200 characters, and withheld whole when it matches a secret marker;
  `withheld` and `empty` stay distinct states so a reader can tell a screened
  message from an exception that carried none. (#1619)

- **The ja/zh confidence tier is now a recorded decision, not an unpinned
  artifact.** A Japanese or Chinese trigger phrase reaches its skill one tier
  below the English equivalent: a CJK sentence is one routing token, so a pack
  phrase inside a longer sentence earns the phrase credit but not the token
  credit an exact-message match adds, and lands at clarify-with-candidate where
  English dispatches. Measured over every shipped pack rather than the two
  phrases the report named: 84 of 91 ja phrases and 81 of 88 zh phrases
  dispatch at high when sent bare and clarify at medium once a sentence
  surrounds them, while ko -- space-segmented and NFKD-folded -- barely moves,
  895 of 962 bare against 899 wrapped. `RoutingInterventionCase` gains
  `expected_confidence`, so a case pinned at `clarify` can state which tier it
  reached instead of passing at any tier below dispatch, and four cases record
  the gap: a ja and a zh phrase inside a sentence at clarify/medium with the
  skill still named, and one zh phrase pinned bare at dispatch/high beside the
  same phrase inside a question at clarify/medium. The scoring half is
  deliberately not taken here: lifting CJK credit would move roughly 165 pack
  phrases in one change, and it now has cases to move deliberately. (#1607)

- **The judge agreement bands now say they are unverified here.**
  `agent-evaluation`'s `references/self-evaluation-loops.md` tells a reader
  where an LLM judge's usable thresholds sit -- unmeasured is unqualified,
  below 0.4 unusable, 0.4 to 0.6 relative comparison only, above 0.6 absolute
  scoring. Those bands are the conventional reading of a chance-corrected
  agreement statistic and were measured on no judge this repository uses, so a
  reader who applied the section's own rule correctly still read their figure
  against a table nobody checked. Measuring them here needs a judge already
  used in an OMH evaluation lane and a hand-labeled sample from its own
  distribution, and neither exists: OMH's evaluation lanes score with
  deterministic predicates against frozen corpora, there is no grader model,
  and there is no human-labeled sample. So the table now states its own
  provenance rather than carrying an invented measurement or losing the
  guidance: the bands are the starting default, the first row is a rule rather
  than a calibration and holds whatever a measurement shows, and a sample too
  small to separate 0.4 from 0.6 is itself the reportable result. The
  measurement remains open. (#1612)
- Clamped the TUI plan dock to the terminal it renders in. The panel capped
  items at eight but nothing capped rows, and each distinct phase adds a
  header of its own, so eight items could be twenty rows above the composer at
  any terminal height. On a 24-row terminal that left three lines of
  transcript and pushed the session banner off entirely. The dock-top render
  now reads the `rows` the host already passes it (the same RenderCtx both
  docks get, `stdout.rows`) and takes at most a third of it, the split shared
  with the transcript and with the bottom dock plus composer. The window
  shrinks outward from the active item, an item and the phase header it
  introduces leave together, and whatever leaves is counted on the existing
  earlier/later fold lines. A terminal too short even for that gets the
  header-and-rule summary the panel already had rather than a truncated
  checklist. From 60 rows up the budget covers the tallest frame the renderer
  can produce, so a roomy terminal is unchanged. (#1727)

- **A refused re-read of a TRUNCATED file now names the offset instead of
  claiming the model already has the content.** Measured in session
  20260919_140745_db409e: a model that needed line 2318 of a 9,172-line file
  called `read_file(path)` with no `offset`. The read returned lines 1-1666
  with `truncated: true` and `next_offset: 1667`, and the model kept calling
  it with the same arguments. After three full results the host answered
  twice with a `status: unchanged` stub and then with 117 distinct `BLOCKED`
  refusals saying "the content from your earlier read_file result in this
  conversation is still current. Proceed with your task using the information
  you already have." For a truncated read that is false in the way that
  matters: line 2318 was in no result. Neither the stub nor the refusal
  mentions `offset`, and the one place it appeared was the `hint` field of
  the successful read, which the model had already ignored three times.

  A fifth pass in the composed `transform_tool_result` seam records what a
  truncated `read_file` returned, keyed on the session, the path, and the
  window the read started from, all taken from the call's own arguments. A
  later refusal or stub whose own call asked for that same window gains one
  bounded note: that read returned lines 1 to 1666 of 9,172 and stopped there,
  lines past the stop were not in that result, and another region needs
  `offset`. Every decision reads a structured field and never the refusal's
  wording -- `truncated`, `next_offset` and `total_lines` on the way in,
  `already_read`, `status == "unchanged"` and `guardrail_refusal` on the way
  out -- so a host that rewrites the sentence keeps working, and a host too old
  to send `guardrail_refusal` (the measured one) is recognised by the other
  two. The window start is half the key rather than payload: a truncated read
  from `offset=5000` says nothing about lines 1-4999, so keying on the path
  alone would have annotated a first-window refusal with a mid-file read's
  numbers. That key is also the whole gate, replacing a literal "the offset is
  1" test with the fact it stood in for, and a model looping on any other
  offset now gets the same note with its own numbers. The window start itself
  is derived through the host's own `max(1, int(offset))` clamp, so it
  describes the read that happened. The map is bounded at 64 sessions and 16
  windows each, evicting oldest first.

  Neither half of the defect is OMH's. The model ignored an explicit
  `Use offset=1667 to continue` three times, and the host wrote the refusal;
  OMH has the one seam that sees both. What this does not claim: that any
  model follows the note. That needs a live run, and none was done. The note
  is prepared instruction, never evidence that a region was read. (#1723)

- **The menu bar helper stops spawning a Python CLI every 8 seconds to learn
  that nothing changed.** The macOS helper ran `omh menubar status
  --observe-local-processes --json` on a flat 8 s timer under launchd, about
  10,800 times a day, whether or not a session existed. One reading measures
  0.69 s wall and 0.53 s user; profiled, that is about 0.46 s of interpreter
  start plus importing the CLI, 0.24 s of the `ps` scan, and 4 ms for every
  file the payload reads put together. It was the largest steady-state cost
  on the owner machine.

  The helper now backs off while the menu is not changing. Each consecutive
  reading that renders the same menu doubles the gap -- 8 s, 16 s, 32 s, then
  a 60 s ceiling -- and any change drops straight back to the active
  interval. `--interval` still means the active cadence, and the ceiling
  never polls faster than an operator who asked for something slower.
  Measured side by side against the old helper for 25 minutes with nothing
  changing: 190 readings became 27, or 456 an hour to 65. A machine whose
  Hermes agent count actually moves restarts the ladder each time and lands
  nearer 4x, which is the intended behaviour rather than a shortfall.

  What it compares is the rendered `display`, not the payload. Comparing
  payloads was the obvious design and does not work: `hermes_processes`
  stamps `observed_at` and the process overlay recomputes `age_seconds` on
  every reading, so two readings of an untouched machine are never equal and
  the ladder would have sat on rung 0 forever.

  The ceiling would otherwise cost lateness, so the payload now names its own
  `watch_paths` and the helper stats them on a 2 s tick, spawning nothing
  unless one moved. Those paths come from the module that opens them rather
  than a list kept by hand, and they include the write-ahead log: Hermes runs
  `state.db` in WAL mode, so a session write lands in the sidecar and leaves
  the database's own mtime untouched until a checkpoint -- on the owner
  machine the two stamps were four minutes apart. What the ceiling does still
  cost is a change only the `ps` scan can see, such as a Hermes process that
  has not touched its session store: that waits for the next scheduled
  reading.

  That wake is floored at the active interval, and the floor is not a detail.
  Hermes writes its session store every few seconds while a session is live,
  so waking on any moved stamp reads far more often than the rung allows.
  Measured over 15 minutes against a home with one live session writing once
  a second: unfloored 169 readings, the flat 8 s timer it replaces 102,
  floored 93. Without the floor this change would have cost two thirds more
  than the timer it removes, precisely when the machine is busiest. A
  reading woken by a moved file also restarts the ladder at the active rung,
  so it cannot climb through a live session.

  A failed reading steps the ladder too. A machine where `omh` cannot be run
  was spawning the failure 450 times an hour; the attention mark still
  arrives on the third consecutive failure. (#1726)
- **The repeat guard can see a cycle, and can tell a loop from a poll.** It
  counted CONSECUTIVE identical calls, so an A,B,A,B alternation reset the
  streak on every call and the guard sat armed and silent through the whole
  failure -- which is the loop the reporting session actually burned its turn
  on, two `terminal` commands alternating to the end. And it compared
  arguments only, so a status poll and a stuck loop looked the same from
  outside, which is why its ladder had to leave room for the poll and its
  message had to hedge about the result.

  Both are one defect, and the fix is one mechanism. A bounded per-session
  history of recent calls replaces the single counter, and a repeating cycle
  of period 1 to 4 replaces the streak -- period 1 IS the streak, so there is
  one detector, not a second one bolted beside it. The periods are the host's
  own (`agent/tool_guardrails.py`), matched deliberately: two detectors that
  disagreed about what a cycle is would refuse different sequences and a
  person comparing the two notes could not tell which was wrong.

  A call now counts toward the ladder only when its ARGUMENTS and its RESULT
  both repeat. `post_tool_call` digests the result under the same privacy
  rule as the arguments -- a length and a bounded one-way hash, never the
  text -- so a poll whose output is changing never reaches a stage however
  long it runs, and the block message may now say the results were identical,
  and says it only when they were compared. A result this seam cannot digest
  leaves the call unknown, which falls back to the argument comparison that
  shipped before and to the message that claims nothing about results.

  Two things the host does that a simpler reading of those seams misses, both
  found by driving the ladder through a worker pool rather than one call at a
  time. Hermes fires `post_tool_call` for a BLOCKED call too, with the
  refusal as the result -- OMH's own message, on OMH's own blocks -- and that
  digest was landing in the history of a sibling call that really ran, which
  broke the cycle chain and restarted the ladder; the host marks that post
  `status="blocked"`, so the structured field is read and the refusal is not
  digested. And a call still in flight has no result yet, which the
  comparison was reading as "no evidence, fall back to arguments" -- so an
  eight-wide poll with a different answer every call was blocked at call 9.
  The ladder is now computed over the calls that have returned, with the
  fallback kept for the host it was written for: one that fires no
  `post_tool_call` at all, where nothing has a result and the guard is the
  argument-only one it has always been.

  Stated limit, unchanged and now plainer: a result carrying a timestamp, an
  elapsed duration or a progress percentage never repeats byte-for-byte, so
  it reads as progress forever. A single-call loop whose output is
  timestamped -- a `terminal` loop returning `1 failed in 0.4Ns` -- was
  blocked at call 9 before this change and is not caught now. That is the
  price of telling a poll from a loop by its output, and OMH does not
  normalize result text to avoid it: deciding which bytes of a result do not
  count is wording inference.

  What the ladder costs, per period: 8 calls at period 1 (unchanged), 8 at
  period 2, 9 at period 3, 12 at period 4. Counting laps alone would have
  given a period-4 cycle 32 calls before anyone noticed, four times a
  period-1 streak's budget, bought by padding the loop.

  Dispatch width shifts where the rungs land, because a call in flight is not
  yet evidence. For a period-1 loop of 24 identical calls, allowed `.`,
  blocked `B`, escalated `A`:

  ```
  width 1: ........BBBBAAAAAAAAAAAA
  width 2: .........BBBBAAAAAAAAAAA
  width 8: ...............BBBBAAAAA
  ```

  The same poll at every width is `........................`.

  A tool the host exempts from its own identical-call notice is exempt here
  too, by the host's predicate rather than a second list: `process_manage`
  and any tool ending `_poll` or `_get_result`
  (`agent/tool_guardrails.py`). Result-awareness covers a poll whose output
  moves; it does not cover the case the host actually names, a status poll
  returning the same line, which is the tool a model is told to use while it
  waits. A cycle that only partly polls is still a loop.

  Stage two, the human-approval gate, is withheld where no person can answer.
  Measured at `tools/approval.py`, an unattended context does not park on a
  card -- at the `approvals.unattended_mode` default of `deny` it returns the
  host's own block text, losing OMH's advice, and at `approve` it returns
  `_approved()`, running the very call stage one was refusing.

  Which lanes those are is the approval layer's question, and the answer is
  taken from the code that decides it (`tools/approval_context.py`): the
  three programmatic platforms whose adapters can neither raise a card nor
  receive an `/approve` reply, plus a single-query (`-q`) process. Every chat
  gateway escalates, because a person can answer there. So does an unknown
  platform, which is the host's own answer for a surface added later. The
  platform comes from `pre_llm_call`, the one hook OMH registers that is
  passed one; `pre_tool_call` is not. A delegated child is withheld too, by
  choice rather than by measurement: its card names a session the person did
  not start.

  **Cron cannot be detected from a plugin, so a cron turn escalates.**
  `HERMES_CRON_SESSION` is a ContextVar name and never a process variable --
  the in-process ticker binds it through `gateway.session_context`, the
  detached worker's environment is built without it, and Hermes' own
  regression test asserts the process environment stays clean after a job --
  and a plugin cannot read a host ContextVar. An earlier draft read the
  variable anyway and claimed the dedicated-process case worked; that was a
  gate frozen on a state the host never produces, and it is gone rather than
  kept as a line that cannot fire. The cost is bounded and is not a
  regression, since every lane escalated before this: at the
  `approvals.cron_mode` default of `deny` the host resolves the escalation as
  a block, so the loop still stops with the host's wording instead of OMH's
  advice; at `approve` it auto-approves the looping call. Single-query is
  different and does work, because Hermes exports that marker on both of its
  entry paths.

  The projection a surface reads (`repeat_call_streak`, which #1687's HUD row
  will be the first caller of) requires the attendance answer as an argument
  with no default, so a caller cannot render an escalation the gate is
  withholding by omitting it.

  The escalation's `[a]lways` key is derived from the cycle's elements in
  their lexicographically smallest rotation, so A,B,A,B and B,A,B,A are one
  key and a person who answered once is not re-prompted by a key that moved.

  Once a cycle is engaged, every call belonging to it is refused, not only
  the one the cycle would run next. Driving the ladder through the two
  registered hooks found the difference: a blocked call never runs, so the
  cycle's phase does not advance, and a model that answered the block by
  issuing the OTHER element got eight more calls before the guard re-armed.
  The observed ladder for a period-2 cycle is now calls 1-8 allowed, 9-12
  blocked, 13 escalated -- the same shape a period-1 streak has. A call that
  is not in the cycle still clears the guard, which is the only thing that
  ever did.

  The refusal the model reads says that now. It used to end "any different
  tool call clears the guard immediately", which was true while the guard
  watched a single repeated call and false the moment membership replaced
  position: under a cycle the other element IS a different tool call and is
  refused, so the message was telling the model to do the one thing this
  change made it stop doing. It now names a call outside the cycle.

  Hook cost, measured before and after on the same machine with the ledger at
  its caps, median of three back-to-back passes, both hooks. At 64
  simultaneously live sessions `pre_tool_call` goes from 3.11 ms to 3.89 ms
  p50 and `post_tool_call` from 2.28 ms to 2.96 ms, with the ledger growing
  from 57.8 KiB to 119.6 KiB. At the everyday two-session shape both hooks
  are unchanged and the ledger SHRINKS, from 47.1 KiB to 33.4 KiB. Four
  things hold the ceiling down: a session that is not repeating anything is
  trimmed to the shortest window a cycle can be found in, the gate reads one
  session's row instead of rebuilding every row, a write carries other
  sessions' rows through untouched, and this one ledger is now written
  without the pretty-printing every other OMH ledger keeps -- it is rewritten
  on every tool call and nothing reads it as text. (#1719, #1706)

## 2.0.3 - 2026-09-12

Everything merged since the 2.0.2 tag (2026-09-07). Highlights, grouped:

- **A dispatched unit that stops working now says so.** A session limit read as
  `crash`, a batch whose every unit failed exited 0, a worker alive for 36
  minutes retrying one git workaround read as progress, and a plan with open
  items sat unchanged while each turn ended on a status report. That whole
  chain is closed. Provider refusals classify as limit-shaped, and any unit
  carrying a `failure_kind` makes the command exit non-zero (a derived gate
  fails any future exit-code mapper that maps failed work to 0). A unit's
  execution state is named apart from its process: `running` requires new
  evidence, and a live process without it is `progress_stalled`, beside
  `awaiting_input`, `permission_blocked`, `account_limit`, `data_missing`,
  `failed`, and `verified` — the only success state, which requires a validated
  result record. Progress is read from the unit's own output, including the
  same failure line repeating while bytes still grow. The status board, the
  plugin reader, the TUI widget, and `omh coding fanout status --json` all
  report that state with its reason and how long output has been still, and the
  roster answers the supervisor's own question with `all_units_terminal` and
  `stuck_units`.
- **A unit is refused before the spawn when its workspace cannot take the
  work.** File write, git index write, the objects the work needs actually
  present (including a partial clone whose promisor fetch is forbidden), and
  case-only filename collisions on a case-insensitive filesystem, all probed in
  the unit's own isolation with no network call. A failing check ends the unit
  as `workspace_blocked` before any CLI starts. Executor readiness stops
  claiming more than it saw: a passing `--version` is `binary_version_only`.
- **Recovery matches the cause.** A permission denial re-probes the workspace,
  a limit checks the account and its reset before any retry, missing objects
  are supplemented and verified before one unit resumes, and a stall is only
  re-run with changed conditions or from a checkpoint. A live in-flight marker
  on a scope outranks every cause: no second worker is added to work already
  running. The account a CLI is configured with is recorded as a redacted
  one-way tag so a limit can be told apart from the account that hit it.
- **The plan drives the work.** Open items mean the plan is not finished: the
  per-turn reminder says to advance the next item rather than end on a status
  report, and it stops when every item is done or one is recorded blocked with
  its reason. A plan that stops moving is a finding even while tool calls keep
  running. A finished dispatch arrives as an event with the verb it owes —
  verify, record, then recover or advance — and a continuation announced with
  nothing started is reported back.
- **Fixed: a grown `--help` page silently disabled the structured-session
  lane.** The help probe was capped at 16 KiB; `claude --help` reached 21,401
  bytes with `--verbose` past the cut, so the negotiation refused a protocol
  the CLI does support, the spawn omitted `--output-format stream-json`, and
  every Claude unit ran with no token counts and no session id to steer with —
  visible only as an empty column. The help probe now gets a document-sized
  budget, a truncated read still answers the question when every flag was found
  in what was read, and a refusal states its reason.
- **Setup and routing.** Provider entitlements are asked as one plain ticked
  list with detected providers pre-ticked; the native-lane chain interview is
  offered during setup; `capable`, `simple-work`, and `deep-work` join the model
  categories. DeepSeek V4.1 Flash onboarded with superseded generations retired
  from the shipped chains, and a vendor's dated snapshot id is recognized as the
  base alias it is a snapshot of.
- **Memory and HUD.** Past-session history routes to the session store rather
  than a record; reviewed records and consolidation briefs reach the Hermes turn
  with the host saying so; store containment is decided lexically instead of by
  two resolves. A lane routed to the parent's own model keeps its category and
  says `=parent`; a gateway child the host could not price is approximated with
  its provenance.
- **Install and update.** An `omh update` survives a symlinked plugin
  directory; a Hermes profile registered at any OMH-managed skills path counts
  as registered and opting out removes every one; the pre-pointer skills home is
  a managed registration on managed installs too.
- **Windows fixes found through "flaky" tests.** A sharing-denial retry for the
  store write that silently dropped a record, and containment decided without a
  resolve race. Both Windows shards now run to completion, and a process-global
  interrupt flag is restored after every test that sets it, which was showing up
  as a CI-only failure in whichever test ran next.
- **Docs and gates.** Public documentation structure is gated by an offline
  navigation check, the shipped chain table in `docs/INSTALLATION.md` is
  generated and gated, and the two traps that cost a day of diagnosis (the stale
  editable install, and concluding a platform fact settles a call site) are
  written into `CLAUDE.md`.

Entries recorded during the cycle, in full:

- Added bounded GPT-6 Astra mode/service-tier contract inheritance and a deterministic `model_contract_coverage/v1` audit CLI for local model inventories, preserving exact-versus-declared provenance without treating catalog rows as provider availability or execution evidence.
- Added a read-only shape view for one selected work artifact. The common facade supports registered handoff, plan, status, and review source schemas; the persisted wrapper path projects prompt/runtime handoffs plus every recorded `coding_briefing/v1` artifact through `omh runtime artifacts show-shape --artifact-id <id> --lens flow --json`, retaining the exact source schema rather than relabeling it. The lens vocabulary is `flow`, `structure`, `change`, `state`, and `ownership`, with each source family exposing only the lenses its fields can support, and every node and edge carries the source refs it was projected from. `ascii` is the default format, `tree` and `diff` are the other text formats (`diff` requires the `change` lens), and `mermaid` stays unavailable until a Mermaid capability is observed rather than inferred from a flag. An unknown artifact id, an unrecorded source, an unsupported lens or schema, unsafe content, or an exhausted render budget all come back as an explicit `unavailable` result with a named reason and an empty body. People keep asking Hermes about the work in plain language; the projection is a wrapper-facing selected action, and the command above is the observed operator/agent path into it. Showing a shape never advances the session, and it is not dispatch, execution, verification, review, CI, merge-readiness, or merge evidence.
- Added `omh coding paired-run dispatch --decision <paired_run_decision/v1>` as an explicit operator/maintainer boundary for an already-committed paired-run decision. `--dry-run` prints the inert plan and launches nothing. Without `--dry-run`, dispatch refuses unless `--confirm-dispatch` is typed. A confirmed Hermes matrix requires one digest-matching `--task-file` per frozen task, an exact repository revision, and a provider; it reuses the sanctioned Hermes-child bridge, passes task bytes over stdin, runs independent cells with a derived concurrency ceiling of two in detached worktrees under an atomically unique invocation-owned parent, verifies the signed evaluation binding, removes only paths reserved by that invocation, and persists no task body. The paired path opts into that bounded scheduler while the child bridge remains single-dispatch by default for every other caller. A timed-out Git worktree command becomes one `crashed` cell with explicit partial-cleanup evidence rather than aborting the matrix. Executors without a receipt-capable adapter are refused without substitution, while caller-injected adapters remain the executor-neutral extension seam. The plan carries the isolation mode, shared-resource keys, launch waves, and the global/per-executor/per-provider concurrency and cost/time budgets derived from the frozen decision, never from CLI overrides. Execution evidence closes back into a decision only through an authenticated receipt fan-in: a missing, stale, mismatched, unauthenticated, partial, timed-out, cancelled, crashed, or rate-limited cell blocks the decision instead of degrading it, and behavior verdicts stay explicit request values rather than being read off exit codes or process output. Confirmed cells also write bounded metadata-only queue/start/finish and cleanup events, so `omh runtime health-summary --run-id <decision-id>` projects evaluation critical-path health directly.
- Added an optional post-GREEN diagnostic pass to fanout dispatch behind `--diagnostics` (`--no-diagnostics` is the default). The explicit operator path now discovers only the closed local `pyright`, `basedpyright`, and `ruff` command set from `PATH`; caller-injected engines remain the executor-neutral extension seam. Providers run over detached baseline/end revision worktrees with fixed argv templates, bounded global/per-provider concurrency, serialized stateful providers, process-group timeout/cancellation, an allowlisted environment, hard-capped output, and mandatory cleanup. The complete owned provider process group/tree is terminated and reaped after every leader exit, including exit zero, and unproved cleanup cannot become clean evidence. Windows providers start suspended, enter a kill-on-close Job Object before executing, and require zero active job processes before clean evidence. Only normalized severity/code/relative-position metadata reaches compatible `language_diagnostic_evidence/v1` records; messages, source, absolute paths, stderr, and raw provider payloads are discarded. Diagnostics still run only after producer verification GREEN at fixed revisions, and a missing provider, process failure, dirty/moved checkout, or non-clean outcome becomes `held` without changing the unit's verification ladder.
- Added `--health-events` to fanout dispatch (off unless typed) and a matching read path, `omh runtime health-summary --run-id <fanout-id>`. Enabled dispatch appends bounded metadata-only lifecycle events to the run's own `critical_path_health_events.jsonl`; the health summary reads it through fixed byte/line/record ceilings and projects it into a committed `critical_path_health/v1` section, upgrading the record to `run_health_summary/v2`. Same-millisecond zero-duration spans remain valid. Without that journal, the projector falls back to existing observation-journal evidence, and a lifecycle it cannot reconcile (a dependency cycle, an out-of-order dependency, or an over-limit journal) reports explicit evidence gaps with null metrics instead of a plausible number. `--input` still reads a `run_health_input/v1` or `/v2` file.
- Added immutable concurrent final-review lanes for integrated fanout work. The four lenses use the fixed reporting order `requirement`, `quality`, `safety`, `real_surface`, execute concurrently within the configured limits, and bind read-only to one 40-hex integrated revision. The explicit `omh coding fanout dispatch --final-review` path reuses the sanctioned Hermes-child boundary after integration GREEN, requires the clean integrated worktree/revision and named provider/model, and parses only an exact closed verdict token; caller-injected engines remain the extension seam. Every built-in lane runs in its own detached fixed-revision checkout with filesystem writes denied, rechecks that disposable tree before accepting the verdict, and removes it in `finally`, so a bypassed write is contained and blocks without touching the integrated checkout. The fanout hook also proves the integrated tree is clean and unchanged before/after execution and requires one matching observed execution ref per lane, so a silent complete-looking engine result cannot become `PASS`. The wave reduces to a deterministic `PASS`, `HOLD`, or `BLOCK`: `HOLD` when integration is not green or producer evidence is missing, `BLOCK` when a revision is not immutable or a lane drifted off the bound revision, mutated, lacked an execution observation, or went missing, and `PASS` only when every lane completed at that exact revision. A review verdict remains review evidence only, never merge evidence.
- Put the offline live-model benchmark framework in every static CI shard lane. Its upstream cases live outside `tests/`, so statically declared delegators expose each one to the sharding inventory, with an AST parity check that fails loudly when an upstream case is added, removed, or renamed. The delegated cases run the real upstream implementation with no paid-live authorization. Each test id is assigned exactly once to a shard or quarantine by the shared plan, then that assignment is executed by each applicable Linux or Windows version lane and reconciled by `aggregate`.

## 2.0.2 - 2026-09-07

Everything merged since the 2.0.1 tag (2026-09-05).

- **Fix: `omh update` rolled back at `post_activation` on installer-managed machines.** The staged transaction rendered the candidate workflow pack into its own generation, then re-entered the update against the real home, whose manifest still recorded the active generation's pack; every skill the catalog had changed since the last install was judged a "local modification", the re-entry refused without `--force`, and the whole update rolled back with only the phase name printed. The installer now applies its local-modification and orphan-prune guards only to the directory the manifest actually records, the summary line names the failing phase's reason and the rollback target, and the re-entered update's stderr is captured for that reason and replayed. A transaction-level regression test drives the real CLI through the smoke and re-entry against an older-manifest home, and a companion test proves the guard is what prevents the refusal. (#1377)
- **Release and update.** A release cut ends with the owner machine synced, and a bare `omh` announces its Auto Update; `omh --version` and `omh doctor` expose a verifiable build identity; the cut stages the site badge it rewrites.
- **Coding and fanout.** Fanout dispatch runs under an OS write fence proven per run, with the confined owner CLI still able to write its own state; workspace targets are declared by path shape, glued and encoded spellings of a target token are declared, and decoding runs to a fixpoint before a containment slot is charged; long-running waits bind to the host's completion signal; `cancelled` is a first-class observed terminal state; an explicit user merge directive survives the delegation boundary; delegation continuity is recorded as a goal-ledger obligation.
- **Routing and models.** Claude Mythos 5.1 leaves the shipped recommendation chains; the Codex Maestro defaults name the GPT generation the CLI serves; the Astra round's measured lessons join the onboarding loop.
- **Install and memory.** The PowerShell installer reads the redirect Location header through a capability probe, proven on both PowerShell versions; memory credential boundaries are hardened.
- **Skills and docs.** llm-app-dev treats public-board communication as public disclosure; Apple visual production and 3D examples; README showcase, demo grid, and a Quick Start that takes the same shape in every language.

## 2.0.1 - 2026-09-05

Everything merged since the 2.0.0 tag (2026-08-29). Highlights, grouped:

- **Models.** Onboarded GPT-6 Astra with an exact-model contract (documented effort ladder with a `low` floor, Responses-only tool calling, list pricing), exact-model calibration overrides resolved before the family block, and both-lane routing with GPT-5.6 Sol as fall-through; measured the Astra override against the block it replaced on the live benchmark and revised its wording on the number. Onboarded Claude Fable 5.1 / Mythos 5.1 with 5.1-aware calibration, the GLM 5.3 generation with chains and speed-tier projection, and MiniMax family recognition. Token prices moved into a config document with a cited source per rate.
- **Routing.** A deterministic request-complexity scorer feeds a model-class recommendation; an exhaustive-search signal lifts "find every reference / all usages" requests to the standard tier on their own. Trigger language packs make any input language addable; Korean bare-name delegation and generic delivery cues route to the coding lane; a vagueness gate holds heavy modes back; a dispatch that would inherit a provider which cannot serve it is refused. The provider-entitlement interview reorders chains per machine.
- **Coding and fanout.** Single-run Maestro dispatch with explicit owner override and per-run `--model` / `--effort`; operator category→model chains (`category-maestro`) surfaced through setup; revision-bound, tiered, reusable verification plans with an explicit post-integration gate; resumable fanout via a terminal-state run journal; adaptive provider-pressure admission; capped recursion depth and spawn ceiling; retry classification gated on replay safety; preflight blocks for doomed Hermes child spawns; dispatch-failure classification, repair, and interview; shared build artifacts symlinked into unit worktrees; a completion-integrity gate that refuses fake completion.
- **Observability and HUD.** Live mid-run token telemetry and Claude Code-style aligned token columns on subagent rows; Hermes-native cost provenance in the HUD (confirmed zero vs unknown vs approximated); honest-unknown elapsed time; the plan todo scoped to the session that declared it; selectable TUI themes and `omh theme repair`; a copy/export manifest for the current work artifacts.
- **Skills.** New workflows: adversarial-consensus, llm-app-dev, backend/rust/native-debugging domain pack, codebase-uml (with `omh codegraph uml`), frontend-refactor, refactor-plan, inference-serving, instrumentation ladder, tech-debt-audit, decision records, a11y rule IDs, web-vitals budgets, self-evaluation loops, award-bar-score, model-optimization, omh-docs, GitHub issue intake, and memory-sync interviews. Existing skills gained a slop taxonomy (ai-slop-cleaner), a spec-conformance axis (code-review), and split web-lookup and audience-aware briefings (ulw-research). A skill upstream-sources registry records reconstruction provenance.
- **Quality gates.** Instruction-density and shared-prompt budgets sized for the smallest model in the fleet; denominator hygiene for every self-reported rate; cross-surface duplicate-content detection; prompt/schema overlap classification; adversarial-regression rule before a guard deletion; evidence freshness bound to the git tree hash; the routing corpus calibrated against recorded decisions.
- **Security.** A named strict posture via `OMH_SECURITY`, an approval-tier resolver that centralizes confirm/refuse decisions, and a verification lane that escalates on sensitive path touches.
- **Benchmarks.** A live cross-harness lane that executes what it submits, ternary live verdicts with baseline comparison, manifest-aware analysis for targeted family runs, a `family` condition that measures an exact-model override against the block it replaced, and the offline framework tests running inside the sharded CI suite.
- **CI and release.** The unit-test suite is sharded by measured duration with a serial quarantine and exact-once aggregation; the landing page's version badge is parity-gated and bumped with the other version surfaces.
- **Fixes.** `plugins.enabled` list items level with their key are read and written correctly; the fanout admission tests and the cross-harness crash fixture no longer flake on loaded runners; a zero cost renders only with the provenance that earns it; HUD row identity keeps its parentheses; the context dash the header could never fill is gone.

## 1.0.6 - 2026-08-13

- Made `omh update` installation-aware: Homebrew, Bun, npm, curl, and PowerShell installs now update their owning command package first, re-enter the updated CLI, and then refresh managed skills, the installed plugin bundle, and existing Hermes registration.
- Added the Hermes dock-bottom OMH activity HUD, fresh-install TUI selection, and an all-in-one agent install protocol with approval-gated model aliases; recommendation resolution now reports `owner_default` through `model_recommendation_resolution/v2` and completes setup without a model-config write when no confirmed candidate matches.
- Added typed unit-result sidecars for fan-out dispatch: `fanout_unit_result/v1` schema with structured process status, command evidence, and reporter-vs-observer provenance marks out exactly what was dispatched, what it reported, and what the dispatcher verified independently — replacing the exit-0 overclaim with a four-state vocabulary (`process_succeeded`, `result_schema_valid`, `unit_verification_observed`, `integration_ready`) that reflects the actual evidence ladder.
- Hardened worktree creation with runtime base-SHA validation, unique-branch enforcement, and crash-cleanup receipts logged to the observation journal.
- Unified dispatch-profile capability metadata into `executor_capability_snapshot/v1`: edit formats, persistent eval, tool reentry, and code-mode batching now use the same observation-backed source as owner fit, with bounded evidence and `unknown` defaults. Briefing and fanout receipts project that snapshot without independently selecting or ranking an owner.
- Fanout preparations now freeze deterministic owner capability evidence in `fanout_contract/v2` with closed local provenance. Direct v1 dispatch is retired: maintainers use `omh coding fanout migrate-legacy` to validate or explicitly confirm the exact legacy payload and freeze it as v2 first. Dispatch preflight rejects goal, safety, schema, merge-order, owner, or snapshot drift before Git, discovery, readiness, or executor activity.
- Added `omh coding fanout status` read-only roster command that projects dispatch journal events into a unit-level summary table.
- Strengthened delegation guidance in the skill catalog with five bounded blocks: code-mode batching (capability-conditional), edit-format steering, resource-reference idiom, review-verdict format (P0-P3 priority framework), and commit-planning discipline.
- Added orchestration patterns documentation: boundary-policy rules with retry-from-checkpoint, and async advisor-as-reviewer contract with explicit severity gates.
- Added benchmark fixture discipline guidance: seeded deterministic mutations, fresh sessions, exact-equality grading, raw transcript retention, and first-party authored measurement labels.
- Added capability-shape parity documentation linking OMH-native schema contracts to the oh-my-pi designs that inspired them.
- Strengthened memory documentation: durability-receipt state vocabulary (`candidate_persisted`, `approved_record_persisted`, `indexes_refreshed`, `replay_ready`) and explicit learned-skill candidate-gate wording.

## 1.0.5 - 2026-08-08

- Added a message gate: every coding delegation now shows which skill ran, which executor and model it ran on, what evidence class the answer belongs to, and a digest of the prompt behind it, rendered by OMH as exact lines instead of asked for in skill prose. The composed Hermes order ships as its own follow-on message, bounded and fenced.
- Replaced the raw evidence vocabulary in everything a person reads. `prepared_not_observed` now renders as `Plan · not run`, `completed` as `Code · reported done`, and `worktree_failed` as `Setup · failed`, across chat, the status board, the route summary, the menu bar, and the README. The wire values are unchanged, so anything parsing them keeps working.
- Separated an executor's own claim from a checked result: a unit that reported itself finished no longer renders identically to one that passed a gate.
- Added `omh goal status --text`, so a goal ledger can be read as lines instead of escaped JSON.
- Added a coding handoff safety boundary, a single safety preflight with an opt-in organization rule source, a task authority envelope, and risky-action classification with run-bound approval receipts.
- Added external effect receipts, a normalized owner-progress vocabulary, safe blocked-work records with a decision history, and one shared append-only store with stale-update rejection.
- Made unit prompts skill-aware: fan-out work discovers, arranges, and interviews the skills available to the executor it is handed to.
- Gated follow-on engine starts on explicit user confirmation, and taught the delegate rules the real Claude Code permission-grant and session-resume mechanics.
- Made the capability policy changeable and enforced rather than advisory.
- Brought Windows to parity: the full suite runs on `windows-latest` in CI, journal lines stay LF, atomic replaces retry under sharing denials, and the installer path was fixed.
- Added CI gates for roles, capability families, and whitespace, plus a catalog deference gate covering the sibling relationships the catalog writes in prose.
- Bound observed workflows to snapshot evidence, and narrowed the plugin awareness markers to the routes they actually support.

## 1.0.4 - 2026-08-01

- Overhauled Hermes memory into a governed lifecycle: admission, evaluation, retention, expiry, and retirement policies, write-replay hardening, migration with reactivation for legacy stores, rollup signals, peer-perspective records, and record fusion, plus recall packs with freshness, budget, and conflict-aware sibling controls.
- Added a reviewed domain-intelligence store with an operator-controlled capture, review, approve, replace, and retire lifecycle, backed by descriptor-bound fail-closed snapshot validation and lineage, rejection, and retirement audit trails.
- Added domain-aware clarification: after a project-local domain profile is approved, an unresolved chat question can ask the exact catalog-owned expert question (English or Korean) for eight specialist workflows, while every already-resolved route, dispatch, and protected body stays byte-identical.
- Added eight specialist domain skills (sales development, finance analysis, legal compliance review, curriculum design, localization review, people ops, product brief, support operations) with domain-affinity ranking in the picker.
- Added model inventory routing: setup captures which coding agents and models are actually installed, and routing, main-agent composition, and dispatch recommendations follow that inventory instead of assuming a fixed owner.
- Added a research depth dial with declared shallow and deep chains, research-role routing, and a bounded executor prompt contract for prepared coding handoffs.
- Reworked dispatch ergonomics: choice-required dispatch when several owners fit, a unit verification protocol for fan-out work, delegation-protocol guidance across surfaces, and session follow-up handoffs that keep context across turns.
- Tightened routing quality with an accuracy program, overroute audits, picker-completion fixes, and clearer skill names and descriptions across the catalog.
- Made `omh update` report package-version and content movement explicitly, refresh every installed surface, and bust stale caches.
- Refreshed the README family with workflow GIFs, highlights, a uniform demo grid, and community links, and froze per-skill Korean copy behind explicit opt-in.

## 1.0.3 - 2026-07-26

- Added a `/omh` meta-router gateway skill with live-catalog routing, four Hermes setup-guide skills, and a generated full-catalog index reference so Hermes can discover the workflow surface from chat.
- Added an `omh-` display prefix to generated skill frontmatter, so a Hermes status line shows `omh-ultrawork` instead of a bare name that could belong to any skill, and made echo-back of those display names route correctly.
- Bounded the deep interview: every question now carries a `Round {n}/6` header with a clarity percentage over three fixed dimensions, and the interview stops on resolution, an explicit user stop, or the round budget.
- Reworked coding delegation around request-led states: coding route next actions split into four states, named coding-agent delivery takes precedence over advisor and feedback lanes, and setup asks one question with usage-time owner delegation.
- Added an opt-in local dispatch bridge that executes fan-out contracts in parallel against a deterministic merge contract, plus executor-scoped handoff validation.
- Made messenger rendering honor the render-profile contract on the chat route-hint path, which is the only limited-rendering path for the Hermes platforms that are not named individually, and made a present-but-unsafe body warn instead of passing silently.
- Surfaced wrapper degradation to chat users instead of dropping it at the wrapper, and taught progress reporting to detect claim/observation mismatches rather than only exempting them.
- Added an `omh doctor` advisory lane for the costliest Hermes misconfigurations, including noticing when the plugin is installed but disabled.
- Added a pinned Ruff static-analysis gate to CI and contributor docs, and a self-checking broad-exception policy gate.
- Cut repeated common-rail context in generated skills and bounded prompt, capability, stdout, and status payload budgets so shared context does not become prompt bloat.
- Defaulted skill-pack install to a core profile with opt-in full, and added a reconcile path from full back to core.
- Defaulted all setup and CLI output to English; localization is explicit opt-in through `--language` or `OMH_LANG`.
- Retired OMH worktree creation in favor of native Hermes and Git tooling.

## 1.0.2 - 2026-07-01

- Added stronger Hermes chat routing, workflow picker, direct-answer, file-lookup, and operator fast paths for common English and Korean requests.
- Added localized chat-card framing and release gates for localized copy, router fast paths, Hermes UX quality, routing precision, context brief coverage, route-hint alignment, and release evidence bundles.
- Added richer plugin, MCP, menu bar, codegraph, workflow-learning, source-finder, paper-learning, and worktree/session observation surfaces while preserving metadata-only evidence boundaries.
- Modernized the public site, README workflow presentation, docs, generated skill guidance, role context, and release readiness instructions around the Hermes-native wrapper contract.

## 1.0.0 - 2026-06-09

- Added the initial `omh` installer and Hermes skill workflow pack.
- Added a direct `src/` package layout for future growth.
- Added generated routing catalog and rendered skill content.
- Added open-source project operations files and GitHub templates.

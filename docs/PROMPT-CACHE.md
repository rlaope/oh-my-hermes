# Prompt-Cache Report

`omh cache` shows how much of a profile's model input came from the prompt
cache and why the cache went cold. It reads the active profile's
`<HERMES_HOME>/state.db` read-only (`mode=ro`) and nothing else; it sends no
model request, writes nothing and keeps no cache warm.

```bash
omh cache              # last 7 days
omh cache --days 1     # last 24 hours
omh cache --json       # machine-readable report
```

The window counts sessions whose `started_at` falls within the last `--days`
days. The report prints the window's start and end times.

## What it prints

- **Read share by source**: `cache_read / (input + cache_read + cache_write)`
  tokens per session source (`discord`, `subagent`, `cron`, ...).
- **Idle gaps**: the time between consecutive user messages inside the
  sessions of human-paced sources (every source outside Hermes'
  machine-paced list), bucketed `<5m`, `5-60m` and `>1h`. A gap longer than
  the cache TTL means the next turn starts cold.
- **Cron jobs**: one row per job. The job key is the session title before
  `' · '` (`?` for sessions without one, such as script-gated runs that never
  called a model). Each row shows the runs, the model runs
  (`message_count > 0`), cache write tokens, the median gap between model runs,
  and how many distinct `system_prompt_hash` values the model runs used.
- **Write split** of every cron cache write into three classes. The job's
  smallest model-run write stands in for its stable prefix `P`:
  - **cold**: `min(write, P)` of a run that started more than one hour after
    the job's previous model run, or the job's first run in the window. Even
    the 1h cache tier has expired by then, so this write is unavoidable at the
    job's cadence.
  - **churn**: `min(write, P)` of a run within one hour of the previous run
    whose system prompt hash changed. The prefix was still cached but the
    prompt moved, so this write can be fixed.
  - **other**: the rest. That is `write - min(write, P)` of every run (growth
    inside a run, such as tool loops) plus the prefix part of a warm run with
    an unchanged prompt.
- **Top churn job**: for the job with the most churn, the first line that
  differs between the two consecutive system prompts. Each side is cut to
  160 characters, with secret-shaped strings masked. Typical culprits are a
  memory usage header, a skills index line, or a `Conversation started:` date
  line.
- **Suggestions**: one to three plain next steps, in order of each class's
  share of the write.

## HUD field

`omh hud --json` (and every surface built on `build_hud_payload`) carries a
`cache` object: `{"window_hours": 24, "sessions": N, "read_share": 0.958}`.
It is the read share of the main sessions, meaning human-paced sessions with no
parent, active in the last 24 hours. One aggregate query over at most 500
recent rows opens `state.db` read-only and never waits on a lock (timeout 0):
a writer holding the database makes the read give up at once. When the
database is missing, unreadable, locked or empty for the window, the field is
left out and the rest of the payload is unchanged. With the field, the HUD's
text line (`omh hud`, `omh status`) ends its focused and full presets with
`cache:NN%`; without it, the segment is left out.

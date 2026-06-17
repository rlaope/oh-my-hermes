# Discord Bot Wrapper Flow

This example shows the recommended shape for a Discord bot or hosted chat
wrapper. Hermes Agent remains the user-facing runtime. OMH supplies local,
deterministic contracts that the wrapper can render, persist, and update with
observed evidence.

The user should not need to know OMH command names. The wrapper translates a
plain Discord message into a chat response, plan decision, coding handoff, and
status update.

## Primary Flow

1. The bot receives a Discord message and writes the raw platform event to a
   temporary local file such as `event.json`.

2. The bot asks OMH for the wrapper-native interaction envelope:

   ```sh
   interaction_json="$(omh chat interact --source discord --event-json event.json)"
   ```

3. The bot renders the safe chat response in the same Discord thread:

   ```sh
   printf '%s' "$interaction_json" |
     python -c 'import json,sys; data=json.load(sys.stdin)["chat_response"]; print(data["headline"]); print(data["body"])'
   ```

   `chat_response.headline` already starts with a visible marker such as
   `[omh] web-research`. Render `chat_response.actions` as buttons when the
   platform supports them, and use `chat_response.messenger_rendering` to avoid
   wide Markdown tables in Discord. Research comparisons should become short
   sections, bullets, or split messages instead of a single table-heavy block.
   Keep the prefix on the first line only; repeat it only when posting separate
   split messages.
   Typical action ids include `accept_plan`, `revise_plan`, `choose_executor`,
   `show_prompt_handoff`, `copy_prompt_handoff`, `send_to_executor`,
   `show_status`, and `cancel`. `send_to_codex` is only a compatibility alias
   when the selected executor profile is `codex`.

4. If the wrapper needs restart recovery, start or resume a metadata-only chat
   session keyed to the Discord message/thread:

   ```sh
   session_json="$(
     omh chat session start \
       --source discord \
       --source-event-id "$DISCORD_MESSAGE_ID" \
       --channel-ref "$DISCORD_CHANNEL_ID" \
       "risky refactor"
   )"
   session_id="$(printf '%s' "$session_json" | python -c 'import json,sys; print(json.load(sys.stdin)["session"]["session_id"])')"
   ```

5. If OMH returns a plan, wait for the user to accept or revise it before
   preparing a coding handoff:

   ```sh
   omh chat session accept-plan "$session_id"
   ```

6. For accepted implementation-shaped work, choose who owns the coding work.
   Codex can create a run-backed lifecycle; non-Codex profiles prepare
   prompt-only handoffs without creating a runtime run:

   ```sh
   omh chat session select-executor "$session_id" codex
   ```

7. Prepare the selected handoff and link it to the wrapper session:

   ```sh
   handoff_json="$(omh chat session prepare-handoff "$session_id" "risky refactor")"
   run_id="$(printf '%s' "$handoff_json" | python -c 'import json,sys; print(json.load(sys.stdin)["session"]["current_run_id"])')"
   ```

8. If the selected executor is Codex, dispatch the
   `coding_executor_handoff/v1` payload to the external coding executor outside
   OMH, then record only transitions the wrapper actually observed:

   ```sh
   omh coding lifecycle dispatch --run "$run_id"
   omh coding lifecycle result --run "$run_id" --result completed --evidence-ref codex-log
   omh coding lifecycle verify --run "$run_id" --completion-status completed
   ```

   If the selected executor is prompt-only, render the `prompt_handoff` for the
   user to copy or for the wrapper to pass to its own executor integration. Do
   not mark dispatch, execution, review, CI, or merge evidence as observed from
   the prompt alone.

9. Render status updates from the local lifecycle report:

   ```sh
   omh coding lifecycle report --run "$run_id"
   omh chat session status "$session_id"
   ```

## Status Boundaries

- A prepared handoff is not execution evidence.
- Hermes should not claim it implemented code from an OMH record.
- Review, verification, CI, and merge status require separately observed
  wrapper or runtime evidence.
- Use `not_observed` or `not_available` when the bot cannot prove a transition.

## Lower-Level Diagnostics

The lower-level runtime commands are still useful for debugging custom wrappers
or inspecting local artifacts directly:

```sh
run_json="$(omh runtime record --skill oh-my-hermes --harness coding-handling --status started)"
run_id="$(printf '%s' "$run_json" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"

omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed
omh runtime show "$run_id"
omh runtime validate --run "$run_id"
```

Use these diagnostic commands when you need explicit artifact inspection. For
normal Discord or Slack UX, prefer `omh chat interact`, `omh chat session`, and
`omh coding lifecycle`.

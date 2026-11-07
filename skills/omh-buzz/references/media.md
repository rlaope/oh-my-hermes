# Buzz Media Delivery

Use this lane only for a local attachment destined for the active Buzz
conversation. General media editing belongs to the media workflows.

## Preflight

1. Confirm the source path exists, is readable, and is the file the user meant.
2. Use the live Hermes Buzz context or gateway evidence to obtain the current
   channel/conversation id. Never guess it.
3. Inspect relevant media metadata. For video, use `ffprobe` when available.
4. Preserve the private key in the subprocess environment only; never add it
   to command arguments or rendered output.

## Delivery

Prefer Hermes' normal `MEDIA:/absolute/path` delivery. If the native response
path cannot deliver the file and the user still wants direct Buzz delivery,
run the Buzz CLI as Hermes' adapter does: the configured CLI path,
`messages send --channel <observed channel id> --file <absolute path>
--content -`, with `BUZZ_RELAY_URL`, `BUZZ_PRIVATE_KEY` and, when set,
`BUZZ_AUTH_TAG` in the subprocess environment only. `--content -` reads the
caption from stdin; give it the caption or an empty stdin. Confirm the flags with
`buzz messages send --help` first and stop if they differ.

Treat the receipt as valid delivery evidence only when it parses as an object,
contains `accepted=true`, and includes a non-empty event id. Empty stdout,
empty objects, malformed JSON, `accepted=false`, or an accepted response
without an event id are failures or ambiguous outcomes, never success.

When a raw receipt is available, classify it with
`omh.system.buzz_delivery.parse_buzz_delivery_receipt`. Its
`omh_buzz_delivery_evidence/v1` reason codes include
`receipt_not_json_object`, `receipt_missing_accepted`, `receipt_rejected`,
`receipt_missing_event_id`, and `event_accepted`.

Do not auto-retry an ambiguous write: the relay may have accepted the first
event and lost only the response.

## Evidence Ladder

Report the highest observed stage and leave later stages unobserved:

1. `prepared` — file and target validated.
2. `uploaded` — bytes were accepted by the upload surface.
3. `event_accepted` — relay receipt has `accepted=true` and an event id.
4. `retrievable` — the attachment URL can be fetched.
5. `subscription_observed` — the event appears on a subscribed Buzz client.
6. `client_rendered` — the intended client rendered the attachment.

An event id does not prove client rendering. A local CLI exit code does not
prove relay acceptance.

## Media Recovery

- MP4 rejected or not rendered: first try a fast-start remux when the codecs
  are already compatible; re-encode only when necessary.
- Animation rejected: convert to a supported format only with the user's
  approval because conversion changes the artifact.
- Oversized file: report the observed limit and ask before transcoding.
- Wrong channel evidence: stop and recover the current live context instead of
  sending to a guessed destination.

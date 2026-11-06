# Hermes Native Buzz Gateway Setup

Use this lane to connect or repair a Hermes gateway that should participate as
a native agent in a Buzz community. Hermes owns the adapter; do not build a
second transport in OMH.

## Inputs

- The target Hermes home/profile.
- The Buzz community relay URL.
- A dedicated agent identity that is already admitted to the community.
- The intended access policy: private (`allowed_users` listed, `allow_all_users` false) or community (`allow_all_users` true).
- An observable verification target: inbound message, outbound message, or
  both.

Do not ask the user to paste a private key into chat. A private key belongs in
the target Hermes `.env`; non-secret gateway settings belong in Hermes config.

## Safe Setup

1. Read the current official Hermes Buzz guide (the Buzz page under the messaging
   user guide of the Hermes docs) and the stable Buzz release notes when they
   conflict with this reference. If neither can be opened, mark the read
   `not_observed` instead of recalling it.
2. Check whether `hermes` and the configured Buzz CLI executable exist.
   Presence is installation evidence, not relay readiness.
3. Confirm that the agent identity is separate from the human owner identity
   and is already a member of the target community.
4. Prefer `hermes gateway setup` and select Buzz. Use direct config editing
   only when the guided setup cannot express the accepted configuration.
5. Keep `BUZZ_PRIVATE_KEY` in the Hermes `.env`. Never put it in argv, logs,
   diagnostic output, workflow artifacts, or version-control.
6. Configure the relay URL, agent display name, optional channel/DM scope,
   transport mode, and access policy. Do not silently add to `allowed_users` or set `allow_all_users` true; either widens who can drive the agent and needs the user's explicit answer.
7. Start or restart the Hermes gateway only when the user asked for execution.

## Read-only Diagnosis

Observe these independently:

| Stage | Passing evidence |
|---|---|
| configuration | Buzz is enabled and required non-secret fields are present |
| executable | the exact configured CLI path resolves and reports a version |
| identity | a public identity can be derived without printing the private key |
| membership | the agent identity is admitted to the intended community |
| transport | Hermes reports WebSocket or polling activity for Buzz |
| inbound | a new addressed event reaches Hermes without history replay |
| outbound | the send receipt has `accepted=true` and a non-empty event id |

Report missing or inaccessible evidence as `not_observed`; do not turn it into
success. Keep raw relay URLs, account identifiers, channel ids, event ids, and
filesystem paths out of reusable workflow artifacts unless the user explicitly
requests an operator-local artifact.

## Recovery

- Authentication failure: separate key format, relay membership, NIP-42, and
  owner-attestation evidence before changing configuration.
- No inbound messages: distinguish connection state, channel scope, mention
  policy, DM discovery, and self-echo/de-duplication behavior.
- Outbound ambiguity: do not auto-retry when the relay may have accepted an
  event but the response was lost.
- CLI absent: stop at installation guidance; never claim gateway readiness.

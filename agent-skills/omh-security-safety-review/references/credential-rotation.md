# Credential Rotation

Finding the secret that needs rotating is the easy half. This is the order that
keeps the service up while the credential changes, and the check that proves
the old one is dead.

## The order

Five steps, and the order is the whole point:

1. **Issue new** - create the replacement alongside the current credential.
   Most providers allow two live credentials per identity; where they do not,
   the rotation needs a second identity and that changes the plan, so find out
   before step 2 rather than during it.
2. **Deploy new** - put the new credential everywhere the old one is used.
   Enumerate those places first: application config, CI secrets, developer
   machines, scheduled jobs, infrastructure-as-code state, and any partner who
   was given it. A place nobody listed is the outage.
3. **Verify new** - a real call succeeds with the new credential, from each
   deployed environment, not only from a laptop.
4. **Revoke old** - disable the previous credential.
5. **Verify revoked** - a call with the old credential FAILS.

## What breaks if the order changes

| Change | Result |
| --- | --- |
| Revoke before deploy | a full outage for the window between them - this is the mistake the sequence exists to prevent |
| Deploy before issue | the new credential is not live yet, so every call fails with an authentication error nobody expects |
| Skip verify-new | a deployment that silently fell back to the old credential looks healthy until step 4 turns it off |
| Skip verify-revoked | the old credential is assumed dead; if revocation did not take, the exposure that triggered the rotation is still open |
| Revoke immediately after deploy | in-flight requests and cached tokens issued under the old credential fail; the overlap window exists for them |

## The overlap window

Both credentials are live between steps 1 and 4. Size it by the longest thing
that can still be holding the old one: token lifetime, cache TTL, a scheduled
job that runs hourly, a mobile client that updates weekly. A window shorter than
the slowest of those turns step 4 into the outage step 1 was meant to avoid.

A compromised credential inverts this: the exposure outranks the availability,
so revoke first and accept the outage. Say which case applies before naming a
window.

## Revocation is proven by a failure, not by an exit code

**A revoke command's success means the request was accepted.** It does not mean
the credential stopped working. Providers cache authorization decisions,
propagate revocation asynchronously across regions, and sometimes keep issued
tokens valid to their expiry after the credential behind them is disabled.

The proof is a call made with the OLD credential that fails with an
authentication or authorization error. Record what was called, when, and the
exact status returned. Three results that are not proof: a connection error
(the endpoint was unreachable, not the credential rejected), a 404 (wrong
path), and a success (revocation has not propagated - wait and re-check rather
than calling it done).

Where the provider issues bearer tokens from the credential, a token minted
before revocation may outlive it. Say so explicitly, name the longest such
lifetime, and treat the rotation as incomplete until it has passed.

## Per credential type

- **API key or token** - the five steps as written.
- **Certificate** - deploy the new chain to trust stores before switching the
  leaf; a client that does not trust the new issuer fails at step 3, which is
  where it should fail.
- **Database password** - some engines allow only one password per role;
  rotation then needs a second role plus a connection-string switch, or a
  maintenance window.
- **Signing key** - verifiers must accept both keys before the signer switches,
  so the overlap window is set by the slowest verifier, and the old key is
  retired only after nothing signed with it is still in flight.
- **OAuth client secret** - refresh tokens issued under the old secret may
  survive it; check whether the provider invalidates them, because "we rotated
  the secret" and "old sessions are dead" are different claims.

## Boundary

OMH core makes no network calls, so the rotation itself is always the
operator's execution. This is the sequence and its proof step. A delivered
sequence is not a rotation that happened, a planned verify step is not observed
evidence, and a credential is reported rotated only from an observed failure
with the old one.

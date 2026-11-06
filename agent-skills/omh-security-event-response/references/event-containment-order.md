# Event Containment Order

Load this while responding to a security event. OMH never scans, never contacts a registry, and rotates nothing: every advisory, scanner result, revocation, and rewrite below is something the executor or operator runs and reports back. Each step is `prepared` until its output is observed, and the event stays open while any closing step is prepared.

## 1. Leaked secret

Decide the case first, and write down the evidence for it. **Compromised:** the secret was pushed to a public repository or log, or the issuer's access log shows a call nobody made. The exposure outranks availability, so revoke first (step 3 before step 2), accept the outage, then issue and deploy the replacement. **Planned:** only when all of these are shown by evidence: the repository is private, the issuer's access log (read it first, before changing anything) shows no call you cannot attribute across the window, and the window is short. **If any of them cannot be shown, treat the case as compromised.** Use the order in the table for a planned case; it keeps the service up through an overlap window. The case rule is the same one `omh-security-safety-review/references/credential-rotation.md` states for any rotation.

| Order | Step | Observed when |
| --- | --- | --- |
| 1 | Record the credential type, its scope, where it was pushed, whether the repository or log is public, and the first push time; read the issuer's access log now if one exists | the push is located in the history or the log |
| 2 | Issue the replacement and deploy it to every consumer | the service runs on the new credential |
| 3 | Revoke the leaked credential at its issuer | a call with the old credential is rejected; the revoke command's exit status only says the request was accepted |
| 4 | Audit the issuer's access log for the exposure window | the window's calls are listed and attributed |
| 4a | Remove persistence: list the identities, keys, roles, grants, and automations created in the window and remove or revoke them; treat tokens and sessions derived from the credential as live until they expire or the identity's permissions are removed, and record the longest lifetime | every created item is removed, and derived tokens have either passed their longest lifetime or a call with the identity, with its permissions removed, is refused |
| 5 | Rewrite history (`git filter-repo`, BFG) and coordinate every clone, only if the value must also leave the repository | the rewritten refs are pushed and forks and caches are named |
| 6 | Add prevention: push protection, a pre-commit secret scan, the ignore rule | the guard rejects a planted test secret |

Rotation comes before any rewrite. A rewrite does not reach clones, forks, CI caches, or a scraper that read the public push in its first minutes, so a rewrite without a rotation leaves a live credential in circulation. The per-credential issue-deploy-verify-revoke steps live with `omh-security-safety-review` (`credential_rotation_sequence/v1`); this event owns the order around them and the closure.

## 2. CVE or advisory in a dependency

1. Read the advisory: id (CVE, GHSA), affected range, fixed version, vulnerable function or input.
2. Read the installed version from the lockfile, not the manifest range, including every transitive path to the package.
3. Reachability: find the repository call sites that reach the vulnerable function or accept the vulnerable input, or observe that none do.
4. Severity: start from the advisory score, then adjust. Reachable from untrusted input on a request path keeps it; reachable only from trusted input or tooling lowers it; unreachable is a scheduled upgrade, not an event, unless the advisory is listed as exploited in the wild (CISA KEV) or has a published exploit; then the upgrade is next, not scheduled. State the adjustment and its evidence.
5. Contain: upgrade to the fixed version, pin or override a transitive version, or disable the feature path; a workaround is recorded as a workaround, not a fix.
6. Close only when the fixed version is observed in the lockfile and the build that ships it.

When the fixed version is only in a new major, hand the migration to its own staged upgrade plan and keep this event open, with the workaround in place, until that fix is observed.

## 3. License question

| License family | Typical obligation | Risk for closed distribution |
| --- | --- | --- |
| MIT, BSD, Apache-2.0, ISC | keep the notice; Apache-2.0 adds the NOTICE file and a patent grant | low |
| MPL-2.0 | modified files of the library stay open | low to moderate |
| LGPL | allow relinking; ship the library dynamically or provide objects | moderate |
| GPL-2.0, GPL-3.0 | the combined work is distributed under the GPL | high when distributed |
| AGPL-3.0 | network use counts as distribution | high for a hosted service |
| No license, custom, or "non-commercial" | no grant by default | needs counsel |

Read the declared license from the package metadata and the repository `LICENSE`, not from a README badge. The verdict is fits, conflicts, or needs counsel, for the stated distribution model; anything past the declared terms is a legal question for counsel.

## 4. Suspected unauthorized access

An unfamiliar admin login, a possible account takeover, or data leaving that nobody sent is an event with no code to patch. In order: (1) take the quick evidence first (export the relevant logs, note the account state) without delaying containment of an exfiltration in progress, and snapshot the host when that costs no time; (2) contain, by disabling the account, revoking its sessions and tokens, and isolating the host; (3) scope from the logs what the identity touched and when; (4) remove persistence as in section 1; (5) check the notification obligations and their clocks with the owner and counsel; (6) when the access is ongoing or the service is affected, hand command to `omh-live-incident-response` with this record as input.

## 5. Closure

`event_closure_verdict/v1` is closed only when every closing step is observed: the rotation, the old credential's rejection and an empty persistence list for a secret, the fixed version in the shipped build for a CVE, the recorded decision for a license, and the observed refusal of the identity's sessions with an empty persistence list for unauthorized access. Name each step that is still prepared.

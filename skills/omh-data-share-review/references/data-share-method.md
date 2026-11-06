# Data Share Method

Load this while preparing a file to leave the team. OMH prepares; the scan runs where the user or the session's tools run, and the file's verdict stays `not_observed` until its scan counts are observed. Where a team or regulator rule is stricter than this page, that rule governs; say which one was used.

## 1. Field classes

A field's class comes from its content, not its name: a `notes` column holds emails, and a `ref` column can hold an account number.

| Class | Examples | Default action |
| --- | --- | --- |
| direct identifier | name, email, phone number, postal address, customer or account number, national id, device id, IP address, user handle | drop; pseudonymize only when the destination must join rows |
| quasi-identifier | birth date, postcode, age, gender, job title, employer, exact timestamps, a rare value | generalize (year, region, band) or drop |
| secret | API key, token, password, session cookie, private key, connection string with credentials | drop; a secret found in the data is also a leak to rotate |
| free text | notes, comments, ticket bodies, transcript excerpts, log messages, URLs with query strings | drop, or keep only after the scan counts it clean |
| sensitive category | health, biometric, genetic, political, union, religion, sexual orientation, criminal record | drop or aggregate; count groups smaller than k within these fields |
| not personal | product id, count, price, status code | keep when the destination needs it |

## 2. Minimization order

1. Drop every field the destination did not ask for.
2. Generalize the quasi-identifiers that stay: a date to its month or year, a postcode to its region, an age to a band.
3. Pseudonymize a direct identifier only when rows must stay joinable.
4. Mask what must stay partly readable (the last four digits), knowing a masked value is still a quasi-identifier.

## 3. Pseudonymization

- Use a keyed hash (HMAC-SHA256 with a key made for this share) or a random token table. A plain hash of an email or a phone number is reversible by hashing candidate values.
- The key or the table is the mapping. Keep it at a local path outside the shipped file and its folder; never commit, attach, or upload it.
- A new destination gets a new key, so two shared files cannot be joined against each other.

## 4. Residual scan, counted per class

Run it on the exact file that leaves, after the last transform, and print counts only. A count of `0` is a result; a scan that did not run is `not_observed`.

| Class | What to count |
| --- | --- |
| direct identifier | email shapes; phone number shapes; card numbers that pass the Luhn check; IP addresses; national-id shapes for the countries in scope, each with its check digit where one exists (Korean resident registration number: 6 digits, optional hyphen, 7 digits; US SSN shape; passport shapes the user names); bank account shapes and mobile formats for the countries in scope (for Korea `01[016789]` with or without hyphens); and each original value of a dropped or pseudonymized identifier column, matched exactly in the output |
| secret | vendor key prefixes, bearer tokens, private key headers, password assignments, connection strings with credentials |
| quasi-identifier | rows whose combination of kept quasi-identifiers is shared by fewer than k rows; k comes from the team, and 5 is a common starting point |
| sensitive category | groups of rows smaller than k within the kept sensitive fields |
| free text | the direct-identifier shapes above and the original identifier values, inside each free-text field; names only against a supplied list of known names (customers, staff), exact and case-folded |

The original-value check is the one a pattern scan cannot replace: a pseudonymized email column passes every email pattern while a notes field quotes the same address. Run it as a script that reads the source column and the output file and prints one count; never type a value into a search pattern, which puts it into the session.

A name-recognition tool may add candidates; its hits are leads for the user to accept, and a clean name result reads `checked against N known names`, never `no names`. Confirm the countries in scope before the scan.

Verdict: `redacted` when every class counts zero, or each remaining hit is named and accepted by the user; `not_observed` when no scan ran or the digest of the scanned bytes differs from the share record's; otherwise not redacted, with the counts. `redacted` means the scan counted zero in each class, not that the data is anonymous: a file with pseudonymized identifiers or kept quasi-identifiers is `pseudonymized`, still personal data, and the lawful-basis question stays with `omh-legal-compliance-review`.

## 5. Share record

Destination, date, fields shipped, row count, the sha256 digest of the shipped file (the scan record carries the same digest), and the scan reference. No value from the file, no mapping, no key.

## 6. What Hermes redacts on its own

- `privacy.redact_pii` (off by default) hashes user and chat identifiers in the gateway's session prompt on platforms marked PII-safe; WhatsApp, Signal, and Telegram are among them, while Discord and Slack are left out, since a mention there needs the raw id. Display names are not changed.
- `security.redact_secrets` (on by default) masks secret-shaped strings in tool output before they enter the session and its logs.

Neither edits a file on disk or a file that leaves, so neither replaces the scan in section 4.

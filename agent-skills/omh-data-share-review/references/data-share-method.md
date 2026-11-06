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
| sensitive category | health, biometric, genetic, racial or ethnic origin, political opinion, philosophical or religious belief, union membership, sex life or sexual orientation, criminal record | drop or aggregate; count groups smaller than k within these fields |
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
| direct identifier | email shapes; phone number shapes; card numbers that pass the Luhn check; IP addresses; national-id, bank-account and mobile shapes for the countries in scope (patterns below); and each original value of a dropped or pseudonymized identifier column, matched exactly in the output |
| secret | vendor key prefixes, bearer tokens, private key headers, password assignments, connection strings with credentials |
| quasi-identifier | rows whose combination of kept quasi-identifiers is shared by fewer than k rows; k comes from the team, and 5 is a common starting point |
| sensitive category | groups of rows smaller than k within the kept sensitive fields |
| free text | the direct-identifier shapes above and the original identifier values, inside each free-text field; names only against a supplied list of known names (customers, staff), exact and case-folded |

The original-value check is the one a pattern scan cannot replace: a pseudonymized email column passes every email pattern while a notes field quotes the same address. Run it as a script that reads the source column and the output file and prints one count; never type a value into a search pattern, which puts it into the session.

A name-recognition tool may add candidates; its hits are leads for the user to accept, and a clean name result reads `checked against N known names`, never `no names`. Confirm the countries in scope before the scan.

Scan patterns. Run them on text normalized with NFKC (fullwidth digits and dashes become ASCII), as PCRE patterns in a detector script or `rg -P`: `search_files` is ripgrep without look-around, so these patterns fail there, and a `total_count` of 0 beside an `error` is not a count. A valid-date test also needs a script. In every pattern the separator class covers spaces, the hyphen and dash family, the minus sign and dots, and the mask class is `*`, `x`, `X`, `#`, `●`, `○`, `■`, `□`, `•`.

- Korean resident registration number: `(?<!\d)\d{6}[\s\-\u2010-\u2015\u2212.]{0,3}[1-8]\d{6}(?!\d)`, then check that the first six digits form a valid date. A tail masked fully or after the gender digit: `(?<!\d)\d{6}[\s\-\u2010-\u2015\u2212.]{0,3}(?:[1-8][*xX#\u25cf\u25cb\u25a0\u25a1\u2022]{6}|[*xX#\u25cf\u25cb\u25a0\u25a1\u2022]{7})`. Never use the check digit as a filter: numbers issued since October 2020 reportedly carry a random tail, so the check digit may raise confidence and must never drop a hit.
- US SSN: `(?<!\d)(?!000|666|9\d\d)\d{3}[\s\-\u2010-\u2015\u2212.]{0,3}(?!00)\d{2}[\s\-\u2010-\u2015\u2212.]{0,3}(?!0000)\d{4}(?!\d)`; ITIN-shaped (area 9xx, reported separately, still a personal tax id): `(?<!\d)9\d{2}[\s\-\u2010-\u2015\u2212.]{0,3}\d{2}[\s\-\u2010-\u2015\u2212.]{0,3}\d{4}(?!\d)`; masked leading digits: `(?<![\dA-Za-z])[*xX#\u25cf\u25cb\u25a0\u25a1\u2022]{3}[\s\-\u2010-\u2015\u2212.]{0,3}[*xX#\u25cf\u25cb\u25a0\u25a1\u2022]{2}[\s\-\u2010-\u2015\u2212.]{0,3}\d{4}(?!\d)`.
- Korean mobile number: `(?<![\d.])\(?(?:(?:\+|00)?82[\s\-\u2010-\u2015\u2212.]{0,3}(?:\(0\)[\s\-\u2010-\u2015\u2212.]{0,3})?0?|0)1[016789]\)?[\s\-\u2010-\u2015\u2212.]{0,3}\d{3,4}[\s\-\u2010-\u2015\u2212.]{0,3}\d{4}(?!\d)` (national, `+82`, `0082` and `(0)` forms); with the leading zero dropped, shape-only: `(?<![\d.])1[016789][\s\-\u2010-\u2015\u2212.]{0,3}\d{3,4}[\s\-\u2010-\u2015\u2212.]{0,3}\d{4}(?!\d)`.
- Shape-only counts, reported beside the full hits and accepted by column, never ignored: bare 13 digits `(?<!\d)\d{13}(?!\d)` and bare 9 digits `(?<!\d)\d{9}(?!\d)`. Barcodes starting 880 and date-based order ids are full resident-number hits; accept them by column.

A pattern scan is a floor. Zero hits never prove a file is `redacted`, for any string a pattern misses. Free-text fields also need a sample read by the reviewer, and `residual_scan/v1` records which fields and how many rows were read.

Verdict: `redacted` when every class counts zero and the free-text sample read found nothing, or each remaining hit is named and accepted by the user; `not_observed` when no scan ran, no free-text sample was read or the digest of the scanned bytes differs from the share record's; otherwise not redacted, with the counts. The verdict says what the scan and the read found, not that the data is anonymous. Record a separate `data_state` on the share record: `personal data` by default, `pseudonymized, still personal data` when identifiers were replaced by tokens or hashes; the scan never earns `anonymous`. The lawful-basis question stays with `omh-legal-compliance-review`.

## 5. Share record

Destination, date, fields shipped, row count, the sha256 digest of the shipped file (the scan record carries the same digest), the `data_state`, and the scan reference. No value from the file, no mapping, no key.

## 6. What Hermes redacts on its own

- `privacy.redact_pii` (off by default) hashes user and chat identifiers in the gateway's session prompt on platforms marked PII-safe; WhatsApp, Signal, and Telegram are among them, while Discord and Slack are left out, since a mention there needs the raw id. Display names are not changed.
- `security.redact_secrets` (on by default) masks secret-shaped strings in tool output before they enter the session and its logs.

Neither edits a file on disk or a file that leaves, so neither replaces the scan in section 4.

# Data Share Review

Load this on-demand contract after the compact `data-share-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Whether the data may lawfully leave at all -- the lawful basis, a DPA, consent, or a cross-border transfer -- is a contract and compliance question; use `omh-legal-compliance-review`, then return here for the fields.
- The exposure is an agent's tool permissions, a secret in code, or a prompt-injection path rather than a file about to leave; use `omh-security-safety-review`.
- The ask is analysing the dataset itself -- trends, a cleanup, a chart; use `omh-data-analysis`.
- Filing the issue once its attachment is clean -- the title, labels, and reproduction steps; use `omh-github-issue-intake`.
- Building the training set or deciding whether to train once the corpus is clean; use `omh-model-finetuning`.
- Working the support queue -- triaging or answering tickets rather than exporting them; use `omh-support-operations`.

## Examples

Good example:

- Prompt: the analytics vendor wants last month's ticket export, take the customer details out first
- Expected behavior: Ask what the vendor needs, inventory the columns from the header and per-column shape counts, drop the ones it does not need, pseudonymize the customer id with the mapping kept in a local folder, count email shapes, phone shapes, secret shapes and every original identifier value in the output with a scan that prints counts only, and write the share record.
- Why: A masking step that was never followed by a scan of the shipped file has not shown that anything came out.

Bad example:

- Prompt: I ran find and replace on the emails, so the file is clean, right
- Expected behavior: Hold the verdict at not_observed: count every class in the exact file that leaves, free-text fields included, before calling it redacted.
- Why: A find and replace covers the shapes it was given; names and account numbers in a notes column stay.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the file or export about to leave, the destination it goes to, and the countries whose id and phone formats apply
- why the destination needs it, which decides the fields it may keep
- the header or schema, and per-column shape counts when a field's content is unclear
- where the pseudonym mapping may be kept locally, when a field must stay joinable

Expected outputs:

- field_inventory/v1
- minimization_plan/v1
- residual_scan/v1
- share_record/v1

Artifact expectations:

- field_inventory/v1 lists every column, key, and free-text field with its class -- direct identifier, quasi-identifier, secret, free text, sensitive category, or not personal -- and the evidence for the class
- minimization_plan/v1 gives each field one action -- drop, aggregate, generalize, mask, or pseudonymize -- with the destination's need for the fields it keeps, and names the local path that holds any pseudonym mapping outside the shipped file
- residual_scan/v1 records, for the exact file that leaves, the scan method and an observed count per class with zero hits or each remaining hit accepted by name, its sha256 of the scanned bytes, the free-text sample the reviewer read, and its verdict: redacted, not redacted with the counts while a hit remains unaccepted, or not_observed when no scan ran, no free-text sample was read or its digest differs from the share record's
- share_record/v1 is metadata only -- destination, date, fields shipped, row count, the sha256 digest of the shipped file, and its data_state (pseudonymized, still personal data, when identifiers were pseudonymized) -- and holds no value from it
- optional offline counts-only residual scan via `toolkit/scripts/residual_scan.py` (`residual_scan/v1`, never prints matched values)

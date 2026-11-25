---
name: "omh-data-share-review"
description: "[omh] Before data leaves the team: a dataset, log, ticket export or transcript excerpt bound for a vendor, a public issue, a model provider or a training corpus; classify every field, minimize first, pseudonymize with the mapping kept local, and call it redacted only after an observed residual scan. Use when the user says: data-share-review, data share review, pii redaction, redact pii, pseudonymize, de-identify, anonymize the dataset, residual pii."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: data-share-review
    role: reviewer
    quality_tier: observed-residual-scan
    related_skills: [omh-legal-compliance-review, omh-security-safety-review, omh-data-analysis, omh-github-issue-intake, omh-model-finetuning, omh-support-operations]
---

# Data Share Review

Required: the file or export about to leave, the destination it goes to, and the countries whose id and phone formats apply, why the destination needs it, which decides the fields it may keep, the header or schema, and per-column shape counts when a field's content is unclear, where the pseudonym mapping may be kept locally, when a field must stay joinable. Output: field_inventory/v1, minimization_plan/v1, residual_scan/v1, share_record/v1.

## Why This Exists

`data-share-review` exists because data leaving the team had no owner: Hermes redacts identifiers in gateway chat and secrets in tool output, `omh-security-safety-review` reviews an agent's own exposure, and `omh-legal-compliance-review` reads the obligations, while nothing minimized a file's fields, kept its pseudonym mapping local, and refused to call it redacted before a scan of what actually leaves.

## First Steps

- Ask where the file goes and what the destination needs it for before touching a field.
- Inventory the fields from the header and the schema before planning any masking.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a dataset, log bundle, ticket or CRM export, or transcript excerpt is about to leave the team -- to a vendor or contractor, a public issue, a model provider, or a training corpus -- and its personal data, identifiers, and secrets must come out first. The output is a field inventory with each field's class, a minimization plan, a residual scan of the file that leaves with counts per class, and a metadata-only record of what left; OMH uploads nothing and keeps no raw data.

    Strong routing signals: `data-share-review`, `data share review`, `pii redaction`, `redact pii`, `pseudonymize`, `de-identify`, `anonymize the dataset`, `residual pii`, `redact the pii`, `redact personal data`, `strip pii`, `strip the pii`, `remove pii`, `remove the pii`, `scrub pii`, `scrub the pii`, `mask pii`, `mask personal data`, `remove personal data`, `scan for pii`, `pseudonymise`, `pseudonymizing`, `pseudonymization`, `pseudonymisation`, `de-identifying`, `deidentify`, `quasi-identifier`, `quasi-identifiers`, `direct identifiers`, `anonymize this dataset`, `anonymize the data`, `anonymize the logs`, `redact the logs`, `redact these logs`, `개인정보`, `개인 정보`, `고객 정보`, `고객정보`, `민감정보`, `민감 정보`, `식별 정보`, `식별정보`, `식별자`, `주민번호`, `주민등록번호`, `전화번호`, `연락처`, `계좌번호`, `카드번호`, `실명`, `이메일 주소`, `익명화`, `익명 처리`, `익명처리`, `가명화`, `가명 처리`, `가명처리`, `비식별`, `벤더`, `외부`, `업체`, `협력사`, `파트너사`, `거래처`, `제3자`, `외주`, `대행사`, `에이전시`, `연구자`, `연구기관`

## Catalog Metadata

Category: `review`
Phase: `data-share-review`
Hermes role: `reviewer`
Quality tier: `observed-residual-scan`
Reasoning demand: `standard`

Quality bar:

- Inventory fields from the header and the schema, read with `read_file` and its line limit; when a field's class is unclear, prefer a script that prints per-column shape counts, and read a row only when that still leaves it unclear, because every row read enters the session.
- Load `references/data-share-method.md` for the field classes, the minimization order, the pseudonymization method, the per-class scan patterns, and the quasi-identifier group check instead of recalling them.
- Count each class with `search_files` in its `count` output mode, or with a detector script run through `execute_code` when `execute_code` is in your tool list or tool_search finds it; its stdout returns, and so do stderr and any traceback, so it prints counts only and catches its own errors without echoing a value. With neither, hand the user the scan to run and keep the verdict not_observed until the counts come back.
- Hermes' `privacy.redact_pii` hashes user and chat identifiers in the gateway's session prompt on the platforms that allow it, and `security.redact_secrets` masks secret-shaped strings in tool output; neither changes a file that leaves, so neither is this scan.
- Run `toolkit/scripts/residual_scan.py` (see `skill_view(name='omh-data-share-review', file_path='toolkit/README.md')`, counts-only, never prints matched values) on the exact file that leaves to produce the observed `residual_scan/v1` record.
- Keep inventoried, minimized, masked, scanned, and shipped as separate states for the file.

Handoff policy:

Keep the field inventory, minimization plan, residual scan result, and share record in Hermes. Field classes come from the header, the schema, and per-column shape counts; scan counts come only from an observed scan of the exact file that leaves; OMH uploads nothing, stores no raw value, and keeps no pseudonym mapping.

Safety rules:

- Call the output redacted only after an observed residual scan of the exact file that leaves, counted per class; without one the state is not_observed, whatever the masking step reported.
- Minimize before masking: drop every field the destination does not need, because a masked field that ships still links rows back to people.
- Keep the pseudonym mapping local, outside the shipped file and its folder; a mapping that travels with the data reverses it.
- Treat free text as unscanned until the residual scan counts it: notes, comments, and transcript excerpts hide names, emails, and account numbers that a column plan never touches.
- A scan prints counts, never matched values; a hit printed to the session reaches the model provider the same way the raw file would.
- OMH uploads nothing, keeps no raw value, and records only the metadata-only share record; whether the data may lawfully leave at all is not decided here.

## Completion Checklist

- Every field has a class and an action, and each kept field names the destination's need for it.
- The pseudonym mapping, if any, sits at a local path outside the shipped file.
- The residual scan ran on the exact file that leaves and counted every class, free text included.
- The verdict is redacted only with that scan observed; otherwise it reads not_observed.
- The share record holds destination, date, fields, row count, and digest, and no value from the file.

## Recovery Notes

- If the scan cannot run in this session, hand the user the per-class scan and keep the verdict not_observed until the counts come back.
- If a class still has hits after masking, fix the field or the free text and scan again; never ship on an explained hit that was not accepted by name.

## Runtime Evidence

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill data-share-review --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

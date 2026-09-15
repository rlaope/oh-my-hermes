# Toolcall Rules

User-authored rules that block a Hermes tool call the moment it matches a
pattern you wrote. Rules sit dormant until the model goes off-script; when a
call matches, the call is refused before execution and the model reads your
rule text as the tool result, then course-corrects. You pay no context cost on
calls that never match.

Enforcement rides the OMH plugin's `pre_tool_call` hook using the Hermes
host's own block directive (`hermes_cli/plugins.py`,
`_get_pre_tool_call_directive_details`): a hook may return
`{"action": "block", "message": ...}` and the message becomes the tool result
the model sees.

## Opt-in

Create the rules file — its presence is the opt-in:

```
$OMH_HOME/rules/toolcall-rules.json     (default: ~/.omh/rules/toolcall-rules.json)
```

```json
{
  "schema_version": "omh_toolcall_rules/v1",
  "rules": [
    {
      "name": "no-box-leak",
      "pattern": "Box::leak",
      "message": "Do not reach for Box::leak in production code paths; use Arc instead.",
      "tools": ["write_file", "patch", "execute_code"],
      "repeat": "once"
    }
  ]
}
```

## Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Unique rule name, at most 64 characters. Shown in the block message. |
| `pattern` | yes | Python regex, at most 512 characters, matched against the tool name plus the JSON-serialized tool arguments (first 20,000 characters). Patterns that nest unbounded repeats — `(a+)+`, `(x*)*` — are refused as catastrophic-backtracking shapes. |
| `message` | yes | The rule text the model reads, at most 1,000 characters. |
| `tools` | no | Tool names this rule watches (at most 16). Empty or omitted means every tool. |
| `repeat` | no | `"once"` (default): fire at most once per session, so a blocked retry cannot loop. `"always"`: fire on every matching call. |

Rules match in file order; the first match wins. At most 64 rules are read,
and a file over 262,144 bytes is ignored whole.

## Validation

The enforcing hook fails open — an invalid rule is silently skipped — so
validate after editing:

```sh
omh ops toolcall-rules-validate            # default path
omh ops toolcall-rules-validate --path …   # explicit file
```

Exit 0 with `"valid": true` means every rule parses and loads; exit 1 lists
each defect with its rule index, including patterns the enforcing hook would
refuse and a file-size overflow that would disable the whole file.

## Rehearsing a planned batch

Validation answers whether your rules load. It does not answer whether the
batch you are about to schedule will get through them. Before a cron entry or
an unattended run starts, rehearse its planned calls — nothing is executed and
nothing is written:

```sh
omh ops permission-rehearse --plan planned-batch.json
```

The plan lists the `(tool, args)` pairs the run intends to issue:

```json
{
  "schema_version": "omh_permission_rehearsal_plan/v1",
  "calls": [
    {"tool": "write_file", "args": {"path": "src/lib.rs", "content": "Box::leak(x)"}},
    {"tool": "read_file", "args": {"path": "README.md"}}
  ]
}
```

Each planned call comes back with one verdict:

| Verdict | Meaning |
| --- | --- |
| `refused` | A rule matches the call. The row names the rule; the enforcing hook would return the block directive and the call would not run. |
| `unknown` | No rule refuses the call, and whether Hermes stops it for approval **is not derivable here** — that lives in Hermes' per-tool approval declarations, which OMH has no reader for. |

`unknown` is not permission, and the summary has no allowed bucket to fold
one into: it counts `planned`, `refused`, and `unknown` only. The payload also
carries `approval_bypass`, because a rehearsal run while a bypass is active
describes a policy nobody is currently applying — `summary.approval_bypass_active`
is the one-field answer, projected from `approvals.mode` in `config.yaml` plus
the live session's persisted `/yolo` flag.

Unlike the rules file it reads, the plan fails **closed**: a plan document OMH
cannot read whole is an error, never a quiet "nothing refused".

Exit codes, for the cron wrapper that reads only the status:

| Code | Meaning |
| --- | --- |
| `0` | No rule refuses any planned call. Not a claim that they are allowed. |
| `1` | At least one planned call is refused. |
| `2` | The command could not run — usually a plan file that does not parse. |
| `3` | The rules file is present but defective, so the refusal verdicts answered from a policy you did not write. Run `omh ops toolcall-rules-validate`. |

A batch is rehearsed as one fresh session in plan order, so a `repeat: "once"`
rule refuses the first matching call and the rest proceed past it — what the
hook would do to that batch.

## Boundaries

- Everything fails open: a missing, malformed, or oversized rules file and any
  single invalid rule degrade to "no intervention", never to a broken hook.
- A returned block directive is a request to the host. OMH does not observe
  whether the host honored it, so a block is never recorded as evidence that
  OMH stopped anything (see the enforcing/observing split in
  `src/workflows/blocked_work_records.py`).
- The block message contains only your rule text plus a fixed suffix; tool
  input is never echoed back into context.

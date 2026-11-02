# Fanout child-environment policy

Fanout child processes use `child_environment_policy/v1`. The default is least privilege: a child receives only portable process variables, its selected owner's state location, dispatch lineage, and capability names explicitly declared for that child. It never inherits the ambient parent environment wholesale.

## CLI declarations

`omh coding fanout dispatch` and `omh coding run` accept name-only declarations:

```sh
omh coding fanout dispatch --owner-env codex:ISSUE_TRACKER_TOKEN \
  --project-env CI --verification-env TEST_DATABASE_URL --run-verification
```

- `--owner-env OWNER:NAME` grants an existing parent value only to that owner's work process. Repeat it for multiple grants.
- `--project-env NAME` grants an existing parent value to owner and verification environments.
- `--verification-env NAME` grants an existing parent value to verification environments only.
- `--deny-env NAME` removes a parent-only variable from every child; an unrelated denied parent name remains ready, while denying an explicitly requested grant fails before spawn.
- `--allow-broad-environment` is an explicit temporary compatibility mode. It restores parent inheritance and labels every policy receipt `compatibility_explicit`; remove it after migrating declarations.

Arguments accept variable *names*, not values. Missing required names fail the affected unit before spawn. A verification environment does not receive owner-only grants. Verification-command environment overrides are also checked: sensitive names require an explicit verification grant. Existing file, keychain, socket, and native-agent authentication flows remain untouched because the policy neither reads nor requires credentials as environment values.

## Stored defaults

Flags last one command. Grants an operator needs on every run, including runs an agent starts (ulw-maestro, a dag node exported to a coding owner), go in `<omh_home>/coding/fanout-settings.json`:

```json
{
  "schema_version": "omh_fanout_settings/v1",
  "environment_policy": {
    "owner_capabilities": {"codex": ["ISSUE_TRACKER_TOKEN"]},
    "project_variables": ["CI"],
    "verification_capabilities": [],
    "denied_names": []
  },
  "codex": {"windows_sandbox": "mxc"}
}
```

Every dispatch reads it and adds its names to the command's own declaration. A flag can add names for one run, but it cannot drop a stored one. The file holds names only. It cannot turn on broad inheritance, which stays the per-command `--allow-broad-environment`. With no file, nothing changes. A file that exists but does not parse or validate stops the dispatch with an error naming the file, because silently dropping a grant the operator wrote down is the failure the file exists to prevent. `codex.windows_sandbox` is described under "Codex on native Windows" below.

## Programmatic API

Pass the same shape to `dispatch_fanout(..., environment_policy=...)`:

```python
{
    "owner_capabilities": {"codex": ["ISSUE_TRACKER_TOKEN"]},
    "project_variables": ["CI"],
    "verification_capabilities": ["TEST_DATABASE_URL"],
    "allow_broad_inheritance": False,
}
```

`resolve_child_environment()` returns the filtered `environment` and a receipt. The receipt records schema, owner, purpose, status, bounded names passed/removed/approved/denied/missing, counts and truncation markers, classification/reason/policy source, and a digest of the full effective name-only decision. It contains no environment values. The journal retains only this validated, bounded name-only receipt for the owner process; integration and unit verification receipts remain in the dispatch summary. Operator note: nonportable parent names are omitted from journalable previews, while their full name-only decision remains reflected in counts, truncation markers, and the digest.

This is a process-environment boundary, not proof that a tool used a capability or that the capability was protected after it reached that process. Child subprocesses can still pass their received variables onward.

## Portable base on Windows

The portable base includes the Windows system variables a native child needs to start: `SYSTEMDRIVE`, `SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATHEXT`, `HOMEDRIVE`, `HOMEPATH`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP` and `TMP`. None of them carries a credential. `SYSTEMDRIVE` is required by Codex's MXC sandbox, which otherwise refuses every shell call with `MXC requires nonempty Unicode host SystemDrive` (#2471).

## Codex on native Windows

On native Windows, `codex exec` runs its session read-only unless `config.toml` selects a sandbox backend, even with `-s workspace-write`. Every write the unit needs is then refused, and the unit ends without a result. Set one of the backends Codex documents in `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`, or the project's `.codex/config.toml`):

```toml
[windows]
sandbox = "mxc"   # native isolation on recent Windows 11 builds; else "elevated", then "unelevated"
```

Or let OMH pass it: `"codex": {"windows_sandbox": "mxc"}` in `coding/fanout-settings.json` makes every codex dispatch run `codex exec --config windows.sandbox=mxc ...`, which takes precedence over the Codex config files. The value must be `mxc`, `elevated` or `unelevated`.

When a unit fails because of the sandbox, the failure diagnostic names it instead of `malformed_result` or `nonzero`: `executor_sandbox_read_only` when Codex printed that a write was blocked by the read-only sandbox, and `executor_sandbox_start_failed` when MXC refused to start (`MXC requires nonempty Unicode host ...`). The journal summary names the fix. Only the reason is recorded; the matched output is not retained.

`omh coding executor-readiness --executor codex` reads the backend on Windows (OMH's setting first, then the project and user Codex config) and reports it as `windows_sandbox`. With no backend set it keeps `available: true` (the binary runs), adds the read-only warning to the summary, and sets `next_action` to `configure_codex_windows_sandbox`. It reads the user and project config files only: managed `requirements.toml`, `-c` overrides and config profiles are not read, and it does not start a sandbox. To confirm that the backend starts on the host, run Codex's own probe: `codex -c windows.sandbox=mxc sandbox --permission-profile :workspace -- cmd.exe /d /c echo OK`.

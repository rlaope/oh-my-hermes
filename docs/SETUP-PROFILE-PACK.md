# Moving a Configured OMH Profile

`omh setup` configures a machine: the coding owner, the operating model, the
memory mode, the capability policy, the MCP host recipe, the Hermes model
aliases. Until now nothing serialized any of that back out, so reproducing the
setup on a second machine — or handing it to a teammate — meant retyping flags
from memory.

Two commands close that.

```sh
omh setup-profile export --output profile-pack.json     # on the configured machine
omh setup-profile apply --from profile-pack.json        # dry run on the other one
omh setup-profile apply --from profile-pack.json --apply
```

`apply` is a dry run until `--apply`, the same shape as `omh ops rules-import`.

## Transport is yours, not OMH's

Export writes a local file. Apply reads a local file. Getting the file from one
machine to the other is your own git repository, `scp`, or file copy.

OMH makes no network calls, and a pack that fetched or pushed itself would
cross that line. There is deliberately no `--from <url>`.

## What the pack carries

| Section | From | Applied by `apply` |
| --- | --- | --- |
| `profile` | `~/.omh/setup-profile.json` | Yes — coding owner, operating model, memory mode, selected categories |
| `capability_policy` | the same file, rebuilt from its disable list | Yes |
| `mcp` | the recorded MCP host config install | Only under `--with-mcp` |
| `model_aliases` | `model.aliases` in the Hermes config | No — reported, with the command that writes them |
| `manifest` | built at export | n/a — pack id, section digests, the OMH version that built it |
| `withheld` | built at export | n/a — every field the export refused to carry, and why |

The `pack_id` is content-addressed, so two exports of an unchanged
configuration carry the same id and you can tell "unchanged" from
"re-exported".

## What never enters the artifact

Redaction reuses the same primitives every OMH record store screens against —
`RAW_OR_HIDDEN_KEYS` in `src/system/append_only_store.py` and the predicates in
`src/system/metadata_safety.py`. There is no second denylist to drift from
them.

A field is withheld when:

- its name marks credential material (`token`, `secret`, `api_key`, …), or
  names a raw or hidden payload (`prompt`, `transcript`, `stdout`, …);
- its value is credential-shaped (an issued `ghp_`/`sk-`/`AKIA…` string);
- its value is a machine-local path or a link, which would not resolve on the
  other machine anyway.

**Every withheld field is named.** The `withheld` list in the pack, the export
report, and the apply report all carry the field path and the reason. A silent
drop would make an incomplete artifact look complete, which is the failure this
feature exists to avoid — so it is treated as a defect, not as redaction
working.

## What `apply` will not write for you

Some fields are carried, reported, and deliberately not written. Each one comes
back with the reason and, where one exists, the exact command that does write
it:

- **Hermes model aliases.** Writing them goes through
  `omh setup --model-setup --apply-model-config`, which binds the write to a
  Hermes config digest and an explicit confirmation. A pack apply carries
  neither, so it hands you the fully-formed command instead.
- **The MCP host config**, unless you pass `--with-mcp`. It writes another
  product's configuration file (Codex's `config.toml`, Claude Code's
  `.claude.json`, …), which a profile apply should not do unasked. With
  `--with-mcp` it goes through the same writer `omh setup --with-mcp` uses;
  `--mcp-config-path` targets an explicit file instead of the host's default.
- **The org safety rule source**, when the source machine had it on. It names
  local file paths, which the export withheld; re-enable it with the paths that
  exist on the target.
- **An edited `parallelism` block.** `omh setup` writes the shipped defaults and
  accepts no parallelism flag. The row appears only when the source machine had
  actually edited the block, and it names the differing values so you can copy
  them across.

A value this OMH does not recognize — an executor name or an operating model a
newer OMH shipped — is reported as not applied with the accepted set named, and
every other field still lands. One unknown name should not cost you the rest of
the profile.

## A pack from a newer OMH is refused whole

If the pack (or its inner profile) declares a schema generation this install
does not know, `apply` refuses before the first write and says so:

```text
the setup profile pack is omh_setup_profile_pack/v2, written by a newer OMH;
OMH <this version> applies omh_setup_profile_pack/v1 only -- update OMH before
applying this pack. Nothing was written.
```

A pack whose schema this install simply does not recognize is refused the same
way, but without the "newer OMH" claim — an unknown name is not evidence that
the other side is ahead.

Half a profile in a shape nobody validated is not a partial success, so this
one is all-or-nothing rather than field-by-field.

## Not a team profile pack

`omh profile list` and `omh profile inspect` read the authored team role packs
in `src/profiles/team.py` — product content whose `install_command` points back
at `omh setup --profile-pack <id>`. Those describe roles OMH ships. A setup
profile pack describes one machine's own state. Same word, different things;
they have separate schemas and separate commands for exactly that reason.

## Evidence boundary

A setup profile pack records local OMH configuration. It carries no
credentials, moves itself nowhere, and is not execution, review, CI, or merge
evidence. Applying one records routing defaults; it does not prove Hermes used
a skill, that any executor ran, or that a host loaded the MCP bridge.

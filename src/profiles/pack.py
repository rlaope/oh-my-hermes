"""Serialize one machine's configured OMH setup profile, and apply it elsewhere.

`omh setup` already configures every ingredient of a profile -- the coding
owner, the operating model, the memory mode, the capability policy, the MCP
host recipe, the Hermes model aliases -- and nothing serialized any of it back
out. Reproducing a configured machine meant retyping `omh setup` flags from
memory.

`build_setup_profile_pack` reads that configured state into one local JSON
artifact, and `apply_setup_profile_pack` writes as much of the artifact as this
install's own setup writers accept. Neither is a team profile pack: the packs
in `profiles/team.py` are authored product content whose `install_command`
points back at `omh setup --profile-pack <id>`, and this one is a machine's
own state, which is why it has its own schema and its own commands.

Four boundaries hold this module to what it is:

- **No transport.** Export writes a local file; apply reads a local file.
  Moving one between machines is the person's own git or file copy. OMH makes
  no network calls, and a pack that fetched or pushed itself would cross that
  line.
- **No second denylist.** Redaction reuses `RAW_OR_HIDDEN_KEYS` and the
  `metadata_safety` predicates. A parallel list here would drift from the one
  every record store already screens against, and the drift would be silent.
- **Nothing is dropped silently.** Every field the export withholds and every
  field the apply does not write is named, with its reason, in the payload. A
  silent drop makes an incomplete artifact look complete, which is worse than
  carrying nothing.
- **An unknown pack is refused whole.** A pack whose schema this install does
  not know is rejected before the first write, never applied field by field.
  Half a profile in a shape nobody validated is not a partial success.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..capabilities.toggles import (
    CapabilityPolicyError,
    normalize_family_id,
    read_capability_policy,
    toggleable_family_ids,
    write_capability_policy,
)
from ..coding.executors import CODING_EXECUTOR_TARGETS
from ..local_store import read_json_object_result, utc_now
from ..maintenance.advisory import parse_hermes_model_aliases
from ..mcp.host_config import install_mcp_host_config
from ..paths import OmhPaths
from ..system.append_only_store import RAW_OR_HIDDEN_KEYS
from ..system.hashutil import sha256_text
from ..system.metadata_safety import is_secret_value_shaped, is_sensitive_metadata_text
from ..version import __version__
from .setup import (
    PARALLELISM_DEFAULTS,
    PROJECT_MEMORY_MODES,
    SETUP_PROFILE_SCHEMA_VERSION,
    build_parallelism_settings,
    read_setup_profile,
    setup_profile_choices,
    write_setup_profile,
)
from .team import operating_model_ids


SETUP_PROFILE_PACK_SCHEMA_VERSION = "omh_setup_profile_pack/v1"
SETUP_PROFILE_PACK_MANIFEST_SCHEMA_VERSION = "omh_setup_profile_pack_manifest/v1"
SETUP_PROFILE_PACK_MCP_SCHEMA_VERSION = "omh_setup_profile_pack_mcp/v1"
SETUP_PROFILE_PACK_MODEL_ALIASES_SCHEMA_VERSION = "omh_setup_profile_pack_model_aliases/v1"
SETUP_PROFILE_PACK_EXPORT_SCHEMA_VERSION = "omh_setup_profile_pack_export/v1"
SETUP_PROFILE_PACK_APPLY_SCHEMA_VERSION = "omh_setup_profile_pack_apply/v1"

SETUP_PROFILE_PACK_SECTIONS = ("profile", "capability_policy", "mcp", "model_aliases")

SETUP_PROFILE_PACK_CLAIM_BOUNDARY = (
    "A setup profile pack records one machine's local OMH configuration. It carries no credentials, "
    "moves itself nowhere, and is not execution, review, CI, or merge evidence."
)

# Why a value never leaves this machine. Each one names the property that makes
# the value unsafe or useless elsewhere, because "withheld" alone tells the
# reader nothing about whether to go find the value by hand.
WITHHELD_RAW_OR_HIDDEN = "field name carries a raw or hidden payload"
WITHHELD_SENSITIVE_NAME = "field name marks credential material"
WITHHELD_CREDENTIAL = "value is credential-shaped; a pack never carries issued secret material"
WITHHELD_MACHINE_LOCAL = "machine-local path or link; it does not resolve on another machine"

# A path or a link, as opposed to a word. Anchored on purpose: a prose sentence
# in a claim boundary must not read as a filesystem location just because it
# contains a slash later on.
_MACHINE_LOCAL_LOCATION = re.compile(r"^(?:~|/|[A-Za-z]:[\\/]|\\\\)")
_SCHEMA_GENERATION = re.compile(r"^(?P<name>.+)/v(?P<generation>\d+)$")


class SetupProfilePackError(ValueError):
    """Raised when a pack cannot be built, read, or applied at all."""


# --- Export ------------------------------------------------------------------


def build_setup_profile_pack(paths: OmhPaths) -> dict[str, Any]:
    """Serialize this install's configured profile into one portable payload."""
    try:
        stored = read_setup_profile(paths)
        # Read through `read_capability_policy` rather than copied out of the
        # profile dict: that reader rebuilds the policy from the disable list,
        # so a hand-edited `enabled_families` cannot travel as fact.
        policy = read_capability_policy(paths)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        # A hand-edited profile is the usual cause, and the person needs to be
        # told which file to look at rather than handed a decoder traceback.
        raise SetupProfilePackError(
            f"cannot read the configured OMH profile at {paths.setup_profile_path}: {error}"
        ) from error
    if not isinstance(stored, dict):
        raise SetupProfilePackError(
            "no configured OMH profile to export; run `omh setup` on this machine first"
        )
    withheld: list[dict[str, str]] = []
    sections = {
        "profile": _redact(stored, path="profile", withheld=withheld),
        "capability_policy": policy,
        "mcp": _mcp_section(paths, withheld=withheld),
        "model_aliases": _model_alias_section(paths),
    }
    return {
        "schema_version": SETUP_PROFILE_PACK_SCHEMA_VERSION,
        **sections,
        "withheld": sorted(withheld, key=lambda item: item["field"]),
        "manifest": _manifest(sections, withheld_count=len(withheld)),
    }


def write_setup_profile_pack(paths: OmhPaths, output_path: Path) -> dict[str, Any]:
    """Build the pack and write it where the person asked, returning the pack."""
    pack = build_setup_profile_pack(paths)
    target = Path(output_path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        raise SetupProfilePackError(f"cannot write setup profile pack: {error}") from error
    return pack


def setup_profile_pack_export_report(pack: dict[str, Any], *, output_path: str = "") -> dict[str, Any]:
    """The human- and machine-readable account of one export."""
    manifest = pack.get("manifest", {}) if isinstance(pack.get("manifest"), dict) else {}
    withheld = pack.get("withheld", []) if isinstance(pack.get("withheld"), list) else []
    model_aliases = pack.get("model_aliases", {}) if isinstance(pack.get("model_aliases"), dict) else {}
    mcp = pack.get("mcp", {}) if isinstance(pack.get("mcp"), dict) else {}
    return {
        "schema_version": SETUP_PROFILE_PACK_EXPORT_SCHEMA_VERSION,
        "pack_schema_version": str(pack.get("schema_version", "")),
        "pack_id": str(manifest.get("pack_id", "")),
        "source_omh_version": str(manifest.get("source_omh_version", "")),
        "output_path": str(output_path or ""),
        "sections": list(SETUP_PROFILE_PACK_SECTIONS),
        # The five fields someone comparing two machines actually reads, lifted
        # out so a diff does not mean reading two whole profiles.
        "configured": configured_field_summary(
            pack.get("profile"), capability_policy=pack.get("capability_policy")
        ),
        "model_alias_status": str(model_aliases.get("status", "")),
        "model_alias_count": len(model_aliases.get("aliases", {}) or {}),
        "mcp_status": str(mcp.get("status", "")),
        "withheld": list(withheld),
        "withheld_field_count": len(withheld),
        "apply_command": "omh setup-profile apply --from <pack.json> --apply",
        "transport_boundary": (
            "Moving this file to another machine is your own git or file copy; OMH makes no network calls."
        ),
        "claim_boundary": SETUP_PROFILE_PACK_CLAIM_BOUNDARY,
    }


def _manifest(sections: dict[str, Any], *, withheld_count: int) -> dict[str, Any]:
    digests = {
        name: sha256_text(json.dumps(value, sort_keys=True))
        for name, value in sorted(sections.items())
    }
    return {
        "schema_version": SETUP_PROFILE_PACK_MANIFEST_SCHEMA_VERSION,
        # Content-addressed, so two exports of the same configuration carry the
        # same id and a reader can tell "unchanged" from "re-exported".
        "pack_id": "pack-" + sha256_text("".join(digests[name] for name in sorted(digests)))[:12],
        "created_at": utc_now(),
        "source_omh_version": __version__,
        "sections": sorted(sections),
        "section_digests": digests,
        "withheld_field_count": int(withheld_count),
        "claim_boundary": SETUP_PROFILE_PACK_CLAIM_BOUNDARY,
    }


def _withheld_reason(key: str, value: Any) -> str:
    if key in RAW_OR_HIDDEN_KEYS:
        return WITHHELD_RAW_OR_HIDDEN
    if is_sensitive_metadata_text(key):
        return WITHHELD_SENSITIVE_NAME
    if isinstance(value, str) and value:
        if is_secret_value_shaped(value):
            return WITHHELD_CREDENTIAL
        if _MACHINE_LOCAL_LOCATION.match(value) or "://" in value:
            return WITHHELD_MACHINE_LOCAL
    return ""


def _redact(value: Any, *, path: str, withheld: list[dict[str, str]]) -> Any:
    """Copy the payload, dropping anything unsafe or unportable, and say so."""
    if isinstance(value, dict):
        kept: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            reason = _withheld_reason(str(key), child)
            if reason:
                withheld.append({"field": child_path, "reason": reason})
                continue
            kept[str(key)] = _redact(child, path=child_path, withheld=withheld)
        return kept
    if isinstance(value, list):
        return [
            _redact(item, path=f"{path}[{index}]", withheld=withheld)
            for index, item in enumerate(value)
        ]
    # A list entry has no key to screen, so the credential test runs on the
    # leaf too. A dict value reaching here already passed the key-level test.
    if isinstance(value, str) and value and is_secret_value_shaped(value):
        withheld.append({"field": path, "reason": WITHHELD_CREDENTIAL})
        return ""
    return value


def _mcp_section(paths: OmhPaths, *, withheld: list[dict[str, str]]) -> dict[str, Any]:
    empty = {
        "schema_version": SETUP_PROFILE_PACK_MCP_SCHEMA_VERSION,
        "status": "not_configured",
        "host": "",
        "command": "",
        "server_args": [],
        "scope": "",
        "reason": "",
    }
    state, error = read_json_object_result(paths.runtime_state_path)
    if error:
        return {**empty, "status": "unreadable", "reason": f"runtime state could not be read: {error}"}
    record = (state or {}).get("last_mcp_host_config_install")
    if not isinstance(record, dict):
        return {**empty, "reason": "this machine recorded no MCP host config install"}
    # The absolute config path is the one field of the record that is about
    # this filesystem rather than about the recipe; the target resolves its own.
    if str(record.get("path", "") or ""):
        withheld.append({"field": "mcp.path", "reason": WITHHELD_MACHINE_LOCAL})
    return {
        "schema_version": SETUP_PROFILE_PACK_MCP_SCHEMA_VERSION,
        "status": "recorded",
        "host": str(record.get("host", "") or ""),
        "command": str(record.get("command", "") or "omh"),
        "server_args": [str(item) for item in record.get("server_args", []) or [] if isinstance(item, str)],
        "scope": str(record.get("scope", "") or "user"),
        "reason": "",
    }


def _model_alias_section(paths: OmhPaths) -> dict[str, Any]:
    empty = {
        "schema_version": SETUP_PROFILE_PACK_MODEL_ALIASES_SCHEMA_VERSION,
        "status": "no_hermes_config",
        "aliases": {},
        "reason": "no Hermes config on this machine",
    }
    try:
        text = paths.hermes_config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty
    except (OSError, UnicodeDecodeError) as error:
        return {**empty, "status": "unreadable", "reason": f"Hermes config could not be read: {type(error).__name__}"}
    # The shared parser already runs both halves of every entry through
    # `require_opaque_metadata_ref`, so a credential cannot arrive as an alias
    # target; that is the reason to reuse it rather than read the YAML here.
    aliases, error_text = parse_hermes_model_aliases(text)
    if error_text:
        return {**empty, "status": "unreadable", "reason": error_text}
    return {
        "schema_version": SETUP_PROFILE_PACK_MODEL_ALIASES_SCHEMA_VERSION,
        "status": "configured" if aliases else "unset",
        "aliases": dict(sorted(aliases.items())),
        "reason": "" if aliases else "Hermes config declares no model aliases",
    }


# --- Version gate ------------------------------------------------------------


def pack_version_refusal(pack: dict[str, Any]) -> str:
    """Why this OMH must not apply the pack at all, or "" when it may."""
    reason = _version_reason(
        str(pack.get("schema_version", "") or ""),
        SETUP_PROFILE_PACK_SCHEMA_VERSION,
        "setup profile pack",
    )
    if reason:
        return reason
    profile = pack.get("profile")
    if not isinstance(profile, dict):
        return "setup profile pack carries no profile section"
    return _version_reason(
        str(profile.get("schema_version", "") or ""),
        SETUP_PROFILE_SCHEMA_VERSION,
        "profile section",
    )


def _schema_parts(value: str) -> tuple[str, int]:
    match = _SCHEMA_GENERATION.match(value)
    if not match:
        return value, -1
    return match.group("name"), int(match.group("generation"))


def _version_reason(declared: str, supported: str, label: str) -> str:
    if declared == supported:
        return ""
    if not declared:
        return f"the {label} declares no schema version; OMH {__version__} applies {supported} only"
    declared_name, declared_generation = _schema_parts(declared)
    supported_name, supported_generation = _schema_parts(supported)
    if declared_name == supported_name and declared_generation > supported_generation:
        return (
            f"the {label} is {declared}, written by a newer OMH; OMH {__version__} applies "
            f"{supported} only -- update OMH before applying this pack"
        )
    return f"the {label} is {declared}; OMH {__version__} applies {supported} only"


# --- Apply -------------------------------------------------------------------


def read_setup_profile_pack(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    try:
        raw = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SetupProfilePackError(f"cannot read setup profile pack: {error}") from error
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SetupProfilePackError(f"setup profile pack is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise SetupProfilePackError("setup profile pack must be a JSON object")
    return data


def apply_setup_profile_pack(
    paths: OmhPaths,
    pack: dict[str, Any],
    *,
    dry_run: bool = True,
    with_mcp: bool = False,
    mcp_config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write every field of the pack this install accepts, and report the rest.

    The version gate runs before any write. Past it, a field this install
    cannot accept is reported and skipped rather than raising, because one
    unknown executor name in a pack should not cost the person every other
    field they configured.
    """
    refusal = pack_version_refusal(pack)
    if refusal:
        raise SetupProfilePackError(f"{refusal}. Nothing was written.")

    profile = pack["profile"]
    status = "would_apply" if dry_run else "applied"
    fields: list[dict[str, Any]] = []
    next_actions: list[str] = []

    executor, executor_reason = _accepted_value(
        "default_executor", profile.get("default_executor"), CODING_EXECUTOR_TARGETS
    )
    operating_model, operating_model_reason = _accepted_value(
        "operating_model_id", profile.get("operating_model_id"), operating_model_ids()
    )
    memory_mode, memory_mode_reason = _accepted_value(
        "memory_mode", profile.get("memory_mode"), PROJECT_MEMORY_MODES
    )
    categories, category_reason, categories_partial = _accepted_categories(
        profile.get("selected_categories")
    )
    disabled, family_reason, families_partial = _accepted_families(pack.get("capability_policy"))

    for field, value, reason in (
        ("default_executor", executor, executor_reason),
        ("operating_model_id", operating_model, operating_model_reason),
        ("memory_mode", memory_mode, memory_mode_reason),
    ):
        fields.append(_field_row(field, value, reason, status=status))
    for field, value, reason, partial in (
        ("selected_categories", list(categories), category_reason, categories_partial),
        ("capability_policy.disabled_families", list(disabled), family_reason, families_partial),
    ):
        fields.append(_list_field_row(field, value, reason, partial=partial, status=status))

    fields.extend(_parallelism_rows(profile, paths))
    fields.extend(_org_rule_rows(profile))
    fields.extend(_model_alias_rows(pack, next_actions))

    profile_after: dict[str, Any] | None = None
    if not dry_run:
        write_setup_profile(
            paths,
            list(categories) or None,
            default_executor=executor or None,
            operating_model=operating_model or None,
            memory_mode=memory_mode or None,
        )
        write_capability_policy(paths, list(disabled))
        profile_after = read_setup_profile(paths)

    fields.append(
        _mcp_row(
            paths,
            pack,
            dry_run=dry_run,
            with_mcp=with_mcp,
            mcp_config_path=mcp_config_path,
            next_actions=next_actions,
        )
    )

    manifest = pack.get("manifest", {}) if isinstance(pack.get("manifest"), dict) else {}
    withheld = pack.get("withheld", []) if isinstance(pack.get("withheld"), list) else []
    return {
        "schema_version": SETUP_PROFILE_PACK_APPLY_SCHEMA_VERSION,
        "applied": not dry_run,
        "dry_run": bool(dry_run),
        "pack_id": str(manifest.get("pack_id", "")),
        "pack_schema_version": str(pack.get("schema_version", "")),
        "source_omh_version": str(manifest.get("source_omh_version", "")),
        "target_omh_version": __version__,
        "fields": fields,
        "applied_fields": [row["field"] for row in fields if row["status"] != "not_applied"],
        "not_applied_fields": [row["field"] for row in fields if row["status"] == "not_applied"],
        "profile_after": profile_after,
        # What the pack asked for beside what this install now holds; equal
        # summaries are what "the second install matches the first" means.
        "configured_in_pack": configured_field_summary(
            profile, capability_policy=pack.get("capability_policy")
        ),
        "configured_after": configured_field_summary(profile_after),
        "setup_profile_path": str(paths.setup_profile_path),
        "withheld": list(withheld),
        "next_actions": next_actions,
        "claim_boundary": (
            "Applying a setup profile pack records local OMH routing defaults only. It does not prove "
            "Hermes used a skill, that any executor ran, or that a host loaded the MCP bridge."
        ),
    }


def _field_row(field: str, value: Any, reason: str, *, status: str) -> dict[str, Any]:
    if reason:
        return {"field": field, "status": "not_applied", "value": value, "reason": reason}
    return {"field": field, "status": status, "value": value, "reason": ""}


def _list_field_row(
    field: str, value: list[str], reason: str, *, partial: bool, status: str
) -> dict[str, Any]:
    """A list field whose entries can be accepted one at a time.

    `partial` is what keeps the row honest: when some entries were written and
    some were refused, the status has to say the field was written, because
    `not_applied` beside a value that did land would send the reader looking
    for a write that already happened.
    """
    if reason and partial:
        return {"field": field, "status": status, "value": value, "reason": reason}
    return _field_row(field, value, reason, status=status)


def _accepted_value(field: str, value: Any, allowed: tuple[str, ...]) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", f"the pack carries no {field}"
    if text not in allowed:
        return "", f"this OMH does not accept {field} {text!r}; it accepts {', '.join(allowed)}"
    return text, ""


def _accepted_categories(value: Any) -> tuple[tuple[str, ...], str, bool]:
    """(accepted entries, refusal reason, whether anything was accepted)."""
    valid = {str(choice["id"]) for choice in setup_profile_choices()}
    if not isinstance(value, list) or not value:
        return (), "the pack carries no selected_categories", False
    accepted = tuple(str(item) for item in value if str(item) in valid)
    rejected = tuple(str(item) for item in value if str(item) not in valid)
    if rejected:
        return accepted, (
            f"this OMH does not accept setup profile category "
            f"{', '.join(repr(item) for item in rejected)}; it accepts {', '.join(sorted(valid))}"
        ), bool(accepted)
    return accepted, "", True


def _accepted_families(policy: Any) -> tuple[tuple[str, ...], str, bool]:
    if not isinstance(policy, dict):
        return (), "the pack carries no capability policy", False
    declared = policy.get("disabled_families")
    if not isinstance(declared, list):
        return (), "the pack's capability policy declares no disabled_families list", False
    accepted: list[str] = []
    rejected: list[str] = []
    for item in declared:
        try:
            accepted.append(normalize_family_id(str(item)))
        except CapabilityPolicyError:
            rejected.append(str(item))
    if rejected:
        return tuple(sorted(accepted)), (
            f"this OMH does not accept capability family "
            f"{', '.join(repr(item) for item in rejected)}; it accepts "
            f"{', '.join(toggleable_family_ids())}"
        ), bool(accepted)
    # An empty disable list is a real configuration -- every family offered --
    # so it is applied, not reported as a missing field.
    return tuple(sorted(accepted)), "", True


def _parallelism_rows(profile: dict[str, Any], paths: OmhPaths) -> list[dict[str, Any]]:
    """Report parallelism only when the pack's values would actually be lost.

    `omh setup` accepts no parallelism flag, so `write_setup_profile` always
    writes the shipped defaults. Reporting that unconditionally would be noise;
    reporting it when the source machine had edited the block is the difference
    between a carried profile and a quietly reset one.
    """
    carried = profile.get("parallelism")
    if not isinstance(carried, dict):
        return []
    defaults = build_parallelism_settings()
    if carried == defaults:
        return []
    differing = {
        key: carried.get(key)
        for key in (*PARALLELISM_DEFAULTS, "per_owner")
        if carried.get(key) != defaults.get(key)
    }
    return [
        {
            "field": "parallelism",
            "status": "not_applied",
            "value": differing,
            "reason": (
                "`omh setup` writes the shipped parallelism defaults and accepts no parallelism flag; "
                f"edit the parallelism block in {paths.setup_profile_path.name} to restore these values"
            ),
        }
    ]


def _org_rule_rows(profile: dict[str, Any]) -> list[dict[str, Any]]:
    policy = profile.get("org_rule_source_policy")
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return []
    return [
        {
            "field": "org_rule_source_policy",
            "status": "not_applied",
            "value": {"enabled": True},
            "reason": (
                "the org safety rule source names machine-local file paths, which the export withheld; "
                "re-enable it locally with the paths that exist on this machine"
            ),
        }
    ]


def _model_alias_rows(pack: dict[str, Any], next_actions: list[str]) -> list[dict[str, Any]]:
    section = pack.get("model_aliases")
    aliases = section.get("aliases") if isinstance(section, dict) else None
    if not isinstance(aliases, dict) or not aliases:
        return []
    flags = " ".join(f"--model-alias {alias}={target}" for alias, target in sorted(aliases.items()))
    next_actions.append(f"omh setup --model-setup {flags} --apply-model-config")
    return [
        {
            "field": "model_aliases",
            "status": "not_applied",
            "value": dict(sorted(aliases.items())),
            "reason": (
                "Hermes model aliases are written only through `omh setup --model-setup "
                "--apply-model-config`, which binds the write to a Hermes config digest and an explicit "
                "confirmation; a pack apply carries neither"
            ),
        }
    ]


def _mcp_row(
    paths: OmhPaths,
    pack: dict[str, Any],
    *,
    dry_run: bool,
    with_mcp: bool,
    mcp_config_path: str | Path | None,
    next_actions: list[str],
) -> dict[str, Any]:
    section = pack.get("mcp") if isinstance(pack.get("mcp"), dict) else {}
    host = str(section.get("host", "") or "")
    command = str(section.get("command", "") or "omh")
    scope = str(section.get("scope", "") or "user")
    value = {"host": host, "command": command, "scope": scope}
    if str(section.get("status", "")) != "recorded" or not host:
        return {
            "field": "mcp.host_config",
            "status": "not_applied",
            "value": value,
            "reason": "the pack records no MCP host config",
        }
    if not with_mcp:
        next_actions.append(f"omh setup --with-mcp --mcp-host {host} --mcp-command {command}")
        return {
            "field": "mcp.host_config",
            "status": "not_applied",
            "value": value,
            "reason": (
                "an MCP host config writes another product's configuration file; re-run with --with-mcp "
                "to write it"
            ),
        }
    try:
        install = install_mcp_host_config(
            paths,
            host=host,
            command=command,
            config_path=mcp_config_path,
            scope=scope,
            dry_run=dry_run,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "field": "mcp.host_config",
            "status": "not_applied",
            "value": value,
            "reason": f"the MCP host config could not be written: {error}",
        }
    install_status = str(install.get("status", ""))
    if install_status == "skipped":
        return {
            "field": "mcp.host_config",
            "status": "not_applied",
            "value": value,
            "reason": str(install.get("reason", "the host does not support automatic config install")),
        }
    return {
        "field": "mcp.host_config",
        "status": "would_apply" if dry_run else "applied",
        "value": {**value, "status": install_status},
        "reason": "",
    }


def configured_field_summary(
    profile: dict[str, Any] | None, *, capability_policy: Any = None
) -> dict[str, Any]:
    """The five routing fields a reader compares between two machines.

    `capability_policy` overrides the copy nested in the profile, because the
    pack's own top-level section is the one the applier reads; comparing
    against the nested copy would hide a divergence between them.
    """
    source = profile if isinstance(profile, dict) else {}
    policy = capability_policy if isinstance(capability_policy, dict) else source.get("capability_policy")
    disabled = policy.get("disabled_families") if isinstance(policy, dict) else []
    return {
        "default_executor": str(source.get("default_executor", "")),
        "operating_model_id": str(source.get("operating_model_id", "")),
        "memory_mode": str(source.get("memory_mode", "")),
        "selected_categories": _string_list(source.get("selected_categories")),
        "disabled_families": _string_list(disabled),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]

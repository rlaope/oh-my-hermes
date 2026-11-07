"""What a Jev-class Hermes plugin DECLARES, and nothing about what it does.

Jev (TypeSafe System One) is a non-generative model: it answers typed
questions and cannot write code. Several community Hermes plugins call it, and
some of them ask for the same hooks the OMH bridge registers. An operator
deciding whether that matters needs two things, which is all this module
supplies: the plugin names OMH recognizes as Jev-class, and what each one's
catalog entry declares about the tools it registers, the hooks it asks for, and
what leaves the machine.

Every value below is a DECLARATION, never an observation. A catalog description
is written by the plugin's author; a ``plugin.yaml`` under
``$HERMES_HOME/plugins`` is written by whoever installed it. Neither proves the
plugin loaded, that it ran, or that any request left the machine, and no text
built from this module may be read as saying it did. ``read_from`` and
``read_on`` name the artifact and the date each record was transcribed from, so
a reader can check the quote instead of trusting it.

The disclosure strings are copied verbatim from the ``description`` field of
the named catalog entry, folded to one line the way YAML folds a plain
multi-line scalar. A record whose catalog entry carries no ``Disclosure --``
clause holds an empty string rather than a summary OMH invented.

``CLOUDFLARE_JEV_API_TOKEN`` is deliberately absent from
``JEV_CREDENTIAL_ENV_NAMES``: no vendor page and no catalog entry declares that
name, and a credential name OMH made up would be reported as a machine fact.
``OPENROUTER_API_KEY`` is here because two entries below declare it as their
route, and the posture builder only consults it once a Jev-class plugin is
detected -- on its own it is an OpenRouter account, not a Jev signal.

OMH never calls a third-party Jev plugin, this module reads no credential
value, and it never imports a plugin. It is a table plus one classifier over
it, with no I/O. OMH's own opt-in path to Jev is the `omh_jev_ask` tool, whose
name deliberately falls outside `is_jev_tool_name`: its calls are OMH's, not a
third-party plugin's, and never promote a `jev_plugin` rung.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from .metadata import PROVIDED_HOOKS

# Every tool a Jev-class plugin registers in the catalog uses this prefix, so a
# plugin under a name this table does not hold is still classified when its
# manifest declares one. It survives a rename of the plugin, not of its tools:
# a lineage that renamed its tools too carries its own prefix on its record
# (`lineage_tool_prefix`), honored for that record's name alone.
JEV_TOOL_PREFIX: Final = "jev_"

# Vendor-documented (docs.typesafe.ai/models) plus the route two catalog
# entries declare. NAMES only: no value is ever copied, here or anywhere below.
JEV_CREDENTIAL_ENV_NAMES: Final[frozenset[str]] = frozenset({"TYPESAFE_API_KEY", "OPENROUTER_API_KEY"})

# The date every record below was transcribed. A record is a quote with a
# provenance, so both halves move together or neither does.
JEV_CATALOG_READ_ON: Final = "2026-09-21"

# Two provenances, because the two artifacts are different reads. `jev` is the
# only Jev entry in the catalog revision installed on the machine this was read
# from; the rest exist only on the catalog's upstream branch at the commit
# named here.
_INSTALLED_CATALOG_COMMIT: Final = "577990c3a0"
_UPSTREAM_CATALOG_COMMIT: Final = "7efacc8f62"


def _installed_catalog(name: str) -> str:
    return f"hermes-agent plugin-catalog/{name}.yaml @ {_INSTALLED_CATALOG_COMMIT}"


def _upstream_catalog(name: str) -> str:
    return f"hermes-agent plugin-catalog/{name}.yaml @ origin/main {_UPSTREAM_CATALOG_COMMIT}"


# A later read, for the records added after the table above was transcribed.
# `jev-curator` is on the catalog's upstream branch at the commit named here;
# `nerve` is on no branch at all yet -- it exists only in the head of an OPEN
# pull request, and its provenance says so rather than reading as catalog fact.
_REFRESH_READ_ON: Final = "2026-09-23"
_REFRESH_UPSTREAM_CATALOG_COMMIT: Final = "38c289c014"
_NERVE_RENAME_PR: Final = "NousResearch/hermes-agent#119045"
_NERVE_RENAME_PR_HEAD: Final = "84fca22d8b"


@dataclass(frozen=True, slots=True)
class JevPluginRecord:
    """One Jev-class plugin as its catalog entry declares it.

    `overlap` names an OMH surface the entry's own description says the plugin
    acts on, and is left empty when the entry claims none. It is deliberately
    NOT where hook overlap is recorded: the hooks a plugin and OMH both ask for
    are computed from the installed manifest against OMH's own declared hook
    list, so that claim is derived where it is made rather than written beside
    a value that can drift out from under it.
    """

    name: str
    repo: str
    declares_tools: tuple[str, ...] = ()
    declares_hooks: tuple[str, ...] = ()
    declared_disclosure: str = ""
    overlap: str = ""
    read_from: str = ""
    read_on: str = JEV_CATALOG_READ_ON
    # A second tool prefix this lineage uses, counted only for a plugin whose
    # name is this record's. Never a global prefix: another plugin's tool that
    # happens to share it is not a Jev signal.
    lineage_tool_prefix: str = ""


KNOWN_JEV_PLUGINS: Final[tuple[JevPluginRecord, ...]] = (
    JevPluginRecord(
        name="jev",
        repo="https://github.com/ourines/hermes-jev",
        declares_tools=("jev_evaluate",),
        declares_hooks=(),
        # The entry carries no `Disclosure --` clause, and its `requires_env`
        # is empty with a comment saying credentials are chosen per backend at
        # setup. An empty string is what that reads as; a summary would be OMH
        # speaking for the author.
        declared_disclosure="",
        overlap="",
        read_from=_installed_catalog("jev"),
    ),
    JevPluginRecord(
        name="jev-typesafe",
        repo="https://github.com/ajensenwaud/hermes-jev-plugin",
        declares_tools=("jev_evaluate", "jev_check", "jev_route", "jev_score"),
        declares_hooks=(),
        declared_disclosure=(
            "Disclosure — every tool call sends the model-supplied question/state together with your "
            "TYPESAFE_API_KEY to api.typesafe.ai (TypeSafe AI, an independent vendor); the catalog has not "
            "verified the plugin author's affiliation with that vendor."
        ),
        overlap="",
        read_from=_upstream_catalog("jev-typesafe"),
    ),
    JevPluginRecord(
        # A different repository from `jev` above, under a different
        # maintainer, with the same `hermes-jev` name. Both are recorded, and
        # neither record speaks for the other.
        name="hermes-jev",
        repo="https://github.com/keeltrace/hermes-jev",
        declares_tools=(
            "jev_decide",
            "jev_rank",
            "jev_verify",
            "jev_assess",
            "jev_context_curate",
            "jev_context_rehydrate",
            "jev_stats",
            "jev_nervous_event",
        ),
        declares_hooks=(
            "pre_tool_call",
            "post_tool_call",
            "pre_llm_call",
            "transform_tool_result",
            "pre_verify",
            "post_llm_call",
            "on_session_end",
        ),
        declared_disclosure=(
            "Disclosure — with the default settings (nervous_enabled / turn_admission on) each turn's user "
            "prompt (up to 12k characters) and redacted tool/result previews are sent to OpenRouter Decisions "
            "(TypeSafe Jev) using your OPENROUTER_API_KEY or TYPESAFE_API_KEY, spending your credits on every turn."
        ),
        overlap="",
        read_from=_upstream_catalog("hermes-jev"),
        # A `hermes-jev` directory updated in place to the renamed plugin keeps
        # its directory name while its manifest now declares `nerve_` tools;
        # the lineage prefix keeps those tools on this record's rung.
        lineage_tool_prefix="nerve_",
    ),
    JevPluginRecord(
        # `hermes-jev` above, renamed by its maintainer: same maintainer, the
        # same eight tools under `nerve_` plus eight new ones. Both names stay,
        # because a machine that has not updated still holds the old one. The
        # rename is an OPEN pull request, so this record is a read of that
        # PR's head, not of a catalog Hermes ships.
        name="nerve",
        repo="https://github.com/keeltrace/hermes-nerve",
        declares_tools=(
            "nerve_decide",
            "nerve_rank",
            "nerve_verify",
            "nerve_assess",
            "nerve_context_curate",
            "nerve_context_rehydrate",
            "nerve_stats",
            "nerve_nervous_event",
            "nerve_supervise_card",
            "nerve_work_event",
            "nerve_work_status",
            "nerve_remote_delegate_task",
            "nerve_remote_worker_status",
            "nerve_remote_worker_result",
            "nerve_remote_worker_cancel",
            "nerve_remote_worker_control",
        ),
        declares_hooks=(
            "pre_tool_call",
            "post_tool_call",
            "pre_llm_call",
            "transform_tool_result",
            "pre_verify",
            "post_api_request",
            "api_request_error",
            "post_llm_call",
            "on_session_end",
        ),
        declared_disclosure=(
            "Disclosure — the default Reflex backend is hosted Jev; when enabled it can send user prompts and "
            "redacted tool/result previews to the configured Jev provider using the user's provider credentials. "
            "Laya and OpenJev can be configured as local/self-hosted backends."
        ),
        overlap="",
        read_from=(
            f"hermes-agent plugin-catalog/nerve.yaml @ open PR {_NERVE_RENAME_PR} head {_NERVE_RENAME_PR_HEAD} "
            "(not merged)"
        ),
        read_on=_REFRESH_READ_ON,
        lineage_tool_prefix="nerve_",
    ),
    JevPluginRecord(
        name="jev-approvals",
        repo="https://github.com/anpicasso/hermes-jev-approvals",
        declares_tools=(),
        declares_hooks=(),
        declared_disclosure=(
            "Disclosure — each command routed to smart approval (redacted best-effort) and the operator's "
            "smart-policy text leave the machine for the configured third-party endpoint; provider or validation "
            "failures fail closed to ESCALATE."
        ),
        overlap="",
        read_from=_upstream_catalog("jev-approvals"),
    ),
    JevPluginRecord(
        # Its description names Hermes' own Curator and `skill_manage`, and no
        # OMH surface, so `overlap` stays empty. Its `pre_tool_call` is still
        # compared with the bridge's hooks, where that claim is computed.
        name="jev-curator",
        repo="https://github.com/anpicasso/hermes-jev-curator",
        declares_tools=("jev_skill_relations",),
        declares_hooks=("on_skill_lifecycle", "pre_tool_call"),
        declared_disclosure=(
            "Disclosure — no egress occurs by default; after allow_content_egress is explicitly enabled, "
            "redacted bounded skill content is sent to the configured TypeSafe, OpenRouter, or custom Jev "
            "endpoint and may spend provider credits. Automatic refreshes never apply mutations, and missing, "
            "stale, or incomplete evidence fails closed."
        ),
        overlap="",
        read_from=f"hermes-agent plugin-catalog/jev-curator.yaml @ origin/main {_REFRESH_UPSTREAM_CATALOG_COMMIT}",
        read_on=_REFRESH_READ_ON,
    ),
    JevPluginRecord(
        name="hermes-structured-aux-models",
        repo="https://github.com/trajectoire-ai/hermes-structured-aux-models",
        declares_tools=(),
        declares_hooks=(),
        declared_disclosure=(
            "Disclosure — sends redacted approval prompts, MCP tool names and compression transcript blocks "
            "to openrouter.ai using your OpenRouter key (read-only); on any error approvals escalate to you, never "
            "auto-approve; the default decision_model is a moving alias, pin it."
        ),
        overlap="",
        read_from=_upstream_catalog("hermes-structured-aux-models"),
    ),
    JevPluginRecord(
        name="typesafe-skill-router",
        repo="https://github.com/DECRUX9812/typesafe-skill-router",
        declares_tools=(),
        declares_hooks=("pre_llm_call",),
        declared_disclosure="",
        overlap=(
            "nominates one skill on the user message at pre_llm_call, the hook where OMH injects its route hint, "
            "so the model receives two nominations"
        ),
        read_from=_upstream_catalog("typesafe-skill-router"),
    ),
    JevPluginRecord(
        name="jev-model-router",
        repo="https://github.com/Pinutss/jev-model-router",
        declares_tools=(),
        declares_hooks=(),
        declared_disclosure="",
        overlap="selects a model, the surface OMH's mixture chains order",
        read_from=_upstream_catalog("jev-model-router"),
    ),
    JevPluginRecord(
        name="jev-memory-selector",
        repo="https://github.com/Pinutss/jev-memory-selector",
        declares_tools=(),
        declares_hooks=(),
        declared_disclosure="",
        overlap="selects memory, the surface OMH's memory provider serves",
        read_from=_upstream_catalog("jev-memory-selector"),
    ),
    JevPluginRecord(
        name="jev-agent-router",
        repo="https://github.com/Pinutss/jev-agent-router",
        declares_tools=(),
        declares_hooks=(),
        declared_disclosure="",
        overlap="routes an agent, the surface OMH's delegation routing answers for",
        read_from=_upstream_catalog("jev-agent-router"),
    ),
    JevPluginRecord(
        name="jev-mcp-router",
        repo="https://github.com/Pinutss/jev-mcp-router",
        declares_tools=(),
        declares_hooks=(),
        declared_disclosure="",
        overlap="selects MCP servers, the surface OMH's capability report describes",
        read_from=_upstream_catalog("jev-mcp-router"),
    ),
)

_BY_NAME: Final[dict[str, JevPluginRecord]] = {record.name: record for record in KNOWN_JEV_PLUGINS}

# The exact tool names a lineage's own catalog entry declares under its own
# prefix. A dispatched tool call carries a name and no plugin, so this is how
# the observed tier recognizes a renamed lineage without claiming every tool
# that merely shares its prefix.
_LINEAGE_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    tool
    for record in KNOWN_JEV_PLUGINS
    if record.lineage_tool_prefix
    for tool in record.declares_tools
    if tool.startswith(record.lineage_tool_prefix)
)


def is_jev_tool_name(tool: str) -> bool:
    """Whether a tool name, seen without its plugin, is a Jev-class tool.

    The `jev_` prefix, or one of the exact names a renamed lineage's catalog
    entry declares. A `nerve_`-prefixed name that entry does not declare is
    another plugin's tool and reads as not Jev-class.
    """
    return tool.startswith(JEV_TOOL_PREFIX) or tool in _LINEAGE_TOOL_NAMES


def classify_plugin(
    name: str,
    provides_tools: Iterable[str] = (),
    provides_hooks: Iterable[str] = (),
) -> dict[str, object] | None:
    """Classify one installed plugin, or return None when it is not Jev-class.

    Two independent signals, because either alone would miss a real install: a
    name this table holds, and a declared tool carrying the `jev_` prefix. A
    plugin matching only the second is reported with ``known: false`` and no
    catalog quote, which is the honest reading -- OMH recognizes the tool
    shape and has read nothing about that plugin. A known record's
    `lineage_tool_prefix` also counts, for that name alone: `nerve_` tools
    are Jev tools under the `nerve` name and nothing under any other.

    `provides_tools` and `provides_hooks` come from the manifest installed on
    this machine; `declared_disclosure`, `overlap` and the provenance come
    from the table above. The catalog's own tool and hook lists are not
    carried beside them: nothing compares the two, and a field carried for a
    comparison no code, message or test makes is a capability the change does
    not deliver. A caller that wants the disagreement computes it and says so
    in a sentence; the table is where the catalog's side is read.

    `hook_overlap` is computed here rather than stored, against OMH's own
    declared hook list, so it cannot drift out of date with the bridge.

    `name` is the identity OMH will report. A caller that could not read the
    manifest's `name` passes the empty string rather than a directory name it
    guessed, because a guess that lands on a table entry would attach that
    maintainer's record to this install.
    """
    record = _BY_NAME.get(name)
    prefixes: tuple[str, ...] = (JEV_TOOL_PREFIX,)
    if record is not None and record.lineage_tool_prefix:
        prefixes += (record.lineage_tool_prefix,)
    jev_tools = sorted({tool for tool in provides_tools if tool.startswith(prefixes)})
    if record is None and not jev_tools:
        return None
    hooks = sorted(set(provides_hooks))
    return {
        "name": name,
        "known": record is not None,
        "repo": record.repo if record is not None else "",
        "jev_tools": jev_tools,
        "declares_hooks": hooks,
        "hook_overlap": sorted(set(hooks) & set(PROVIDED_HOOKS)),
        "declared_disclosure": record.declared_disclosure if record is not None else "",
        "overlap": record.overlap if record is not None else "",
        "read_from": record.read_from if record is not None else "",
        "read_on": record.read_on if record is not None else "",
    }

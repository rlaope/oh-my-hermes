from __future__ import annotations

from dataclasses import dataclass
import importlib.resources as resources
import json
from pathlib import Path
import re
import shlex
import shutil
from typing import Mapping, Sequence

from ..version import __version__
from ..capabilities.playbooks import playbook_capabilities
from ..capabilities.skills import skill_capabilities
from ..catalogs.roles import role_definitions, role_file_markdown
from ..command_path import (
    installed_command_path_check_plan,
    inspect_installed_command_path,
    path_check_kind,
)
from ..local_store import atomic_write_json, read_json_object_result, utc_now
from ..plugin_bundle.omh.awareness import (
    awareness_primer_context,
    awareness_primer_markdown,
    awareness_primer_payload,
    awareness_workflow_context_markdown,
)
from ..plugin_bundle.omh.tools.capability_tool import (
    standalone_playbook_capability_items,
    standalone_skill_capability_ids,
    standalone_skill_capability_items,
)
from ..parity import build_parity_matrix
from ..quality.chat_card_coverage import build_chat_card_coverage_demo
from ..quality.context_brief_coverage import build_context_brief_coverage_demo
from ..quality.grounded_score import build_grounded_score_demo
from ..quality.hermes_ux_quality import build_hermes_ux_quality_demo, hermes_ux_quality_errors
from ..quality.localized_chat_copy import build_localized_chat_copy_demo, localized_chat_copy_errors
from ..quality.route_hint_alignment import build_route_hint_alignment_demo
from ..quality.router_fast_path import build_router_fast_path_demo, router_fast_path_errors
from ..quality.routing_precision import build_routing_precision_demo, routing_precision_errors
from ..release_smoke_core import CommandResult, Runner, bounded_text, expand_home, subprocess_runner
from ..skill_pack import builtin_skill_templates
from ..skills.catalog import builtin_definitions
from ..system.paths import OmhPaths
from ..use_cases import (
    USE_CASES,
    build_all_use_case_artifacts,
    demo_all_use_cases,
    replay_use_case_fixtures,
    use_case_readiness,
    validate_use_case_artifact,
)

REPOSITORY_ARCHIVE_ROOT = "https://github.com/rlaope/oh-my-hermes/archive/refs"
RELEASE_CHANNELS = ("stable", "preview", "local")
HERMES_SMOKE_SCHEMA = "hermes_release_smoke/v1"
RELEASE_CHECKLIST_SCHEMA = "release_readiness_checklist/v1"
INSTALLED_COMMAND_SMOKE_SCHEMA = "installed_omh_command_smoke/v1"
FIRST_USE_STATUS_SMOKE_SCHEMA = "first_use_status_smoke/v1"
SKILL_CONTENT_SMOKE_SCHEMA = "skill_content_smoke/v1"
PRODUCT_READINESS_SCHEMA = "omh_product_readiness/v1"
RELEASE_EVIDENCE_BUNDLE_SCHEMA = "omh_release_evidence_bundle/v1"
RELEASE_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[-_+.]?[A-Za-z0-9][A-Za-z0-9._+-]*)?$")
DEFAULT_HERMES_TAP = "rlaope/oh-my-hermes"
DEFAULT_HERMES_SKILL = "oh-my-hermes"
DEFAULT_FIRST_USE_MESSAGE = "I want to safely add a feature to this repo"
INSTALL_PATHS = ("tap", "setup")
REPRESENTATIVE_CONTEXT_RAIL_SKILLS = (
    "img-summary",
    "frontend",
    "visual-qa",
    "loop",
    "ultraprocess",
    "web-research",
    "materials-package",
)
ROUTER_CONTENT_MARKERS = ("OMH Awareness Primer", "img-summary", "Normal users should talk to Hermes Agent")
WORKFLOW_CONTEXT_MARKERS = ("OMH Context Rail", "not a standalone executor", "Prepared OMH routing")
ROLE_CONTEXT_MARKERS = ("OMH Role Context", "OMH workflow-layer responsibility context", "prepared guidance only")
CONCEPTUAL_AWARENESS_SURFACES = ("request-to-handoff", "executor selection", "coding runtime handoff")
AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT = 900
AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT = 3200
AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT = 1500
ROLE_CONTEXT_CHAR_LIMIT = 2600
FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT = 235000
FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT = 9000
STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT = 80000
STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT = 2200


@dataclass(frozen=True)
class ReleaseSelection:
    channel: str
    version: str
    package_url: str
    source_label: str


def package_url_for(channel: str, version: str = "", package_url: str = "") -> ReleaseSelection:
    if channel not in RELEASE_CHANNELS:
        raise ValueError(f"unsupported release channel: {channel}")
    if package_url:
        return ReleaseSelection(channel, version, package_url, "custom-url")
    if channel == "stable":
        if not version:
            raise ValueError("stable channel requires --version or OMH_VERSION")
        tag = version if version.startswith("v") else f"v{version}"
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/tags/{tag}.zip", tag)
    if channel == "preview":
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/heads/main.zip", "main")
    return ReleaseSelection(channel, version, "local", "local")


@dataclass(frozen=True)
class HermesSmokeStep:
    name: str
    command: tuple[str, ...]
    phase: str
    mutates_profile: bool
    required: bool = True
    proof_boundary: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "phase": self.phase,
            "mutates_profile": self.mutates_profile,
            "required": self.required,
            "proof_boundary": self.proof_boundary,
        }


@dataclass(frozen=True)
class ReleaseChecklistItem:
    item_id: str
    title: str
    command: str
    phase: str
    required: bool
    mutates_profile: bool
    evidence_required: str
    proof_boundary: str
    requires_release_authority: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "title": self.title,
            "command": self.command,
            "phase": self.phase,
            "required": self.required,
            "observed": False,
            "mutates_profile": self.mutates_profile,
            "requires_release_authority": self.requires_release_authority,
            "evidence_required": self.evidence_required,
            "proof_boundary": self.proof_boundary,
        }


@dataclass(frozen=True)
class ReleaseQualityEvidence:
    skill_content: dict[str, object]
    parity: dict[str, object]
    grounded_score: dict[str, object]
    chat_cards: dict[str, object]
    route_hints: dict[str, object]
    context_briefs: dict[str, object]
    routing_precision: dict[str, object]
    localized_chat_copy: dict[str, object]
    router_fast_path: dict[str, object]
    hermes_ux: dict[str, object]
    checklist: dict[str, object]


def release_readiness_checklist(
    *,
    version: str = __version__,
    omh_command: str = "omh",
) -> dict[str, object]:
    release_version = _normalize_release_version(version)
    tag = f"v{release_version}"
    wheel = f"dist/oh_my_hermes-{release_version}-py3-none-any.whl"
    omh_display = _shell_word(omh_command or "omh")
    items = [
        ReleaseChecklistItem(
            "unit_tests",
            "Run the full unittest suite",
            "PYTHONPATH=tests uv run python -m unittest discover -s tests -v",
            "local-quality",
            True,
            False,
            "All tests pass locally or in CI.",
            "Unit tests prove local contracts only; they do not prove Hermes loaded the installed skills.",
        ),
        ReleaseChecklistItem(
            "compileall",
            "Compile Python sources",
            "uv run python -m compileall -q src tests",
            "local-quality",
            True,
            False,
            "compileall exits successfully.",
            "Syntax/import compilation is local source evidence only.",
        ),
        ReleaseChecklistItem(
            "docs_workflows_check",
            "Check generated workflow docs",
            "uv run python -m omh.cli docs workflows --check",
            "contract-quality",
            True,
            False,
            "Generated workflow docs match catalog data.",
            "This proves generated references are in sync, not that Hermes selected a workflow in chat.",
        ),
        ReleaseChecklistItem(
            "harness_validate",
            "Validate harness catalog contracts",
            "uv run python -m omh.cli harness validate",
            "contract-quality",
            True,
            False,
            "Harness catalog validation exits successfully.",
            "Harness validation proves local schemas and metadata, not runtime execution.",
        ),
        ReleaseChecklistItem(
            "source_checkout_command_smoke",
            "Check source-checkout console command importability",
            'uv run --no-editable omh recommend "risky refactor" --limit 1 --json',
            "local-quality",
            True,
            False,
            "The source checkout can build/install the package non-editably and run the `omh` console script.",
            "This proves console-script importability for the local checkout only; it does not prove Hermes chat visibility, plugin load, executor work, review, CI, merge, or delivery.",
        ),
        ReleaseChecklistItem(
            "use_case_demo_cards",
            "Check G1-G10 use-case demo cards",
            "uv run python -m omh.cli cases demo --all --json",
            "contract-quality",
            True,
            False,
            "Use-case demo card collection renders all ten G1-G10 cards with route, action, wrapper card, and evidence boundary metadata.",
            "Use-case demo cards prove wrapper-renderable projections only; they do not prove cron, connector, file, memory, executor, review, CI, merge, or delivery work happened.",
        ),
        ReleaseChecklistItem(
            "use_case_artifact_bundle",
            "Check G1-G10 use-case artifact bundle",
            "uv run python -m omh.cli cases artifact --all --json",
            "contract-quality",
            True,
            False,
            "Use-case artifact bundle renders all ten G1-G10 prepared artifacts with route, operator-step, proof-surface, wrapper-card, and evidence-boundary metadata.",
            "Use-case artifacts prove prepared runbook projection only; they do not prove runtime execution, connector invocation, delivery, file generation, memory mutation, executor dispatch, review, CI, merge, or billing evidence.",
        ),
        ReleaseChecklistItem(
            "use_case_replay",
            "Replay G1-G10 natural-language use-case fixtures",
            "uv run python -m omh.cli cases replay --json",
            "contract-quality",
            True,
            False,
            "Use-case replay passes deterministic English and Korean operator fixtures for every G1-G10 application case.",
            "Use-case replay proves deterministic recommendation routing for synthetic fixtures only; it does not prove live Hermes chat behavior or any runtime execution.",
        ),
        ReleaseChecklistItem(
            "use_case_readiness",
            "Check G1-G10 use-case readiness rollup",
            "uv run python -m omh.cli cases readiness --json",
            "contract-quality",
            True,
            False,
            "Use-case readiness reports catalog, demo-card, artifact-bundle, and replay gates as passing while separating optional local artifact-store state.",
            "Use-case readiness proves deterministic local use-case contracts only; it does not prove live Hermes chat behavior, connector work, executor work, review, CI, merge, delivery, or billing evidence.",
        ),
        ReleaseChecklistItem(
            "grounded_score",
            "Check grounded routing score",
            "uv run python -m omh.cli demo grounded-score --json",
            "contract-quality",
            True,
            False,
            "Grounded score reports every representative operator scenario at 10/10.",
            "Grounded score proves deterministic local route, response-kind, next-action, playbook, and boundary checks only; it does not prove live Hermes chat rendering, executor work, review, CI, merge, delivery, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "chat_card_coverage",
            "Check wrapper chat card coverage",
            "uv run python -m omh.cli demo chat-card-coverage --json",
            "contract-quality",
            True,
            False,
            "Chat card coverage reports all dedicated workflow cards passing with generic ack count 0.",
            "Chat card coverage proves deterministic local wrapper-card contracts only; it does not prove live Hermes chat rendering, platform delivery, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "route_hint_alignment",
            "Check route and awareness hint alignment",
            "uv run python -m omh.cli demo route-hint-alignment --json",
            "contract-quality",
            True,
            False,
            "Route hint alignment reports every representative grounded-score and chat-card scenario with a primary plugin awareness hint that matches the selected workflow.",
            "Route hint alignment proves deterministic local router/hint agreement only; it does not prove live Hermes chat rendering, platform delivery, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "context_brief_coverage",
            "Check Hermes context brief coverage",
            "uv run python -m omh.cli demo context-brief-coverage --json",
            "contract-quality",
            True,
            False,
            "Context brief coverage reports every representative first-turn context case with metadata-only OMH mental model, route hint or picker hint, generic-tool checkpoint, and evidence boundary.",
            "Context brief coverage proves deterministic local Hermes-facing context only; it does not prove live Hermes chat rendering, plugin load, platform delivery, generic tool invocation, executor work, review, CI, merge, or delivery.",
        ),
        ReleaseChecklistItem(
            "routing_precision",
            "Check routing precision boundaries",
            "uv run python -m omh.cli demo routing-precision --json",
            "contract-quality",
            True,
            False,
            "Routing precision reports ordinary direct-answer and file-lookup prompts with overroute count 0, plus expected OMH prompts with missed intervention count 0.",
            "Routing precision proves deterministic local over-intervention and missed-intervention guards only; it does not prove live Hermes chat rendering, platform delivery, source retrieval, file inspection, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "localized_chat_copy",
            "Check localized chat-card framing",
            "uv run python -m omh.cli demo localized-chat-copy --json",
            "contract-quality",
            True,
            False,
            "Localized chat copy reports common non-English operator prompts with expected locale, card kind, next action, and no English catalog fallback.",
            "Localized chat copy proves deterministic local copy framing only; it does not prove live Hermes chat rendering, translation service quality, platform delivery, source retrieval, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "router_fast_path",
            "Check router fast-path quality",
            "uv run python -m omh.cli demo router-fast-path --json",
            "contract-quality",
            True,
            False,
            "Router fast-path quality reports high-frequency chat turns with explicit fast-path markers and no route or next-action drift.",
            "Router fast-path quality proves deterministic local fast-path route markers only; it does not prove wall-clock latency, live Hermes chat rendering, platform delivery, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "hermes_ux_quality",
            "Check Hermes-facing UX quality rollup",
            "uv run python -m omh.cli demo hermes-ux-quality --json",
            "contract-quality",
            True,
            False,
            "Hermes UX quality reports routing score, dedicated chat-card coverage, route-hint alignment, context-brief coverage, routing precision, localized chat copy, and router fast-path quality as passing in one user-facing rollup.",
            "Hermes UX quality proves deterministic local routing, card, hint, context, precision, localized-copy, and fast-path contracts only; it does not prove live Hermes chat rendering, platform delivery, plugin load, generic tool invocation, executor work, review, CI, merge, or delivery.",
        ),
        ReleaseChecklistItem(
            "product_readiness",
            "Check product readiness rollup",
            f"{omh_display} release product-readiness --version {release_version} --json",
            "contract-quality",
            True,
            False,
            "Product readiness reports skill-content, G1-G10 use-case, grounded score, wrapper chat card coverage, route hint alignment, context brief coverage, routing precision, localized chat copy, router fast-path quality, Hermes UX quality, parity, and release checklist gates as passing.",
            "Product readiness proves deterministic local package and product contracts only; it does not prove live Hermes chat behavior, connector work, executor work, review, CI, merge, delivery, or billing evidence.",
        ),
        ReleaseChecklistItem(
            "release_evidence_bundle",
            "Write the local release evidence bundle",
            f"{omh_display} release evidence-bundle --version {release_version} --write --json",
            "evidence-packaging",
            True,
            False,
            "A local `omh_release_evidence_bundle/v1` artifact is written with checklist, product readiness, skill content, use-case readiness, grounded score, chat card coverage, route hint alignment, context brief coverage, routing precision, localized chat copy, router fast-path quality, Hermes UX quality, and parity snapshots.",
            "The evidence bundle packages local deterministic evidence only; it is not live Hermes runtime use, connector execution, executor dispatch, review, CI, merge, delivery, or release publication evidence.",
        ),
        ReleaseChecklistItem(
            "stable_install_dry_run",
            "Dry-run stable install metadata",
            (
                "uv run python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke "
                f"install --dry-run --channel stable --version {release_version}"
            ),
            "install-plan",
            True,
            False,
            "Dry-run payload names the stable channel, version, source ref, and package URL.",
            "Dry-run install is not evidence that files were written or Hermes reloaded.",
        ),
        ReleaseChecklistItem(
            "stable_setup_dry_run",
            "Dry-run stable setup metadata",
            (
                "uv run python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke "
                f"setup --dry-run --channel stable --version {release_version}"
            ),
            "install-plan",
            True,
            False,
            "Dry-run setup shows the managed skill and Hermes registration plan.",
            "Dry-run setup does not mutate Hermes and is not native runtime-load evidence.",
        ),
        ReleaseChecklistItem(
            "probe_smoke",
            "Run local capability probe",
            "uv run python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke probe",
            "local-quality",
            True,
            False,
            "Capability probe exits successfully.",
            "Probe output is local capability evidence, not observed Hermes chat behavior.",
        ),
        ReleaseChecklistItem(
            "release_smoke_plan",
            "Render Hermes release smoke plan",
            "uv run python -m omh.cli release hermes-smoke",
            "release-smoke",
            True,
            False,
            "Release smoke plan renders with plan-only evidence boundaries.",
            "Plan mode does not touch the current Hermes profile.",
        ),
        ReleaseChecklistItem(
            "installed_command_path",
            "Check installed omh command is on PATH",
            f"command -v {omh_display}",
            "installed-command",
            True,
            False,
            "The shell resolves the installed OMH command before any nested smoke uses it.",
            "PATH resolution proves command discoverability only; it does not prove console-script importability.",
        ),
        ReleaseChecklistItem(
            "installed_command_help",
            "Check installed omh command help",
            f"{omh_display} --help",
            "installed-command",
            True,
            False,
            "Installed command prints help successfully.",
            "This proves console-script importability only.",
        ),
        ReleaseChecklistItem(
            "skill_content_smoke",
            "Check installed command package skill content",
            f"{omh_display} release skill-content-smoke --json",
            "installed-command",
            True,
            False,
            "Skill content smoke reports ok=true for router awareness, generated workflow context rails, bundled role context, all-skill awareness lane coverage, full capability manifest context, playbook capability context, standalone plugin capability fallback coverage, G1-G10 use-case demo cards, G1-G10 use-case artifact bundles, G1-G10 natural-language use-case replay, bounded prompt context budgets, and bounded capability payload budgets.",
            "This proves the installed OMH command package can render expected skill guidance; it does not prove Hermes loaded or selected it in chat.",
        ),
        ReleaseChecklistItem(
            "installed_command_smoke",
            "Observe installed command smoke without Hermes mutation",
            (
                f"{omh_display} --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke "
                f"release hermes-smoke --install-path setup --omh-command {omh_display} --include-command-smoke"
            ),
            "installed-command",
            True,
            False,
            "Nested installed_command_smoke is mode=live, observed=true, ok=true, and includes installed skill content smoke.",
            "This observes the installed OMH command path and generated skill guidance while keeping the outer Hermes profile smoke plan-only.",
        ),
        ReleaseChecklistItem(
            "build_artifacts",
            "Build sdist and wheel",
            "uv build",
            "package-build",
            True,
            False,
            "sdist and wheel are built without packaging warnings or errors.",
            "Build output proves package construction, not install success.",
        ),
        ReleaseChecklistItem(
            "wheel_install",
            "Install the built wheel into an isolated venv",
            (
                "python3 -m venv /tmp/omh-wheel-smoke && "
                f"/tmp/omh-wheel-smoke/bin/python -m pip install --upgrade {wheel}"
            ),
            "package-build",
            True,
            False,
            "The isolated venv installs the built wheel successfully.",
            "Wheel install is isolated package evidence, not target Hermes profile evidence.",
        ),
        ReleaseChecklistItem(
            "wheel_command_smoke",
            "Run the wheel-installed command smoke",
            (
                "/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home "
                "release hermes-smoke --install-path setup --omh-command /tmp/omh-wheel-smoke/bin/omh --include-command-smoke"
            ),
            "package-build",
            True,
            False,
            "Wheel-installed command smoke reports nested installed_command_smoke ok=true.",
            "This still does not mutate a real Hermes profile.",
        ),
        ReleaseChecklistItem(
            "wheel_setup_dry_run",
            "Run wheel-installed setup dry-run for the stable release",
            (
                "/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home "
                f"setup --dry-run --channel stable --version {release_version}"
            ),
            "package-build",
            True,
            False,
            "Wheel-installed setup dry-run renders the stable bootstrap plan successfully.",
            "The setup dry-run does not install skills, reload Hermes, or mutate a target profile.",
        ),
        ReleaseChecklistItem(
            "installer_smoke",
            "Run the install.sh smoke in an isolated temp home",
            f"{omh_display} release install-smoke --live --repo-root \"$PWD\" --install-script \"$PWD/install.sh\"",
            "installer",
            True,
            False,
            "install_script_smoke reports ok=true after install.sh creates a temp venv/bin command without running setup or doctor, then proves the installed command can render release smoke.",
            "Install script smoke mutates only its isolated temp HOME/venv/bin unless --work-dir points elsewhere; it is not live Hermes runtime-use evidence.",
        ),
        ReleaseChecklistItem(
            "live_tap_smoke",
            "Run exactly one live Hermes tap smoke before tagging",
            f"{omh_display} release hermes-smoke --live --install-path tap --target-confirmed",
            "manual-release-candidate",
            True,
            True,
            "Hermes CLI install/list/check/inspect commands succeed for the target profile.",
            "This mutates the target Hermes profile and still does not prove later chat selection without wrapper evidence.",
            True,
        ),
        ReleaseChecklistItem(
            "tag_and_publish",
            "Tag and publish only after all required evidence is attached",
            f'git tag -a {tag} -m "Release {tag}" && git push origin {tag}',
            "release-authority",
            False,
            False,
            "Maintainer explicitly approves tag/release publication after local and live evidence are recorded.",
            "This checklist does not create tags, GitHub releases, or production artifacts by itself.",
            True,
        ),
    ]
    return {
        "schema_version": RELEASE_CHECKLIST_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "version": release_version,
        "tag": tag,
        "proof_boundary": (
            "This checklist is a deterministic release plan. It does not run commands, create tags, publish GitHub releases, "
            "or prove Hermes runtime use until the listed evidence is observed separately."
        ),
        "items": [item.to_payload() for item in items],
        "required_item_count": sum(1 for item in items if item.required),
        "manual_authority_item_count": sum(1 for item in items if item.requires_release_authority),
        "recommended_next_action": (
            "Run the required local gates, record one live Hermes smoke from the target profile, then request explicit "
            "release authority before tagging or publishing."
        ),
    }


def product_readiness_report(
    *,
    version: str = __version__,
    omh_command: str = "omh",
    paths: OmhPaths | None = None,
) -> dict[str, object]:
    release_version = _normalize_release_version(version)
    resolved_paths = paths or OmhPaths(omh_home=Path("~/.omh").expanduser(), hermes_home=Path("~/.hermes").expanduser())
    evidence = _build_release_quality_evidence(release_version=release_version, omh_command=omh_command)
    return _product_readiness_report_from_evidence(
        release_version=release_version,
        omh_command=omh_command,
        evidence=evidence,
        paths=resolved_paths,
    )


def _build_release_quality_evidence(*, release_version: str, omh_command: str) -> ReleaseQualityEvidence:
    skill_content = skill_content_smoke()
    parity = build_parity_matrix()
    grounded_score = build_grounded_score_demo()
    chat_cards = build_chat_card_coverage_demo()
    route_hints = build_route_hint_alignment_demo(
        grounded_score=grounded_score,
        chat_card_coverage=chat_cards,
    )
    context_briefs = build_context_brief_coverage_demo()
    routing_precision = build_routing_precision_demo()
    localized_chat_copy = build_localized_chat_copy_demo()
    router_fast_path = build_router_fast_path_demo()
    hermes_ux = build_hermes_ux_quality_demo(
        grounded_score=grounded_score,
        chat_card_coverage=chat_cards,
        route_hint_alignment=route_hints,
        context_brief_coverage=context_briefs,
        routing_precision=routing_precision,
        localized_chat_copy=localized_chat_copy,
        router_fast_path=router_fast_path,
    )
    checklist = release_readiness_checklist(version=release_version, omh_command=omh_command)
    return ReleaseQualityEvidence(
        skill_content=skill_content,
        parity=parity,
        grounded_score=grounded_score,
        chat_cards=chat_cards,
        route_hints=route_hints,
        context_briefs=context_briefs,
        routing_precision=routing_precision,
        localized_chat_copy=localized_chat_copy,
        router_fast_path=router_fast_path,
        hermes_ux=hermes_ux,
        checklist=checklist,
    )


def _product_readiness_report_from_evidence(
    *,
    release_version: str,
    omh_command: str,
    evidence: ReleaseQualityEvidence,
    paths: OmhPaths,
) -> dict[str, object]:
    omh_display = _shell_word(omh_command)
    skill_content = evidence.skill_content
    parity = evidence.parity
    grounded_score = evidence.grounded_score
    chat_cards = evidence.chat_cards
    route_hints = evidence.route_hints
    context_briefs = evidence.context_briefs
    routing_precision = evidence.routing_precision
    localized_chat_copy = evidence.localized_chat_copy
    router_fast_path = evidence.router_fast_path
    hermes_ux = evidence.hermes_ux
    checklist = evidence.checklist
    use_case_readiness_payload = use_case_readiness(paths)
    use_case_readiness_failures = _blocking_gate_messages(use_case_readiness_payload)
    use_case_readiness_warnings = _warning_gate_messages(use_case_readiness_payload)
    local_store_status = _release_local_store_status(use_case_readiness_payload)

    checklist_items = checklist.get("items", [])
    checklist_ids = {
        str(item.get("id"))
        for item in checklist_items
        if isinstance(item, dict) and item.get("id")
    }
    required_checklist_ids = {
        "unit_tests",
        "docs_workflows_check",
        "harness_validate",
        "skill_content_smoke",
        "use_case_readiness",
        "grounded_score",
        "chat_card_coverage",
        "route_hint_alignment",
        "context_brief_coverage",
        "routing_precision",
        "localized_chat_copy",
        "router_fast_path",
        "hermes_ux_quality",
        "product_readiness",
        "release_evidence_bundle",
        "installed_command_smoke",
        "installer_smoke",
        "live_tap_smoke",
    }
    missing_checklist_ids = sorted(required_checklist_ids - checklist_ids)

    parity_summary = parity.get("summary", {}) if isinstance(parity.get("summary"), dict) else {}
    parity_errors = []
    for status_key in ("partial", "planned", "deferred"):
        count = int(parity_summary.get(status_key, 0) or 0)
        if count:
            parity_errors.append(f"{status_key}: {count}")

    grounded_score_errors = _grounded_score_errors(grounded_score)
    chat_card_summary = chat_cards.get("summary", {}) if isinstance(chat_cards.get("summary"), Mapping) else {}
    chat_card_errors = _chat_card_coverage_errors(chat_cards)
    route_hint_summary = route_hints.get("summary", {}) if isinstance(route_hints.get("summary"), Mapping) else {}
    route_hint_errors = _route_hint_alignment_errors(route_hints)
    context_brief_summary = (
        context_briefs.get("summary", {}) if isinstance(context_briefs.get("summary"), Mapping) else {}
    )
    context_brief_errors = _context_brief_coverage_errors(context_briefs)
    routing_precision_summary = (
        routing_precision.get("summary", {}) if isinstance(routing_precision.get("summary"), Mapping) else {}
    )
    routing_precision_gate_errors = routing_precision_errors(routing_precision)
    localized_chat_copy_summary = (
        localized_chat_copy.get("summary", {}) if isinstance(localized_chat_copy.get("summary"), Mapping) else {}
    )
    localized_chat_copy_gate_errors = localized_chat_copy_errors(localized_chat_copy)
    router_fast_path_summary = (
        router_fast_path.get("summary", {}) if isinstance(router_fast_path.get("summary"), Mapping) else {}
    )
    router_fast_path_gate_errors = router_fast_path_errors(router_fast_path)
    hermes_ux_summary = hermes_ux.get("summary", {}) if isinstance(hermes_ux.get("summary"), Mapping) else {}
    hermes_ux_errors = hermes_ux_quality_errors(hermes_ux)
    gates = [
        _product_readiness_gate(
            "skill_content",
            "Installed package skill content",
            "passed" if skill_content.get("ok") else "failed",
            True,
            (
                f"{skill_content.get('skill_count')} skill surface(s), "
                f"{skill_content.get('checked_marker_count')} marker(s), "
                f"{len(skill_content.get('failed_checks', [])) if isinstance(skill_content.get('failed_checks'), list) else 0} failed marker(s)"
            ),
            "omh release skill-content-smoke --json",
            _skill_content_product_errors(skill_content),
            [],
            str(skill_content.get("proof_boundary", "")),
        ),
        _product_readiness_gate(
            "use_cases",
            "G1-G10 application use cases",
            "passed" if use_case_readiness_payload.get("blocking_failures") == 0 else "failed",
            True,
            (
                f"score {use_case_readiness_payload.get('score')}/100; "
                f"blocking {use_case_readiness_payload.get('blocking_failures')}; "
                f"warnings {use_case_readiness_payload.get('warning_count')}; "
                f"local artifact store {local_store_status}"
            ),
            "omh cases readiness --json",
            use_case_readiness_failures,
            use_case_readiness_warnings,
            str(use_case_readiness_payload.get("boundary", "")),
        ),
        _product_readiness_gate(
            "grounded_score",
            "Grounded routing score",
            "passed" if not grounded_score_errors else "failed",
            True,
            _grounded_score_summary_text(grounded_score),
            "omh demo grounded-score --json",
            grounded_score_errors,
            [],
            str(grounded_score.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "chat_card_coverage",
            "Wrapper chat card coverage",
            "passed" if not chat_card_errors else "failed",
            True,
            (
                f"{chat_card_summary.get('passing_count', 0)}/{chat_card_summary.get('case_count', 0)} "
                f"dedicated workflow cards; generic ack {chat_card_summary.get('generic_ack_count', 0)}"
            ),
            "omh demo chat-card-coverage --json",
            chat_card_errors,
            [],
            str(chat_cards.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "route_hint_alignment",
            "Route and awareness hint alignment",
            "passed" if not route_hint_errors else "failed",
            True,
            (
                f"{route_hint_summary.get('aligned_count', 0)}/{route_hint_summary.get('case_count', 0)} "
                f"route hints aligned; missing {route_hint_summary.get('missing_hint_count', 0)}; "
                f"mismatches {route_hint_summary.get('mismatch_count', 0)}"
            ),
            "omh demo route-hint-alignment --json",
            route_hint_errors,
            [],
            str(route_hints.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "context_brief_coverage",
            "Hermes context brief coverage",
            "passed" if not context_brief_errors else "failed",
            True,
            (
                f"{context_brief_summary.get('passing_count', 0)}/{context_brief_summary.get('case_count', 0)} "
                f"context brief cases passing; route hints {context_brief_summary.get('route_hint_count', 0)}; "
                f"catalog picker hints {context_brief_summary.get('catalog_question_count', 0)}"
            ),
            "omh demo context-brief-coverage --json",
            context_brief_errors,
            [],
            str(context_briefs.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "routing_precision",
            "Routing precision boundaries",
            "passed" if not routing_precision_gate_errors else "failed",
            True,
            (
                f"{routing_precision_summary.get('passing_count', 0)}/{routing_precision_summary.get('case_count', 0)} "
                f"negative-control cases; "
                f"{routing_precision_summary.get('intervention_passing_count', 0)}/"
                f"{routing_precision_summary.get('intervention_case_count', 0)} interventions; "
                f"overroutes {routing_precision_summary.get('overroute_count', 0)}; "
                f"catalog pickers {routing_precision_summary.get('catalog_picker_count', 0)}; "
                f"generic ack {routing_precision_summary.get('generic_ack_count', 0)}; "
                f"missed interventions {routing_precision_summary.get('missed_intervention_count', 0)}"
            ),
            "omh demo routing-precision --json",
            routing_precision_gate_errors,
            [],
            str(routing_precision.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "localized_chat_copy",
            "Localized chat-card framing",
            "passed" if not localized_chat_copy_gate_errors else "failed",
            True,
            (
                f"{localized_chat_copy_summary.get('passing_count', 0)}/"
                f"{localized_chat_copy_summary.get('case_count', 0)} localized card cases; "
                f"locales {localized_chat_copy_summary.get('locale_count', 0)}"
            ),
            "omh demo localized-chat-copy --json",
            localized_chat_copy_gate_errors,
            [],
            str(localized_chat_copy.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "router_fast_path",
            "Router fast-path quality",
            "passed" if not router_fast_path_gate_errors else "failed",
            True,
            (
                f"{router_fast_path_summary.get('passing_count', 0)}/"
                f"{router_fast_path_summary.get('case_count', 0)} fast-path cases; "
                f"missing markers {router_fast_path_summary.get('missing_marker_count', 0)}; "
                f"route mismatches {router_fast_path_summary.get('route_mismatch_count', 0)}"
            ),
            "omh demo router-fast-path --json",
            router_fast_path_gate_errors,
            [],
            str(router_fast_path.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "hermes_ux_quality",
            "Hermes-facing UX quality",
            "passed" if not hermes_ux_errors else "failed",
            True,
            (
                f"{hermes_ux_summary.get('passing_gate_count', 0)}/{hermes_ux_summary.get('gate_count', 0)} "
                f"UX gates passing; routing avg {hermes_ux_summary.get('grounded_score_average', 0)}; "
                f"generic ack {hermes_ux_summary.get('chat_card_generic_ack_count', 0)}; "
                f"route mismatches {hermes_ux_summary.get('route_hint_mismatch_count', 0)}; "
                f"context {hermes_ux_summary.get('context_brief_passing_count', 0)}/"
                f"{hermes_ux_summary.get('context_brief_cases', 0)}; "
                f"localized {hermes_ux_summary.get('localized_chat_copy_passing_count', 0)}/"
                f"{hermes_ux_summary.get('localized_chat_copy_cases', 0)}; "
                f"fast paths {hermes_ux_summary.get('router_fast_path_passing_count', 0)}/"
                f"{hermes_ux_summary.get('router_fast_path_cases', 0)}"
            ),
            "omh demo hermes-ux-quality --json",
            hermes_ux_errors,
            [],
            str(hermes_ux.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "parity_contracts",
            "Common runtime parity contract coverage",
            "passed" if not parity_errors else "failed",
            True,
            (
                f"{parity_summary.get('available', 0)}/{parity_summary.get('capability_count', 0)} "
                "capability axis/axes available"
            ),
            "omh probe --parity --json",
            parity_errors,
            [],
            str(parity.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "release_checklist",
            "Release checklist shape",
            "passed" if not missing_checklist_ids and checklist.get("ok") else "failed",
            True,
            f"{checklist.get('required_item_count')} required release gate(s) indexed",
            f"{omh_display} release checklist --version {release_version} --json",
            [f"missing checklist id: {item_id}" for item_id in missing_checklist_ids],
            [],
            str(checklist.get("proof_boundary", "")),
        ),
    ]
    blocking_failures = [gate for gate in gates if gate["blocking"] and gate["status"] != "passed"]
    warnings = [
        str(warning)
        for gate in gates
        for warning in gate.get("warnings", [])
        if warning
    ]
    return {
        "schema_version": PRODUCT_READINESS_SCHEMA,
        "status": "ready" if not blocking_failures else "needs_attention",
        "score": 100 if not blocking_failures else round(((len(gates) - len(blocking_failures)) / max(1, len(gates))) * 100),
        "mode": "live",
        "observed": True,
        "version": release_version,
        "blocking_failures": len(blocking_failures),
        "warning_count": len(warnings),
        "warnings": warnings,
        "local_artifact_store": local_store_status,
        "gates": gates,
        "next_actions": _product_readiness_next_actions(blocking_failures, warnings),
        "boundary": (
            "Product readiness proves deterministic local OMH package and product contracts only. "
            "It does not run the release checklist, mutate Hermes, prove live Hermes chat selection, "
            "run connectors, dispatch executors, review code, pass CI, merge, deliver messages, or spend provider budget."
        ),
    }


def hermes_release_smoke_steps(
    *,
    install_path: str,
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> list[HermesSmokeStep]:
    if install_path not in INSTALL_PATHS:
        raise ValueError(f"unsupported Hermes install path: {install_path}")
    if not skill:
        raise ValueError("Hermes smoke skill must not be empty")
    if install_path == "tap" and not tap:
        raise ValueError("Hermes smoke tap must not be empty for tap installs")
    skill_name = _skill_name_for_hermes(skill)
    tap_identifier = _tap_skill_identifier(tap=tap, skill=skill)
    setup_command = _omh_scoped_command(
        omh_command,
        "setup",
        omh_home=omh_home,
        hermes_home=hermes_home,
    )
    doctor_command = _omh_scoped_command(
        omh_command,
        "doctor",
        omh_home=omh_home,
        hermes_home=hermes_home,
    )
    install_steps = (
        [
            HermesSmokeStep(
                "tap_add",
                ("hermes", "skills", "tap", "add", tap),
                "install",
                True,
                proof_boundary="Registers the OMH GitHub tap in the current Hermes profile; this is setup evidence only.",
            ),
            HermesSmokeStep(
                "skill_install",
                ("hermes", "skills", "install", tap_identifier, "--yes"),
                "install",
                True,
                proof_boundary=(
                    "Installs the router skill by full GitHub identifier in the current Hermes profile; "
                    "this does not prove chat usage."
                ),
            ),
        ]
        if install_path == "tap"
        else [
            HermesSmokeStep(
                "omh_setup",
                setup_command,
                "install",
                True,
                proof_boundary="Bootstraps generated skills and skills.external_dirs for the current Hermes home.",
            )
        ]
    )
    check_steps = [
        HermesSmokeStep(
            "tap_list",
            ("hermes", "skills", "tap", "list"),
            "verify",
            False,
            proof_boundary="Shows configured taps; absence means tap install has not been observed.",
        ),
        HermesSmokeStep(
            "skills_list",
            ("hermes", "skills", "list", "--enabled-only"),
            "verify",
            False,
            proof_boundary="Shows enabled Hermes skills; the OMH router should be visible after install/reload.",
        ),
        HermesSmokeStep(
            "skill_check",
            ("hermes", "skills", "check", skill_name),
            "verify",
            False,
            proof_boundary="Runs Hermes skill validation for the OMH router skill.",
        ),
    ]
    if install_path == "tap":
        check_steps.append(
            HermesSmokeStep(
                "skill_inspect",
                ("hermes", "skills", "inspect", tap_identifier),
                "verify",
                False,
                proof_boundary="Prints Hermes-visible skill metadata/content for operator confirmation.",
            )
        )
    else:
        check_steps.append(
            HermesSmokeStep(
                "setup_doctor",
                doctor_command,
                "verify",
                False,
                proof_boundary=(
                    "Checks OMH-managed local skill registration. Hermes v0.15.1 does not reliably inspect "
                    "skills.external_dirs local skills by short name, so setup-path smoke uses list/check plus OMH doctor."
                ),
            )
        )
    return install_steps + check_steps


def _skill_name_for_hermes(skill: str) -> str:
    return skill.rstrip("/").split("/")[-1]


def _normalize_release_version(version: str) -> str:
    value = str(version or "").strip()
    if value.startswith("v"):
        value = value[1:]
    if not value:
        raise ValueError("release checklist version must not be empty")
    if not RELEASE_VERSION_RE.fullmatch(value):
        raise ValueError("release checklist version must be a tag-safe version like 1.0.0")
    return value


def _shell_word(value: str) -> str:
    stripped = str(value or "").strip()
    if not stripped:
        raise ValueError("release checklist omh command must not be empty")
    return shlex.quote(stripped)


def _tap_skill_identifier(*, tap: str, skill: str) -> str:
    if "/" in skill:
        return skill
    return f"{tap.rstrip('/')}/skills/{skill}"


def hermes_release_smoke_plan(
    *,
    install_path: str = "tap",
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    installed_command_smoke: Mapping[str, object] | None = None,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = hermes_release_smoke_steps(
        install_path=install_path,
        skill=skill,
        tap=tap,
        omh_command=omh_command,
        omh_home=target["omh_home"],
        hermes_home=target["hermes_home"],
    )
    command_smoke = (
        dict(installed_command_smoke)
        if installed_command_smoke is not None
        else installed_command_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        )
    )
    ok = bool(command_smoke.get("ok", True))
    return {
        "schema_version": HERMES_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": ok,
        "observed": False,
        "install_path": install_path,
        "skill": skill,
        "tap": tap,
        "target_binding": target,
        "proof_boundary": (
            "Plan mode does not touch the current Hermes profile and is not evidence that Hermes "
            "installed, loaded, or used OMH. Run with --live against the target profile for observed smoke evidence."
        ),
        "steps": [step.to_payload() for step in steps],
        "installed_command_smoke": command_smoke,
        "first_use_status_smoke": first_use_status_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        ),
        "live_command": _live_smoke_command(install_path, target),
    }


def installed_command_smoke_plan(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = [
        HermesSmokeStep(
            "installed_omh_help",
            (omh_command, "--help"),
            "verify",
            False,
            proof_boundary="Verifies the installed OMH console script is importable and runnable from the current PATH.",
        ),
        HermesSmokeStep(
            "installed_omh_skill_content",
            (omh_command, "release", "skill-content-smoke", "--json"),
            "verify",
            False,
            proof_boundary=(
                "Verifies the installed OMH command package can render router awareness and workflow context rails. "
                "This is package-content evidence only, not Hermes runtime-load evidence."
            ),
        ),
        HermesSmokeStep(
            "installed_omh_setup_plan",
            _omh_release_plan_command(
                omh_command,
                install_path="setup",
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "verify",
            False,
            proof_boundary=(
                "Verifies the installed OMH console script can render the setup-path Hermes smoke plan. "
                "This is still plan evidence, not live Hermes profile mutation."
            ),
        ),
    ]
    return {
        "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "command_under_test": omh_command,
        "target_binding": target,
        "path_check": installed_command_path_check_plan(omh_command),
        "proof_boundary": (
            "Plan mode lists installed-command checks only. Run release hermes-smoke with "
            "--include-command-smoke to observe PATH resolution and the installed OMH executable."
        ),
        "steps": [step.to_payload() for step in steps],
    }


def skill_content_smoke() -> dict[str, object]:
    templates = {template.name: template.content for template in builtin_skill_templates()}
    workflow_skill_names = set(templates) - {DEFAULT_HERMES_SKILL}
    role_contexts = {role.id: role_file_markdown(role) for role in role_definitions()}
    bundled_role_contexts = _bundled_role_contexts()
    awareness = awareness_primer_payload()
    lane_skill_names = _awareness_lane_skill_names(awareness)
    catalog_skill_names = {definition.name for definition in builtin_definitions()}
    missing_awareness_skills = sorted(workflow_skill_names - lane_skill_names)
    unexpected_awareness_surfaces = sorted(lane_skill_names - catalog_skill_names - set(CONCEPTUAL_AWARENESS_SURFACES))
    standalone_capability_skill_names = standalone_skill_capability_ids()
    standalone_capability_items = standalone_skill_capability_items()
    full_capability_items = skill_capabilities()
    full_playbook_items = playbook_capabilities()
    standalone_playbook_items = standalone_playbook_capability_items()
    full_capability_skill_names = {
        str(item.get("id") or "")
        for item in full_capability_items
        if str(item.get("id") or "")
    }
    missing_full_capability_skills = sorted(workflow_skill_names - full_capability_skill_names)
    missing_standalone_capability_skills = sorted(workflow_skill_names - standalone_capability_skill_names)
    unexpected_standalone_capability_skills = sorted(
        standalone_capability_skill_names - catalog_skill_names - set(CONCEPTUAL_AWARENESS_SURFACES)
    )
    required_standalone_context_fields = {
        "workflow_routing_hint",
        "workflow_context_rule",
        "chat_rule",
        "fallback_rule",
        "evidence_boundary",
        "cross_lane_examples",
    }
    required_playbook_context_fields = {
        "workflow_context_rule",
        "chat_rule",
        "fallback_rule",
        "evidence_boundary",
        "prepared_is_not",
        "pipeline",
        "primary_owner_role",
        "stage_owners",
        "available_wrapper_actions",
        "first_stage",
    }
    missing_standalone_capability_context_skills = sorted(
        str(item.get("id") or "")
        for item in standalone_capability_items
        if str(item.get("id") or "") in workflow_skill_names
        and any(not item.get(field) for field in required_standalone_context_fields)
    )
    missing_full_capability_context_skills = sorted(
        str(item.get("id") or "")
        for item in full_capability_items
        if str(item.get("id") or "") in workflow_skill_names
        and any(not item.get(field) for field in required_standalone_context_fields)
    )
    missing_playbook_context_playbooks = sorted(
        str(item.get("id") or "")
        for item in full_playbook_items
        if any(not item.get(field) for field in required_playbook_context_fields)
    )
    missing_standalone_playbook_context_playbooks = sorted(
        str(item.get("id") or "")
        for item in standalone_playbook_items
        if any(not item.get(field) for field in required_playbook_context_fields)
    )
    required_playbook_ids = {
        "request-to-handoff",
        "safe-feature-change",
        "feedback-triage",
        "research-department",
        "materials-processing",
        "idea-to-deploy",
    }
    full_playbook_ids = {str(item.get("id") or "") for item in full_playbook_items}
    standalone_playbook_ids = {str(item.get("id") or "") for item in standalone_playbook_items}
    missing_required_playbook_capabilities = sorted(required_playbook_ids - full_playbook_ids)
    missing_required_standalone_playbook_capabilities = sorted(required_playbook_ids - standalone_playbook_ids)
    full_capability_skill_section_chars = len(json.dumps(full_capability_items, sort_keys=True, ensure_ascii=False))
    standalone_capability_skill_section_chars = len(
        json.dumps(standalone_capability_items, sort_keys=True, ensure_ascii=False)
    )
    use_case_demo_cards = demo_all_use_cases()
    use_case_demo_failures = _use_case_demo_card_failures(use_case_demo_cards)
    use_case_artifact_bundle = build_all_use_case_artifacts()
    use_case_artifact_failures = _use_case_artifact_failures(use_case_artifact_bundle)
    use_case_replay = replay_use_case_fixtures()
    use_case_replay_failures = _use_case_replay_failures(use_case_replay)
    use_case_readiness_payload = use_case_readiness(None)
    use_case_readiness_failures = _blocking_gate_messages(use_case_readiness_payload)
    use_case_readiness_warnings = _warning_gate_messages(use_case_readiness_payload)
    max_full_capability_skill_chars = max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in full_capability_items),
        default=0,
    )
    max_standalone_capability_skill_chars = max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in standalone_capability_items),
        default=0,
    )
    primer_context_chars = len(awareness_primer_context())
    primer_markdown_chars = len(awareness_primer_markdown())
    workflow_context_chars = {
        name: len(awareness_workflow_context_markdown(name))
        for name in sorted(workflow_skill_names)
    }
    role_context_chars = {name: len(context) for name, context in role_contexts.items()}
    oversized_role_contexts = [
        name
        for name, char_count in role_context_chars.items()
        if char_count > ROLE_CONTEXT_CHAR_LIMIT
    ]
    missing_role_context_roles = sorted(
        name
        for name, context in role_contexts.items()
        if any(marker not in context for marker in ROLE_CONTEXT_MARKERS)
    )
    missing_bundled_role_context_roles = sorted(
        name
        for name, context in bundled_role_contexts.items()
        if any(marker not in context for marker in ROLE_CONTEXT_MARKERS)
    )
    missing_bundled_role_files = sorted(set(role_contexts) - set(bundled_role_contexts))
    unexpected_bundled_role_files = sorted(set(bundled_role_contexts) - set(role_contexts))
    stale_bundled_role_context_roles = sorted(
        name
        for name, context in role_contexts.items()
        if bundled_role_contexts.get(name) is not None and bundled_role_contexts[name] != context
    )
    oversized_awareness_contexts = [
        name
        for name, char_count in workflow_context_chars.items()
        if char_count > AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT
    ]
    awareness_budget_failures = []
    if primer_context_chars > AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT:
        awareness_budget_failures.append("awareness_primer_context")
    if primer_markdown_chars > AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT:
        awareness_budget_failures.append("awareness_primer_markdown")
    if oversized_awareness_contexts:
        awareness_budget_failures.append("workflow_context_rail")
    role_context_budget_failures = []
    if oversized_role_contexts:
        role_context_budget_failures.append("role_context")
    capability_budget_failures = []
    if full_capability_skill_section_chars > FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT:
        capability_budget_failures.append("full_capability_skill_section")
    if max_full_capability_skill_chars > FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT:
        capability_budget_failures.append("full_capability_skill_item")
    if standalone_capability_skill_section_chars > STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT:
        capability_budget_failures.append("standalone_capability_skill_section")
    if max_standalone_capability_skill_chars > STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT:
        capability_budget_failures.append("standalone_capability_skill_item")
    checks: list[dict[str, object]] = []

    def add_check(name: str, marker: str, ok: bool, *, scope: str) -> None:
        checks.append(
            {
                "scope": scope,
                "skill": name,
                "marker": marker,
                "ok": ok,
            }
        )

    router = templates.get(DEFAULT_HERMES_SKILL, "")
    for marker in ROUTER_CONTENT_MARKERS:
        add_check(DEFAULT_HERMES_SKILL, marker, marker in router, scope="router_awareness")

    missing_representative = [name for name in REPRESENTATIVE_CONTEXT_RAIL_SKILLS if name not in templates]
    for name, content in sorted(templates.items()):
        if name == DEFAULT_HERMES_SKILL:
            continue
        for marker in WORKFLOW_CONTEXT_MARKERS:
            add_check(name, marker, marker in content, scope="workflow_context_rail")

    failed_checks = [check for check in checks if not check["ok"]]
    ok = (
        not failed_checks
        and not missing_representative
        and not missing_awareness_skills
        and not unexpected_awareness_surfaces
        and not missing_full_capability_skills
        and not missing_full_capability_context_skills
        and not missing_playbook_context_playbooks
        and not missing_required_playbook_capabilities
        and not missing_standalone_capability_skills
        and not unexpected_standalone_capability_skills
        and not missing_standalone_capability_context_skills
        and not missing_standalone_playbook_context_playbooks
        and not missing_required_standalone_playbook_capabilities
        and not missing_role_context_roles
        and not missing_bundled_role_context_roles
        and not missing_bundled_role_files
        and not unexpected_bundled_role_files
        and not stale_bundled_role_context_roles
        and not awareness_budget_failures
        and not role_context_budget_failures
        and not capability_budget_failures
        and not use_case_demo_failures
        and not use_case_artifact_failures
        and not use_case_replay_failures
        and not use_case_readiness_failures
    )
    return {
        "schema_version": SKILL_CONTENT_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": True,
        "skill_count": len(templates),
        "catalog_skill_count": len(catalog_skill_names),
        "router_skill": DEFAULT_HERMES_SKILL,
        "workflow_skill_count": max(len(templates) - 1, 0),
        "non_installed_catalog_surface_count": len(catalog_skill_names - set(templates)),
        "representative_skills": list(REPRESENTATIVE_CONTEXT_RAIL_SKILLS),
        "missing_representative_skills": missing_representative,
        "awareness_lane_skill_count": len(lane_skill_names),
        "missing_awareness_lane_skills": missing_awareness_skills,
        "unexpected_awareness_surfaces": unexpected_awareness_surfaces,
        "allowed_conceptual_awareness_surfaces": list(CONCEPTUAL_AWARENESS_SURFACES),
        "full_capability_skill_count": len(full_capability_skill_names),
        "missing_full_capability_skills": missing_full_capability_skills,
        "missing_full_capability_context_skills": missing_full_capability_context_skills,
        "playbook_capability_count": len(full_playbook_items),
        "standalone_playbook_capability_count": len(standalone_playbook_items),
        "required_playbook_capability_ids": sorted(required_playbook_ids),
        "missing_required_playbook_capabilities": missing_required_playbook_capabilities,
        "missing_required_standalone_playbook_capabilities": missing_required_standalone_playbook_capabilities,
        "missing_playbook_context_playbooks": missing_playbook_context_playbooks,
        "missing_standalone_playbook_context_playbooks": missing_standalone_playbook_context_playbooks,
        "standalone_capability_skill_count": len(standalone_capability_skill_names),
        "missing_standalone_capability_skills": missing_standalone_capability_skills,
        "unexpected_standalone_capability_skills": unexpected_standalone_capability_skills,
        "missing_standalone_capability_context_skills": missing_standalone_capability_context_skills,
        "role_context_count": len(role_contexts),
        "missing_role_context_roles": missing_role_context_roles,
        "bundled_role_context_count": len(bundled_role_contexts),
        "missing_bundled_role_context_roles": missing_bundled_role_context_roles,
        "missing_bundled_role_files": missing_bundled_role_files,
        "unexpected_bundled_role_files": unexpected_bundled_role_files,
        "stale_bundled_role_context_roles": stale_bundled_role_context_roles,
        "required_role_context_markers": list(ROLE_CONTEXT_MARKERS),
        "required_capability_context_fields": sorted(required_standalone_context_fields),
        "required_standalone_capability_context_fields": sorted(required_standalone_context_fields),
        "required_playbook_context_fields": sorted(required_playbook_context_fields),
        "capability_context_char_limits": {
            "full_skill_section": FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            "full_skill_item": FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
            "standalone_skill_section": STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            "standalone_skill_item": STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
        },
        "full_capability_skill_section_chars": full_capability_skill_section_chars,
        "max_full_capability_skill_chars": max_full_capability_skill_chars,
        "standalone_capability_skill_section_chars": standalone_capability_skill_section_chars,
        "max_standalone_capability_skill_chars": max_standalone_capability_skill_chars,
        "capability_budget_failures": capability_budget_failures,
        "use_case_demo_collection_schema": use_case_demo_cards.get("schema_version"),
        "use_case_demo_card_count": len(use_case_demo_cards.get("cards", []))
        if isinstance(use_case_demo_cards.get("cards"), list)
        else 0,
        "expected_use_case_demo_card_count": len(USE_CASES),
        "use_case_demo_failures": use_case_demo_failures,
        "use_case_artifact_collection_schema": use_case_artifact_bundle.get("schema_version"),
        "use_case_artifact_count": len(use_case_artifact_bundle.get("artifacts", []))
        if isinstance(use_case_artifact_bundle.get("artifacts"), list)
        else 0,
        "expected_use_case_artifact_count": len(USE_CASES),
        "use_case_artifact_failures": use_case_artifact_failures,
        "use_case_replay_schema": use_case_replay.get("schema_version"),
        "use_case_replay_status": use_case_replay.get("status"),
        "use_case_replay_total": use_case_replay.get("total"),
        "use_case_replay_passed": use_case_replay.get("passed"),
        "expected_use_case_replay_total": use_case_replay.get("expected_total"),
        "use_case_replay_failures": use_case_replay_failures,
        "use_case_readiness_schema": use_case_readiness_payload.get("schema_version"),
        "use_case_readiness_status": use_case_readiness_payload.get("status"),
        "use_case_readiness_score": use_case_readiness_payload.get("score"),
        "use_case_readiness_blocking_failures": use_case_readiness_payload.get("blocking_failures"),
        "use_case_readiness_warning_count": use_case_readiness_payload.get("warning_count"),
        "use_case_readiness_failures": use_case_readiness_failures,
        "use_case_readiness_warnings": use_case_readiness_warnings,
        "use_case_readiness_boundary": use_case_readiness_payload.get("boundary"),
        "awareness_context_char_limits": {
            "primer_context": AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
            "primer_markdown": AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
            "workflow_context": AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
            "role_context": ROLE_CONTEXT_CHAR_LIMIT,
        },
        "awareness_primer_context_chars": primer_context_chars,
        "awareness_primer_markdown_chars": primer_markdown_chars,
        "max_workflow_context_chars": max(workflow_context_chars.values(), default=0),
        "max_role_context_chars": max(role_context_chars.values(), default=0),
        "oversized_awareness_contexts": oversized_awareness_contexts,
        "awareness_budget_failures": awareness_budget_failures,
        "oversized_role_contexts": oversized_role_contexts,
        "role_context_budget_failures": role_context_budget_failures,
        "checked_marker_count": len(checks),
        "failed_checks": failed_checks,
        "proof_boundary": (
            "This validates generated skill guidance inside the current OMH command package. "
            "It does not prove the target Hermes profile installed, loaded, selected, or used those skills in chat."
        ),
    }


def _product_readiness_gate(
    gate_id: str,
    title: str,
    status: str,
    blocking: bool,
    summary: str,
    command: str,
    errors: Sequence[object] | None,
    warnings: Sequence[object] | None,
    proof_boundary: str,
) -> dict[str, object]:
    return {
        "id": gate_id,
        "title": title,
        "status": status,
        "blocking": blocking,
        "summary": summary,
        "command": command,
        "errors": [str(error) for error in errors or []],
        "warnings": [str(warning) for warning in warnings or []],
        "proof_boundary": proof_boundary,
    }


def _skill_content_product_errors(payload: Mapping[str, object]) -> list[str]:
    keys = (
        "failed_checks",
        "missing_representative_skills",
        "missing_awareness_lane_skills",
        "unexpected_awareness_surfaces",
        "missing_full_capability_skills",
        "missing_full_capability_context_skills",
        "missing_playbook_context_playbooks",
        "missing_required_playbook_capabilities",
        "missing_standalone_capability_skills",
        "unexpected_standalone_capability_skills",
        "missing_standalone_capability_context_skills",
        "missing_standalone_playbook_context_playbooks",
        "missing_required_standalone_playbook_capabilities",
        "missing_role_context_roles",
        "missing_bundled_role_context_roles",
        "missing_bundled_role_files",
        "unexpected_bundled_role_files",
        "stale_bundled_role_context_roles",
        "awareness_budget_failures",
        "role_context_budget_failures",
        "capability_budget_failures",
        "use_case_demo_failures",
        "use_case_artifact_failures",
        "use_case_replay_failures",
        "use_case_readiness_failures",
    )
    errors: list[str] = []
    for key in keys:
        values = payload.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
            errors.append(f"{key}: {len(values)}")
    if not payload.get("ok"):
        errors.append("skill_content_smoke_ok_false")
    return errors


def _chat_card_coverage_ready(payload: Mapping[str, object]) -> bool:
    return not _chat_card_coverage_errors(payload)


def _grounded_score_ready(payload: Mapping[str, object]) -> bool:
    return not _grounded_score_errors(payload)


def _route_hint_alignment_ready(payload: Mapping[str, object]) -> bool:
    return not _route_hint_alignment_errors(payload)


def _context_brief_coverage_ready(payload: Mapping[str, object]) -> bool:
    return not _context_brief_coverage_errors(payload)


def _grounded_score_summary_text(payload: Mapping[str, object]) -> str:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return "grounded score summary missing"
    total = int(summary.get("scenario_count", 0) or 0)
    minimum = summary.get("minimum_score", 0)
    average = summary.get("average_score", 0)
    maximum = summary.get("maximum_score", 0)
    perfect_count = sum(
        1
        for scenario in _mapping_rows(payload.get("scenarios"))
        if int(scenario.get("score", 0) or 0) == 10
    )
    return f"{perfect_count}/{total} scenarios at 10/10; min {minimum}, avg {average}, max {maximum}"


def _grounded_score_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_10")):
        errors.append("not_all_grounded_scenarios_scored_10")
    if str(summary.get("score_scale") or "") != "0_to_10":
        errors.append(f"unexpected_score_scale: {summary.get('score_scale')}")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, Sequence) or isinstance(scenarios, (str, bytes)):
        errors.append("scenarios_not_sequence")
        return errors
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            errors.append("scenario_not_mapping")
            continue
        score = int(scenario.get("score", 0) or 0)
        if score == 10:
            continue
        scenario_id = str(scenario.get("id") or "unknown")
        failed_checks = [
            str(check.get("name", "unknown"))
            for check in _mapping_rows(scenario.get("checks"))
            if not bool(check.get("passed"))
        ]
        errors.append(f"{scenario_id}: score {score}/10 ({', '.join(failed_checks) or 'unknown check failure'})")
    return errors


def _chat_card_coverage_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_passing")):
        errors.append("not_all_card_coverage_cases_passed")
    if int(summary.get("generic_ack_count", 0) or 0) != 0:
        errors.append(f"generic_ack_count: {summary.get('generic_ack_count')}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        issues = case.get("issues")
        if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes)):
            issue_text = ", ".join(str(issue) for issue in issues) or "unknown issue"
        else:
            issue_text = "unknown issue"
        errors.append(f"{case_id}: {issue_text}")
    return errors


def _route_hint_alignment_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_aligned")):
        errors.append("not_all_route_hints_aligned")
    if int(summary.get("missing_hint_count", 0) or 0):
        errors.append(f"missing_hint_count: {summary.get('missing_hint_count')}")
    if int(summary.get("mismatch_count", 0) or 0):
        errors.append(f"mismatch_count: {summary.get('mismatch_count')}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("aligned")):
            continue
        errors.append(
            f"{case.get('corpus', 'unknown')}:{case.get('id', 'unknown')}: "
            f"{', '.join(_string_list(case.get('issues'))) or 'unknown alignment failure'}"
        )
    return errors


def _context_brief_coverage_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_passing")):
        errors.append("not_all_context_brief_cases_passed")
    if int(summary.get("route_hint_count", 0) or 0) < 1:
        errors.append("route_hint_count_zero")
    if int(summary.get("catalog_question_count", 0) or 0) < 1:
        errors.append("catalog_question_count_zero")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_list(case.get('issues'))) or 'unknown context failure'}")
    return errors


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _blocking_gate_messages(payload: Mapping[str, object]) -> list[str]:
    gates = payload.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        return ["gates_not_sequence"]
    messages = []
    for gate in gates:
        if not isinstance(gate, Mapping):
            messages.append("gate_not_mapping")
            continue
        if gate.get("blocking") and gate.get("status") != "passed":
            messages.append(f"{gate.get('id', 'unknown')}: {gate.get('summary', gate.get('status', 'failed'))}")
    return messages


def _warning_gate_messages(payload: Mapping[str, object]) -> list[str]:
    gates = payload.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        return []
    messages = []
    for gate in gates:
        if not isinstance(gate, Mapping):
            continue
        if not gate.get("blocking") and gate.get("status") != "passed":
            messages.append(f"{gate.get('id', 'unknown')}: {gate.get('status', 'warning')}")
    return messages


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _product_readiness_next_actions(blocking_failures: Sequence[Mapping[str, object]], warnings: Sequence[str]) -> list[str]:
    if blocking_failures:
        return [
            "Fix blocking product readiness gates, then rerun `omh release product-readiness --json`.",
            "Use the per-gate command to inspect the failing contract before tagging.",
        ]
    actions = [
        "Write `omh release evidence-bundle --version <version> --write --json` and attach it to the release notes or PR.",
        "Attach observed evidence for each required release checklist item before tagging or publishing.",
        "Run one live Hermes tap smoke from the target profile before treating Hermes runtime visibility as observed.",
        "Use `omh release product-readiness --json` when a wrapper or release note needs the full machine-readable payload.",
    ]
    if any(warning.startswith("local_artifact_store:") for warning in warnings):
        actions.insert(0, "Optional: write local use-case artifacts with `omh cases artifact --all --write --json`.")
    elif warnings:
        actions.insert(0, "Review non-blocking warnings; they should be acknowledged but do not block local product readiness.")
    return actions


def release_evidence_bundle(
    *,
    version: str = __version__,
    omh_command: str = "omh",
    paths: OmhPaths | None = None,
    write: bool = False,
) -> dict[str, object]:
    release_version = _normalize_release_version(version)
    resolved_paths = paths or OmhPaths(omh_home=Path("~/.omh").expanduser(), hermes_home=Path("~/.hermes").expanduser())
    quality_evidence = _build_release_quality_evidence(release_version=release_version, omh_command=omh_command)
    checklist = quality_evidence.checklist
    product = _product_readiness_report_from_evidence(
        release_version=release_version,
        omh_command=omh_command,
        evidence=quality_evidence,
        paths=resolved_paths,
    )
    skill_content = quality_evidence.skill_content
    use_cases = use_case_readiness(resolved_paths)
    grounded_score = quality_evidence.grounded_score
    chat_cards = quality_evidence.chat_cards
    route_hints = quality_evidence.route_hints
    context_briefs = quality_evidence.context_briefs
    routing_precision = quality_evidence.routing_precision
    localized_chat_copy = quality_evidence.localized_chat_copy
    router_fast_path = quality_evidence.router_fast_path
    hermes_ux = quality_evidence.hermes_ux
    parity = quality_evidence.parity
    local_store_status = _release_local_store_status(use_cases)
    required_status = {
        "release_checklist": "passed" if checklist.get("ok") else "failed",
        "product_readiness": "passed" if product.get("status") == "ready" else "failed",
        "skill_content": "passed" if skill_content.get("ok") else "failed",
        "use_case_readiness": "passed" if use_cases.get("blocking_failures") == 0 else "failed",
        "grounded_score": "passed" if _grounded_score_ready(grounded_score) else "failed",
        "chat_card_coverage": "passed" if _chat_card_coverage_ready(chat_cards) else "failed",
        "route_hint_alignment": "passed" if _route_hint_alignment_ready(route_hints) else "failed",
        "context_brief_coverage": "passed" if _context_brief_coverage_ready(context_briefs) else "failed",
        "routing_precision": "passed" if not routing_precision_errors(routing_precision) else "failed",
        "localized_chat_copy": "passed" if not localized_chat_copy_errors(localized_chat_copy) else "failed",
        "router_fast_path": "passed" if not router_fast_path_errors(router_fast_path) else "failed",
        "hermes_ux_quality": "passed" if not hermes_ux_quality_errors(hermes_ux) else "failed",
        "parity_contracts": "passed" if _parity_contracts_ready(parity) else "failed",
    }
    blocking_failures = [
        f"{gate_id}: {status}"
        for gate_id, status in required_status.items()
        if status != "passed"
    ]
    warnings = []
    if local_store_status != "passed":
        warnings.append(f"local_artifact_store: {local_store_status}")
    grounded_score_summary = grounded_score.get("summary", {}) if isinstance(grounded_score.get("summary"), Mapping) else {}
    chat_card_summary = chat_cards.get("summary", {}) if isinstance(chat_cards.get("summary"), Mapping) else {}
    route_hint_summary = route_hints.get("summary", {}) if isinstance(route_hints.get("summary"), Mapping) else {}
    context_brief_summary = (
        context_briefs.get("summary", {}) if isinstance(context_briefs.get("summary"), Mapping) else {}
    )
    routing_precision_summary = (
        routing_precision.get("summary", {}) if isinstance(routing_precision.get("summary"), Mapping) else {}
    )
    localized_chat_copy_summary = (
        localized_chat_copy.get("summary", {}) if isinstance(localized_chat_copy.get("summary"), Mapping) else {}
    )
    router_fast_path_summary = (
        router_fast_path.get("summary", {}) if isinstance(router_fast_path.get("summary"), Mapping) else {}
    )
    hermes_ux_summary = hermes_ux.get("summary", {}) if isinstance(hermes_ux.get("summary"), Mapping) else {}
    payload: dict[str, object] = {
        "schema_version": RELEASE_EVIDENCE_BUNDLE_SCHEMA,
        "mode": "live",
        "observed": True,
        "written": False,
        "version": release_version,
        "tag": f"v{release_version}",
        "created_at": utc_now(),
        "status": "ready" if not blocking_failures else "needs_attention",
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "summary": {
            "release_checklist_required_items": checklist.get("required_item_count"),
            "product_readiness_status": product.get("status"),
            "product_readiness_score": product.get("score"),
            "skill_content_ok": skill_content.get("ok"),
            "use_case_readiness_status": use_cases.get("status"),
            "use_case_readiness_score": use_cases.get("score"),
            "grounded_score_perfect": sum(
                1
                for scenario in _mapping_rows(grounded_score.get("scenarios"))
                if int(scenario.get("score", 0) or 0) == 10
            ),
            "grounded_score_total": grounded_score_summary.get("scenario_count"),
            "grounded_score_average": grounded_score_summary.get("average_score"),
            "chat_card_coverage_passing": chat_card_summary.get("passing_count"),
            "chat_card_coverage_total": chat_card_summary.get("case_count"),
            "chat_card_generic_ack_count": chat_card_summary.get("generic_ack_count"),
            "route_hint_alignment_aligned": route_hint_summary.get("aligned_count"),
            "route_hint_alignment_total": route_hint_summary.get("case_count"),
            "route_hint_missing_count": route_hint_summary.get("missing_hint_count"),
            "route_hint_mismatch_count": route_hint_summary.get("mismatch_count"),
            "context_brief_coverage_passing": context_brief_summary.get("passing_count"),
            "context_brief_coverage_total": context_brief_summary.get("case_count"),
            "context_brief_route_hint_count": context_brief_summary.get("route_hint_count"),
            "context_brief_catalog_question_count": context_brief_summary.get("catalog_question_count"),
            "routing_precision_passing": routing_precision_summary.get("passing_count"),
            "routing_precision_total": routing_precision_summary.get("case_count"),
            "routing_precision_overroute_count": routing_precision_summary.get("overroute_count"),
            "routing_precision_catalog_picker_count": routing_precision_summary.get("catalog_picker_count"),
            "routing_precision_generic_ack_count": routing_precision_summary.get("generic_ack_count"),
            "routing_precision_intervention_passing": routing_precision_summary.get("intervention_passing_count"),
            "routing_precision_intervention_total": routing_precision_summary.get("intervention_case_count"),
            "routing_precision_missed_intervention_count": routing_precision_summary.get("missed_intervention_count"),
            "localized_chat_copy_passing": localized_chat_copy_summary.get("passing_count"),
            "localized_chat_copy_total": localized_chat_copy_summary.get("case_count"),
            "localized_chat_copy_locale_count": localized_chat_copy_summary.get("locale_count"),
            "router_fast_path_passing": router_fast_path_summary.get("passing_count"),
            "router_fast_path_total": router_fast_path_summary.get("case_count"),
            "router_fast_path_missing_marker_count": router_fast_path_summary.get("missing_marker_count"),
            "hermes_ux_quality_score": hermes_ux.get("score"),
            "hermes_ux_quality_passing_gates": hermes_ux_summary.get("passing_gate_count"),
            "hermes_ux_quality_total_gates": hermes_ux_summary.get("gate_count"),
            "local_artifact_store": local_store_status,
            "parity_available": (parity.get("summary") or {}).get("available")
            if isinstance(parity.get("summary"), Mapping)
            else None,
            "parity_capability_count": (parity.get("summary") or {}).get("capability_count")
            if isinstance(parity.get("summary"), Mapping)
            else None,
        },
        "evidence": {
            "release_checklist": checklist,
            "product_readiness": product,
            "skill_content": skill_content,
            "use_case_readiness": use_cases,
            "grounded_score": grounded_score,
            "chat_card_coverage": chat_cards,
            "route_hint_alignment": route_hints,
            "context_brief_coverage": context_briefs,
            "routing_precision": routing_precision,
            "localized_chat_copy": localized_chat_copy,
            "router_fast_path": router_fast_path,
            "hermes_ux_quality": hermes_ux,
            "parity_contracts": parity,
        },
        "claims": [
            "deterministic_local_package_contracts_checked",
            "release_checklist_indexed",
            "product_readiness_rollup_ready",
            "skill_content_smoke_ready",
            "g1_to_g10_use_case_readiness_ready",
            "grounded_score_ready",
            "chat_card_coverage_ready",
            "route_hint_alignment_ready",
            "context_brief_coverage_ready",
            "routing_precision_ready",
            "localized_chat_copy_ready",
            "router_fast_path_ready",
            "hermes_ux_quality_ready",
            "parity_contract_matrix_ready",
        ],
        "not_evidence_for": [
            "live_hermes_chat_selection",
            "connector_execution",
            "executor_dispatch",
            "implementation",
            "review",
            "ci",
            "merge",
            "delivery",
            "billing_or_provider_budget",
            "github_release_publication",
        ],
        "next_actions": _release_evidence_next_actions(blocking_failures, local_store_status),
        "boundary": (
            "A release evidence bundle packages deterministic local OMH evidence and optional local artifact-store state. "
            "It does not mutate Hermes, run live profile smoke, call connectors, dispatch executors, review code, pass CI, "
            "merge, deliver messages, publish GitHub releases, or prove provider billing/quota truth."
        ),
    }
    if write:
        artifact_path = resolved_paths.release_evidence_dir / f"omh-release-evidence-{release_version}.json"
        payload["written"] = True
        payload["artifact_path"] = str(artifact_path)
        atomic_write_json(artifact_path, payload, private=True)
        _write_release_evidence_index(resolved_paths, payload)
    else:
        payload["artifact_path"] = str(resolved_paths.release_evidence_dir / f"omh-release-evidence-{release_version}.json")
    return payload


def _release_evidence_next_actions(blocking_failures: Sequence[str], local_store_status: str) -> list[str]:
    if blocking_failures:
        return [
            "Fix blocking bundle gates, then rerun `omh release evidence-bundle --write --json`.",
            "Inspect the nested evidence payload for the failing gate before tagging.",
        ]
    actions = [
        "Attach this bundle to the release PR or release notes as local deterministic evidence.",
        "Run the required CI and live Hermes smoke separately; this bundle does not observe those remote/runtime gates.",
    ]
    if local_store_status != "passed":
        actions.insert(0, "Run `omh cases artifact --all --write --json` if you want the optional local use-case artifact store populated.")
    return actions


def _release_local_store_status(use_case_payload: Mapping[str, object]) -> str:
    gates = use_case_payload.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        return "unknown"
    for gate in gates:
        if isinstance(gate, Mapping) and gate.get("id") == "local_artifact_store":
            return str(gate.get("status") or "unknown")
    return "missing"


def _parity_contracts_ready(payload: Mapping[str, object]) -> bool:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return False
    for key in ("partial", "planned", "deferred"):
        if int(summary.get(key, 0) or 0) != 0:
            return False
    return int(summary.get("available", 0) or 0) == int(summary.get("capability_count", 0) or 0)


def _write_release_evidence_index(paths: OmhPaths, payload: Mapping[str, object]) -> None:
    version = str(payload.get("version") or "")
    artifact_path = str(payload.get("artifact_path") or "")
    existing, _ = read_json_object_result(paths.release_evidence_index_path)
    entries = []
    if existing and isinstance(existing.get("entries"), list):
        entries = [entry for entry in existing["entries"] if isinstance(entry, dict) and entry.get("version") != version]
    entries.append(
        {
            "version": version,
            "tag": payload.get("tag"),
            "status": payload.get("status"),
            "created_at": payload.get("created_at"),
            "artifact_path": artifact_path,
            "schema_version": payload.get("schema_version"),
        }
    )
    entries.sort(key=lambda entry: str(entry.get("created_at") or ""))
    index = {
        "schema_version": "omh_release_evidence_index/v1",
        "latest_version": version,
        "latest_artifact_path": artifact_path,
        "count": len(entries),
        "entries": entries,
    }
    atomic_write_json(paths.release_evidence_index_path, index, private=True)


def _use_case_demo_card_failures(payload: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if payload.get("schema_version") != "omh_use_case_demo_collection/v1":
        failures.append("collection_schema")
    cards = payload.get("cards", [])
    if not isinstance(cards, Sequence) or isinstance(cards, (str, bytes)):
        return failures + ["cards_not_sequence"]
    if len(cards) != len(USE_CASES):
        failures.append("card_count")
    expected_goals = [case.goal for case in USE_CASES]
    observed_goals: list[str] = []
    for index, card in enumerate(cards):
        if not isinstance(card, Mapping):
            failures.append(f"card_{index}_not_mapping")
            continue
        goal = str(card.get("goal") or "")
        observed_goals.append(goal)
        if card.get("schema_version") != "omh_use_case_demo_card/v1":
            failures.append(f"{goal or index}_schema")
        route = card.get("route")
        wrapper_card = card.get("wrapper_card")
        evidence = card.get("evidence")
        actions = card.get("actions")
        chat_surface = card.get("chat_surface")
        if not isinstance(route, Mapping) or not route.get("primary_skill") or not route.get("next_action"):
            failures.append(f"{goal or index}_route")
        if not isinstance(wrapper_card, Mapping) or wrapper_card.get("component") != "omh_use_case_card":
            failures.append(f"{goal or index}_wrapper_card")
        if isinstance(wrapper_card, Mapping) and wrapper_card.get("status") != "prepared_not_observed":
            failures.append(f"{goal or index}_wrapper_status")
        if not isinstance(evidence, Mapping) or evidence.get("state") != "prepared_not_observed":
            failures.append(f"{goal or index}_evidence_state")
        boundary = str(evidence.get("claim_boundary") if isinstance(evidence, Mapping) else "")
        if "not " not in boundary.casefold() or "evidence" not in boundary.casefold():
            failures.append(f"{goal or index}_boundary")
        if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)) or not actions:
            failures.append(f"{goal or index}_actions")
        elif isinstance(route, Mapping) and isinstance(actions[0], Mapping) and actions[0].get("id") != route.get("next_action"):
            failures.append(f"{goal or index}_primary_action")
        if not isinstance(chat_surface, Mapping) or not str(chat_surface.get("headline") or "").startswith("[omh] "):
            failures.append(f"{goal or index}_chat_surface")
    if observed_goals != expected_goals:
        failures.append("goal_order")
    return failures


def _use_case_artifact_failures(payload: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if payload.get("schema_version") != "omh_use_case_artifact_collection/v1":
        failures.append("collection_schema")
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        return failures + ["artifacts_not_sequence"]
    if len(artifacts) != len(USE_CASES):
        failures.append("artifact_count")
    expected_goals = [case.goal for case in USE_CASES]
    observed_goals: list[str] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"artifact_{index}_not_mapping")
            continue
        goal = str(artifact.get("goal") or "")
        observed_goals.append(goal)
        for error in validate_use_case_artifact(artifact):
            failures.append(f"{goal or index}: {error}")
        steps = artifact.get("operator_steps", [])
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            failures.append(f"{goal or index}_operator_steps")
        elif not any(isinstance(step, Mapping) and step.get("kind") == "hermes_prompt" for step in steps):
            failures.append(f"{goal or index}_missing_hermes_prompt_step")
        proof_surfaces = artifact.get("proof_surfaces", [])
        if not isinstance(proof_surfaces, Sequence) or isinstance(proof_surfaces, (str, bytes)):
            failures.append(f"{goal or index}_proof_surfaces")
        elif "omh cases validate --json" not in proof_surfaces:
            failures.append(f"{goal or index}_missing_validate_surface")
    if observed_goals != expected_goals:
        failures.append("goal_order")
    return failures


def _use_case_replay_failures(payload: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if payload.get("schema_version") != "omh_use_case_replay/v1":
        failures.append("schema")
    if payload.get("status") != "passed":
        failures.append("status")
    results = payload.get("results", [])
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        return failures + ["results_not_sequence"]
    expected_goals = {case.goal for case in USE_CASES}
    covered_goals = {str(result.get("goal", "")) for result in results if isinstance(result, Mapping)}
    if covered_goals != expected_goals:
        failures.append("goal_coverage")
    if len(results) < len(USE_CASES):
        failures.append("fixture_count")
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            failures.append(f"result_{index}_not_mapping")
            continue
        if result.get("status") != "passed":
            failures.append(f"{result.get('fixture_id', index)}_failed")
        expected = result.get("expected", {})
        observed = result.get("observed", {})
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            failures.append(f"{result.get('fixture_id', index)}_route_shape")
            continue
        if expected.get("goal") != observed.get("goal"):
            failures.append(f"{result.get('fixture_id', index)}_goal")
        if expected.get("primary_skill") != observed.get("primary_skill"):
            failures.append(f"{result.get('fixture_id', index)}_primary_skill")
    return failures


def _bundled_role_contexts() -> dict[str, str]:
    try:
        root = resources.files("omh.plugin_bundle.omh.references")
    except (ModuleNotFoundError, FileNotFoundError):
        return {}
    contexts: dict[str, str] = {}
    for path in root.iterdir():
        if not path.is_file() or not path.name.startswith("role-") or path.name == "role-.md":
            continue
        role_id = path.name.removeprefix("role-").removesuffix(".md")
        try:
            contexts[role_id] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return contexts


def _awareness_lane_skill_names(payload: Mapping[str, object]) -> set[str]:
    names: set[str] = set()
    lanes = payload.get("lanes", [])
    if not isinstance(lanes, Sequence) or isinstance(lanes, (str, bytes)):
        return names
    for lane in lanes:
        if not isinstance(lane, Mapping):
            continue
        skills = lane.get("skills", [])
        if not isinstance(skills, Sequence) or isinstance(skills, (str, bytes)):
            continue
        names.update(str(skill) for skill in skills)
    return names


def first_use_status_smoke_plan(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    message: str = DEFAULT_FIRST_USE_MESSAGE,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    session_id = "<session_id>"
    return {
        "schema_version": FIRST_USE_STATUS_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "example_message": message,
        "target_binding": target,
        "proof_boundary": (
            "This first-use smoke is fixture-backed guidance for wrapper/Hermes status UX. It does not prove "
            "a live chat selected OMH unless the wrapper records that chat response."
        ),
        "steps": [
            {
                "name": "chat_session_start",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "start",
                        "--source",
                        "hermes",
                        "--source-event-id",
                        "release-smoke-message",
                        "--channel-ref",
                        "release-smoke",
                        message,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Creates or resumes a metadata-only wrapper session and returns a status card without executor open/result actions.",
                "proof_boundary": "Starting a wrapper session is routing/status evidence only; it is not execution evidence.",
            },
            {
                "name": "chat_session_accept_plan",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "accept-plan",
                        session_id,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Records explicit plan acceptance before any coding handoff can be prepared.",
                "proof_boundary": "Plan acceptance is a wrapper decision; it is still not dispatch or execution evidence.",
            },
            {
                "name": "chat_session_select_executor",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "select-executor",
                        session_id,
                        "codex",
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Records the selected coding agent before backend open/attach actions become visible.",
                "proof_boundary": "Executor selection is not executor dispatch; it only chooses the handoff target.",
            },
            {
                "name": "chat_session_prepare_handoff",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "prepare-handoff",
                        session_id,
                        message,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Prepares the coding handoff while keeping dispatch/result/verification not observed.",
                "proof_boundary": "A prepared handoff is not an observed executor open, result, review, CI, or merge.",
            },
            {
                "name": "chat_session_status_after_handoff",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "status",
                        session_id,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "After plan acceptance, executor selection, and handoff preparation, status shows prepared handoff without observed dispatch/result.",
                "proof_boundary": "Prepared handoff status remains prepared_not_observed until dispatch/result evidence is recorded.",
            },
        ],
        "expected_status_boundary": {
            "before_handoff": {
                "executor_actions_visible": False,
                "forbidden_action_ids": [
                    "open_executor_session",
                    "attach_executor_session",
                    "record_executor_completed",
                    "record_executor_blocked",
                    "record_executor_failed",
                    "ask_hermes_verify",
                ],
            },
            "after_handoff": {
                "handoff": "prepared",
                "dispatch": "not_observed",
                "result": "not_observed",
                "verification": "not_requested",
            },
        },
    }


def run_hermes_release_smoke(
    *,
    install_path: str = "tap",
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    timeout_seconds: int = 30,
    runner: Runner | None = None,
    include_command_smoke: bool = False,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Hermes smoke timeout must be at least one second")
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = hermes_release_smoke_steps(
        install_path=install_path,
        skill=skill,
        tap=tap,
        omh_command=omh_command,
        omh_home=target["omh_home"],
        hermes_home=target["hermes_home"],
    )
    execute = runner or subprocess_runner
    command_smoke = (
        run_installed_command_smoke(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
            timeout_seconds=timeout_seconds,
            runner=execute,
        )
        if include_command_smoke
        else installed_command_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        )
    )
    hermes_path = shutil.which("hermes")
    if include_command_smoke and not bool(command_smoke.get("ok", False)):
        return {
            "schema_version": HERMES_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": bool(command_smoke.get("observed", False)),
            "install_path": install_path,
            "skill": skill,
            "tap": tap,
            "target_binding": target,
            "hermes_cli": {"found": bool(hermes_path), "path": hermes_path},
            "results": [],
            "installed_command_smoke": command_smoke,
            "first_use_status_smoke": first_use_status_smoke_plan(
                omh_command=omh_command,
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "failed_step": "installed_command_smoke",
            "recommended_next_action": _hermes_smoke_next_action(False, "installed_command_smoke"),
            "proof_boundary": (
                "Installed command smoke failed before live Hermes profile mutation. No Hermes install, list, "
                "check, or inspect command was run."
            ),
        }
    results: list[dict[str, object]] = []
    smoke_env = {"HERMES_HOME": str(target["hermes_home"])}
    if not hermes_path:
        return {
            "schema_version": HERMES_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": False,
            "install_path": install_path,
            "skill": skill,
            "tap": tap,
            "target_binding": target,
            "hermes_cli": {"found": False, "path": None},
            "results": [],
            "installed_command_smoke": command_smoke,
            "first_use_status_smoke": first_use_status_smoke_plan(
                omh_command=omh_command,
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "failed_step": "hermes_cli",
            "recommended_next_action": "Install Hermes Agent CLI or run this smoke from the target Hermes profile.",
            "proof_boundary": "No Hermes CLI was observed, so no Hermes install, list, check, or inspect evidence exists.",
        }
    ok = True
    failed_step = ""
    for step in steps:
        result = execute(step.command, timeout_seconds, smoke_env)
        step_ok = result.returncode == 0
        ok = ok and step_ok
        results.append(
            {
                **step.to_payload(),
                "returncode": result.returncode,
                "ok": step_ok,
                "environment": {"HERMES_HOME": smoke_env["HERMES_HOME"]},
                "stdout_excerpt": bounded_text(result.stdout),
                "stderr_excerpt": bounded_text(result.stderr),
            }
        )
        if not step_ok and not failed_step:
            failed_step = step.name
            if step.required:
                break
    if include_command_smoke and not bool(command_smoke.get("ok", False)):
        ok = False
        if not failed_step:
            failed_step = "installed_command_smoke"
    return {
        "schema_version": HERMES_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "install_path": install_path,
        "skill": skill,
        "tap": tap,
        "target_binding": target,
        "hermes_cli": {"found": True, "path": hermes_path},
        "results": results,
        "installed_command_smoke": command_smoke,
        "first_use_status_smoke": first_use_status_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        ),
        "failed_step": failed_step,
        "recommended_next_action": _hermes_smoke_next_action(ok, failed_step),
        "proof_boundary": (
            "Live smoke observes Hermes CLI install/list/check/inspect command results only. "
            "It still does not prove a later chat session selected OMH unless that session is observed separately."
        ),
    }


def run_installed_command_smoke(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    timeout_seconds: int = 30,
    runner: Runner | None = None,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Installed command smoke timeout must be at least one second")
    plan = installed_command_smoke_plan(omh_command=omh_command, omh_home=omh_home, hermes_home=hermes_home)
    target = plan["target_binding"]
    execute = runner or subprocess_runner
    path_check = inspect_installed_command_path(omh_command)
    if not bool(path_check["ok"]):
        return {
            "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": False,
            "command_under_test": omh_command,
            "target_binding": target,
            "path_check": path_check,
            "results": [],
            "failed_step": "installed_omh_path",
            "recommended_next_action": _installed_command_smoke_next_action(
                False,
                "installed_omh_path",
                command_under_test=omh_command,
            ),
            "proof_boundary": (
                "Installed command smoke did not execute because the OMH command was not discoverable or "
                "executable. PATH resolution is recorded separately in path_check."
            ),
        }
    results: list[dict[str, object]] = []
    ok = True
    failed_step = ""
    for raw_step in plan["steps"]:
        step = HermesSmokeStep(
            str(raw_step["name"]),
            tuple(str(part) for part in raw_step["command"]),
            str(raw_step["phase"]),
            bool(raw_step["mutates_profile"]),
            required=bool(raw_step["required"]),
            proof_boundary=str(raw_step["proof_boundary"]),
        )
        result = execute(step.command, timeout_seconds, None)
        step_ok = result.returncode == 0
        ok = ok and step_ok
        results.append(
            {
                **step.to_payload(),
                "returncode": result.returncode,
                "ok": step_ok,
                "stdout_excerpt": bounded_text(result.stdout),
                "stderr_excerpt": bounded_text(result.stderr),
            }
        )
        if not step_ok and not failed_step:
            failed_step = step.name
            if step.required:
                break
    return {
        "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "command_under_test": omh_command,
        "target_binding": target,
        "path_check": path_check,
        "results": results,
        "failed_step": failed_step,
        "recommended_next_action": _installed_command_smoke_next_action(
            ok,
            failed_step,
            command_under_test=omh_command,
        ),
        "proof_boundary": (
            "Installed command smoke observes the OMH console script, generated skill guidance, and plan rendering only. "
            "It does not mutate Hermes or prove live chat usage."
        ),
    }


def _target_binding(*, omh_home: str | Path | None = None, hermes_home: str | Path | None = None) -> dict[str, object]:
    omh = expand_home(omh_home, "OMH_HOME", "~/.omh")
    hermes = expand_home(hermes_home, "HERMES_HOME", "~/.hermes")
    return {
        "omh_home": str(omh),
        "hermes_home": str(hermes),
        "explicit_omh_home": omh_home is not None,
        "explicit_hermes_home": hermes_home is not None,
        "hermes_env_key": "HERMES_HOME",
        "proof_boundary": "Live smoke binds Hermes CLI subprocesses to this HERMES_HOME; it does not prove another profile was checked.",
    }

def _omh_scoped_command(
    omh_command: str,
    *command_parts: str,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    command = list(_omh_base_command(omh_command, omh_home=omh_home, hermes_home=hermes_home))
    command.extend(command_parts)
    return tuple(command)


def _omh_base_command(
    omh_command: str,
    *,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    command = [omh_command]
    if omh_home is not None:
        command.extend(["--omh-home", str(omh_home)])
    if hermes_home is not None:
        command.extend(["--hermes-home", str(hermes_home)])
    return tuple(command)


def _omh_release_plan_command(
    omh_command: str,
    *,
    install_path: str,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    return (
        *_omh_base_command(omh_command, omh_home=omh_home, hermes_home=hermes_home),
        "release",
        "hermes-smoke",
        "--install-path",
        install_path,
        "--omh-command",
        omh_command,
    )


def _live_smoke_command(install_path: str, target: Mapping[str, object]) -> list[str]:
    command = ["omh"]
    if target["explicit_omh_home"]:
        command.extend(["--omh-home", str(target["omh_home"])])
    if target["explicit_hermes_home"]:
        command.extend(["--hermes-home", str(target["hermes_home"])])
    command.extend(["release", "hermes-smoke", "--install-path", install_path, "--live"])
    if not target["explicit_hermes_home"]:
        command.append("--target-confirmed")
    return command


def _hermes_smoke_next_action(ok: bool, failed_step: str) -> str:
    if ok:
        return "Restart or refresh Hermes Agent if required, then try the first OMH Hermes prompt and record the observed response."
    if failed_step == "tap_add":
        return "Check Hermes tap support, network access, and whether the tap is already configured; rerun the smoke after repair."
    if failed_step == "skill_install":
        return (
            "Check tap visibility and Hermes skill scan output, then rerun "
            "`hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes`."
        )
    if failed_step == "omh_setup":
        return "Run `omh setup` manually and inspect `omh doctor` for blocking setup checks."
    if failed_step == "setup_doctor":
        return "Run `omh doctor` manually and repair the OMH-managed skill registration reported there."
    if failed_step == "installed_command_smoke":
        return (
            "Inspect installed_command_smoke.failed_step, then repair the installed `omh` command path, "
            "console script importability, generated skill content, or setup plan rendering before rerunning "
            "with --include-command-smoke."
        )
    if failed_step in {"tap_list", "skills_list", "skill_check", "skill_inspect"}:
        return "Inspect the failing Hermes skills command output and confirm the target Hermes profile is the one OMH was installed into."
    return "Inspect the failed Hermes release smoke step and rerun after repair."


def _installed_command_smoke_next_action(
    ok: bool,
    failed_step: str,
    *,
    command_under_test: str = "omh",
) -> str:
    command = str(command_under_test or "omh").strip() or "omh"
    if ok:
        return (
            f"Installed `{command}` command path is runnable; "
            "continue with Hermes profile smoke or release tagging."
        )
    if failed_step == "installed_omh_path":
        if path_check_kind(command) == "direct_path":
            return f"Make {shlex.quote(command)} executable, or pass --omh-command with an executable OMH path."
        return (
            f"Install OMH so `command -v {shlex.quote(command)}` resolves, "
            "or pass --omh-command with an executable OMH path."
        )
    if failed_step == "installed_omh_help":
        return "Check PATH, package installation, and console-script importability for `omh`."
    if failed_step == "installed_omh_skill_content":
        return "Run `omh release skill-content-smoke --json` directly and inspect missing router awareness or workflow context rail markers."
    if failed_step == "installed_omh_setup_plan":
        return "Run `omh release hermes-smoke --install-path setup` directly and inspect the console-script error."
    return "Inspect the failed installed command smoke step and rerun after repair."

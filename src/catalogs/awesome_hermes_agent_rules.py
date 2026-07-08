from __future__ import annotations

import re
from typing import Final

from .awesome_hermes_agent import AwesomeHermesCoverage, AwesomeHermesItem, CoverageRule, PLUGIN_SUBSECTION


_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
RULE_SET_VERSION: Final = "awesome_hermes_agent_rules/v1"

_RULES = (
    CoverageRule(
        ("oh-my-hermes", "omh"),
        "covered",
        "high",
        ("oh-my-hermes", "skill-scout", "workflow-learning"),
        "OMH has a first-party workflow pack surface; compare upstream only for ecosystem drift.",
        "first_party_omh",
    ),
    CoverageRule(
        (
            "mcp client",
            "mcp integration",
            "mcp tool servers",
            "agentic mcp",
            "skillsdotnet",
            "c implementation of agentskills",
        ),
        "partial",
        "high",
        (
            "external-connector-readiness",
            "toolbelt-readiness",
            "skill-scout",
            "connector-operator",
            "verification-gate",
        ),
        "OMH can evaluate MCP-backed skill bridges for tool scope, auth, packaging, and trial evidence before any server or connector is trusted.",
        "mcp_skill_bridge",
    ),
    CoverageRule(
        ("pydantic ai", "schema validation", "type safe schema", "typed skill", "dynamic tools"),
        "partial",
        "high",
        ("verification-gate", "toolbelt-readiness", "skill-scout", "agent-evaluation"),
        "OMH can review typed tool schemas, validation contracts, and verification gates without importing the runtime by default.",
        "typed_skill_runtime",
    ),
    CoverageRule(
        ("cybersecurity skills", "mitre attack", "nist csf", "structured cybersecurity", "security skills collection"),
        "partial",
        "high",
        ("security-safety-review", "agent-evaluation", "skill-scout", "verification-gate", "toolbelt-readiness"),
        "OMH can route security skill libraries through safety review, evaluator design, and verification gates before adoption.",
        "security_skill_library",
    ),
    CoverageRule(
        ("developer marketing", "seo", "generative engine optimization", "ai discoverability", "content strategy"),
        "partial",
        "medium",
        ("content-operator", "research-department", "web-research", "data-analysis", "skill-scout"),
        "OMH can compare growth, SEO, and content workflow skills as research/content operators without trusting external publishing guidance by default.",
        "growth_content_skills",
    ),
    CoverageRule(
        (
            "wondelai skills",
            "cross platform agent skills",
            "cross-platform agent skills",
            "default taps",
            "github taps",
            "well known skill endpoints",
            "well-known skill endpoints",
        ),
        "partial",
        "high",
        ("skill-scout", "skill-health", "prompt-import-readiness", "toolbelt-readiness", "security-safety-review"),
        "OMH can scout cross-platform skill ecosystems and review tap or well-known metadata before prompt import, installation, or trust.",
        "cross_platform_skill_ecosystem",
    ),
    CoverageRule(
        ("analytical prompts", "meta reasoning", "meta-reasoning", "generates better prompts", "self prompt"),
        "partial",
        "medium",
        ("workflow-learning", "skill-health", "instinct-ledger", "skill-scout"),
        "OMH can review meta-prompt and self-improvement candidates through learning and skill-health surfaces without accepting generated guidance as evidence.",
        "meta_prompt_self_improvement",
    ),
    CoverageRule(
        (
            "obsidian vault into an identity layer",
            "identity layer any ai agent can read",
            "obsidian vault",
        ),
        "partial",
        "high",
        ("memory-curation-review", "wiki", "prompt-import-readiness", "external-connector-readiness", "skill-scout"),
        "OMH can review vault-backed identity or knowledge-workspace skills as memory, wiki, prompt import, and connector readiness work without claiming private vault access.",
        "knowledge_workspace_identity",
    ),
    CoverageRule(
        (
            "ai writing tells",
            "russian text",
            "bureaucratese",
            "calques",
            "chatgpt claude fingerprints",
            "deterministic offline scanner",
        ),
        "partial",
        "medium",
        ("content-operator", "skill-scout", "design-quality-gate", "verification-gate"),
        "OMH can route copy/localization quality skills through content review and verification gates while external style rewrites remain observed output.",
        "copy_localization_quality",
    ),
    CoverageRule(
        (
            "business operations skills",
            "covering crm invoicing",
            "crm invoicing and project management",
        ),
        "partial",
        "medium",
        ("external-connector-readiness", "connector-operator", "data-analysis", "skill-scout", "security-safety-review"),
        "OMH can evaluate business-operations skill packs for SaaS connector scope, data handling, write authority, and observed trial evidence before adoption.",
        "business_operations_skill_pack",
    ),
    CoverageRule(
        (
            "agentskills io compliant skills",
            "output installable skills",
            "transforms repos and docs",
            "module skill forge",
            "skill forge",
        ),
        "partial",
        "high",
        ("skill-scout", "prompt-import-readiness", "skill-health", "workflow-learning", "verification-gate"),
        "OMH can route skill-generation packs through scouting, prompt import readiness, skill-health review, and verification before generated skills become trusted catalog entries.",
        "skill_forge_generation",
    ),
    CoverageRule(
        (
            "monero xmr blockchain gateway",
            "private cryptocurrency transactions",
            "cryptocurrency transactions from agent workflows",
            "xmr gateway",
        ),
        "partial",
        "high",
        ("external-connector-readiness", "security-safety-review", "connector-operator", "production-audit", "skill-scout"),
        "OMH can prepare private-crypto gateway readiness for wallet, credential, cost, compliance, and mutation authority boundaries before any transaction workflow is trusted.",
        "private_crypto_gateway",
    ),
    CoverageRule(
        (
            "pseudonymous coarse geo",
            "double opt in",
            "double-opt-in",
            "agents and humans post findings",
            "earn karma and build reputation",
            "build reputation",
            "shared board nearby agents",
        ),
        "partial",
        "medium",
        ("gateway-intent-card", "external-connector-readiness", "security-safety-review", "connector-operator", "agent-board"),
        "OMH can route community matching, shared-board, and reputation-network skills through gateway, connector, and safety boundaries before external social coordination is claimed.",
        "community_matching_reputation",
    ),
    CoverageRule(
        (
            "chinese k 12 education",
            "chinese k 12",
            "textbook sync",
            "exam prep",
            "photo q a",
            "lesson planning",
            "career skills",
        ),
        "partial",
        "medium",
        ("research-department", "media-input-operator", "content-operator", "skill-scout", "external-connector-readiness"),
        "OMH can evaluate education skill libraries for curriculum research, media/photo inputs, content generation, connector setup, and evidence boundaries before adoption.",
        "education_skill_library",
    ),
    CoverageRule(
        (
            "arabic first skills pack",
            "arabic-first skills pack",
            "islamic tools",
            "prayer times",
            "zakat",
            "quran",
            "dialect aware nlp",
            "dialect-aware nlp",
        ),
        "partial",
        "medium",
        ("content-operator", "live-info-operator", "research-department", "external-connector-readiness", "skill-scout"),
        "OMH can route localized domain skill packs through content, live-information, research, and connector readiness checks without claiming religious, travel, or dialect outputs were produced.",
        "localized_domain_skill_pack",
    ),
    CoverageRule(
        (
            "fantasy spell themed skill pack",
            "fantasy spell-themed skill pack",
            "tabletop rpg interface",
            "wraps real development operations",
        ),
        "partial",
        "low",
        ("skill-scout", "workflow-learning", "verification-gate", "code-review"),
        "OMH can inspect themed development workflow packs for learning value and verification fit while keeping real refactor, lint, and test execution on observed engineering surfaces.",
        "themed_dev_workflow_pack",
    ),
    CoverageRule(
        (
            "dynamic workflow",
            "workflow scripts",
            "subagents",
            "swarm",
            "multi-agent",
            "parallel",
            "agentplane",
            "long running task execution",
            "long-running task execution",
            "progress tracking",
            "checkpoints",
            "failure recovery",
            "skill orchestration",
            "conductor planning",
            "beads tracking",
            "observable pipelines",
        ),
        "partial",
        "high",
        ("team", "ultragoal", "ultrawork", "agent-board", "harness-session-inventory"),
        "OMH covers planning, handoff, board, and evidence boundaries, but does not import external worker runtimes.",
        "dynamic_orchestration",
    ),
    CoverageRule(
        ("discord voice", "gemini multimodal", "voice", "stt", "tts", "whatsapp", "signal", "teams", "feishu", "lark"),
        "partial",
        "high",
        (
            "voice-operator",
            "media-input-operator",
            "gateway-intent-card",
            "visual-qa",
            "web_visual_qa_message_card/v1",
            "toolbelt-readiness",
        ),
        "OMH can prepare voice, media, gateway, and web QA message cards; platform connectors remain observed external tools.",
        "live_media_gateway",
    ),
    CoverageRule(
        ("web search", "search", "scrape", "browser", "chrome profile", "cloudflare", "youtube", "transcript"),
        "partial",
        "high",
        (
            "web-research",
            "source-finder",
            "browser-operator",
            "live-info-operator",
            "web_visual_qa_message_card/v1",
            "toolbelt-readiness",
        ),
        "OMH routes source, browser, and web QA package review work, while provider credentials and live retrieval remain external observations.",
        "web_research",
    ),
    CoverageRule(
        ("memory", "recall", "engram", "context", "fts5", "pgvector", "knowledge graph", "curator"),
        "partial",
        "high",
        ("memory-curation-review", "wiki", "workflow-learning", "instinct-ledger", "skill-health"),
        "OMH reviews and packages retained context without claiming opaque Hermes memory mutation.",
        "memory_recall",
    ),
    CoverageRule(
        (
            "marketplace",
            "registry",
            "curator",
            "motif",
            "dedup",
            "evolver",
            "skill drift",
            "skill creation",
            "skill factory",
            "auto generates reusable skills",
            "monitors agent performance",
            "identifies weak skills",
            "community hub for skill discovery",
            "browse share and install community skills",
        ),
        "partial",
        "high",
        ("skill-scout", "skill-health", "workflow-learning", "instinct-ledger"),
        "OMH can scout, compare, and queue skill improvements; copying or installing external skills requires separate review.",
        "skill_marketplace",
    ),
    CoverageRule(
        ("eval", "benchmark", "trajectory", "quality", "regression", "dangerous pattern", "approval", "pre_llm", "pre_tool"),
        "partial",
        "high",
        ("agent-evaluation", "verification-gate", "security-safety-review", "command-operator", "failure-signal-audit"),
        "OMH covers review and gate framing; host hook installation or enforcement is external runtime evidence.",
        "evaluation_safety",
    ),
    CoverageRule(
        ("cost", "usage", "analytics", "token", "x402", "payment", "usdc", "spending", "billing"),
        "partial",
        "medium",
        ("ops-observability-card", "toolbelt-readiness", "security-safety-review", "production-audit"),
        "OMH can surface cost and safety readiness; provider billing, wallets, and payment actions stay external.",
        "cost_analytics",
    ),
    CoverageRule(
        ("deploy", "docker", "nix", "server", "systemd", "cron", "monitor", "incident", "sre", "ops"),
        "partial",
        "medium",
        ("deploy-and-monitor", "reliability-review", "production-audit", "automation-blueprint", "doctor"),
        "OMH prepares operational runbooks and evidence ladders but does not become infrastructure automation.",
        "operations_readiness",
    ),
    CoverageRule(
        ("pull request", "issue", "release", "paperclip", "agent-to-agent", "message bus"),
        "partial",
        "medium",
        ("github-event-ops", "agent-board", "connector-operator", "gateway-intent-card"),
        "OMH can route events and prepare connector handoffs; external platform mutation requires observed connector evidence.",
        "platform_events",
    ),
    CoverageRule(
        (
            "connects hermes to agentchat",
            "agentchat peer to peer agent messaging",
            "peer-to-peer agent messaging",
            "websocket messaging",
            "social discovery network",
            "shareable profile cards",
            "windy ecosystem",
            "windymail ai mailbox",
            "matrix chat identity",
            "one command pairing",
            "antigravity cli",
            "macos keychain oauth",
            "subscription credentials",
            "bridge to miniverse",
            "miniverse pixel worlds",
            "deep integration of hermes into crustocean",
            "crustocean platform",
            "pixel worlds",
            "oracle oci",
            "oci genai",
            "oracle 26ai integration",
            "enterprise on ramp for oracle",
        ),
        "partial",
        "medium",
        (
            "skill-scout",
            "external-connector-readiness",
            "connector-operator",
            "gateway-intent-card",
            "security-safety-review",
            "toolbelt-readiness",
        ),
        "OMH can prepare ecosystem bridge readiness for identity, messaging, OAuth, platform, and cloud connectors while external pairing, credential use, sends, and network effects remain observed-only.",
        "ecosystem_identity_connector",
    ),
    CoverageRule(
        (
            "static linter for ai agent configs",
            "herm v1 1 scoring",
            "community migration tool from openclaw",
            "native hermes migrate",
            "one command setup for the full hermes agent stack",
            "free models and 29 plugins",
        ),
        "partial",
        "medium",
        (
            "workspace-audit",
            "doctor",
            "skill-scout",
            "toolbelt-readiness",
            "security-safety-review",
            "verification-gate",
        ),
        "OMH can audit prompt/config quality, migration readiness, setup health, tool availability, and safety gates while external installer or migrator execution remains observed-only.",
        "quality_config_migration",
    ),
    CoverageRule(
        (
            "comprehensive community documentation",
            "covers v0 2 0 in detail",
            "wsl2 ubuntu setup",
            "setup instructions for running hermes on windows",
            "practical patterns and deployment advice",
        ),
        "partial",
        "medium",
        (
            "wiki",
            "content-operator",
            "source-finder",
            "workspace-audit",
            "doctor",
            "toolbelt-readiness",
        ),
        "OMH can compare community documentation, prepare wiki or content capture, and surface setup review paths without claiming external docs are current or that Windows/WSL setup ran.",
        "operator_documentation",
    ),
    CoverageRule(
        (
            "living world engine",
            "procedural generation",
            "virtual worlds",
            "contract risk analysis",
            "risky clauses",
            "legal obligations",
            "cash flow analyzer",
            "webgl dashboard",
            "on chain forensics",
            "flow visualization",
        ),
        "partial",
        "medium",
        (
            "research-department",
            "data-analysis",
            "agent-evaluation",
            "security-safety-review",
            "external-connector-readiness",
            "visual-qa",
        ),
        "OMH can prepare domain analysis, research review, safety review, dashboard QA, and connector-readiness plans; legal, blockchain, simulation, and visualization results remain external observed evidence.",
        "domain_research_analysis",
    ),
    CoverageRule(
        (
            "autonomous llm research agent",
            "literature review",
            "hypothesis generation",
            "experiment design",
        ),
        "partial",
        "medium",
        (
            "research-department",
            "source-finder",
            "paper-learning",
            "agent-evaluation",
            "web-research",
        ),
        "OMH can plan and evaluate research-agent workflows, source acquisition, paper explanation, and evidence synthesis without claiming autonomous experiments ran.",
        "research_agent_readiness",
    ),
    CoverageRule(
        (
            "camel trust boundaries",
            "formal trust verification",
            "safety critical deployments",
            "training trajectories",
            "fine tuning data",
            "fine-tuning data",
        ),
        "partial",
        "medium",
        (
            "security-safety-review",
            "verification-gate",
            "agent-evaluation",
            "workflow-learning",
            "skill-scout",
        ),
        "OMH can prepare safety-boundary review, verification gates, evaluator design, and reviewed learning queues; trust enforcement and fine-tuning data generation remain external observed evidence.",
        "safety_training_derivatives",
    ),
    CoverageRule(
        (
            "terminal neurovisualizer",
            "animated themes",
            "decorative terminal overlays",
        ),
        "partial",
        "low",
        (
            "visual-qa",
            "design-quality-gate",
            "content-operator",
            "toolbelt-readiness",
        ),
        "OMH can review terminal visual overlays and presentation quality while decorative renderer installation and live terminal output remain observed-only.",
        "terminal_visual_overlay",
    ),
    CoverageRule(
        (
            "snapmaker",
            "3d printer",
            "printer safety",
            "moonraker",
            "klipper",
            "heat command",
            "camera gate",
            "camera-gated",
            "mycodo",
            "mushroom cultivation",
            "greenhouse",
            "iot relay",
            "sensor relay",
            "raspberry pi",
            "robot",
            "robotics",
            "embodied",
            "vla",
            "physical device",
            "actuator",
        ),
        "partial",
        "medium",
        (
            "physical-device-readiness",
            "external-connector-readiness",
            "security-safety-review",
            "command-operator",
            "visual-qa",
            "toolbelt-readiness",
        ),
        "OMH can prepare physical device safety envelopes, actuator/hazard inventories, camera or sensor gates, operator approvals, dry-run policies, and observed trial slots; device commands and hardware results remain observed-only.",
        "physical_device_readiness",
    ),
    CoverageRule(
        (
            "onequery",
            "read-only sql",
            "sql",
            "database",
            "microsoft workspace",
            "microsoft graph",
            "nextcloud",
            "webdav",
            "caldav",
            "carddav",
            "android",
            "device",
            "cloud",
            "localization",
        ),
        "partial",
        "medium",
        (
            "skill-scout",
            "external-connector-readiness",
            "toolbelt-readiness",
            "connector-operator",
            "data-analysis",
            "security-safety-review",
        ),
        "OMH can score external connector adoption, auth, cost, modality, freshness, SQL/data safety, and fallback routes without claiming provider execution.",
        "external_connector_readiness",
    ),
    CoverageRule(
        (
            "slash prompt",
            "slash prompts",
            "slash command",
            "prompt files",
            "prompt directories",
            "prompt folders",
            "argument interpolation",
            "yaml frontmatter",
            "toml frontmatter",
            "opencode",
            "gemini cli",
        ),
        "partial",
        "high",
        (
            "prompt-import-readiness",
            "skill-scout",
            "workspace-audit",
            "security-safety-review",
            "toolbelt-readiness",
        ),
        "OMH can review external CLI-agent prompt sources, formats, argument interpolation, slash-command collisions, and trust boundaries before any prompt import or command registration.",
        "prompt_import_readiness",
    ),
    CoverageRule(
        ("image", "video", "forensic", "ocr", "media", "flux", "comfyui", "pdf", "deck", "html", "markdown"),
        "partial",
        "medium",
        ("img-summary", "media-input-operator", "materials-package", "deliverable-package", "visual-qa"),
        "OMH covers media and deliverable planning/QA while generated files and attachments remain observed-only.",
        "media_deliverables",
    ),
    CoverageRule(
        (
            "weather",
            "finance",
            "crypto",
            "solana",
            "chainlink",
            "stock",
            "sports",
            "spotify",
            "nextcloud",
            "longbridge",
            "real time quotes",
            "real-time quotes",
            "fundamentals",
            "options chain",
            "portfolio positions",
            "sec filings",
        ),
        "partial",
        "medium",
        (
            "skill-scout",
            "external-connector-readiness",
            "connector-operator",
            "toolbelt-readiness",
            "live-info-operator",
        ),
        "OMH can prepare cost-aware external connector readiness and live-info routing gates; provider calls and domain results remain observed external evidence.",
        "domain_connectors",
    ),
)


def coverage_for_item(item: AwesomeHermesItem) -> AwesomeHermesCoverage:
    tokens = tuple(_TOKEN_RE.findall(_search_text(item)))
    token_set = frozenset(tokens)
    phrase_text = f" {' '.join(tokens)} "
    for rule in _RULES:
        if any(_term_matches(term, token_set, phrase_text) for term in rule.terms):
            return AwesomeHermesCoverage(
                item,
                rule.status,
                _priority_for_item(item, rule.priority),
                rule.surfaces,
                (rule.note, _boundary_note(item)),
                RULE_SET_VERSION,
                rule.rule_id,
            )
    return AwesomeHermesCoverage(
        item,
        _default_status(item),
        _priority_for_item(item, "low"),
        _default_surfaces(item),
        (
            "No precise OMH workflow surface is mapped yet; keep this as a reviewed external candidate.",
            _boundary_note(item),
        ),
        RULE_SET_VERSION,
        _default_rule_id(item),
    )


def _term_matches(term: str, item_tokens: frozenset[str], item_phrase_text: str) -> bool:
    term_tokens = tuple(_TOKEN_RE.findall(term.lower()))
    if not term_tokens:
        return False
    if len(term_tokens) == 1:
        return term_tokens[0] in item_tokens
    return f" {' '.join(term_tokens)} " in item_phrase_text


def _priority_for_item(item: AwesomeHermesItem, fallback: str) -> str:
    if item.subsection == PLUGIN_SUBSECTION:
        return "high"
    if item.maturity == "production" and fallback == "low":
        return "medium"
    return fallback


def _default_status(item: AwesomeHermesItem) -> str:
    if item.section == "Skills & Plugins":
        return "partial"
    return "missing_candidate"


def _default_surfaces(item: AwesomeHermesItem) -> tuple[str, ...]:
    if item.section == "Skills & Plugins":
        return ("skill-scout", "skill-health", "toolbelt-readiness")
    return ("skill-scout", "toolbelt-readiness")


def _default_rule_id(item: AwesomeHermesItem) -> str:
    if item.section == "Skills & Plugins":
        return "default_skills_plugins"
    return "default_external_candidate"


def _boundary_note(item: AwesomeHermesItem) -> str:
    return f"Source: {item.section} / {item.subsection}, README line {item.readme_line}."


def _search_text(item: AwesomeHermesItem) -> str:
    return " ".join(
        (
            item.id,
            item.name,
            item.url,
            item.section,
            item.subsection,
            item.summary,
        )
    ).lower()

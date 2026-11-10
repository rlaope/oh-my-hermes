from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.model_recommendations import (  # noqa: E402
    MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_STATUSES,
    SHIPPED_MODEL_RECOMMENDATIONS,
    load_recommendation_overrides,
    merge_recommendation_catalog,
    resolve_model_recommendation,
    serialize_recommendation_payload,
)
from omh.coding.model_routing import MODEL_CATEGORIES, MODEL_ROLES  # noqa: E402


def _active(
    model_alias: str,
    *,
    provider: str,
    model_id: str | None = None,
    family: str = "",
    owners: tuple[str, ...] = ("hermes", "maestro"),
    status: str = "confirmed_active",
) -> dict[str, object]:
    return {
        "model_alias": model_alias,
        "model_id": model_id or model_alias,
        "provider": provider,
        "provider_family": provider,
        "model_family": family,
        "compatible_owners": owners,
        "status": status,
    }


_ALL_ACTIVE = (
    _active("kimi-k3.1-pro", provider="apitopia", family="kimi"),
    _active("claude-opus-5-5", provider="ccapi", family="claude"),
    _active("claude-fable-5", provider="ccapi", family="claude"),
    _active("gpt-5.6-sol", provider="openai-codex", family="gpt"),
    _active("gpt-5.6-terra", provider="openai-codex", family="gpt"),
    _active("glm-5.2", provider="zai", family="glm"),
    _active("glm-5.2-ultrafast", provider="zai", family="glm"),
    _active("grok-build-0.1", provider="xai", family="grok"),
    _active("gemini-4-argon", provider="google", family="gemini"),
)


class RecommendationCatalogTests(unittest.TestCase):
    def test_public_readmes_and_site_cover_every_shipped_category_chain(self) -> None:
        """Each hand-maintained public row lists exactly its chain, in order.

        The two site pages are edited by hand, so no producer regenerates
        them. The READMEs no longer carry a chain table (the lean README,
        #2269, links docs/INSTALLATION.md#guided-model-setup, whose generated
        table `docs chain-table --check` keeps equal to the catalog). Every row's order cell is split into its
        entries on that surface's own separator and compared whole against
        the catalog's display labels: a missing model, an extra entry whether
        or not it is a known label, a swapped pair, and a wrong generation
        each fail. Where a surface prints the row's effort, that is compared
        too.
        """
        from omh.catalogs.model_chain_table import MODEL_DISPLAY_LABELS

        docs = {
            "site": Path("site/docs/model-routing/index.html").read_text(encoding="utf-8"),
            "home": Path("site/index.html").read_text(encoding="utf-8"),
        }
        # Both HTML surfaces put one category per source line and key the row
        # on a bare ``<span>{category}</span>``; the markdown READMEs use a
        # table row instead, with a connector word between entries.
        html_surfaces = {"site", "home"}
        readme_separators = {"readme": ", then ", "ko": ", 다음 ", "ja": "、次に ", "zh": "，其次 "}

        def entries_listed(surface: str, row: str) -> list[str]:
            if surface == "home":
                cell = re.search(r'<td class="chain-order">(.*?)</td>', row)
                assert cell is not None, row
                return re.findall(r"<code>([^<]*)</code>", cell.group(1))
            if surface == "site":
                paragraph = re.search(r"<p>([^<]*)\.</p>", row)
                assert paragraph is not None, row
                return paragraph.group(1).split(" → ")
            cell = row.rstrip().removesuffix("|").rstrip().rsplit(" | ", 1)[-1]
            return re.sub(r" \(\w+\)$", "", cell).split(readme_separators[surface])

        categories = SHIPPED_MODEL_RECOMMENDATIONS["categories"]
        assert isinstance(categories, dict)

        for name, chain in categories.items():
            assert isinstance(chain, list)
            expected_labels = [MODEL_DISPLAY_LABELS[str(candidate["model_alias"])] for candidate in chain]
            # A row whose entries share one effort prints it once; a row
            # whose entries differ (synthesize, since 2026-10-28) prints one
            # badge per entry, in chain order, so no entry's effort is hidden.
            chain_efforts = [str(candidate["reasoning_effort"]) for candidate in chain]
            expected_badges = chain_efforts[:1] if len(set(chain_efforts)) == 1 else chain_efforts
            for surface, text in docs.items():
                with self.subTest(category=name, surface=surface):
                    if surface in html_surfaces:
                        rows = [line for line in text.splitlines() if f"<span>{name}</span>" in line]
                    else:
                        rows = [line for line in text.splitlines() if line.startswith(f"| `{name}` |")]
                    self.assertEqual(len(rows), 1, "one row per category")
                    row = rows[0]
                    listed = entries_listed(surface, row)
                    self.assertEqual(len(listed), len(expected_labels), row)
                    self.assertEqual(listed, expected_labels, row)
                    if surface == "home":
                        shown = re.findall(r'<span class="chain-badge">([^<]*)</span>', row)
                    elif surface == "site":
                        # The routing page lists the order only, no effort.
                        continue
                    else:
                        shown = re.findall(r"\((\w+)\) \|\s*$", row)
                    self.assertEqual(shown, expected_badges, row)

    def test_last_resort_prose_names_the_shipped_final_order(self) -> None:
        """The shared-final-order sentences name `last_resort.any` by label.

        These are prose outside any generated region, so no drift gate sees
        them: before this test, changing `last_resort` left every one of them
        naming the old model with all gates green. The expected order is
        derived from the catalog and the display-label table, never written
        here, and every label the sentence names is compared -- a stale extra
        model fails as surely as a missing one.
        """
        from omh.catalogs.model_chain_table import MODEL_DISPLAY_LABELS

        last_resort = SHIPPED_MODEL_RECOMMENDATIONS["last_resort"]
        assert isinstance(last_resort, dict)
        expected = [
            MODEL_DISPLAY_LABELS[str(candidate["model_alias"])]
            for candidate in last_resort["any"]
        ]
        # A label must not match as the prefix of a longer version, so
        # "Claude Opus 5" does not count inside "Claude Opus 5.5".
        label_patterns = {
            label: re.compile(rf"(?<![\w.]){re.escape(label)}(?!\w|\.\d)")
            for label in set(MODEL_DISPLAY_LABELS.values())
        }
        sites = (
            ("docs/INSTALLATION.md", "consults one shared final order:"),
            ("docs/ARCHITECTURE.md", "the shared final order tries"),
            ("site/docs/model-routing/index.html", "consult one shared final order:"),
            ("site/docs/model-routing/index.html", "resolution checks the shared"),
            # The model-setup skill body's copy, regenerated into
            # skills/omh-model-setup/SKILL.md and docs/WORKFLOWS.md.
            ("src/skills/catalog_definitions.py", "consult the shared final order"),
        )
        for path, anchor in sites:
            with self.subTest(path=path, anchor=anchor):
                text = " ".join(Path(path).read_text(encoding="utf-8").split())
                self.assertEqual(text.count(anchor), 1, "anchor must name one sentence")
                start = text.index(anchor) + len(anchor)
                end = re.compile(r"\.(\s|$)").search(text, start)
                assert end is not None
                sentence = text[start : end.start()]
                found = sorted(
                    (match.start(), label)
                    for label, pattern in label_patterns.items()
                    for match in pattern.finditer(sentence)
                )
                self.assertEqual([label for _, label in found], expected, sentence)

    def test_agent_install_surfaces_link_to_the_canonical_protocol(self) -> None:
        protocol_url = (
            "https://raw.githubusercontent.com/rlaope/oh-my-hermes/"
            "{resolved-commit-sha}/INSTALL_FOR_AGENTS.md"
        )
        surfaces = {
            "agent_protocol": Path("INSTALL_FOR_AGENTS.md").read_text(encoding="utf-8"),
            "readme": Path("README.md").read_text(encoding="utf-8"),
            "ko": Path("README.ko.md").read_text(encoding="utf-8"),
            "ja": Path("README.ja.md").read_text(encoding="utf-8"),
            "zh": Path("README.zh.md").read_text(encoding="utf-8"),
            "site": Path("site/index.html").read_text(encoding="utf-8"),
            "routing_site": Path("site/docs/model-routing/index.html").read_text(
                encoding="utf-8"
            ),
            **{
                locale: Path(f"README.{locale}.md").read_text(encoding="utf-8")
                for locale in ("de", "es", "fr", "it", "pt-BR", "ru")
            },
        }

        for surface, text in surfaces.items():
            with self.subTest(surface=surface):
                self.assertIn(protocol_url, text)
        # The pasteable request is one text shared byte for byte. It sends
        # the agent down the non-interactive setup path: an agent's shell has
        # no terminal, and the wizard there takes every default unseen.
        protocol_text = surfaces["agent_protocol"]
        start = protocol_text.index("Install and fully configure Oh My Hermes")
        request = protocol_text[start : protocol_text.index("\n```", start)]
        self.assertIn("never run the interactive setup wizard", request)
        for surface, text in surfaces.items():
            with self.subTest(surface=surface, contract="byte-shared-request"):
                self.assertIn(request, text)
        # Every copy of the pasteable request names the model-chain interview
        # step, so URL-driven agent installs enter the interview after setup
        # instead of stopping at doctor.
        for surface, text in surfaces.items():
            if "Install and fully configure Oh My Hermes" not in text:
                continue
            with self.subTest(surface=surface, contract="chain-interview-step"):
                self.assertIn("model-chain interview", text)
                self.assertNotIn("interactive model setup, and doctor steps", text)
        # The model-routing docs show where the chains live: a cat of the
        # seeded file (matching its real key order and indentation) and an
        # edited example, so readers learn the file is the tuning surface. The
        # READMEs link there (the lean README, #2269) instead of copying it.
        seeded_cat_block = (
            "$ cat ~/.omh/routing/model-chains.json\n"
            "{\n"
            '  "categories": {},\n'
            '  "schema_version": "mixture_chain_overrides/v1"\n'
            "}"
        )
        installation = Path("docs/INSTALLATION.md").read_text(encoding="utf-8")
        with self.subTest(surface="installation", contract="chains-file-example"):
            self.assertIn(seeded_cat_block, installation)
            self.assertIn('"claude-fable-5-2", "reasoning_effort": "xhigh"', installation)
            self.assertIn('"gpt-6.1-sol", "reasoning_effort": "xhigh"', installation)
            self.assertIn('"deepseek-v4.1-flash-ultrafast", "reasoning_effort": "low"', installation)
            self.assertIn("omh model-chains show", installation)
        self.assertIn('data-i18n="route.state.owner_default"', surfaces["site"])
        translations = Path("site/i18n.js").read_text(encoding="utf-8")
        self.assertIn('"route.state.owner_default"', translations)
        self.assertNotIn('"route.state.unconfigured"', translations)
        self.assertIn('OMH_SOURCE_REF="$OMH_REF"', surfaces["agent_protocol"])
        self.assertNotIn(
            "raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh",
            surfaces["agent_protocol"],
        )
        for surface, text in surfaces.items():
            with self.subTest(surface=surface):
                self.assertNotIn(
                    "raw.githubusercontent.com/rlaope/oh-my-hermes/"
                    "main/INSTALL_FOR_AGENTS.md",
                    text,
                )
        self.assertIn('data-i18n="route.state.owner_default"', surfaces["site"])
        translations = Path("site/i18n.js").read_text(encoding="utf-8")
        self.assertIn('"route.state.owner_default"', translations)
        self.assertNotIn('"route.state.unconfigured"', translations)

    def test_catalog_is_schema_versioned_and_preserves_closed_vocabularies(self) -> None:
        catalog = SHIPPED_MODEL_RECOMMENDATIONS
        self.assertEqual(catalog["schema_version"], MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION)
        self.assertEqual(set(catalog["categories"]), set(MODEL_CATEGORIES))
        # Order is part of the contract, not just membership: canonical order
        # breaks head and chain-position ties in `mixture_category_for`, so a
        # name that moves takes an existing model's category label with it.
        # The three 2026-09-11 additions and the six 2026-10-28 additions are
        # appended, never inserted.
        self.assertEqual(MODEL_CATEGORIES, (
            "ultrabrain", "deep", "architect", "unspecified-high", "unspecified-low",
            "quick", "writing", "visual-engineering", "artistry",
            "capable", "simple-work", "deep-work",
            "google-search", "x-search", "review", "swarm", "forensics", "synthesize",
        ))
        self.assertEqual(MODEL_ROLES, (
            "brain", "implementation", "design_visual", "review", "docs", "research",
        ))
        self.assertNotIn("main", catalog["categories"])
        self.assertNotIn("x_platform_data", catalog["categories"])
        self.assertEqual(set(catalog["role_suggestions"]), {"main"})
        self.assertEqual(set(catalog["domain_affinities"]), {"x_platform_data"})

    def test_shipped_editorial_chains_are_pinned(self) -> None:
        catalog = SHIPPED_MODEL_RECOMMENDATIONS

        def aliases(section: str, name: str) -> list[str]:
            return [entry["model_alias"] for entry in catalog[section][name]]

        def efforts(section: str, name: str) -> list[str]:
            return [entry["reasoning_effort"] for entry in catalog[section][name]]

        # The 2026-10-13 table (owner decision). Superseded generations left
        # every shipped chain (owner decision, 2026-09-11) and keep leaving
        # it: that day Claude Haiku 4.5 behind Haiku 5.5, and the 2025
        # Qwen3-Coder with no Qwen successor. A chain names the current
        # generation of each line; an older id lives on only in a
        # machine-level override. Inside a chain Claude Opus 5.5 comes before
        # Claude Fable (owner decision, 2026-10-13, reversing 2026-09-06),
        # except ultrabrain, which Fable heads (owner decision, 2026-11-09).
        # Fable 5.2 took every Fable 5.1 slot on 2026-11-10 (owner decision).
        self.assertEqual(aliases("role_suggestions", "main"), [
            "gpt-6.1-sol", "claude-opus-5-5", "claude-fable-5-2", "gpt-6-astra", "kimi-k3.1-pro",
        ])
        # `main` keeps its convention: Sol names `high`, Astra carries its
        # candidate default, and the rest leave the effort to the session.
        self.assertEqual(efforts("role_suggestions", "main"), ["high", "", "", "xhigh", ""])
        self.assertEqual(catalog["last_resort"]["any"][1]["reasoning_effort"], "medium")
        # Opus 5.5 in the shared last resort names its effort (2026-09-24):
        # an entry with none leaves the level to the executor CLI's default.
        self.assertEqual(catalog["last_resort"]["any"][0]["reasoning_effort"], "medium")
        expected = {
            # Fable heads ultrabrain ahead of Astra (owner decision,
            # 2026-11-09; Fable 5.2 since 2026-11-10); Astra alone left a user
            # without OpenAI access no fallback before the parent model.
            "ultrabrain": (["claude-fable-5-2", "gpt-6-astra", "claude-opus-5-5"], "xhigh"),
            # DeepSeek V4.1 Flash left `deep`: a Flash budget model does not
            # fit the strong tier; Opus 5.5 and Kimi K3.1 Pro carry the fallback.
            "deep": (["claude-opus-5-5", "gpt-6.1-sol", "kimi-k3.1-pro"], "high"),
            "architect": (["claude-opus-5-5", "gpt-6-astra", "claude-fable-5-2", "kimi-k3.1-pro"], "xhigh"),
            # The GPT head rests on the 2026-09-05 live-model-tools run.
            "unspecified-high": (["gpt-6.1-sol", "claude-opus-5-5", "kimi-k3.1-pro"], "medium"),
            # A chain that would otherwise sit in one provider ecosystem ends
            # on a comparable-tier candidate from another (owner rule,
            # 2026-08-19). Opus 5.5 left the tail: a frontier model at the end
            # of a cheap lane inverts cost order.
            "unspecified-low": (
                ["glm-5.3", "deepseek-flash", "gpt-6.1-sol", "claude-sonnet-5-5"], "low",
            ),
            # Fable left the tail of `quick` for the same reason.
            "quick": (["glm-5.3-flash", "gpt-6-luna", "claude-haiku-5-5", "kimi-k3.1-pro"], "low"),
            "writing": (
                ["claude-opus-5-5", "claude-sonnet-5-5", "kimi-k3.1-pro", "gemini-4-argon"], "medium",
            ),
            # Fable 5.2 heads visual-engineering (owner decision, 2026-11-10).
            "visual-engineering": (
                ["claude-fable-5-2", "claude-opus-5-5", "gemini-4-argon", "kimi-k3.1-pro"], "high",
            ),
            "artistry": (["gemini-4-argon", "claude-opus-5-5", "claude-fable-5-2", "kimi-k3.1-pro"], "high"),
            "capable": (["claude-opus-5-5", "gpt-6.1-sol", "claude-fable-5-2", "kimi-k3.1-pro"], "medium"),
            "simple-work": (["gpt-6-luna", "claude-haiku-5-5", "deepseek-flash"], "low"),
            # `max` keeps deep-work's head distinct from deep's (owner choice).
            "deep-work": (["claude-opus-5-5", "gpt-6.1-sol"], "max"),
            # The routing-recipe categories (owner recipe, 2026-10-28): the
            # heads are the owner's, each tail crosses provider ecosystems.
            "google-search": (["gemini-4-argon", "gpt-6.1-sol", "claude-opus-5-5"], "medium"),
            "x-search": (["grok-4.7", "kimi-k3.1-pro", "gemini-4-argon"], "high"),
            "review": (["gpt-6.1-sol", "claude-opus-5-5", "kimi-k3.1-pro"], "xhigh"),
            "swarm": (["deepseek-flash", "glm-5.3-flash", "gpt-6-luna"], "low"),
            "forensics": (["gpt-6-astra", "claude-opus-5-5", "kimi-k3.1-pro"], "xhigh"),
            # The one chain whose entries declare different efforts: Gemini
            # closes it at `high`, the rung it carries at depth elsewhere.
            "synthesize": (["claude-opus-5-5", "gpt-6.1-sol", "gemini-4-argon"], ["xhigh", "xhigh", "high"]),
        }
        self.assertEqual(set(expected), set(catalog["categories"]))
        for name, (chain, effort) in expected.items():
            with self.subTest(category=name):
                self.assertEqual(aliases("categories", name), chain)
                expected_efforts = effort if isinstance(effort, list) else [effort] * len(chain)
                self.assertEqual(efforts("categories", name), expected_efforts)
        self.assertEqual(aliases("domain_affinities", "x_platform_data"), [
            "grok-build-0.1", "kimi-k3.1-pro", "gemini-4-argon",
        ])
        for section in ("categories", "role_suggestions", "domain_affinities"):
            for chain in catalog[section].values():
                for candidate in chain:
                    self.assertTrue(candidate["model_family"])
                    self.assertTrue(candidate["preferred_provider_families"])
                    self.assertTrue(candidate["reasoning"])
                    self.assertEqual(candidate["recommendation_source"], "shipped_editorial")

    def test_override_loader_and_merge_are_deterministic_and_secret_free(self) -> None:
        override = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "deep": [{
                    "model_alias": "qwen3-coder",
                    "model_family": "qwen",
                    "preferred_provider_families": ["qwen-oauth"],
                    "reasoning_effort": "high",
                    "reasoning": "Operator-selected deep coding route.",
                }],
            },
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recommendations.json"
            path.write_text(json.dumps(override), encoding="utf-8")
            loaded = load_recommendation_overrides(path)
        self.assertEqual(loaded["categories"]["deep"][0]["recommendation_source"], "user_override")
        first = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, loaded)
        second = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, loaded)
        self.assertEqual(serialize_recommendation_payload(first), serialize_recommendation_payload(second))
        self.assertEqual(first["categories"]["deep"][0]["model_alias"], "qwen3-coder")
        self.assertEqual(first["categories"]["quick"], SHIPPED_MODEL_RECOMMENDATIONS["categories"]["quick"])
        serialized = serialize_recommendation_payload(first)
        self.assertNotIn("api_key", serialized.casefold())
        self.assertNotIn("token", serialized.casefold())

    def test_override_rejects_categories_role_slots_domains_and_secret_fields_at_wrong_surfaces(self) -> None:
        bad_payloads = (
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "categories": {"main": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "categories": {"x_platform_data": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "role_suggestions": {"brain": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "domain_affinities": {"main": []}},
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "categories": {"deep": [{
                    "model_alias": "qwen3-coder", "model_family": "qwen",
                    "preferred_provider_families": ["qwen-oauth"],
                    "reasoning": "x", "api_key": "must-not-be-stored",
                }]},
            },
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    load_recommendation_overrides(payload)


class RecommendationResolverTests(unittest.TestCase):
    def test_recommended_head_and_missing_head_resolution_are_deterministic(self) -> None:
        all_active = resolve_model_recommendation(
            owner="maestro", category="unspecified-high", active_models=reversed(_ALL_ACTIVE)
        )
        self.assertEqual(all_active["status"], "resolved")
        # The shipped head (GPT-6.1 Sol) is not in this active set, so the
        # chain falls through to its next two entries in order.
        self.assertEqual(all_active["selected"]["model_alias"], "claude-opus-5-5")
        self.assertEqual(
            [entry["model_alias"] for entry in all_active["projection"]["chain"]],
            ["claude-opus-5-5", "kimi-k3.1-pro"],
        )

        only_next = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            active_models=[_active("kimi-k3.1-pro", provider="apitopia", family="kimi")],
        )
        self.assertEqual(only_next["selected"]["model_alias"], "kimi-k3.1-pro")
        self.assertEqual([entry["model_alias"] for entry in only_next["projection"]["chain"]], ["kimi-k3.1-pro"])
        self.assertEqual(only_next["inactive_candidates"], ["gpt-6.1-sol", "claude-opus-5-5"])

    def test_explicit_unavailable_freezes_as_choice_required_without_substitution(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            explicit_model="grok-build-0.1",
            active_models=_ALL_ACTIVE[:-2],
        )
        self.assertEqual(route["status"], "choice_required")
        self.assertEqual(route["requested_model"], "grok-build-0.1")
        self.assertIsNone(route["selected"])
        self.assertIsNone(route["projection"])
        self.assertEqual(route["available_chain"], ["claude-opus-5-5", "kimi-k3.1-pro"])

    def test_explicit_active_model_wins_over_editorial_chain(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            explicit_model="grok-build-0.1",
            active_models=_ALL_ACTIVE,
        )
        self.assertEqual(route["status"], "resolved")
        self.assertEqual(route["selected"]["model_alias"], "grok-build-0.1")
        self.assertEqual(route["source"], "explicit_model")
        self.assertEqual([entry["model_alias"] for entry in route["projection"]["chain"]], ["grok-build-0.1"])

    def test_no_active_candidate_uses_each_owner_default_for_every_selector(self) -> None:
        selectors = (
            {"category": "deep"},
            {"role_slot": "main"},
            {"domain": "x_platform_data"},
        )

        for owner in ("hermes", "maestro"):
            for selector in selectors:
                with self.subTest(owner=owner, selector=selector):
                    route = resolve_model_recommendation(
                        owner=owner,
                        active_models=[],
                        **selector,
                    )
                    self.assertEqual(
                        route["schema_version"],
                        MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION,
                    )
                    self.assertEqual(route["status"], "owner_default")
                    self.assertEqual(route["source"], "owner_default")
                    self.assertIn(route["status"], MODEL_RECOMMENDATION_STATUSES)
                    self.assertIsNone(route["selected"])
                    self.assertIsNone(route["projection"])
                    self.assertTrue(route["setup_can_continue"])
                    self.assertTrue(route["inactive_candidates"])

    def test_only_confirmed_active_owner_compatible_models_are_eligible(self) -> None:
        models = (
            _active("gpt-6.1-sol", provider="openai-codex", status="observed_before"),
            _active("gpt-6.1-sol", provider="openai-codex", owners=("maestro",)),
        )
        route = resolve_model_recommendation(owner="hermes", category="deep", active_models=models)
        self.assertEqual(route["status"], "owner_default")

    def test_hermes_projection_is_one_native_binding_not_a_provider_registry(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", role_slot="main", active_models=reversed(_ALL_ACTIVE)
        )
        projection = route["projection"]
        self.assertEqual(projection["kind"], "hermes_native_binding")
        self.assertEqual(projection["alias"], "main")
        # `main` leads with GPT-6.1 Sol, absent here; Opus 5.5 is next.
        self.assertEqual(projection["provider"], "ccapi")
        self.assertEqual(projection["model_id"], "claude-opus-5-5")
        self.assertEqual(projection["binding"], "ccapi/claude-opus-5-5")
        self.assertEqual(projection["apply_state"], "approval_required")
        self.assertNotIn("providers", projection)
        self.assertNotIn("credentials", serialize_recommendation_payload(route).casefold())

    def test_maestro_projection_keeps_ordered_external_chain_and_owner_compatibility(self) -> None:
        active = (
            _active("grok-build-0.1", provider="xai", family="grok", owners=("hermes",)),
            _active("kimi-k3.1-pro", provider="apitopia", family="kimi"),
            _active("gemini-4-argon", provider="google", family="gemini"),
        )
        route = resolve_model_recommendation(
            owner="maestro", domain="x_platform_data", active_models=active
        )
        self.assertEqual(route["selected"]["model_alias"], "kimi-k3.1-pro")
        self.assertEqual(route["projection"]["kind"], "maestro_ordered_chain")
        self.assertEqual(
            [entry["model_alias"] for entry in route["projection"]["chain"]],
            ["kimi-k3.1-pro", "gemini-4-argon"],
        )
        self.assertEqual(route["inactive_candidates"], ["grok-build-0.1"])

    def test_selector_surfaces_are_mutually_exclusive_and_closed(self) -> None:
        invalid = (
            {"category": "main"},
            {"category": "x_platform_data"},
            {"role_slot": "brain"},
            {"domain": "main"},
            {"category": "deep", "domain": "x_platform_data"},
        )
        for selector in invalid:
            with self.subTest(selector=selector):
                with self.assertRaises(ValueError):
                    resolve_model_recommendation(owner="hermes", active_models=(), **selector)

    def test_user_override_drives_resolution_without_mutating_shipped_catalog(self) -> None:
        override = load_recommendation_overrides({
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {"deep": [{
                "model_alias": "qwen3-coder", "model_family": "qwen",
                "preferred_provider_families": ["qwen-oauth"],
                "reasoning_effort": "high", "reasoning": "User deep route.",
            }]},
        })
        route = resolve_model_recommendation(
            owner="hermes",
            category="deep",
            active_models=[_active("qwen3-coder", provider="qwen-oauth", family="qwen")],
            overrides=override,
        )
        self.assertEqual(route["selected"]["model_alias"], "qwen3-coder")
        self.assertEqual(route["selected"]["recommendation_source"], "user_override")
        self.assertEqual(SHIPPED_MODEL_RECOMMENDATIONS["categories"]["deep"][0]["model_alias"], "claude-opus-5-5")

    def test_resolution_serialization_is_stable_across_active_input_order(self) -> None:
        first = resolve_model_recommendation(
            owner="maestro", role_slot="main", active_models=_ALL_ACTIVE
        )
        second = resolve_model_recommendation(
            owner="maestro", role_slot="main", active_models=reversed(_ALL_ACTIVE)
        )
        self.assertEqual(serialize_recommendation_payload(first), serialize_recommendation_payload(second))


class LastResortFallbackTests(unittest.TestCase):
    """The shared final attempt used only after a selected chain is exhausted."""

    _OPUS_ONLY = (_active("claude-opus-5-5", provider="ccapi", family="claude"),)
    _SOL_ONLY = (_active("gpt-6.1-sol", provider="openai-codex", family="gpt"),)

    def test_schema_versions_advance_and_legacy_override_remains_supported(self) -> None:
        self.assertEqual(MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION, "model_recommendation_catalog/v2")
        self.assertEqual(MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "model_recommendation_overrides/v2")
        self.assertEqual(MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION, "model_recommendation_resolution/v3")

        legacy = load_recommendation_overrides({
            "schema_version": "model_recommendation_overrides/v1",
            "categories": {"quick": [{
                "model_alias": "gemini-3.1-pro",
                "model_family": "gemini",
                "preferred_provider_families": ["google"],
                "reasoning": "Legacy category override.",
            }]},
        })
        self.assertEqual(legacy["schema_version"], "model_recommendation_overrides/v1")
        self.assertNotIn("last_resort", legacy)
        merged = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, legacy)
        self.assertEqual(merged["categories"]["quick"][0]["model_alias"], "gemini-3.1-pro")
        self.assertEqual(
            merged["last_resort"]["any"][0]["model_alias"],
            "claude-opus-5-5",
        )
        with self.assertRaises(ValueError):
            load_recommendation_overrides({
                "schema_version": "model_recommendation_overrides/v1",
                "last_resort": {"any": []},
            })

    def test_legacy_catalog_without_last_resort_keeps_owner_default_behavior(self) -> None:
        legacy_catalog = {
            "schema_version": "model_recommendation_catalog/v1",
            "categories": SHIPPED_MODEL_RECOMMENDATIONS["categories"],
            "role_suggestions": SHIPPED_MODEL_RECOMMENDATIONS["role_suggestions"],
            "domain_affinities": SHIPPED_MODEL_RECOMMENDATIONS["domain_affinities"],
        }
        untouched = merge_recommendation_catalog(legacy_catalog, None)
        self.assertNotIn("last_resort", untouched)
        self.assertEqual(
            merge_recommendation_catalog(untouched, None)["schema_version"],
            "model_recommendation_catalog/v1",
        )
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            active_models=self._OPUS_ONLY,
            catalog=legacy_catalog,
        )
        self.assertEqual(route["status"], "owner_default")
        self.assertEqual(route["source"], "owner_default")

        v2_category_only = merge_recommendation_catalog(
            legacy_catalog,
            load_recommendation_overrides({
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "categories": {"quick": [{
                    "model_alias": "gemini-3.1-pro",
                    "model_family": "gemini",
                    "preferred_provider_families": ["google"],
                    "reasoning": "Version 2 override using only a legacy-compatible section.",
                }]},
            }),
        )
        self.assertEqual(v2_category_only["schema_version"], "model_recommendation_catalog/v1")
        self.assertNotIn("last_resort", v2_category_only)
        self.assertEqual(v2_category_only["categories"]["quick"][0]["model_alias"], "gemini-3.1-pro")

        upgraded = merge_recommendation_catalog(
            legacy_catalog,
            load_recommendation_overrides({
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "last_resort": {"any": [{
                    "model_alias": "claude-opus-5-5",
                    "model_family": "claude",
                    "preferred_provider_families": ["ccapi"],
                    "reasoning": "Upgrade the legacy catalog with an explicit final chain.",
                }]},
            }),
        )
        self.assertEqual(upgraded["schema_version"], MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION)

    def test_dead_category_chain_falls_back_to_the_shared_subscription_chain(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", category="quick", active_models=self._OPUS_ONLY
        )
        self.assertEqual(route["status"], "resolved")
        self.assertEqual(route["source"], "last_resort_chain")
        self.assertEqual(route["selected"]["model_alias"], "claude-opus-5-5")
        self.assertEqual(route["available_chain"], ["claude-opus-5-5"])
        self.assertEqual(
            route["inactive_candidates"],
            ["glm-5.3-flash", "gpt-6-luna", "claude-haiku-5-5", "kimi-k3.1-pro", "gpt-6.1-sol"],
        )
        self.assertEqual(route["projection"]["kind"], "hermes_native_binding")
        self.assertEqual(route["projection"]["apply_state"], "approval_required")

    def test_last_resort_never_outranks_an_eligible_selected_chain_candidate(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            active_models=(
                # The tail of `quick`, not the head: a non-head chain
                # candidate still outranks the shared last resort.
                _active("kimi-k3.1-pro", provider="apitopia", family="kimi"),
                *self._OPUS_ONLY,
            ),
        )
        self.assertEqual(route["source"], "recommendation_chain")
        self.assertEqual(route["selected"]["model_alias"], "kimi-k3.1-pro")

    def test_last_resort_also_serves_role_slot_and_domain_selectors(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", domain="x_platform_data", active_models=self._SOL_ONLY
        )
        self.assertEqual(route["source"], "last_resort_chain")
        self.assertEqual(route["selected"]["model_alias"], "gpt-6.1-sol")
        self.assertEqual(
            route["inactive_candidates"],
            ["grok-build-0.1", "kimi-k3.1-pro", "gemini-4-argon", "claude-opus-5-5"],
        )

    def test_unavailable_explicit_model_stays_fail_closed_against_last_resort(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            explicit_model="glm-5.2-ultrafast",
            active_models=self._OPUS_ONLY,
        )
        self.assertEqual(route["status"], "choice_required")
        self.assertIsNone(route["selected"])

    def test_no_active_model_at_all_still_reaches_owner_default(self) -> None:
        route = resolve_model_recommendation(owner="hermes", category="quick", active_models=[])
        self.assertEqual(route["status"], "owner_default")
        self.assertEqual(
            route["inactive_candidates"],
            [
                "glm-5.3-flash",
                "gpt-6-luna",
                "claude-haiku-5-5",
                "kimi-k3.1-pro",
                "claude-opus-5-5",
                "gpt-6.1-sol",
            ],
        )

    def test_maestro_projection_carries_the_whole_last_resort_order(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="quick",
            active_models=(*self._OPUS_ONLY, *self._SOL_ONLY),
        )
        self.assertEqual(
            [entry["model_alias"] for entry in route["projection"]["chain"]],
            ["claude-opus-5-5", "gpt-6.1-sol"],
        )

    def test_last_resort_chain_is_user_overridable_through_the_same_closed_surface(self) -> None:
        override = load_recommendation_overrides({
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "last_resort": {"any": [{
                "model_alias": "gemini-3.1-pro",
                "model_family": "gemini",
                "preferred_provider_families": ["google"],
                "reasoning": "Operator-selected final attempt.",
            }]},
        })
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            active_models=[_active("gemini-3.1-pro", provider="google", family="gemini")],
            overrides=override,
        )
        self.assertEqual(route["source"], "last_resort_chain")
        self.assertEqual(route["selected"]["model_alias"], "gemini-3.1-pro")
        self.assertEqual(route["selected"]["recommendation_source"], "user_override")
        self.assertEqual(
            SHIPPED_MODEL_RECOMMENDATIONS["last_resort"]["any"][0]["model_alias"],
            "claude-opus-5-5",
        )

    def test_override_rejects_unknown_last_resort_slots_and_secret_fields(self) -> None:
        bad_payloads = (
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "last_resort": {"quick": []},
            },
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "last_resort": {"any": [{
                    "model_alias": "gemini-3.1-pro", "model_family": "gemini",
                    "preferred_provider_families": ["google"],
                    "reasoning": "x", "api_key": "must-not-be-stored",
                }]},
            },
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    load_recommendation_overrides(payload)


if __name__ == "__main__":
    unittest.main()

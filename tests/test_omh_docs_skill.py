from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.routing.chat import route_chat_message
from omh.skills.catalog import (
    OMH_SKILL_DISPLAY_NAME_OVERRIDES,
    installable_skill_definitions,
    omh_skill_display_name,
)
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates


class OmhDocsSkillTests(unittest.TestCase):
    def test_catalog_installs_and_renders_the_public_omh_docs_skill(self) -> None:
        # Given: the public installable catalog and generated template registry.
        definitions = {definition.name: definition for definition in installable_skill_definitions()}
        templates = {template.name: template for template in builtin_skill_templates()}

        # When: the canonical product-docs skill and its public label are resolved.
        display_name = omh_skill_display_name("product-docs")

        # Then: one canonical skill renders and installs under the public omh-docs label.
        self.assertIn("product-docs", definitions)
        self.assertIn("product-docs", templates)
        self.assertEqual(display_name, "omh-docs")
        self.assertEqual(OMH_SKILL_DISPLAY_NAME_OVERRIDES["product-docs"], "omh-docs")
        self.assertEqual(definitions["product-docs"].triggers[0], "product-docs")
        self.assertTrue(all(not trigger.startswith("omh-") for trigger in definitions["product-docs"].triggers))
        self.assertIn('name: "omh-docs"', templates["product-docs"].content)

    def test_routes_explicit_omh_self_documentation_prompts(self) -> None:
        # Given: direct invocations and unambiguous OMH self-knowledge questions.
        messages = (
            "use omh-docs",
            "Please use omh-docs to explain OMH",
            "what is OMH?",
            "what is oh-my-hermes?",
            "how does OMH work?",
            "show the OMH capability catalog",
            "Explain the OMH capability catalog",
            "explain OMH model routing",
            "Explain the OMH memory system",
            "where does OMH store local state?",
            "How does OMH store local state?",
        )

        # When: each prompt is classified by the public chat router.
        selected = [route_chat_message(message)["selected_skill"] for message in messages]

        # Then: every explicit OMH documentation prompt selects the canonical skill.
        self.assertEqual(selected, ["product-docs"] * len(messages))
        explicit = route_chat_message("Please use omh-docs to explain OMH")
        self.assertIs(explicit["explicit"], True)
        canonical = route_chat_message("Please use product-docs to explain OMH")
        self.assertEqual(canonical["selected_skill"], explicit["selected_skill"])

    def test_does_not_steal_generic_docs_or_other_product_questions(self) -> None:
        # Given: documentation requests that do not ask about OMH itself.
        messages = (
            "write API documentation for my library",
            "use docs to write my API documentation",
            "Don't use omh-docs; write API documentation for my library",
            "I am discussing the omh-docs skill, not asking you to invoke it.",
            "Can you update omh-docs?",
            "Can you install omh-docs?",
            "Can you remove omh-docs?",
            "Review the omh-docs implementation for bugs.",
            "I plan to use omh-docs tomorrow.",
            "summarize this Markdown document",
            "how do I use the OpenAI API?",
            "how does Hermes Agent work?",
        )

        # When: each prompt is classified by the public chat router.
        routes = [route_chat_message(message) for message in messages]
        selected = [route["selected_skill"] for route in routes]
        recommended = {
            recommendation["skill"]
            for route in routes
            for recommendation in route["recommendations"]
        }

        # Then: the OMH self-documentation skill neither claims nor recommends itself.
        self.assertNotIn("product-docs", selected)
        self.assertNotIn("product-docs", recommended)

    def test_packages_the_custom_body_and_progressive_references(self) -> None:
        # Given: the generated docs skill and its packaged reference registry.
        skill = next(template for template in builtin_skill_templates() if template.name == "product-docs")
        references = {
            template.relative_path: template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == "product-docs"
        }

        # When: the public progressive-disclosure contract is inspected.
        expected_paths = {
            "references/product-and-sources.md",
            "references/capability-map.md",
            "references/model-routing-and-local-state.md",
            "references/long-term-memory.md",
        }

        # Then: one custom source route points to the complete bounded reference set.
        self.assertEqual(set(references), expected_paths)
        for path in expected_paths:
            self.assertIn(f"`{path}`", skill.content)
        self.assertIn("rlaope/oh-my-hermes", skill.content)
        self.assertIn("current `main`", references["references/product-and-sources.md"])
        self.assertIn("omh doctor --json", skill.content)
        self.assertIn("~/.omh", skill.content)
        self.assertIn("docs/MEMORY.md", references["references/long-term-memory.md"])

    def test_enforces_public_local_security_and_public_name_boundaries(self) -> None:
        # Given: every user-facing instruction shipped by the docs skill.
        skill = next(template for template in builtin_skill_templates() if template.name == "product-docs")
        references = [
            template.content for template in builtin_skill_reference_templates() if template.skill_name == "product-docs"
        ]
        combined = "\n".join((skill.content, *references))

        # When: the source, privacy, mutation, and public-name contract is inspected.
        public_ulw_names = (
            "ulw-context",
            "ulw-interview",
            "ulw-research",
            "ulw-plan",
            "ulw-work",
            "ulw-maestro",
            "ulw-loop",
            "ulw-qa",
            "ulw-perf",
        )

        # Then: the prompt has explicit answer labels and never exposes legacy engine labels.
        self.assertIn("`public_product`", skill.content)
        self.assertIn("`current_local_install`", skill.content)
        for public_name in public_ulw_names:
            self.assertIn(f"`{public_name}`", combined)
        self.assertNotIn("ultrawork", combined.lower())
        self.assertNotIn("ralplan", combined.lower())
        for excluded_source in (
            "credentials",
            "tokens",
            "auth files",
            "`.env` values",
            "provider secrets",
            "raw private logs",
            "unrelated user content",
        ):
            self.assertIn(excluded_source, combined)
        self.assertIn("version_or_commit", combined)
        self.assertIn("## Mutation Requests", combined)
        self.assertIn("unless separately authorized", combined)

    def test_sources_match_real_cli_home_catalog_and_memory_boundaries(self) -> None:
        references = {
            template.relative_path: template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == "product-docs"
        }
        product = references["references/product-and-sources.md"]
        capabilities = references["references/capability-map.md"]
        local = references["references/model-routing-and-local-state.md"]
        memory = references["references/long-term-memory.md"]

        self.assertIn("omh capability-policy status", local)
        self.assertNotIn("omh capability-policy show", local)
        self.assertIn("state-write side effect", local)
        self.assertIn("`last_doctor`", local)
        for home_contract in (
            "`OMH_HOME`",
            "`--omh-home`",
            "`--scope project`",
            "`src/system/paths.py`",
            "`current/skills`",
        ):
            self.assertIn(home_contract, local)

        self.assertIn("installed manifest", capabilities)
        self.assertIn("`omh docs workflows --json`", capabilities)
        self.assertIn("public catalog", capabilities)

        combined_sources = "\n".join((product, capabilities, local, memory))
        for source in (
            "`docs/DIRECTION.md`",
            "`docs/ARCHITECTURE.md`",
            "`docs/CAPABILITIES.md`",
            "`docs/WORKFLOWS.md`",
            "`docs/FANOUT.md`",
            "`src/skills/catalog_types.py`",
            "`src/routing/display_names.py`",
            "`src/system/paths.py`",
            "`src/plugin_bundle/omh/hermes_memory.py`",
        ):
            self.assertIn(source, combined_sources)

        self.assertIn("may read", memory)
        self.assertIn("`MEMORY.md`", memory)
        self.assertIn("`USER.md`", memory)
        self.assertIn("metadata-only", memory)
        self.assertIn("cannot mutate Hermes memory", memory)
        self.assertNotIn("OMH does not read", memory)


if __name__ == "__main__":
    unittest.main()

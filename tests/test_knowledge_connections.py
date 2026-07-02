from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.knowledge_connections import (
    KnowledgeConnectionOptions,
    build_knowledge_connection_intent,
    build_knowledge_store_intent,
)
from omh.research_department import build_research_department_plan, validate_research_department_plan


class KnowledgeConnectionTests(unittest.TestCase):
    def test_helper_classifies_vendor_neutral_destinations(self) -> None:
        cases = (
            ("store notes in my Obsidian vault", "Obsidian vault", "markdown_vault", "obsidian", "obsidian_vault"),
            ("save the wiki into a Notion knowledge base", "", "notion_knowledge_base", "notion", "notion_workspace"),
            ("keep briefs in Google Drive docs", "", "google_document_store", "google", "google_drive"),
            ("persist research gaps in a database", "", "database", "", "database"),
            ("write durable notes to a local markdown folder", "", "markdown_folder", "", "markdown_folder"),
            ("send the wiki to Confluence later", "Confluence space", "unknown_external_destination", "", "local_markdown_folder"),
        )

        for text, explicit_target, connection_kind, vendor_hint, legacy_store_type in cases:
            with self.subTest(connection_kind=connection_kind):
                connection = build_knowledge_connection_intent(
                    text,
                    options=KnowledgeConnectionOptions(knowledge_store=explicit_target),
                )

                self.assertEqual(connection["schema_version"], "knowledge_connection_intent/v1")
                self.assertEqual(connection["status"], "prepared")
                self.assertEqual(connection["kind"], connection_kind)
                self.assertEqual(connection["vendor_hint"], vendor_hint)
                self.assertEqual(connection["legacy_store_type"], legacy_store_type)
                self.assertFalse(connection["write_observed"])
                self.assertFalse(connection["query_observed"])
                self.assertTrue(connection["requires_observed_write_evidence"])
                self.assertIn("not write evidence", connection["boundary"])
                self.assertNotEqual(connection["kind"], "synthesis_workspace")

    def test_store_adapter_preserves_research_department_contract(self) -> None:
        store = build_knowledge_store_intent("save source notes into a Notion knowledge base")

        self.assertEqual(
            set(store),
            {
                "schema_version",
                "status",
                "type",
                "explicit_target",
                "vendor_hint",
                "mode",
                "readiness",
                "requested_capability",
                "write_observed",
                "requires_observed_write_evidence",
                "boundary",
            },
        )
        self.assertEqual(store["schema_version"], "knowledge_store_intent/v1")
        self.assertEqual(store["type"], "notion_workspace")
        self.assertEqual(store["vendor_hint"], "notion")
        self.assertFalse(store["write_observed"])

    def test_research_department_uses_store_adapter_without_schema_churn(self) -> None:
        plan = build_research_department_plan(
            "daily research and save durable notes to Google Drive docs",
            created_at="2026-06-17T00:00:00Z",
        )

        self.assertEqual(plan["knowledge_store"]["schema_version"], "knowledge_store_intent/v1")
        self.assertEqual(plan["knowledge_store"]["type"], "google_drive")
        self.assertEqual(plan["knowledge_store"]["vendor_hint"], "google")
        self.assertEqual(plan["optional_integrations"]["knowledge_store"], plan["knowledge_store"])
        self.assertNotIn("knowledge_connection", plan)
        self.assertEqual(validate_research_department_plan(plan), [])

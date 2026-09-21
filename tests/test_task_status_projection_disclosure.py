"""Task status projection disclosure tests."""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.workflows.task_status_projection_disclosure import (
    render_disclosed_fields,
)


class TaskStatusProjectionDisclosureTests(unittest.TestCase):
    def test_only_allowed_fields_are_rendered(self) -> None:
        fields = {
            "task_ref": "T1",
            "status": "running",
            "summary": "implement worker",
            "workspace_path": "C:\\secret\\workspace",
            "prompt": "private prompt",
            "secret": "top-secret",
        }

        result = render_disclosed_fields(
            fields,
            allowed_fields=["task_ref", "status", "summary"],
            max_field_chars=64,
        )

        self.assertEqual(
            result,
            {
                "task_ref": "T1",
                "status": "running",
                "summary": "implement worker",
            },
        )

    def test_disallowed_sensitive_fields_are_never_rendered(self) -> None:
        fields = {
            "task_ref": "T1",
            "body": "private body",
            "prompt": "private prompt",
            "workspace_path": "/workspace/project",
            "secret": "secret-value",
            "attachments": ["file.txt"],
            "provider_metadata": {"thread_id": "123"},
        }

        result = render_disclosed_fields(
            fields,
            allowed_fields=[
                "task_ref",
                "body",
                "prompt",
                "workspace_path",
                "secret",
                "attachments",
                "provider_metadata",
            ],
            max_field_chars=64,
        )

        self.assertEqual(result, {"task_ref": "T1"})

    def test_field_values_are_length_bounded(self) -> None:
        fields = {
            "task_ref": "T1",
            "summary": "x" * 100,
        }

        result = render_disclosed_fields(
            fields,
            allowed_fields=["task_ref", "summary"],
            max_field_chars=32,
        )

        self.assertEqual(result["task_ref"], "T1")
        self.assertEqual(result["summary"], "x" * 32)

    def test_non_string_values_are_not_rendered(self) -> None:
        fields = {
            "task_ref": "T1",
            "status": "running",
            "count": 3,
            "metadata": {"key": "value"},
            "items": ["a", "b"],
        }

        result = render_disclosed_fields(
            fields,
            allowed_fields=["task_ref", "status", "count", "metadata", "items"],
            max_field_chars=64,
        )

        self.assertEqual(
            result,
            {
                "task_ref": "T1",
                "status": "running",
            },
        )

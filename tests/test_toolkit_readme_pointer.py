"""Every skill that ships a `toolkit/` names `toolkit/README.md` with a loadable call.

Hermes' `skill_view` lists only `references/`, `templates/`, `assets/` and
`scripts/` files beside a body, never `toolkit/**`. A toolkit file is still
readable through `skill_view(name, file_path='toolkit/...')`, but only when the
body names that path, so each toolkit owner's rendered body must carry the
exact call that opens the toolkit's README.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import omh_skill_display_name
from omh.skills.packaging import builtin_skill_templates
from omh.skills.support_files import builtin_skill_support_templates


class ToolkitReadmePointerTests(unittest.TestCase):
    def test_every_toolkit_owner_body_names_its_readme_with_a_skill_view_call(self) -> None:
        owners = sorted(
            {template.skill_name for template in builtin_skill_support_templates() if template.relative_path.startswith("toolkit/")}
        )
        self.assertGreaterEqual(len(owners), 8, owners)
        shipped = {
            (template.skill_name, template.relative_path) for template in builtin_skill_support_templates()
        }
        bodies = {template.name: template.content for template in builtin_skill_templates()}
        for owner in owners:
            with self.subTest(skill=owner):
                self.assertIn((owner, "toolkit/README.md"), shipped)
                call = f"skill_view(name='{omh_skill_display_name(owner)}', file_path='toolkit/README.md')"
                self.assertIn(call, bodies[owner])


if __name__ == "__main__":
    unittest.main()

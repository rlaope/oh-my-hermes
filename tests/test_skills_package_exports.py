"""The `omh.skills` package exports its render side lazily, and the router never pulls it in.

`routing.intent` imported `skills.catalog_types` (before the classifier moved
into the bundle); importing any submodule runs `skills/__init__`. An eager
`from .render import` there pulled the renderer and, through it, the plugin
bundle's `awareness` into every router import, and `awareness` imported
`routing.intent` back (#2013). The cycle is gone (#2015);
these tests keep it gone. Import state is process state, so each case runs in
a fresh interpreter.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest


def _fresh(code: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-P", "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


class SkillsPackageExportTests(unittest.TestCase):
    def test_a_router_import_loads_neither_the_renderer_nor_awareness(self) -> None:
        # The property #2015 restored. #2013's per-call resolution in awareness
        # hides the symptom of the cycle, so this is the only thing that goes
        # red when an eager render import returns to `skills/__init__` or
        # `skills/catalog`.
        loaded = _fresh(
            """
            import json, sys
            import omh.routing.policy  # the first router import of this process
            watched = ("omh.skills.render", "omh.skills.packaging", "omh.plugin_bundle.omh.awareness")
            print(json.dumps({name: name in sys.modules for name in watched}))
            """
        )
        self.assertEqual(
            loaded,
            {"omh.skills.render": False, "omh.skills.packaging": False, "omh.plugin_bundle.omh.awareness": False},
        )

    def test_awareness_first_keeps_the_router_classifiers(self) -> None:
        # Awareness is the other end of the former cycle. Imported first, it
        # holds the very classifier objects the router exports: one
        # implementation, in the bundle, re-exported by `routing.intent`.
        probe = _fresh(
            """
            import json
            from omh.plugin_bundle.omh import awareness
            from omh.routing import intent
            print(json.dumps({
                "workflow": awareness.classify_workflow_intent is intent.classify_workflow_intent,
                "quality": awareness.classify_omh_quality_intent is intent.classify_omh_quality_intent,
            }))
            """
        )
        self.assertEqual(probe, {"workflow": True, "quality": True})

    def test_the_lazy_names_resolve_and_list_like_eager_ones(self) -> None:
        probe = _fresh(
            """
            import json
            import omh.skills as skills
            from omh.skills import SkillTemplate, builtin_skill_templates, router_skill
            from omh.skills import render
            namespace = {}
            exec("from omh.skills import *", namespace)
            try:
                skills.no_such_name
                error = None
            except AttributeError as exc:
                error = str(exc)
            print(json.dumps({
                "same_objects": [
                    SkillTemplate is render.SkillTemplate,
                    skills.SkillReferenceTemplate is render.SkillReferenceTemplate,
                    router_skill is render.router_skill,
                    callable(builtin_skill_templates),
                ],
                "star_matches_all": sorted(k for k in namespace if not k.startswith("__")) == sorted(skills.__all__),
                "dir_lists_lazy_names": all(name in dir(skills) for name in skills._RENDER_SIDE_EXPORTS),
                "hasattr_missing": hasattr(skills, "no_such_name"),
                "error": error,
            }))
            """
        )
        self.assertEqual(probe["same_objects"], [True, True, True, True])
        self.assertTrue(probe["star_matches_all"])
        self.assertTrue(probe["dir_lists_lazy_names"])
        self.assertFalse(probe["hasattr_missing"])
        self.assertEqual(probe["error"], "module 'omh.skills' has no attribute 'no_such_name'")


if __name__ == "__main__":
    unittest.main()

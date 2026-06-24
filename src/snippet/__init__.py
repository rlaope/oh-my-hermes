from __future__ import annotations

from ..plugin_bundle.omh.awareness import router_keyword_summary


WORKSPACE_SNIPPET = f"""# oh-my-hermes workspace guidance

When the user mentions oh-my-hermes or a workflow keyword such as {router_keyword_summary()}, first consult the installed Hermes skill `oh-my-hermes`.

Use this as best-effort routing guidance, not as a replacement for Hermes core behavior. If a runtime feature is unavailable in Hermes, use the Hermes Compatibility Contract in the skill.
"""

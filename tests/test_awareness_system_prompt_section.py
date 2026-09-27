"""The awareness primer as a Hermes system prompt section, with its fallback.

Hermes 0.20.2 (tag v2026.8.16) added `register_system_prompt_section`: text
rendered once per new session and frozen into its system prompt. The primer is
session-stable, so on such a host it is registered there and `pre_llm_call`
stops carrying it for the sessions the section rendered for. A host without
the API, or a session the section did not render for, keeps the old path.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.maintenance.doctor import _awareness_delivery_check
from omh.maintenance.release import AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT
from omh.paths import resolve_paths
from omh.plugin_bundle.omh.awareness_delivery import read_awareness_delivery, record_awareness_delivery
from omh.plugin_bundle.omh import register
from omh.plugin_bundle.omh.awareness import awareness_primer_context
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh import skill_shortlist

# Hermes' own limits (`hermes_cli/plugins_dispatch.py`), copied because the
# host is not importable here. The per-section cap is what `max_chars` may not
# exceed; the aggregate is shared by every plugin's rendered sections.
_HOST_MAX_SECTION_CHARS = 4000
_HOST_MAX_SECTIONS_TOTAL_CHARS = 8000
_HOST_HEADING = "## Plugin Context: "

# No OMH vocabulary and no skill candidate line either (`skill_shortlist`), so
# a section session's turn on it has nothing of its own to inject.
_PLAIN_REQUEST = "rename the helper function and update its callers"
_ROUTED_REQUEST = "review this PR for bugs before merge"


class _Ctx:
    """The two methods `register()` requires, and nothing else."""

    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}

    def register_tool(self, name, *args, **kwargs) -> None:
        pass

    def register_hook(self, name, callback) -> None:
        self.hooks[name] = callback


class _SectionCtx(_Ctx):
    """A host that offers system prompt sections, recording each registration."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[dict[str, object]] = []

    def register_system_prompt_section(self, id, content, *, position="after_memory", max_chars=4000):
        self.sections.append({"id": id, "content": content, "position": position, "max_chars": max_chars})


class _RejectingSectionCtx(_Ctx):
    def register_system_prompt_section(self, id, content, **kwargs):
        raise ValueError(f"system prompt section {id!r} is already registered")


def _session_info(session_id: str, **overrides: str) -> dict[str, str]:
    info = {
        "session_id": session_id,
        "model": "gpt-6-astra",
        "provider": "openai-codex",
        "platform": "cli",
        "profile_name": "default",
        "cwd": "/tmp/project-a",
    }
    info.update(overrides)
    return info


class SectionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        llm_hooks._reset_awareness_section_state()
        self.addCleanup(llm_hooks._reset_awareness_section_state)
        skill_shortlist.reset_candidate_line_state()
        self.addCleanup(skill_shortlist.reset_candidate_line_state)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.omh_home = Path(tmp.name) / "omh"
        self.hermes_home = Path(tmp.name) / "hermes"
        self.omh_home.mkdir()
        self.hermes_home.mkdir()

    def first_turn_context(self, session_id: str) -> str:
        # These plain turns match no skill. The session is taken to have seen
        # the no-match line already, so the turn has nothing of its own to
        # inject: the case the delivery accounting below is about.
        skill_shortlist.claim_no_match_line(session_id)
        payload = llm_hooks.pre_llm_call(
            omh_home=str(self.omh_home),
            hermes_home=str(self.hermes_home),
            session_id=session_id,
            user_message=_PLAIN_REQUEST,
            is_first_turn=True,
        )
        return str((payload or {}).get("context", ""))

    def later_turn(self, session_id: str) -> str:
        skill_shortlist.claim_no_match_line(session_id)
        payload = llm_hooks.pre_llm_call(
            omh_home=str(self.omh_home),
            hermes_home=str(self.hermes_home),
            session_id=session_id,
            user_message="thanks",
            is_first_turn=False,
        )
        return str((payload or {}).get("context", ""))


class RegistrationTests(SectionTestCase):
    def test_a_host_with_the_api_gets_one_bounded_section(self) -> None:
        ctx = _SectionCtx()
        register(ctx)
        self.assertEqual(len(ctx.sections), 1)
        section = ctx.sections[0]
        self.assertEqual(section["id"], "omh.awareness")
        self.assertEqual(section["position"], "after_memory")
        self.assertLessEqual(int(section["max_chars"]), _HOST_MAX_SECTION_CHARS)
        content = section["content"]
        self.assertTrue(callable(content))
        text = content(_session_info("s-1"))
        self.assertEqual(text, awareness_primer_context())
        self.assertLessEqual(len(text), AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT)
        self.assertLessEqual(len(text), int(section["max_chars"]))
        # Framed the way the host frames it, the section leaves most of the
        # aggregate budget to other plugins.
        framed = f"{_HOST_HEADING}{section['id']}\n<!-- hermes-plugin-section-chars:{len(text)} -->\n\n{text}"
        self.assertLess(len(framed), _HOST_MAX_SECTIONS_TOTAL_CHARS // 2)
        # The hooks still register beside it.
        self.assertIn("pre_llm_call", ctx.hooks)

    def test_a_host_without_the_api_registers_the_hooks_and_keeps_the_primer_per_turn(self) -> None:
        ctx = _Ctx()
        register(ctx)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn(awareness_primer_context(), self.first_turn_context("s-old-host"))

    def test_a_host_that_rejects_the_section_keeps_the_primer_per_turn(self) -> None:
        ctx = _RejectingSectionCtx()
        register(ctx)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn(awareness_primer_context(), self.first_turn_context("s-rejected"))


class _Manager:
    """Hermes' per-HERMES_HOME plugin manager: the section registry and nothing else."""

    def __init__(self) -> None:
        self._system_prompt_sections: dict[str, object] = {}


class _ManagedSectionCtx(_SectionCtx):
    """A plugin-loader context: registers into its manager, as the host does."""

    def __init__(self, manager: _Manager) -> None:
        super().__init__()
        self._manager = manager

    def register_system_prompt_section(self, id, content, **kwargs):
        if id in self._manager._system_prompt_sections:
            raise ValueError(f"system prompt section {id!r} is already registered by plugin 'omh'")
        self._manager._system_prompt_sections[id] = content
        super().register_system_prompt_section(id, content, **kwargs)


class _CollectorCtx(_Ctx):
    """The memory-provider loader's collector: no `_manager` of its own; it
    forwards to a real context built by `_plugin_context()`."""

    def __init__(self, inner: object) -> None:
        super().__init__()
        self._inner = inner
        self.forwarded: list[str] = []

    def _plugin_context(self):
        if isinstance(self._inner, BaseException):
            raise self._inner
        return self._inner

    def register_system_prompt_section(self, id, content, **kwargs):
        self.forwarded.append(id)
        self._plugin_context().register_system_prompt_section(id, content, **kwargs)


class SingleRegistrationTests(SectionTestCase):
    """`register()` runs on both the plugin loader and the memory-provider
    loader; the section must land once per manager, without a second attempt
    that Hermes' collector logs as a warning on every session init."""

    def test_the_second_loader_pass_skips_a_section_its_manager_already_holds(self) -> None:
        manager = _Manager()
        plugin_ctx = _ManagedSectionCtx(manager)
        register(plugin_ctx)
        collector = _CollectorCtx(_ManagedSectionCtx(manager))
        register(collector)
        self.assertEqual(len(plugin_ctx.sections), 1)
        self.assertEqual(collector.forwarded, [])
        self.assertEqual(list(manager._system_prompt_sections), ["omh.awareness"])

    def test_a_second_pass_on_the_same_plugin_context_also_skips(self) -> None:
        manager = _Manager()
        ctx = _ManagedSectionCtx(manager)
        register(ctx)
        register(ctx)
        self.assertEqual(len(ctx.sections), 1)

    def test_another_home_manager_still_registers_its_own_section(self) -> None:
        first, second = _Manager(), _Manager()
        register(_ManagedSectionCtx(first))
        other = _ManagedSectionCtx(second)
        register(other)
        self.assertEqual(len(other.sections), 1)
        self.assertIn("omh.awareness", second._system_prompt_sections)

    def test_the_collector_path_registers_when_its_manager_lacks_the_section(self) -> None:
        manager = _Manager()
        collector = _CollectorCtx(_ManagedSectionCtx(manager))
        register(collector)
        self.assertEqual(collector.forwarded, ["omh.awareness"])
        self.assertIn("omh.awareness", manager._system_prompt_sections)

    def test_a_context_of_unknown_shape_registers_as_before(self) -> None:
        ctx = _SectionCtx()
        register(ctx)
        self.assertEqual(len(ctx.sections), 1)

    def test_a_collector_whose_context_cannot_be_built_answers_not_registered(self) -> None:
        from omh.plugin_bundle.omh import _section_already_registered

        for error in (ImportError("no hermes_cli.plugins"), AttributeError("shape"), RuntimeError("other")):
            with self.subTest(error=type(error).__name__):
                self.assertFalse(_section_already_registered(_CollectorCtx(error), "omh.awareness"))

    def test_a_context_that_cannot_be_built_does_not_abort_register(self) -> None:
        # The check answers "not registered" and the registration proceeds;
        # the forward then fails the same way, which Hermes' collector logs.
        collector = _CollectorCtx(RuntimeError("unexpected"))
        with self.assertRaises(RuntimeError):
            register(collector)
        self.assertEqual(collector.forwarded, ["omh.awareness"])


class FrozenContentTests(SectionTestCase):
    def test_the_rendered_text_carries_no_session_or_turn_data(self) -> None:
        a = llm_hooks.awareness_system_prompt_section(_session_info("session-alpha-123"))
        b = llm_hooks.awareness_system_prompt_section(
            _session_info(
                "session-beta-456",
                model="claude-opus-5-5",
                provider="anthropic",
                platform="discord",
                profile_name="miku",
                cwd="/srv/other-checkout",
            ),
        )
        self.assertEqual(a, b)
        for value in ("session-alpha-123", "gpt-6-astra", "/tmp/project-a", "cli", "default"):
            with self.subTest(value=value):
                self.assertNotIn(value, a)

    def test_the_rendered_text_is_the_same_after_a_turn_ran(self) -> None:
        # A turn writes its own state (delivery ledger, plan counters); the
        # section reads none of it.
        before = llm_hooks.awareness_system_prompt_section(_session_info("s-state"))
        self.first_turn_context("s-state")
        after = llm_hooks.awareness_system_prompt_section(_session_info("s-state"))
        self.assertEqual(before, after)


class PerTurnDeliveryTests(SectionTestCase):
    def test_a_session_the_section_rendered_for_gets_no_per_turn_primer(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-sectioned"))
        self.assertNotIn(awareness_primer_context(), self.first_turn_context("s-sectioned"))

    def test_a_session_the_section_did_not_render_for_still_gets_it(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-sectioned"))
        self.assertIn(awareness_primer_context(), self.first_turn_context("s-resumed-after-restart"))

    def test_a_primer_the_host_would_skip_is_not_recorded_as_delivered(self) -> None:
        # Over the host's per-section cap the host drops the text after
        # rendering it, so the session must keep the per-turn primer.
        oversized = "p" * (llm_hooks.AWARENESS_SECTION_MAX_CHARS + 1)
        with mock.patch.object(llm_hooks, "awareness_primer_context", return_value=oversized):
            llm_hooks.awareness_system_prompt_section(_session_info("s-oversized"))
            self.assertIn(oversized, self.first_turn_context("s-oversized"))

    def test_an_empty_session_id_is_never_recorded(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info(""))
        self.assertIn(awareness_primer_context(), self.first_turn_context(""))


class DoctorDeliveryTests(SectionTestCase):
    """`omh doctor` must not call a section-delivered install a dead hook."""

    def _attempted_long_ago(self):
        # A hook attempt with nothing returned, 31 days before the check: the
        # state in which the zero-delivery warning is due.
        record_awareness_delivery(
            delivered=False,
            route_hint=False,
            context_chars=0,
            observed_at="2026-07-01T00:00:00Z",
            omh_home=str(self.omh_home),
        )
        return resolve_paths(self.omh_home, self.hermes_home)

    def _check(self, paths):
        return _awareness_delivery_check(paths, now=datetime(2026, 8, 1, tzinfo=UTC))

    def test_a_section_session_turn_counts_one_delivery(self) -> None:
        paths = self._attempted_long_ago()
        llm_hooks.awareness_system_prompt_section(_session_info("s-doctor"))
        # The session's first turn injects nothing: the case at issue.
        self.assertEqual(self.first_turn_context("s-doctor"), "")
        record = read_awareness_delivery(str(self.omh_home))
        self.assertEqual(record["delivery_count"], 1)
        # Nothing rode the message, and the ledger says so.
        self.assertEqual(record["last_context_chars"], 0)
        # Counted once per session, not once per turn.
        self.first_turn_context("s-doctor")
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 1)
        check = self._check(paths)
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "ok")

    def test_a_first_turn_carrying_only_the_no_match_line_counts_the_section_once(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-unmatched"))
        payload = llm_hooks.pre_llm_call(
            omh_home=str(self.omh_home),
            hermes_home=str(self.hermes_home),
            session_id="s-unmatched",
            user_message="lol ok",
            is_first_turn=True,
        )
        context = str((payload or {}).get("context", ""))
        self.assertIn(skill_shortlist.NO_MATCH_LINE, context)
        self.assertNotIn(awareness_primer_context(), context)
        record = read_awareness_delivery(str(self.omh_home))
        self.assertEqual(record["delivery_count"], 1)
        self.assertEqual(record["last_context_chars"], len(context))
        # The next unmatched turn has nothing to inject and counts nothing.
        self.assertEqual(self.first_turn_context("s-unmatched"), "")
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 1)

    def test_a_routed_first_turn_counts_the_section_once(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-routed"))
        payload = llm_hooks.pre_llm_call(
            omh_home=str(self.omh_home),
            hermes_home=str(self.hermes_home),
            session_id="s-routed",
            user_message=_ROUTED_REQUEST,
            is_first_turn=True,
        )
        context = str((payload or {}).get("context", ""))
        self.assertIn("[OMH Route Hint]", context)
        self.assertNotIn(awareness_primer_context(), context)
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 1)
        # A turn that leaves the primer to the section with nothing else to
        # inject does not count the section a second time.
        self.assertEqual(self.first_turn_context("s-routed"), "")
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 1)

    def test_a_re_render_after_the_claim_does_not_re_arm_it(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-rerender"))
        self.first_turn_context("s-rerender")
        # A compaction that keeps the id renders the section again.
        llm_hooks.awareness_system_prompt_section(_session_info("s-rerender"))
        self.assertEqual(self.first_turn_context("s-rerender"), "")
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 1)

    def test_a_render_without_a_turn_is_not_a_delivery(self) -> None:
        # `hermes prompt-size` and a routed review fork render the section
        # without a `pre_llm_call` for that id.
        paths = self._attempted_long_ago()
        llm_hooks.awareness_system_prompt_section(_session_info("prompt-size-inspection"))
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 0)
        check = self._check(paths)
        self.assertFalse(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("for at least 7 days", check.message)

    def test_no_section_and_no_payload_still_warns(self) -> None:
        paths = self._attempted_long_ago()
        # A later turn with nothing to inject, in a session no section rendered for.
        self.assertEqual(self.later_turn("s-plain"), "")
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 0)
        check = self._check(paths)
        self.assertFalse(check.ok)
        self.assertEqual(check.severity, "warning")


class ForkedRenderTests(SectionTestCase):
    """A routed review fork renders under its parent's session id."""

    def routed_later_turn(self, session_id: str) -> str:
        payload = llm_hooks.pre_llm_call(
            omh_home=str(self.omh_home),
            hermes_home=str(self.hermes_home),
            session_id=session_id,
            user_message=_ROUTED_REQUEST,
            is_first_turn=False,
        )
        return str((payload or {}).get("context", ""))

    def test_a_fork_render_for_a_resumed_parent_keeps_the_per_turn_primer(self) -> None:
        # The parent was resumed after a restart: no render, no first turn in
        # this process. Its first review fork renders under the parent's id.
        llm_hooks.awareness_system_prompt_section(_session_info("s-resumed-parent"))
        self.assertIn(awareness_primer_context(), self.routed_later_turn("s-resumed-parent"))
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 1)
        self.assertGreater(read_awareness_delivery(str(self.omh_home))["last_context_chars"], 0)

    def test_a_fork_render_is_never_counted_as_a_section_delivery(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-resumed-parent"))
        # A later turn with nothing to inject: no payload and no section claim.
        self.assertEqual(self.later_turn("s-resumed-parent"), "")
        self.assertEqual(read_awareness_delivery(str(self.omh_home))["delivery_count"], 0)

    def test_a_fork_of_a_live_session_keeps_it_on_the_section(self) -> None:
        llm_hooks.awareness_system_prompt_section(_session_info("s-live"))
        self.first_turn_context("s-live")
        llm_hooks.awareness_system_prompt_section(_session_info("s-live"))  # the fork
        self.assertNotIn(awareness_primer_context(), self.routed_later_turn("s-live"))


class SessionBoundTests(SectionTestCase):
    def test_eviction_is_least_recently_used(self) -> None:
        cap = llm_hooks._AWARENESS_SECTION_SESSION_CAP
        for index in range(cap):
            llm_hooks.awareness_system_prompt_section(_session_info(f"s-{index}"))
        self.first_turn_context("s-0")  # use makes s-0 the most recent
        llm_hooks.awareness_system_prompt_section(_session_info(f"s-{cap}"))
        self.assertIn("s-0", llm_hooks._awareness_section_sessions)
        self.assertNotIn("s-1", llm_hooks._awareness_section_sessions)

    def test_recorded_sessions_are_bounded_oldest_first(self) -> None:
        cap = llm_hooks._AWARENESS_SECTION_SESSION_CAP
        for index in range(cap + 1):
            llm_hooks.awareness_system_prompt_section(_session_info(f"s-{index}"))
        self.assertEqual(len(llm_hooks._awareness_section_sessions), cap)
        # The evicted session falls back to the per-turn primer; the newest keeps the section.
        self.assertIn(awareness_primer_context(), self.first_turn_context("s-0"))
        self.assertNotIn(awareness_primer_context(), self.first_turn_context(f"s-{cap}"))

    def test_a_later_turn_keeps_the_section(self) -> None:
        # Hermes fires `on_session_end` at every turn's end; nothing at a turn
        # boundary may forget the session.
        llm_hooks.awareness_system_prompt_section(_session_info("s-turns"))
        self.first_turn_context("s-turns")
        from omh.plugin_bundle.omh.hooks.session_hooks import on_session_end

        on_session_end(
            session_id="s-turns", omh_home=str(self.omh_home), hermes_home=str(self.hermes_home)
        )
        self.assertNotIn(awareness_primer_context(), self.first_turn_context("s-turns"))

if __name__ == "__main__":
    unittest.main()

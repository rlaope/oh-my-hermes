"""Contract tests for the native data boundary (#801).

Three acceptance criteria, three things these tests refuse to let regress: a
prepared action cannot claim access outside its approved boundary, OMH labels
which limits the selected host can enforce, and out-of-workspace paths and
prohibited data classes are rejected before a handoff exists.

The boundary rides on the safety preflight rather than a module of its own, so
the tests that matter most are the ones proving that decision did not cost
anything: the profile digest still moves only on profile content, the per-host
facts stay *out* of the digest, and ordinary coding work still routes.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from _credential_fixtures import AWS_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()

from omh.coding.coding_delegation import (  # noqa: E402
    _safety_preflight_request,
    build_coding_delegation_payload,
)
from omh.quality.safety_preflight import (  # noqa: E402
    ACCESS_INTENTS,
    DATA_BOUNDARY_ENFORCEMENT_KINDS,
    DATA_BOUNDARY_ENFORCEMENT_SCHEMA_VERSION,
    DATA_BOUNDARY_LIMIT_NAMES,
    DATA_BOUNDARY_LIMITS,
    DATA_CLASSES,
    PERMITTED_DATA_CLASSES,
    PROHIBITED_DATA_CLASSES,
    REQUEST_FIELDS,
    RULE_ACCESS_INTENT_DECLARED,
    RULE_DATA_CLASSES_PERMITTED,
    RULE_DESTINATIONS_APPROVED,
    RULE_TARGET_PATHS_BOUNDED,
    data_boundary_enforcement_facts,
    evaluate_safety_preflight,
    safety_profile_digest,
    safety_profile_revision,
    safety_rule_profile,
)

from test_safety_preflight import request, sharing_request  # noqa: E402


class ApprovedBoundaryTests(unittest.TestCase):
    """A prepared action cannot claim access outside its approved boundary."""

    def test_a_target_inside_a_declared_root_is_allowed(self) -> None:
        verdict = evaluate_safety_preflight(
            request(workspace_roots=["src/quality"], target_paths=["src/quality/safety_preflight.py"])
        )
        self.assertEqual(verdict["status"], "allow")

    def test_a_target_outside_every_declared_root_is_refused(self) -> None:
        verdict = evaluate_safety_preflight(
            request(workspace_roots=["docs", "examples"], target_paths=["docs/x.md", "src/quality/a.py"])
        )
        self.assertEqual(verdict["status"], "deny")
        self.assertEqual(verdict["rule_id"], RULE_TARGET_PATHS_BOUNDED)
        self.assertEqual(verdict["field"], "target_paths[1]")
        self.assertEqual(verdict["reason_code"], "target_path_outside_workspace_roots")
        self.assertTrue(verdict["correction"])

    def test_a_root_prefix_is_compared_by_segment_not_by_substring(self) -> None:
        """`src/quality` must not approve `src/quality-secrets/`."""
        verdict = evaluate_safety_preflight(
            request(workspace_roots=["src/quality"], target_paths=["src/quality-secrets/keys.py"])
        )
        self.assertEqual(verdict["reason_code"], "target_path_outside_workspace_roots")

    def test_both_separators_and_dot_segments_describe_the_same_boundary(self) -> None:
        for root, path in (
            ("src/quality", "src/quality/a.py"),
            ("./src/quality/", "src/quality/a.py"),
            ("src\\quality", "src/quality/a.py"),
            ("src/quality", "src\\quality\\a.py"),
            (".", "src/quality/a.py"),
        ):
            with self.subTest(root=root, path=path):
                verdict = evaluate_safety_preflight(request(workspace_roots=[root], target_paths=[path]))
                self.assertEqual(verdict["status"], "allow", verdict)

    def test_an_undeclared_boundary_leaves_the_project_as_the_boundary(self) -> None:
        """No root declared narrows nothing and widens nothing."""
        self.assertEqual(evaluate_safety_preflight(request(workspace_roots=[]))["status"], "allow")
        escaping = evaluate_safety_preflight(request(workspace_roots=[], target_paths=["../elsewhere/a.py"]))
        self.assertEqual(escaping["reason_code"], "target_path_escapes_project")

    def test_an_out_of_workspace_path_still_denies_with_its_existing_reason_code(self) -> None:
        """#801 added a reason code to this rule; it replaced none of them."""
        for path, reason_code in (
            ("/etc/passwd", "target_path_absolute"),
            ("~/keys.py", "target_path_absolute"),
            ("C:\\Windows\\system32", "target_path_absolute"),
            ("../other-project/a.py", "target_path_escapes_project"),
        ):
            with self.subTest(path=path):
                verdict = evaluate_safety_preflight(request(workspace_roots=["src"], target_paths=[path]))
                self.assertEqual(verdict["status"], "deny")
                self.assertEqual(verdict["rule_id"], RULE_TARGET_PATHS_BOUNDED)
                self.assertEqual(verdict["reason_code"], reason_code)

    def test_a_declared_destination_is_reachable_and_an_undeclared_one_is_not(self) -> None:
        self.assertEqual(evaluate_safety_preflight(sharing_request())["status"], "allow")
        verdict = evaluate_safety_preflight(
            sharing_request(approved_destinations=[{"kind": "git_remote", "ref": "upstream"}])
        )
        self.assertEqual(verdict["status"], "deny")
        self.assertEqual(verdict["rule_id"], RULE_DESTINATIONS_APPROVED)
        self.assertEqual(verdict["field"], "remote_targets[0]")
        self.assertEqual(verdict["reason_code"], "destination_not_declared")

    def test_approving_a_kind_does_not_approve_every_destination_of_that_kind(self) -> None:
        """The pair is the boundary. `git_remote` in the abstract is not one."""
        verdict = evaluate_safety_preflight(
            sharing_request(
                remote_targets=[{"kind": "git_remote", "ref": "attacker-host"}],
                approved_destinations=[{"kind": "git_remote", "ref": "origin"}],
            )
        )
        self.assertEqual(verdict["reason_code"], "destination_not_declared")

    def test_an_empty_approval_approves_nothing_rather_than_everything(self) -> None:
        verdict = evaluate_safety_preflight(
            request(remote_targets=[{"kind": "git_remote", "ref": "origin"}], access_intents=["read", "share"])
        )
        self.assertEqual(verdict["status"], "deny")
        self.assertEqual(verdict["reason_code"], "destination_not_declared")

    def test_the_share_axis_is_checked_in_both_directions(self) -> None:
        reaching = evaluate_safety_preflight(sharing_request(access_intents=["read"]))
        self.assertEqual(reaching["rule_id"], RULE_ACCESS_INTENT_DECLARED)
        self.assertEqual(reaching["reason_code"], "access_intent_undeclared")
        claiming = evaluate_safety_preflight(request(access_intents=["share"]))
        self.assertEqual(claiming["rule_id"], RULE_ACCESS_INTENT_DECLARED)
        self.assertEqual(claiming["reason_code"], "access_intent_unapproved")


class ProhibitedDataClassTests(unittest.TestCase):
    """Prohibited data classes are rejected before a handoff exists."""

    def test_every_permitted_class_is_reachable_from_a_real_request(self) -> None:
        for name in PERMITTED_DATA_CLASSES:
            with self.subTest(data_class=name):
                self.assertEqual(evaluate_safety_preflight(request(data_classes=[name]))["status"], "allow")

    def test_every_prohibited_class_is_refused_by_name(self) -> None:
        for name in PROHIBITED_DATA_CLASSES:
            with self.subTest(data_class=name):
                verdict = evaluate_safety_preflight(request(data_classes=[name]))
                self.assertEqual(verdict["status"], "deny")
                self.assertEqual(verdict["rule_id"], RULE_DATA_CLASSES_PERMITTED)
                self.assertEqual(verdict["field"], "data_classes[0]")
                self.assertEqual(verdict["reason_code"], "data_class_prohibited")
                self.assertIn(name, str(verdict["correction"]))

    def test_the_vocabulary_is_exactly_the_permitted_set_plus_the_prohibited_set(self) -> None:
        self.assertEqual(DATA_CLASSES, (*PERMITTED_DATA_CLASSES, *PROHIBITED_DATA_CLASSES))
        self.assertEqual(set(PERMITTED_DATA_CLASSES) & set(PROHIBITED_DATA_CLASSES), set())
        self.assertEqual(evaluate_safety_preflight(request(data_classes=["telemetry"]))["reason_code"], "data_class_unknown")

    def test_prohibited_class_content_is_refused_even_when_no_class_is_declared(self) -> None:
        """Declaring nothing is not a way past the boundary.

        Each value below is one of the shapes the prohibited vocabulary names,
        caught by the detectors this tree already owns rather than by a pattern
        written for this rule.
        """
        for label, field, value in (
            ("personal data: ssn", "persisted_content_refs", ["ssn-123-45-6789"]),
            ("personal data: email", "observed_record_refs", ["run/dev@example.com"]),
            ("transcript: role marker", "approved_scope", "assistant:reply"),
            ("transcript: sensitive assignment", "owner", "passwd:hunter2"),
        ):
            with self.subTest(label=label):
                verdict = evaluate_safety_preflight(request(**{field: value}))
                self.assertEqual(verdict["status"], "deny")
                self.assertEqual(verdict["rule_id"], RULE_DATA_CLASSES_PERMITTED)
                self.assertEqual(verdict["reason_code"], "prohibited_data_class_content")
                self.assertTrue(verdict["field"])
                self.assertTrue(verdict["correction"])

    def test_credential_material_keeps_naming_the_credential_rule(self) -> None:
        """`secrets_absent` predates #801 and still answers for its own class."""
        verdict = evaluate_safety_preflight(request(owner=AWS_ACCESS_KEY_ID))
        self.assertEqual(verdict["reason_code"], "secret_shaped_value")

    def test_the_prohibited_content_scan_never_reads_a_user_named_path(self) -> None:
        """The lesson that produced the field-class map, re-proved for the new scan.

        A filename is not a credential, an SSN, or an email address. Running
        the wider detector over the path class would deny ordinary coding work
        exactly the way credential shape once did.
        """
        for path in (
            "src/auth/token_store.py",
            "tests/test_authorization_headers.py",
            "src/api/credentials_loader.py",
            "lib/tokenizer.py",
            "bearer_channel.py",
            "src/users/dev@example.com.fixture.py",
            "tests/fixtures/ssn-123-45-6789.json",
            "src/agent/system-prompt.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(evaluate_safety_preflight(request(target_paths=[path]))["status"], "allow")

    def test_a_declared_prohibited_class_is_refused_before_any_handoff_is_built(self) -> None:
        """Rejected `before handoff` is structural, not a claim: the request the
        rule reads is pre-expansion metadata, so nothing has been prepared yet."""
        for forbidden in ("message", "delegation_prompt", "raw_content", "prompt", "diff"):
            self.assertNotIn(forbidden, REQUEST_FIELDS)
        verdict = evaluate_safety_preflight(request(data_classes=["credential_material"]))
        self.assertEqual(verdict["status"], "deny")
        self.assertEqual(verdict["reason_code"], "data_class_prohibited")


class BoundaryVocabularyReachabilityTests(unittest.TestCase):
    def test_every_access_intent_is_reachable_from_a_real_request(self) -> None:
        for intent in ACCESS_INTENTS:
            with self.subTest(intent=intent):
                candidate = sharing_request(access_intents=[intent]) if intent == "share" else request(access_intents=[intent])
                self.assertEqual(evaluate_safety_preflight(candidate)["status"], "allow", candidate)

    def test_every_new_request_field_has_a_declared_class_and_a_rule(self) -> None:
        profile = safety_rule_profile()
        classes = profile["field_classes"]
        axes = {str(rule["axis"]) for rule in profile["rules"]}
        for field, expected_class, axis in (
            ("data_classes", "vocabulary", "data_classes"),
            ("workspace_roots", "path", "workspace_roots"),
            ("approved_destinations", "opaque_ref", "destinations"),
            ("access_intents", "vocabulary", "access_intent"),
        ):
            with self.subTest(field=field):
                self.assertIn(field, REQUEST_FIELDS)
                self.assertEqual(classes[field], expected_class)
                self.assertIn(axis, axes)
        # Which class the two scans read is pinned by the revision, for the
        # same reason `field_classes` is: pointing either at the path class
        # would deny ordinary work, and that must not change silently.
        self.assertEqual(profile["secret_shape_field_classes"], ["opaque_ref"])
        self.assertEqual(profile["prohibited_content_field_classes"], ["opaque_ref"])
        self.assertEqual(profile["destination_fields"], ["remote_targets", "approved_destinations"])
        mutated = safety_rule_profile()
        mutated["prohibited_content_field_classes"] = ["path"]
        self.assertNotEqual(safety_profile_digest(mutated), safety_profile_revision())

    def test_read_and_write_are_declarations_that_no_rule_denies_on_their_own(self) -> None:
        """Stated so the reader is not misled about what is enforced.

        Read and write stay inside the workspace, where `workspace_roots` and
        the path rules are the whole boundary. Only the share axis leaves the
        workspace, so only the share axis carries an intent denial.
        """
        for intents in (["read"], ["write"], ["read", "write"]):
            with self.subTest(intents=intents):
                self.assertEqual(evaluate_safety_preflight(request(access_intents=intents))["status"], "allow")


class BoundaryDeterminismTests(unittest.TestCase):
    def test_the_same_boundary_request_yields_the_same_decision_byte_for_byte(self) -> None:
        candidates = (
            request(workspace_roots=["src"], target_paths=["src/a.py"]),
            request(workspace_roots=["docs"], target_paths=["src/a.py"]),
            sharing_request(),
            request(data_classes=["personal_data"]),
            request(access_intents=["share"]),
        )
        for index, candidate in enumerate(candidates):
            with self.subTest(index=index):
                first = json.dumps(evaluate_safety_preflight(candidate), sort_keys=True)
                for _ in range(5):
                    self.assertEqual(json.dumps(evaluate_safety_preflight(candidate), sort_keys=True), first)
                self.assertEqual(json.dumps(evaluate_safety_preflight(dict(candidate)), sort_keys=True), first)
                self.assertIn(f'"safety_profile_revision": "{safety_profile_revision()}"', first)


class EnforcementFactsTests(unittest.TestCase):
    """OMH labels which limits the selected host can enforce."""

    def facts(self) -> dict[str, object]:
        return data_boundary_enforcement_facts()

    def test_the_facts_cover_every_declared_limit_exactly_once(self) -> None:
        facts = self.facts()
        self.assertEqual(facts["schema_version"], DATA_BOUNDARY_ENFORCEMENT_SCHEMA_VERSION)
        limits = facts["limits"]
        self.assertEqual([entry["limit"] for entry in limits], list(DATA_BOUNDARY_LIMIT_NAMES))
        self.assertEqual(len(set(DATA_BOUNDARY_LIMIT_NAMES)), len(DATA_BOUNDARY_LIMIT_NAMES))
        for entry in limits:
            with self.subTest(limit=entry["limit"]):
                self.assertIn(entry["enforcement_kind"], DATA_BOUNDARY_ENFORCEMENT_KINDS)

    def test_an_enforced_limit_names_an_enforcer_and_an_unenforced_one_names_a_blocker(self) -> None:
        """The anti-decoration rule `action_gate` applies, applied to these facts."""
        for entry in self.facts()["limits"]:
            with self.subTest(limit=entry["limit"]):
                if entry["enforced_here"]:
                    self.assertTrue(entry["enforced_by"])
                    self.assertEqual(entry["blocked_by"], "")
                else:
                    self.assertEqual(entry["enforced_by"], [])
                    self.assertTrue(str(entry["blocked_by"]).strip())

    def test_every_named_enforcer_is_a_symbol_a_reader_can_open(self) -> None:
        import importlib

        for entry in self.facts()["limits"]:
            for symbol in entry["enforced_by"]:
                with self.subTest(symbol=symbol):
                    self.assertTrue(symbol.startswith("omh."))
                    self.assertGreaterEqual(symbol.count("."), 2)
                    module_name, _, attribute = symbol.rpartition(".")
                    module = importlib.import_module(module_name)
                    self.assertTrue(hasattr(module, attribute), symbol)

    def test_refused_before_handoff_limits_hold_on_every_host(self) -> None:
        """No host and no executor is involved, so there is nothing for a host to lack."""
        for entry in self.facts()["limits"]:
            if entry["enforcement_kind"] == "refused_before_handoff":
                with self.subTest(limit=entry["limit"]):
                    self.assertTrue(entry["host_can_enforce"])
                    self.assertTrue(entry["enforced_here"])

    def test_a_host_confinement_limit_is_unenforced_and_says_which_kind_of_unenforced(self) -> None:
        """The genuine per-host difference: which blocker stands in the way.

        A host with a confinement backend still needs a dispatch-specific
        filesystem probe receipt (and fanout deliberately preserves network
        access); a host with none names that capability boundary instead.
        """
        facts = self.facts()
        entries = [entry for entry in facts["limits"] if entry["enforcement_kind"] == "host_confinement"]
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(limit=entry["limit"]):
                self.assertFalse(entry["enforced_here"])
                self.assertEqual(entry["host_can_enforce"], facts["host_confinement_available"])
                expected = (
                    {
                        "runtime_filesystem_confinement": "no_observed_fanout_filesystem_confinement_probe_receipt",
                        "runtime_network_confinement": "fanout_lane_does_not_request_network_confinement",
                    }[entry["limit"]]
                    if facts["host_confinement_available"]
                    else facts["host_confinement_unavailable_reason"]
                )
                self.assertEqual(entry["blocked_by"], expected)

    def test_no_data_boundary_blocker_names_the_workspace_binding_issue(self) -> None:
        """#820 shipped a workspace reservation, not an executor sandbox.

        All three unenforced rows used to cite it. That was a mis-citation even
        before the issue landed -- placing a dispatched executor under the
        adapter lane's sandbox was never in its scope -- and it became a
        dangling pointer once it closed. A blocker names a ticket only when
        landing that ticket would close it, which is the rule
        `action_gate.ACCOUNT_AUTHORIZATION_BLOCKER` already follows.
        """
        for entry in self.facts()["limits"]:
            with self.subTest(limit=entry["limit"]):
                self.assertNotIn("#820", str(entry["blocked_by"]))

    def test_an_advisory_limit_is_enforced_on_no_host(self) -> None:
        for entry in self.facts()["limits"]:
            if entry["enforcement_kind"] == "advisory":
                with self.subTest(limit=entry["limit"]):
                    self.assertFalse(entry["host_can_enforce"])
                    self.assertFalse(entry["enforced_here"])

    def test_the_backend_answer_agrees_with_the_lane_that_builds_the_sandbox(self) -> None:
        """One answer to "which backend", probed twice rather than invented twice."""
        from omh.quality.cross_harness_adapter_sandbox import backend, backend_available

        facts = self.facts()
        selected = str(facts["host_confinement_backend"])
        self.assertEqual(selected, backend("auto"))
        if facts["host_confinement_available"]:
            # Availability here is at least as strict as the lane's own check:
            # the Linux half additionally requires a trusted binary on disk.
            self.assertTrue(backend_available(selected))
        else:
            self.assertTrue(str(facts["host_confinement_unavailable_reason"]).strip())

    def test_each_platform_branch_is_probed_rather_than_assumed(self) -> None:
        """All three answers, proved on one host so none of them is folklore.

        The unsupported branch is what a Windows runner really takes; the two
        Linux branches are the difference between "bwrap is the backend here"
        and "bwrap is the backend here and is actually installed".
        """
        import omh.quality.safety_preflight as module

        with mock.patch("sys.platform", "sunos5"):
            unsupported = module.data_boundary_enforcement_facts()
        self.assertEqual(unsupported["host_confinement_backend"], "unsupported")
        self.assertFalse(unsupported["host_confinement_available"])
        self.assertEqual(
            unsupported["host_confinement_unavailable_reason"], "no_os_confinement_backend_on_this_platform"
        )
        for entry in unsupported["limits"]:
            if entry["enforcement_kind"] == "host_confinement":
                with self.subTest(limit=entry["limit"]):
                    self.assertFalse(entry["host_can_enforce"])
                    self.assertEqual(entry["blocked_by"], "no_os_confinement_backend_on_this_platform")

        with mock.patch("sys.platform", "linux"), mock.patch.object(module, "_trusted_bwrap_present", lambda: False):
            untrusted = module.data_boundary_enforcement_facts()
        self.assertEqual(untrusted["host_confinement_backend"], "bwrap")
        self.assertFalse(untrusted["host_confinement_available"])
        self.assertEqual(untrusted["host_confinement_unavailable_reason"], "bwrap_absent_or_untrusted")

        with mock.patch("sys.platform", "linux"), mock.patch.object(module, "_trusted_bwrap_present", lambda: True):
            trusted = module.data_boundary_enforcement_facts()
        self.assertTrue(trusted["host_confinement_available"])
        self.assertEqual(trusted["host_confinement_unavailable_reason"], "")

        with mock.patch("sys.platform", "darwin"), mock.patch("os.path.exists", return_value=False):
            missing = module.data_boundary_enforcement_facts()
        self.assertEqual(missing["host_confinement_backend"], "sandbox-exec")
        self.assertFalse(missing["host_confinement_available"])
        self.assertEqual(missing["host_confinement_unavailable_reason"], "sandbox_exec_absent")

    def test_no_platform_answer_moves_the_pinned_revision(self) -> None:
        import omh.quality.safety_preflight as module

        live = safety_profile_revision()
        for platform in ("darwin", "linux", "win32", "sunos5"):
            with self.subTest(platform=platform), mock.patch("sys.platform", platform):
                self.assertEqual(module.safety_profile_revision(), live)

    def test_the_facts_are_stable_within_a_host(self) -> None:
        first = json.dumps(self.facts(), sort_keys=True)
        for _ in range(3):
            self.assertEqual(json.dumps(self.facts(), sort_keys=True), first)

    def test_the_per_host_answer_is_not_part_of_the_pinned_revision(self) -> None:
        """A host-dependent digest would read as drift on every second machine."""
        profile = safety_rule_profile()
        encoded = json.dumps(profile, sort_keys=True)
        for key in ("host_confinement_backend", "host_confinement_available", "enforced_here", "host_can_enforce"):
            self.assertNotIn(key, encoded)
        self.assertEqual(
            profile["data_boundary_limits"],
            [
                {"limit": limit, "enforcement_kind": kind, "enforced_by": list(symbols), "blocked_by": blocker}
                for limit, kind, symbols, blocker in DATA_BOUNDARY_LIMITS
            ],
        )
        self.assertEqual(safety_profile_digest(profile), safety_profile_revision())


class DelegationLaneBoundaryTests(unittest.TestCase):
    """The boundary the chat delegation lane actually declares."""

    CODING = "implement pagination in src/routing/chat.py and add unit tests"

    def test_the_lane_declares_its_data_classes_intents_and_boundary_halves(self) -> None:
        prepared = _safety_preflight_request(
            self.CODING,
            owner="codex",
            workflow="plan",
            message_context_mode="full",
            raw_content_included=True,
            intent="coding",
            action="delegate",
        )
        self.assertEqual(prepared["data_classes"], ["workspace_metadata", "workspace_source", "user_request_text"])
        self.assertEqual(prepared["access_intents"], ["read", "write"])
        self.assertEqual(prepared["workspace_roots"], [])
        self.assertEqual(prepared["approved_destinations"], [])
        self.assertEqual(prepared["target_paths"], ["src/routing/chat.py"])
        self.assertLessEqual(set(prepared), set(REQUEST_FIELDS))
        self.assertEqual(evaluate_safety_preflight(prepared)["status"], "allow")

    def test_the_lane_never_declares_a_prohibited_class_or_the_share_intent(self) -> None:
        for intent, action, expected in (
            ("coding", "delegate", ["read", "write"]),
            ("review", "delegate", ["read"]),
            ("coding", "clarify", ["read"]),
            ("research", "delegate", ["read"]),
        ):
            with self.subTest(intent=intent, action=action):
                prepared = _safety_preflight_request(
                    self.CODING,
                    owner="codex",
                    workflow="plan",
                    message_context_mode="bounded",
                    raw_content_included=False,
                    intent=intent,
                    action=action,
                )
                self.assertEqual(prepared["access_intents"], expected)
                self.assertNotIn("share", prepared["access_intents"])
                self.assertEqual(set(prepared["data_classes"]) & set(PROHIBITED_DATA_CLASSES), set())
                self.assertEqual(evaluate_safety_preflight(prepared)["status"], "allow")

    def test_a_message_with_no_named_file_declares_no_workspace_source(self) -> None:
        prepared = _safety_preflight_request(
            "add a caching layer and unit tests",
            owner="codex",
            workflow="plan",
            message_context_mode="bounded",
            raw_content_included=False,
            intent="coding",
            action="delegate",
        )
        self.assertEqual(prepared["target_paths"], [])
        self.assertEqual(prepared["data_classes"], ["workspace_metadata"])

    def test_ordinary_coding_work_is_still_not_denied(self) -> None:
        """The exact class that broke when the preflight first landed.

        Filenames carrying `token`, `authorization`, `credential`, `bearer`,
        and a pasted repository URL. Each one was denied once, and each one has
        to survive every later rule added to this evaluator.
        """
        for message in (
            "refactor src/auth/token_store.py to use a shared cache and add unit tests",
            "fix the failing unit tests in tests/test_authorization_headers.py",
            "refactor src/api/credentials_loader.py error handling and add unit tests",
            "add tests for lib/tokenizer.py",
            "fix the bearer_channel.py backpressure bug",
            "implement pagination in src/routing/chat.py and add unit tests",
            "implement pagination in "
            "https://github.com/rlaope/oh-my-hermes/blob/main/src/routing/chat.py and add unit tests",
            "implement pagination in src/routing/chat.py, see "
            "https://github.com/rlaope/oh-my-hermes/blob/main/src/routing/chat.py, and add unit tests",
        ):
            with self.subTest(message=message):
                gate = build_coding_delegation_payload(message, executor_target="codex")["action_gate"]
                self.assertEqual(gate["outcome"], "allow", gate.get("denial"))

    def test_an_out_of_workspace_path_is_still_denied_end_to_end(self) -> None:
        gate = build_coding_delegation_payload("refactor /etc/passwd.py now", executor_target="codex")["action_gate"]
        self.assertEqual(gate["outcome"], "deny")
        self.assertEqual(gate["denial"]["rule_id"], "target_paths_bounded")
        self.assertIn("target_path_absolute", gate["denial"]["reason_codes"])

    def test_the_boundary_introduces_no_second_allowed_targets_list(self) -> None:
        """The #820 desync this change deliberately did not create.

        `action_gate._allowed_targets_for` already derives the symbolic target
        from the isolation plan and equality-checks it into the contract. The
        workspace boundary is expressed as bounded roots on the preflight
        request instead, where the path rules already refuse an escape, so
        there is one answer to "which target" rather than two that can
        disagree. Declaring roots here as well would have been the second one.
        """
        payload = build_coding_delegation_payload(self.CODING, executor_target="codex")
        envelope = payload["action_gate"]["authority_envelope"]
        # #954 stage 5: the bounded implementation message now routes to
        # `ultrawork`, whose isolation plan prepares a worktree, so the
        # envelope derives both symbolic targets from the one plan.
        self.assertEqual(envelope["allowed_targets"], ["current_workspace", "isolated_worktree"])
        prepared = _safety_preflight_request(
            self.CODING,
            owner="codex",
            workflow="plan",
            message_context_mode="bounded",
            raw_content_included=False,
            intent="coding",
            action="delegate",
        )
        self.assertEqual(prepared["workspace_roots"], [])
        self.assertNotIn("allowed_targets", prepared)


if __name__ == "__main__":
    unittest.main()

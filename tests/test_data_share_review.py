from __future__ import annotations

import unicodedata
import unittest

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.awareness import (
    _ROUTE_HINT_RULES,
    _data_share_awareness_marked,
    awareness_context_matches_message,
    awareness_route_hint,
)
from omh.plugin_bundle.omh.data_share_cues import (
    DATA_SHARE_REVIEW_KOREAN_PHRASES,
    DATA_SHARE_REVIEW_PHRASES,
    data_share_phrases_said,
    data_share_request_admitted,
)
from omh.routing.localization import normalized_phrase, routing_tokens
from omh.routing.recommend import _SKILL_OFFERS_ITSELF, recommend_skills
from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.wrapper.contract import build_chat_interaction_payload

SKILL = "data-share-review"
REFERENCE_PATH = "references/data-share-method.md"


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


def _route(message: str) -> dict[str, object]:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _body() -> str:
    return next(template.content for template in builtin_skill_templates() if template.name == SKILL)


def _reference() -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == SKILL and template.relative_path == REFERENCE_PATH
    )


def _offered(message: str) -> bool:
    query = normalized_phrase(message)
    return _SKILL_OFFERS_ITSELF[SKILL](query, routing_tokens(query))


class DataShareReviewCatalogTests(unittest.TestCase):
    """A file leaving the team is redacted only after an observed scan of what leaves."""

    def test_each_named_output_has_one_expectation(self) -> None:
        mine = _definition(SKILL)
        self.assertEqual(
            mine.expected_outputs,
            ("field_inventory/v1", "minimization_plan/v1", "residual_scan/v1", "share_record/v1"),
        )
        for schema in mine.expected_outputs:
            with self.subTest(schema=schema):
                self.assertEqual(len([line for line in mine.artifact_expectations if line.startswith(schema)]), 1)

    def test_the_triggers_are_the_routed_phrases(self) -> None:
        self.assertEqual(_definition(SKILL).triggers, DATA_SHARE_REVIEW_PHRASES)

    def test_redacted_needs_an_observed_scan_of_the_file_that_leaves(self) -> None:
        mine = _definition(SKILL)
        self.assertEqual(
            mine.safety_rules[0],
            "Call the output redacted only after an observed residual scan of the exact file that leaves, counted per "
            "class; without one the state is not_observed, whatever the masking step reported.",
        )
        scan = next(line for line in mine.artifact_expectations if line.startswith("residual_scan/v1"))
        self.assertEqual(
            scan,
            "residual_scan/v1 records, for the exact file that leaves, the scan method and an observed count per class "
            "with zero hits or each remaining hit accepted by name, its sha256 of the scanned bytes, the free-text "
            "sample the reviewer read, and its verdict: redacted, not redacted with the counts while a hit remains "
            "unaccepted, or not_observed when no scan ran, no free-text sample was read or its digest differs from "
            "the share record's",
        )

    def test_the_mapping_stays_local_and_the_record_holds_no_value(self) -> None:
        mine = _definition(SKILL)
        self.assertIn(
            "Keep the pseudonym mapping local, outside the shipped file and its folder; a mapping that travels with "
            "the data reverses it.",
            mine.safety_rules,
        )
        record = next(line for line in mine.artifact_expectations if line.startswith("share_record/v1"))
        self.assertEqual(
            record,
            "share_record/v1 is metadata only -- destination, date, fields shipped, row count, the sha256 digest of "
            "the shipped file, and its data_state (pseudonymized, still personal data, when identifiers were "
            "pseudonymized) -- and holds no value from it",
        )

    def test_rows_are_read_only_when_shape_counts_leave_a_field_unclear(self) -> None:
        self.assertIn(
            "- Inventory fields from the header and the schema, read with `read_file` and its line limit; when a "
            "field's class is unclear, prefer a script that prints per-column shape counts, and read a row only when "
            "that still leaves it unclear, because every row read enters the session.",
            _body(),
        )
        self.assertIn(
            "Run it as a script that reads the source column and the output file and prints one count; never type a "
            "value into a search pattern, which puts it into the session.",
            _reference(),
        )

    def test_a_scan_prints_counts_and_its_error_output_returns_too(self) -> None:
        body = _body()
        self.assertIn(
            "- A scan prints counts, never matched values; a hit printed to the session reaches the model provider "
            "the same way the raw file would.",
            body,
        )
        self.assertIn(
            "- Count each class with `search_files` in its `count` output mode, or with a detector script run "
            "through `execute_code` when `execute_code` is in your tool list or tool_search finds it; its stdout "
            "returns, and so do stderr and any traceback, so it prints counts only and catches its own errors without "
            "echoing a value. With neither, hand the user the scan to run and keep the verdict not_observed until the "
            "counts come back.",
            body,
        )

    def test_hermes_native_redaction_is_stated_as_not_this_scan(self) -> None:
        self.assertIn(
            "- Hermes' `privacy.redact_pii` hashes user and chat identifiers in the gateway's session prompt on the "
            "platforms that allow it, and `security.redact_secrets` masks secret-shaped strings in tool output; "
            "neither changes a file that leaves, so neither is this scan.",
            _body(),
        )
        self.assertIn(
            "Neither edits a file on disk or a file that leaves, so neither replaces the scan in section 4.",
            _reference(),
        )

    def test_the_reference_classes_and_scan_rows_cover_the_same_classes(self) -> None:
        reference = _reference()
        classes = reference.split("## 1. Field classes", 1)[1].split("## 2.", 1)[0]
        scan = reference.split("## 4. Residual scan", 1)[1].split("## 5.", 1)[0]

        def first_cells(section: str) -> list[str]:
            rows = [line for line in section.splitlines() if line.startswith("| ") and "---" not in line]
            return [row.strip("|").split("|")[0].strip() for row in rows[1:]]

        self.assertEqual(
            first_cells(classes),
            ["direct identifier", "quasi-identifier", "secret", "free text", "sensitive category", "not personal"],
        )
        self.assertEqual(first_cells(scan), ["direct identifier", "secret", "quasi-identifier", "sensitive category", "free text"])
        self.assertIn(REFERENCE_PATH, _body())

    def test_the_reference_and_the_why_use_the_skills_own_words(self) -> None:
        # A state or a sibling the model cannot use is a pointer it cannot follow.
        self.assertIn(
            "OMH prepares; the scan runs where the user or the session's tools run, and the file's verdict stays "
            "`not_observed` until its scan counts are observed.",
            _reference(),
        )
        self.assertNotIn("`prepared`", _reference())
        self.assertIn(
            "`omh-security-safety-review` reviews an agent's own exposure, and `omh-legal-compliance-review` reads "
            "the obligations",
            _body(),
        )

    def test_siblings_are_named_once_each_and_legal_points_back(self) -> None:
        mine = _definition(SKILL).do_not_use_when
        for other in (
            "legal-compliance-review",
            "security-safety-review",
            "data-analysis",
            "github-issue-intake",
            "model-finetuning",
            "support-operations",
        ):
            with self.subTest(sibling=other):
                self.assertEqual(len([text for text in mine if f"`{other}`" in text]), 1)
        back = [text for text in _definition("legal-compliance-review").do_not_use_when if f"`{SKILL}`" in text]
        self.assertEqual(
            back,
            [
                "Redact the PII in the file itself and scan it before sending it, once sharing it is cleared; use "
                "`data-share-review`."
            ],
        )


class DataShareReviewRoutingTests(unittest.TestCase):
    """Conservative by design: the skill takes nothing another skill holds."""

    def test_a_protective_lead_on_a_file_leaving_dispatches_here(self) -> None:
        for message in INTERVENTIONS:
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], SKILL)

    def test_the_same_words_elsewhere_do_not_dispatch_it(self) -> None:
        for message in NEGATIVES:
            with self.subTest(message=message):
                route = _route(message)
                self.assertNotEqual(route["action"], "dispatch")
                self.assertNotEqual(route.get("candidate_skill"), SKILL)

    def test_a_request_another_skill_holds_stays_there(self) -> None:
        for message, owner in OWNERS:
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], owner)

    def test_two_owners_with_a_phrase_each_ask_instead_of_dispatching(self) -> None:
        route = _route("pseudonymize the customer ids in this dataset before it goes into the fine-tune corpus")
        self.assertEqual(route["action"], "clarify")
        self.assertEqual(route["candidate_skill"], SKILL)

    def test_only_an_inherently_protective_lead_admits_the_skill(self) -> None:
        for message, offered in (
            ("redact pii from this csv before sending to the vendor", True),
            ("pseudonymize the customer ids before the vendor gets the export", True),
            ("anonymize the dataset before we upload it to the provider", True),
            ("hey, redact personal data from the spreadsheet before it goes to the contractor", True),
            ("can you de-identify this export for the researcher", True),
            # Every courtesy opener the other readers strip is stripped here
            # too (`request_lead`); before, only "hey," of these was.
            ("hi, redact pii from this csv before sending to the vendor", True),
            ("pls redact pii from this csv before sending to the vendor", True),
            ("kindly redact pii from this csv before sending to the vendor", True),
            ("would you redact pii from this csv before sending to the vendor", True),
            ("hermes, redact pii from this csv before sending to the vendor", True),
            ("hey hermes, de-identify this export for the researcher", True),
            # An everyday verb, a later clause, or another job leads.
            ("strip the pii from this dataset before we send it to an external contractor", False),
            ("take the customer names out of the export before sending it to the vendor", False),
            ("we need to share a ticket export with a vendor, redact the pii first", False),
            ("review the export before we share it with the vendor and redact the pii", False),
            ("scan the export for pii before sharing it with the vendor", False),
            ("write a blog post about the export, then redact the pii before we share the file with the vendor", False),
            # A sentence that opens in Hangul has no Latin lead.
            ("깃허브 이슈 라벨 달아줘, 제목: redact the pii from the export before sending to the vendor", False),
        ):
            with self.subTest(message=message):
                self.assertIs(_offered(message), offered)

    def test_the_lead_verbs_object_must_be_data(self) -> None:
        for message, offered in (
            ("redact the customer names in the export before sending it to the vendor", True),
            ("redact the pii redaction label from the export before sending it to the vendor", False),
            ("pseudonymize the export script before we share the file with the vendor", False),
            ("redact the header row from the csv before we send it to the vendor", False),
        ):
            with self.subTest(message=message):
                self.assertIs(_offered(message), offered)

    def test_a_defined_lead_verb_or_a_question_is_not_a_command(self) -> None:
        for message, offered in (
            ("de-identify this export for the researcher", True),
            ("de-identify means what exactly, before we send the file to the researcher?", False),
            ("de-identify is the term we use in the guide; write a page on how we send files to vendors", False),
            ("redact stands for removing text, so redact the export before sending it to the vendor", False),
            ("pseudonymize refers to replacing ids in the export we send the vendor", False),
            ("redact the pii in this export before sending it to the vendor?", False),
        ):
            with self.subTest(message=message):
                self.assertIs(_offered(message), offered)

    def test_a_carrier_and_a_recipient_must_both_be_present(self) -> None:
        for message, offered in (
            ("redact the pii in the export and hand it over to the vendor", True),
            ("redact the pii in this spreadsheet before I give it to the contractor", True),
            # No carrier: a sample is as often a sample message.
            ("redact the pii from the sample before we send it to the vendor", False),
            # No recipient: by hand, back to me, or to me.
            ("redact the pii in the export by hand", False),
            ("pseudonymize the user ids in this file and give it back to me", False),
            ("redact pii from this file and give me a summary", False),
            ("redact pii from this csv", False),
        ):
            with self.subTest(message=message):
                self.assertIs(_offered(message), offered)

    def test_a_legal_question_a_setting_or_a_storage_scan_withdraws_it(self) -> None:
        for message in (
            "pseudonymize this export for the vendor as gdpr requires",
            "redact pii in the export before hermes uploads it to the vendor",
            # Hermes named after the opener withdraws it whatever the opener.
            "hi, redact pii in the export before hermes uploads it to the vendor",
            "hermes, redact pii in the export before hermes uploads it to the vendor",
            "redact the pii in the files we share with vendors on s3",
            "redact pii across our shared files before the vendor audit",
            "redact pii in the export before sending it to the vendor, then turn on the gateway hashing",
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))

    def test_held_back_words_score_nothing_for_the_skill(self) -> None:
        # The sentence is admitted, so only the hold-back keeps "redact",
        # "pii", "data", "export" and "share" from crediting the skill one by
        # one; a finished state ("pseudonymized") is not its trigger either.
        recommendation = next(
            item
            for item in recommend_skills("redact the pii from the pseudonymized data export before we share it with the vendor")
            if item["skill"] == SKILL
        )
        single_word_credits = [
            label for label in recommendation["matched"] if label.startswith("trigger:") and " " not in label
        ]
        self.assertEqual(single_word_credits, [])

    def test_only_words_that_mean_nothing_else_stay_creditable(self) -> None:
        from omh.routing.recommend import _tokens, held_back_trigger_tokens

        creditable = _tokens(" ".join(_definition(SKILL).triggers)) - held_back_trigger_tokens(SKILL)
        self.assertEqual(
            creditable,
            {
                "de-identify", "de-identifying", "deidentify", "pseudonymisation", "pseudonymise", "pseudonymization",
                "pseudonymize", "pseudonymizing", "quasi-identifier", "quasi-identifiers",
            },
        )

    def test_the_route_hint_needs_the_same_lead(self) -> None:
        def hinted(message: str) -> bool:
            return any(hint.get("workflow") == SKILL for hint in awareness_route_hint(message).get("hints", []))

        self.assertTrue(hinted("redact pii from this csv before sending to the vendor"))
        self.assertTrue(hinted("pseudonymize the emails in customers.csv before I share it with the agency"))
        # The hint reads the router's own trigger table. Before, a smaller one
        # gave this sentence source-finder's hint while the router dispatched
        # it here; and nothing armed awareness for it on a later turn.
        message = "anonymize the dataset before we upload it to the provider"
        self.assertEqual((_route(message)["action"], _route(message)["selected_skill"]), ("dispatch", SKILL))
        self.assertTrue(hinted(message))
        self.assertTrue(awareness_context_matches_message(message))
        rule = next(rule for rule in _ROUTE_HINT_RULES if rule["id"] == "data_share_review")
        self.assertIs(rule["phrases"], DATA_SHARE_REVIEW_PHRASES)
        # The spaced name is no invocation on either surface; the hyphenated
        # name is one on both.
        self.assertFalse(hinted("data share review"))
        self.assertNotIn(SKILL, (_route("data share review").get("selected_skill"), _route("data share review").get("candidate_skill")))
        self.assertTrue(hinted("data-share-review"))
        self.assertEqual(_route("data-share-review")["selected_skill"], SKILL)
        for message in (
            # Admitted, but "pseudonymized" is a finished state, not the token cue.
            "redact the names in the pseudonymized export before sending it to the vendor",
            "strip the pii from this dataset before we send it to an external contractor",
            "run churn analysis on the pseudonymized dataset",
            "does gdpr require us to pseudonymize customer data",
            "close the github issue titled redact pii from logs",
            "how do I enable redact pii in hermes",
            "send a slack message saying the export file is ready to share once we redact pii",
            "de-identify means what exactly, before we send the file to the researcher?",
            "de-identify is the term we use in the guide; write a page on how we send files to vendors",
        ):
            with self.subTest(message=message):
                self.assertFalse(hinted(message))


INTERVENTIONS = (
    "de-identify this csv of patient records before the model provider sees it",
    "de-identify this export for the researcher",
)
NEGATIVES = (
    "what does pii stand for",
    "does gdpr require us to pseudonymize customer data",
    "our privacy policy says we redact pii from logs, is that gdpr compliant",
    "strip pii from our logging pipeline going forward",
    "the movie is a redacted version of the original cut",
    "share this doc with my team",
    "mask the background in this photo",
    "run churn analysis on the pseudonymized dataset",
    "write a python function to redact pii from strings",
    "how do I enable redact pii in hermes",
    "scan for pii in our s3 buckets",
    "send a slack message to the data team asking who owns pii redaction",
    "remove personal data from my google account",
    "explain de-identify versus anonymize",
    "is an ip address pii",
    "pii",
    "send the customer details out to the vendor in the export file",
    "get the personal details out to the contractor in the spreadsheet",
    "go ahead and merge the pr that adds pii redaction to the export file before sending to the vendor",
    "review the pull request that adds pii redaction to the files we send vendors",
    "tell the data team on slack that we will strip the pii from the export before the vendor gets it",
    "post a message in #privacy that we pseudonymize the csv before sharing with researchers",
    "write a blog post on how to strip pii from a dataset before sharing it with vendors",
    "translate this paragraph about how to redact pii from export files sent to vendors into korean",
    "schedule a calendar reminder to redact pii from the monthly export before it goes to the vendor",
    "watch this video about how to redact pii from log files before sharing them",
    "which vendor is best for pseudonymization of datasets shared with third party processors",
    "give me a sample message to tell the vendor we redact pii",
    "take the vendor names out of the export before sending it to the researcher",
    "remove pseudonymization from the export before sending it to the researcher, they need the real ids",
    "strip the de-identify flag from the csv before uploading it to the vendor",
    "review the pii redaction pull request before we send the export to the vendor",
    "check the log file for pii redaction bugs before sending it to the vendor",
    "merge the pr, then redact the pii in the export before sending it to the vendor",
    "de-identify means what exactly, before we send the file to the researcher?",
    "de-identify is the term we use in the guide; write a page on how we send files to vendors",
)
class DataShareReviewKoreanTests(unittest.TestCase):
    """A Korean request to protect data leaving the team reaches the review (KO-2); the same words elsewhere do not."""

    def _hinted(self, message: str) -> bool:
        return any(hint.get("workflow") == SKILL for hint in awareness_route_hint(message).get("hints", []))

    def _named(self, message: str) -> set[str]:
        route = _route(message)
        handoff = route.get("candidate_handoff") or {}
        return {
            str(route.get("selected_skill") or ""),
            str(route.get("candidate_skill") or ""),
            *(str(item.get("skill")) for item in route.get("recommendations", [])),
            *(str(item.get("skill")) for item in handoff.get("candidates", [])),
        }

    def test_a_korean_data_share_request_reaches_the_review(self) -> None:
        # The first dispatched gateway-intent-card on its "보내줘" and the
        # second asked about automation-blueprint: the review now scores its
        # personal-data phrase and its recipient, in either order of the two
        # clauses.
        for message in (
            "고객 정보 마스킹해서 벤더한테 보내줘",
            "개인정보 지우고 외부에 공유해줘",
            "벤더한테 보내기 전에 개인정보 마스킹해줘",
            "고객 데이터 익명화해서 연구자한테 보내줘",
            "개인정보 제거한 다음에 외부에 올려줘",
            "외부에 공유하기 전에 고객 정보 가려줘",
            # An address to Hermes before the request is its address, not a
            # Hermes setting.
            "헤르메스, 고객 정보 마스킹해서 벤더한테 보내줘",
            "헤르메스야 개인정보 지우고 외부에 공유해줘",
            # Asked as a question that is itself a request.
            "개인정보 마스킹해서 벤더한테 보내줄래?",
            "계약서에서 개인정보 지우고 거래처에 보내줘",
            # A protective verb's noun before "후", and the honorific send.
            "상담 기록 개인정보 마스킹 후 외부 업체에 전달해줘",
            "고객 명단 비식별화해서 외부 연구기관에 보내드려 줘",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", SKILL))
                self.assertTrue(self._hinted(message))
                self.assertTrue(_data_share_awareness_marked(message))

    def test_a_recipient_is_where_the_data_goes_only_as_a_destination(self) -> None:
        # The recipient alone carries the data out here: no verb sends it.
        for message in ("벤더한테 줄 파일에서 개인정보 지워줘", "외부 공유용으로 개인정보 지워줘"):
            with self.subTest(message=message):
                self.assertTrue(data_share_request_admitted(message))
                self.assertIn(SKILL, self._named(message))
                self.assertTrue(self._hinted(message))
        # A recipient's 로 before a verb that sends is a destination; a team
        # named after an outside word is outside.
        for message in ("개인정보 지우고 외부로 보내줘", "고객 정보 가려서 외부 연구팀에 공유해줘"):
            with self.subTest(message=message):
                self.assertTrue(data_share_request_admitted(message))
        # A source, a kind, or a word inside another is not a destination.
        for message in (
            "업체 목록에서 전화번호 삭제해줘",
            "거래처 주소록에서 퇴사자 연락처 삭제해줘",
            "외부 로그에서 개인정보 마스킹해줘",
            "해외부서 명단에서 개인정보 삭제해줘",
            "연구자 명단에서 전화번호 지워줘",
            # 로 before anything but a verb that sends names a means or a basis,
            # and a word that starts with a recipient is not one.
            "업체별로 고객 정보 마스킹해줘",
            "거래처별로 전화번호 삭제해줘",
            "외부키로 연결된 고객 정보 삭제해줘",
            "외부키에 연결된 고객 정보 삭제해줘",
            "벤더로 분류된 고객 정보 마스킹해줘",
            "업체명으로 정렬해서 고객 정보 마스킹해줘",
        ):
            with self.subTest(message=message):
                self.assertFalse(data_share_request_admitted(message))
                self.assertNotIn(SKILL, self._named(message))
                self.assertFalse(self._hinted(message))

    def test_a_later_send_and_a_finished_removal_count(self) -> None:
        # Only a future send carries the data out ("올릴"); only "지운 다음에"
        # protects it.
        for message in ("캐글에 올릴 데이터에서 개인정보 지워줘", "개인정보 지운 다음에 외부에 공유해줘"):
            with self.subTest(message=message):
                self.assertTrue(data_share_request_admitted(message))
                self.assertTrue(self._hinted(message))

    def test_the_same_words_elsewhere_name_no_review(self) -> None:
        for message in (
            # Shared, summarized, sent: nothing protected.
            "화면 공유해줘",
            "이 문서 요약해서 공유해줘",
            "회의록 팀에 공유해줘",
            "파일 보내줘",
            # A background masked, not personal data, even for a vendor; and
            # personal data said, but not as what is removed.
            "사진 배경 마스킹해서 보내줘",
            "사진 배경 마스킹해서 벤더한테 보내줘",
            "개인정보 들어간 사진에서 배경 지우고 벤더한테 보내줘",
            # Code, a feature, a policy, a setting: another job.
            "개인정보 마스킹하는 코드 짜줘",
            "개인정보 마스킹 기능 구현해줘",
            "개인정보 처리방침 검토해서 법무팀에 보내줘",
            "개인정보 마스킹 설정 켜줘",
            "개인정보 마스킹해서 법무팀에 보내줘",
            "개인정보 마스킹해서 법률 검토용으로 외부 업체에 보내줘",
            "개인정보 마스킹해서 PR 올려줘",
            # The request ends on another job.
            "개인정보 지우고 벤더 목록 정리해줘",
            "개인정보 지우고 외부에 공유하는 방법 알려줘",
            # Protected, but leaving for nowhere, or staying inside the team.
            "고객 개인정보 지워줘",
            "개인정보 마스킹해줘",
            "테스트 데이터에서 고객 정보 지우고 스테이징에 올려줘",
            "개인정보 지우고 팀원들한테 공유해줘",
            "고객 정보 마스킹해서 개발팀에 보내줘",
            "개인정보 지우고 QA팀한테 넘겨줘",
            "고객 정보 마스킹해서 테스트 서버에 올려줘",
            # Exported to a file or a folder: nothing leaves.
            "개인정보 지운 다음 엑셀로 내보내줘",
            "고객 정보 마스킹해서 CSV로 내보내줘",
            "고객 정보 지우고 백업 폴더로 내보내줘",
            # A field name alone is no phrase of the skill.
            "이름 지우고 공유해줘",
            # Already anonymized, or a question.
            "익명화된 데이터 벤더한테 보내줘",
            "개인정보 지우고 외부에 공유해도 돼?",
            # A negated clause is not the request.
            "벤더한테 보내지 말고 개인정보만 마스킹해줘",
            "개인정보 마스킹하지 말고 벤더한테 보내줘",
            # Labelled text is not the request.
            "사용자 발화 예시: 고객 정보 마스킹해서 벤더한테 보내줘",
        ):
            with self.subTest(message=message):
                self.assertNotIn(SKILL, self._named(message))
                self.assertFalse(self._hinted(message))
                # Folded as `awareness_context_matches_message` folds it.
                self.assertFalse(_data_share_awareness_marked(message.casefold()))

    def test_a_korean_phrase_inside_a_compound_is_read(self) -> None:
        # The router reads a Korean trigger by containment. Korean writes
        # compounds without a space, and the hint's whole-word reader found
        # neither phrase here, so the hint named nothing while the router
        # dispatched the review.
        message = "고객개인정보 지우고 협력업체에 공유해줘"
        self.assertEqual(data_share_phrases_said(message), ["개인정보", "업체"])
        self.assertEqual(data_share_phrases_said("pseudonymized export"), [])
        self.assertEqual((_route(message)["action"], _route(message)["selected_skill"]), ("dispatch", SKILL))
        self.assertTrue(self._hinted(message))

    def test_the_router_and_the_hint_admit_alike(self) -> None:
        for message in (
            "고객 정보 마스킹해서 벤더한테 보내줘",
            "벤더한테 보내기 전에 개인정보 마스킹해줘",
            "사진 배경 마스킹해서 보내줘",
            "이름 지우고 공유해줘",
            "업체 목록에서 전화번호 삭제해줘",
        ):
            with self.subTest(message=message):
                self.assertEqual(_offered(message), self._hinted(message))
        # A field name admits a request only beside one of the review's
        # phrases; alone, the rule itself refuses it.
        self.assertFalse(data_share_request_admitted("이름 지우고 공유해줘"))
        self.assertTrue(data_share_request_admitted("이름 지우고 외부에 공유해줘"))
        self.assertTrue(data_share_request_admitted("pii 마스킹해서 벤더한테 보내줘"))

    def test_an_admitted_korean_request_always_says_a_scored_phrase(self) -> None:
        for message in ("고객 정보 마스킹해서 벤더한테 보내줘", "데이터셋 가명 처리해서 업로드해줘"):
            with self.subTest(message=message):
                self.assertTrue(data_share_request_admitted(message))
                self.assertTrue(set(data_share_phrases_said(message)) & set(DATA_SHARE_REVIEW_KOREAN_PHRASES))
                score = next(item["score"] for item in recommend_skills(message, limit=50) if item["skill"] == SKILL)
                self.assertGreaterEqual(score, 6)


class DataShareReviewInternalDestinationTests(unittest.TestCase):
    """Owner decision 2026-10-16: data sent to a team inside the same company is internal, in English as in Korean.

    The gate fails safe: a place is inside only when every word of it is
    proven inside. Any other word keeps the review.
    """

    def _hinted(self, message: str) -> bool:
        return any(hint.get("workflow") == SKILL for hint in awareness_route_hint(message).get("hints", []))

    def _named(self, message: str) -> bool:
        route = _route(message)
        return SKILL in (route.get("selected_skill"), route.get("candidate_skill")) or SKILL in (
            item.get("skill") for item in route.get("recommendations", [])
        )

    def test_a_send_to_a_place_proven_inside_names_no_review(self) -> None:
        for message in (
            "redact pii in the export before we send it to the dev team",
            "anonymize the dataset before sharing it with the marketing team",
            "redact pii in the csv before sending it to qa",
            "redact the logs before uploading them to staging",
            "de-identify the records before we upload the file to the test server",
            "redact pii from this csv before sending it to my coworker",
            "anonymize the export and share it with a colleague",
            "pseudonymize the email addresses in the dataset before sharing it with another department",
            "redact personal data from the spreadsheet before sending it to the internal analytics team",
            "anonymize the logs before we share them with the in-house data team",
            "redact pii in the export and hand it over to our security team",
            "de-identify this csv before I give it to the qa team",
            "redact the pii in the export before sharing it with my teammates",
            "de-identify the export before posting it to the internal wiki",
            "redact pii in the export and upload it to the in-house analytics tool",
            "redact pii from the records before sending them to a coworker in finance",
            "redact pii in the export, give me a summary, and send it to the dev team",
            "redact pii in the export and send it to the data team and the qa team",
            # The lead verb's object is the data, not a send ("email"), and its
            # containers and field names are closed words.
            "redact the email addresses in the export before we send it to the dev team",
            "redact the pii in the export for us and send it to the dev team",
            "redact the phone number column in the csv and send it to the dev team",
            "redact the logs before uploading them into staging",
            "redact the logs before uploading them onto the test server",
            # Every later verb that sends it on names an inside place too.
            *(
                f"redact pii in the export, send it to the dev team and {verb} it to the qa team"
                for verb in (
                    "cc", "email", "emailing", "forward", "forwarding", "give", "giving", "hand", "handing", "pass",
                    "passing", "transfer", "transferring",
                )
            ),
            # "give", "hand" and "pass" send nothing to the person themself;
            # with another first object, that object is the place.
            *(
                f"redact pii in the export, send it to the dev team and {verb} me a summary"
                for verb in ("give", "giving", "hand", "handing", "pass", "passing")
            ),
            "redact pii in the export, send it to the dev team and give us the summary",
            "redact pii in the export, send it to the dev team and give it back",
            "redact pii in the export, send it to the qa team and give the dev team a copy",
            "redact pii in the export, send it to the qa team and hand the dev team the export",
            "redact pii in the export, send it to the qa team and give the dev team access",
            "개인정보 지우고 동료한테 보내줘",
            "고객 정보 가명 처리해서 QA에 보내줘",
            "개인정보 가명 처리해서 다른 부서에 공유해줘",
            "개인정보 지우고 인사 부서에 보내줘",
            "개인정보 지우고 부서원들한테 공유해줘",
            "이메일 주소를 익명화해서 사내 슬랙 채널에 공유해줘",
            "개인정보 지우고 개발팀에 이메일로 보내줘",
            "고객 정보 마스킹해서 개발팀에 보내고 QA팀으로도 보내줘",
            "redact pii in the export and send it back to the dev team",
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
                self.assertFalse(self._hinted(message))
                self.assertFalse(_data_share_awareness_marked(message.casefold()))

    def test_any_word_not_proven_inside_keeps_the_review(self) -> None:
        # A company, a client, a possessive other than ours, a relative
        # clause, a place after "at", "of" or "via", a purpose, and a team with
        # no owner: none is proven inside, so the data leaves.
        for message in (
            "redact the pii in the export and send it to the vendor's team",
            "anonymize the dataset before sharing it with an external team",
            "pseudonymize the customer ids in the csv before sending it to the partner team at acme",
            "redact the pii in the files and share them with the client team",
            "redact the pii in the export before sharing it with the customer's team",
            "anonymize the dataset before sharing it with the partner's staging server",
            "redact pii in the export before we send it to the acme team",
            "redact pii in the export before we send it to acme's data team",
            "anonymize the dataset before sharing it with the hospital team",
            "redact pii in the export before we send it to the regulator's team",
            "redact pii in the export before we send it to the law firm's team",
            "anonymize the dataset before sharing it with the deloitte team",
            "redact pii in the export before we send it to the subcontractor team",
            "redact pii in the export before we send it to the department of health",
            "redact pii in the export before we send it to a former colleague who now works at acme",
            "anonymize the dataset before uploading it to the acme staging server",
            "redact pii in the export before we send it to the data team at acme",
            "redact pii in the export before we send it to the data team over at acme's office",
            "redact pii in the export before we upload it via acme's portal to the data team",
            "redact pii in the export and send it to the dev team for review",
            "redact pii in the export and send it to our team in seoul",
            "redact the pii in the files and share them with the whole team",
            "redact pii in the export and send it to the team",
            # Safe-direction disclosures: these may be internal, but nothing proves it.
            "anonymize the dataset before sharing it with the customer success team",
            "redact pii in the export and send it to my manager",
            "고객 정보 익명화해서 외부 팀에 공유해줘",
            "개인정보 마스킹해서 벤더 팀에 보내줘",
            "개인정보 지우고 외부팀에 보내줘",
            "개인정보 비식별화해서 벤더 테스트 서버에 올려줘",
            "개인정보 마스킹해서 외부 연구팀에 보내줘",
            "개인정보 지우고 벤더 쪽 팀에 보내줘",
            "전화번호 지우고 협력업체 보안팀에 전달해줘",
            "고객 정보 마스킹해서 은행 담당 부서에 보내줘",
            "고객 정보 마스킹해서 카드사 보안 부서에 보내줘",
            "고객 정보 마스킹해서 다른 회사 동료에게 보내줘",
            "고객 정보 마스킹해서 acme qa에 보내줘",
            "이메일 주소 지우고 acme 데이터팀에 보내줘",
            "개인정보 지우고 팀 전체에 공유해줘",
            "개인정보 지우고 고객지원팀에 보내줘",
            # Every word back to the clause's edge is read, however many, and
            # only a joined form of a verb the rule knows is an edge: a noun
            # that ends in 서 or 고 is read as part of the place.
            "고객 정보 마스킹해서 경찰서 보안팀에 보내줘",
            "고객 정보 마스킹해서 세무서 데이터팀에 보내줘",
            "고객 정보 마스킹해서 소방서 개발팀에 보내줘",
            "고객 정보 마스킹해서 물류창고 운영팀에 보내줘",
            "고객 정보 마스킹해서 창고 운영팀에 보내줘",
            "고객 정보 마스킹해서 삼성전자서 데이터팀에 보내줘",
            "고객 정보 마스킹해서 삼성하고 데이터팀에 보내줘",
            "개인정보 지우고 명단을 개발팀에 보내줘",
            "고객 정보 마스킹해서 은행 보안 개발 팀에 보내줘",
            "고객 정보 마스킹해서 은행 it 보안 개발 팀에 보내줘",
            "고객 정보 마스킹해서 삼성 데이터 분석 플랫폼 운영 팀에 보내줘",
            # Before the place, every word is closed too: "업체별로" (by
            # vendor) is no place, and no closed word either.
            "업체별로 정리한 고객 정보 마스킹해서 개발팀에 보내줘",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))
                self.assertTrue(self._hinted(message))

    def test_a_party_named_before_a_korean_place_keeps_the_review(self) -> None:
        # Korean names the data, and any party, before the place, so every
        # word outside the places and before the verb must be closed: data
        # containers and field names, a verb the rule knows, an inside place
        # word, a determiner or a softener.
        for message in (
            "보험사가 원하는 고객 엑셀 개인정보 마스킹해서 개발팀에 보내줘",
            "보험사가 원하는 고객 파일을 가명 처리해서 개발팀에 보내줘",
            "감사법인이 볼 자료에서 개인정보를 삭제하고 재무팀에 보내줘",
            "협력사용 파일 비식별화해서 QA팀에 올려줘",
            "보험사의 고객 파일 가명 처리해서 개발팀에 보내줘",
            "보험사를 위한 고객 파일 가명 처리해서 개발팀에 보내줘",
            "은행 제출용 고객 데이터 익명화해서 데이터팀에 보내줘",
            "삼성 고객 파일 가명 처리해서 개발팀에 보내줘",
            "외부 감사인이 볼 자료 개인정보 마스킹해서 재무팀에 보내줘",
            "대행사가 받을 고객 리스트 개인정보 지우고 마케팅팀에 공유해줘",
            "보험사랑 공유할 고객 파일 가명 처리해서 개발팀에 보내줘",
            "Acme가 받을 엑셀에서 개인정보 마스킹하고 개발팀에 공유해줘",
            "Acme's 고객 파일 가명 처리해서 개발팀에 보내줘",
            "the bank가 요청한 고객 명단 가명 처리해서 데이터팀에 보내줘",
            # After the place too.
            "개발팀에 보내기 전에 보험사가 원하는 고객 파일 가명 처리해줘",
            # A word that says whose records the data holds, with a particle,
            # is the party, as "the customer's" is in English.
            "고객의 개인정보 마스킹해서 개발팀에 보내줘",
            "고객용 엑셀 개인정보 마스킹해서 개발팀에 보내줘",
            "고객이 받을 파일 개인정보 지우고 QA팀에 올려줘",
            # Not right before a data word, it is the party too, as "the
            # customer and employee emails" is in English.
            "고객 및 직원 연락처 마스킹해서 인사팀에 보내줘",
            # A party word off the list, before a data word or owning one.
            "보험사 엑셀 개인정보 마스킹해서 개발팀에 보내줘",
            "은행의 고객 명단 개인정보 마스킹해서 데이터팀에 공유해줘",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))
                self.assertTrue(self._hinted(message))
                self.assertTrue(_offered(unicodedata.normalize("NFD", message)))
        for message in (
            "고객 엑셀에서 개인정보 마스킹해서 개발팀에 보내줘",
            "회원 명단 가명 처리해서 데이터팀에 공유해줘",
            "테스트 데이터에서 고객 정보 지우고 스테이징에 올려줘",
            "이 파일 개인정보 삭제하고 우리 팀에 공유해줘",
            "회원 DB 덤프에서 주민번호 삭제하고 개발서버에 올려줘",
            "고객 주소랑 전화번호 마스킹해서 개발팀에 보내줘",
            "고객 이름과 연락처 마스킹해서 QA팀에 보내줘",
            "회원 정보 좀 마스킹해서 개발팀에 보내줘",
            "해당 파일의 개인정보 삭제하고 데이터팀에 공유해줘",
            "고객데이터 익명화해서 개발팀에 보내줘",
            "내부용 파일 개인정보 지우고 개발팀에 보내줘",
            "개발용 데이터에서 개인정보 지우고 개발팀에 보내줘",
            "개발팀에 보낼 고객 파일 가명 처리해줘",
            "개인정보 마스킹 후 데이터팀에 공유해줘",
            "개인정보 마스킹 진행 후 개발팀에 보내줘",
            # "-기 전에" is a step, as "다음에" is, not a place.
            "개발팀에 보내기 전에 고객 정보 마스킹해줘",
            "스테이징에 올리기 전에 회원 데이터에서 개인정보 지워줘",
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
                self.assertFalse(self._hinted(message))
                self.assertFalse(_offered(unicodedata.normalize("NFD", message)))

    def test_every_korean_sentence_is_read(self) -> None:
        # A later sentence that sends, names a place outside, or names a party
        # acting keeps the review; one of remarks only says nothing about
        # where the data goes, and a later request read inside keeps it inside.
        for message in (
            "고객 정보 마스킹해서 개발팀에 보내줘. 보험사가 볼 거야.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 벤더한테도 보내줘.",
            "고객 정보 마스킹해서 개발팀에 보내줘. Acme가 검토할 거야.",
            "개인정보 지우고 QA팀에 올려줘. 그다음 은행에 넘겨줘.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 협력사에도 공유해줘.",
            "고객 정보 마스킹해줘. 그리고 벤더한테 보내줘.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 그리고 보험사가 원하는 형식으로 정리해줘.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 벤더한테도 보낼 거야.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 고객이 볼 거야.",
            "고객 정보 마스킹해줘. 벤더한테 줄 거야.",
            "고객 정보 마스킹해줘. 그리고 Acme에 보내줘.",
            # Each later sentence is read on its own: the request after a
            # remark names a party.
            "고객 정보 마스킹해서 개발팀에 보내줘. 감사합니다. 그리고 삼성 형식으로 정리해줘.",
            # An apostrophe opens no quote, on either fold: both surfaces read
            # the request, and its place outside.
            "고객 정보 마스킹해서 Acme's team에 보내줘. It's urgent.",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))
                self.assertTrue(self._hinted(message))
        for message in (
            "고객 정보 마스킹해서 개발팀에 보내줘. 급해요.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 고마워!",
            "개인정보 지우고 QA팀에 올려줘. 감사합니다.",
            "고객 정보 마스킹해서 개발팀에 보내줘. It's urgent.",
            "고객 정보 마스킹해서 개발팀에 보내줘. QA팀에도 공유해줘.",
            "고객 정보 마스킹해서 개발팀에 보내줘. 제가 확인할게요.",
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
                self.assertFalse(self._hinted(message))

    def test_a_korean_quote_reads_alike_on_both_folds(self) -> None:
        # The router passes Hangul decomposed and the hint composed; the Korean
        # reader finds the same quoted span in both.
        for message in ("'고객 정보' 마스킹해서 벤더한테 보내줘", "고객 정보 '마스킹'해서 개발팀에 보내줘"):
            with self.subTest(message=message):
                self.assertEqual(
                    data_share_request_admitted(unicodedata.normalize("NFD", message)),
                    data_share_request_admitted(message),
                )
        # A mark before a Latin letter closes no quote, so the request and its
        # recipient are read.
        for fold in ("NFC", "NFD"):
            with self.subTest(fold=fold):
                self.assertTrue(
                    data_share_request_admitted(unicodedata.normalize(fold, "'고객 정보 마스킹해서 벤더에 보내줘. it's urgent"))
                )

    def test_the_data_sent_may_be_described_between_a_send_and_its_to(self) -> None:
        # Between a send and its "to" stand only closed words, read as the
        # span before the first send is: the data, also as protected, counted
        # or the version the redaction made, a party word right before a
        # container, the verb's particle, how it goes, and remarks.
        for message in (
            "Anonymize the dataset and share the anonymized copy with the data team.",
            "Pseudonymize the user IDs and share the pseudonymized dataset with the analytics team.",
            "Redact the logs and upload the redacted logs to staging.",
            "De-identify the records and send the de-identified records to my colleague.",
            "Redact the PII in the export and send the clean export to the dev team.",
            "Redact the PII in the export and send the cleaned file to the dev team.",
            "Redact the PII in the logs and upload the sanitized logs to staging.",
            "Redact the PII in the export and send the masked export to the dev team.",
            "Redact the PII in the export and send the whole export to the dev team.",
            "Redact the PII in the export and send both files to the dev team.",
            "Redact the PII in the export and send all of it to the dev team.",
            "Redact the PII in the export and send the result to the dev team.",
            "Redact the PII in the export and send the output to the dev team.",
            "Redact the PII in the export and send the updated file to the dev team.",
            "Redact the PII in the export and send the final CSV to the dev team.",
            "Redact the PII in the export and send the new version to the dev team.",
            "Redact the PII in the export and send the user export to the dev team.",
            "Redact the PII in the export and send the customer export to the dev team.",
            "Redact the PII in the export and send it straight to the dev team.",
            "Redact the PII in the export and send it directly to the dev team.",
            "Redact the PII in the export and send it back to the dev team.",
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
                self.assertFalse(self._hinted(message))
        # Any other word there may name who receives it.
        for message in (
            "Redact the PII in the export and send the Acme copy to the dev team.",
            "Redact the PII in the export and send the customer's export to the dev team.",
            "Redact the PII in the export and send the export Acme wants to the dev team.",
            "Redact the PII in the export and send the new Acme version to the dev team.",
            "Redact the PII in the export and send the customer export for Acme to the dev team.",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))
                self.assertTrue(self._hinted(message))

    def test_an_english_place_ends_with_its_sentence(self) -> None:
        # A place stops at ".", "!", "?" or ";" before a space. What follows,
        # up to the next send, must be remarks; sends are read in every
        # sentence.
        for message in (
            "Redact the PII in the export and send it to the dev team. It's urgent.",
            "Redact the PII in the export and send it to the dev team! Thanks!",
            "Redact the PII in the export and send it to the dev team; it’s urgent.",
            "Pseudonymize the patient CSV and share it with our QA team. Please hurry.",
            "Anonymize the user logs and upload them to staging. ASAP please.",
            "Redact the PII in the export and send it to the dev team... No rush.",
            "Redact the PII in the export and send it to the dev team. 감사합니다.",
            "Redact the PII in the export and send it to the dev team. Then share it with the QA team.",
            # Read composed on both folds, a Korean remark is a remark anywhere.
            "Redact the PII in the export and send it 빨리 to the dev team.",
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
                self.assertFalse(self._hinted(message))
        for message in (
            "Redact the PII in the export and send it to the dev team. Acme will review it.",
            "Redact the PII in the export and send it to the dev team. Also cc Acme.",
            "Redact the PII in the export and send it to the dev team. Then forward it to Acme.",
            "Redact the PII in the export and send it to the dev team; Acme will audit it.",
            "Redact the PII in the export and send it to the dev team. Thanks, Kim.",
            "Redact the PII in the export and send it to the dev team. It's for Acme.",
            "Redact the PII in the export and send it. Acme wants it delivered to the dev team.",
            # A line break alone ends nothing: the router reads it as a space.
            "Redact the PII in the export and send it to the dev team\nThanks",
            # A period before a space ends the place, which can only cut it
            # short: what follows is read as remarks.
            "Redact the PII in the export and send it to the U.S. team.",
            "Redact the PII in the export and send it to Acme Inc. The dev team will check.",
            "Redact the PII in the export and send it to the dev team, e.g. Kim.",
            "Redact the PII in the v1.2 export and send it to the dev team.",
            # Between a send and its "to", only the data sent and remarks.
            "Redact the PII in the export and send it where Acme wants it, to the dev team.",
            "Redact the PII in the export and send it, as Acme asked, to the dev team.",
            "Redact the PII in the export and send Acme's copy to the dev team.",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))
                self.assertTrue(self._hinted(message))

    def test_an_english_recipient_in_a_korean_sentence_keeps_the_review(self) -> None:
        for message in (
            "고객 정보 마스킹해서 vendor team에 보내줘",
            "고객 정보 마스킹해서 external team에 보내줘",
            "고객 정보 마스킹해서 agency team에 보내줘",
            "고객 정보 마스킹해서 contractor team에 보내줘",
            "고객 정보 마스킹해서 third-party team에 보내줘",
            "고객 정보 마스킹해서 data team에 보내고 vendor에도 보내줘",
            # Outside any place too, also with a particle glued on.
            "vendor 요청으로 고객 정보 마스킹해서 데이터팀에 보내줘",
            "vendor가 쓸 거라서 고객 정보 마스킹해서 데이터팀에 보내줘",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))
                self.assertTrue(self._hinted(message))
        self.assertFalse(_offered("고객 정보 마스킹해서 data team에 보내줘"))

    def test_every_send_and_every_joined_place_must_be_inside(self) -> None:
        for message in (
            # Between the lead verb's object and the first send, only where the
            # data is, a pronoun, a determiner and a joining word may stand.
            "redact the pii in the export before acme sees it, and send it to the dev team",
            "redact the pii in the export before the auditors review it and share it with the data team",
            "redact the pii in the export so acme can use it, and send it to the dev team",
            "redact the pii in the export acme will get, then send it to the dev team",
            "redact the pii in the export, which acme receives weekly, and send it to the dev team",
            "redact the pii in the export for the bank's auditors and send it to the dev team",
            "redact the pii in the export acme asked for and send it to the dev team",
            "redact the pii in the export before the regulator gets it, and send it to the security team",
            "redact the pii in the export for acme and send it to the dev team first",
            "redact the pii in the export for them and send it to the dev team",
            # The lead verb's object is read with the same closed words.
            "redact the export acme gets every week and send it to the dev team",
            "redact acme's export and send it to the dev team",
            "redact the acme export and send it to the dev team",
            "redact the export that acme will receive and send it to the dev team",
            "redact the export headed to the regulator and send it to the security team",
            "redact the export we owe acme and send it to the dev team",
            "redact the spreadsheet acme will publish and send it to the dev team",
            "pseudonymize the csv the bank wants and share it with the data team",
            "anonymize the logs acme will audit and upload them to staging",
            "de-identify the records the regulator requested and send them to the security team",
            # "give", "hand" and "pass" with a first object: it is the place.
            "redact pii in the export, send it to the dev team and give acme a copy",
            "redact pii in the export, send it to the dev team and give acme access",
            "redact pii in the export, send it to the dev team and give the auditors a copy",
            "redact pii in the export, send it to the dev team and give acme the file",
            "redact pii in the export, send it to the dev team and give them a copy",
            "redact pii in the export, send it to the dev team and hand acme a copy",
            "redact pii in the export, send it to the dev team and pass acme a copy",
            "redact pii in the export, send it to the dev team and hand the auditors the file",
            "redact pii in the export, give acme a copy and send it to the dev team",
            "redact pii in the export we give acme and send it to the dev team",
            # A first object that is no place keeps the review too.
            "redact pii in the export, pass the checks, and send it to the dev team",
            "redact pii in the export before we send it",
            "redact pii in the export and hand it over",
            # Handed back to the person, it names no place, and no other send
            # names one either.
            "redact pii in the export and hand it back",
            "redact pii in the export, share it with the dev team and post it publicly",
            "anonymize the dataset, send it to the qa team and upload it to kaggle",
            "redact pii in the export and send it to the dev team a copy",
            "redact pii in the export and send the dev team a copy",
            "redact pii in the export before we send it to acme so the team can check it",
            "redact pii in the export and upload it to github for the dev team",
            "redact pii in the export and send it to the data team and acme",
            "redact pii in the export and send it to the data team or the auditor",
            "redact pii in the export and send it to the data team plus acme",
            "redact pii in the export and send it to the data team as well as acme",
            "redact pii in the export and send it to both the data team and acme",
            "redact pii in the export and send it to the data team, the auditors, and acme",
            "redact pii in the export and send it to the data team, cc the auditor",
            "redact pii in the export and send it to the data team so they can forward it to acme",
            "redact pii in the export and send it to the data team who will pass it to acme",
            "redact pii in the export, send it to the dev team and email it to acme",
            "redact pii in the export, send it to the dev team and transfer it to acme",
            "개인정보 익명화해서 QA팀에 보내고 캐글에 올려줘",
            # A route or a party between the send and its place.
            *(
                f"redact pii in the export and send it {word} acme to the dev team"
                for word in ("at", "by", "for", "from", "on", "through", "using", "via")
            ),
            # A second Korean place with 도 ("also").
            *(
                f"고객 정보 마스킹해서 데이터팀에 보내고 acme{particle} 보내줘"
                for particle in ("에게도", "한테도", "께도", "으로도", "로도", "에도")
            ),
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))

    def test_a_shielded_region_never_proves_a_place_inside(self) -> None:
        # Both surfaces remove quoted, code and link text before they call the
        # rule, and both tell it so (`shielded`): 'the "acme" data team'
        # arrives as "the data team", and is still no place proven inside.
        for message in (
            'redact pii in the export and send it to the "partner" team',
            'redact pii in the export and send it to the team called "acme support"',
            'redact pii in the export and send it to "our team"',
            'redact pii in the export and send it to the "acme" data team',
            "redact pii in the export and send it to the 'acme' data team",
            "redact pii in the export and send it to the \u201cacme\u201d data team",
            "redact pii in the export and send it to the `acme` data team",
            "redact pii in the export and send it to the \u2018acme\u2019 data team",
            'redact pii in the export and send it to acme\'s "data" team',
            "redact pii in the export and upload it to https://acme.example/upload and the dev team",
            '고객 정보 마스킹해서 "삼성" 개발팀에 보내줘',
            # A masked region at the end of the message: the masker reports
            # it, so no surface reads the place before it as proven.
            "Redact the PII in the export and send it to the dev team https://acme.com",
            'Redact the PII in the export and send it to the dev team "at Acme"',
            "Redact the PII in the export and send it to the dev team `@acme`",
            "Redact the PII in the export and send it to the dev team 'acme side'",
            'Redact the PII in the export and send it to the dev team "Acme"  ',
            'Redact the PII in the export and send it to the dev team\u3000"Acme"',
            'Redact the PII in the export and send it to the dev team "Acme".',
        ):
            with self.subTest(message=message):
                self.assertTrue(self._named(message))
                self.assertTrue(self._hinted(message))
        # The rule alone reads no place as inside when it sees the quotes, as
        # the awareness marker reads the unmasked message.
        self.assertTrue(data_share_request_admitted('고객 정보 마스킹해서 "acme" 개발팀에 보내줘'))
        self.assertTrue(data_share_request_admitted('redact pii in the export and send it to "our team"'))
        self.assertTrue(data_share_request_admitted("redact pii in the export and send it to the data team", shielded=True))
        self.assertFalse(data_share_request_admitted("redact pii in the export and send it to the data team"))
        self.assertTrue(data_share_request_admitted("고객 정보 마스킹해서 개발팀에 보내줘", shielded=True))

    def test_a_party_word_describes_the_data_only_right_before_a_container(self) -> None:
        # Right before a data container or a field name, not possessive and
        # not after "for", "to" or "from", a party word says whose records
        # the data holds: the place decides.
        for message in (
            "redact the pii in the customer export before we send it to the dev team",
            "pseudonymize the patient csv and share it with our qa team",
            "anonymize the user logs and upload them to the data team",
            "redact the customers table and send it to the dev team",
            "redact the customer emails export and send it to the dev team",
            "redact the member records and share them with the data team",
            *(
                f"redact the {word} export and send it to the dev team"
                for word in (
                    "account", "accounts", "applicant", "applicants", "client", "clients", "customer", "customers",
                    "donor", "donors", "employee", "employees", "member", "members", "patient", "patients", "staff",
                    "student", "students", "subscriber", "subscribers", "user", "users",
                )
            ),
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
        # Anywhere else it may name a recipient, and a word off the list never
        # describes the data.
        for message in (
            "redact the customer's export and send it to the dev team",
            "redact the customers' export and send it to the dev team",
            # Not right before a container or a field: it is the party.
            "redact the export of the customer and send it to the dev team",
            "redact the export of the users and send it to the dev team",
            "redact the export for the customer and send it to the dev team",
            "redact the pii for the customer export and send it to the dev team",
            "redact the pii from the client file and send it to the dev team",
            "redact the pii in the export to the client file and send it to the dev team",
            "redact the customer export the regulator wants and send it to the dev team",
            "redact the patient csv for the insurer and send it to the data team",
            "anonymize the user logs acme will audit and upload them to staging",
            "de-identify the client file headed to the auditors and send it to the security team",
            "redact the customer export customers will see and send it to the dev team",
            "redact the customer support logs and send them to the dev team",
            "redact the acme export and send it to the dev team",
            "redact the partner export and send it to the dev team",
            "redact the bank records and send them to the dev team",
            "redact the insurer file and send it to the dev team",
            "redact the regulator records and send them to the dev team",
            "redact the auditor extract and send it to the dev team",
            "redact the customer-facing export and send it to the dev team",
            # The place still decides: a customer, the customer team.
            "redact the customer export, then send it to the customer",
            "redact the customer export and send it to the customer team",
            # A copy given to someone outside, also beside the person.
            "redact the pii in the customer export and send it to the dev team and give me and acme a copy",
            "redact the pii in the customer export and send it to the dev team and give myself and acme a copy",
            "redact the pii in the customer export and send it to the dev team and give acme back the file",
        ):
            with self.subTest(message=message):
                self.assertTrue(_offered(message))

    def test_the_router_carries_the_maskers_report(self) -> None:
        from omh.routing.query import RoutingQuery

        quoted = 'redact pii in the export and send it to the "acme" data team'
        masked = "redact pii in the export and send it to the        data team"
        # A query that masks its own text reports it; one handed masked text
        # reports it only when its caller says so.
        self.assertTrue(RoutingQuery.from_message(quoted).shielded)
        self.assertFalse(RoutingQuery.from_message(masked).shielded)
        self.assertTrue(RoutingQuery.from_message(masked, shielded=True).shielded)
        self.assertIn(SKILL, [item["skill"] for item in recommend_skills(quoted, limit=50)])
        # The shortlist's reader and the scorer read the same flag.
        self.assertTrue(RoutingQuery.from_message(masked).offers_itself_withheld(SKILL))
        self.assertFalse(RoutingQuery.from_message(masked, shielded=True).offers_itself_withheld(SKILL))
        # The cache keeps a masked text apart from the same text unmasked by
        # nobody, in either order.
        for first, second in ((False, True), (True, False)):
            with self.subTest(first=first):
                from omh.routing import recommend

                recommend._recommend_skills_cached.cache_clear()
                runs = {}
                for shielded in (first, second):
                    query = RoutingQuery.from_message(masked, shielded=shielded)
                    runs[shielded] = SKILL in [item["skill"] for item in recommend_skills(query, limit=50)]
                self.assertEqual(runs, {True: True, False: False})

    def test_a_plural_possessive_hides_nothing_after_it(self) -> None:
        # The masker read the `'` of "customers' export" as an opening quote
        # that never closed, so neither surface read the send or the place.
        for message in (
            "Redact the PII in the customers' export and send it to Acme.",
            "Pseudonymize the users' IDs in the dataset and share it with the third-party analytics vendor.",
            "Redact the PII in the clients' file and share it with the vendor",
            "Redact the PII in the users' 'draft' file and send it to the vendor.",
        ):
            with self.subTest(message=message):
                self.assertTrue(self._named(message))
                self.assertTrue(self._hinted(message))

    def test_an_apostrophe_quotes_nothing_in_either_spelling(self) -> None:
        # Smart punctuation types `’` for `'`. Between two letters it is an
        # apostrophe, as `'` is, and keeps no place from being read inside.
        for spelling in ("'", "’"):
            message = f"고객 정보 마스킹해서 개발팀에 보내줘. It{spelling}s urgent."
            with self.subTest(message=message):
                self.assertFalse(_offered(message))
        # At the edge of a word either spelling quotes, and so does `‘` on its
        # own, so a place proven inside unquoted is no longer proven inside.
        self.assertFalse(data_share_request_admitted("redact pii in the export and send it to the dev team"))
        for message in (
            "redact pii in the export and send it to the 'dev team'",
            "redact pii in the export and send it to the ’dev team’",
            "redact pii in the export and send it to the ‘dev team",
        ):
            with self.subTest(message=message):
                self.assertTrue(data_share_request_admitted(message))

    def test_english_and_korean_agree(self) -> None:
        for english, korean, offered in (
            ("redact pii in the export before we send it to the dev team", "개인정보 지우고 개발팀에 보내줘", False),
            ("redact the logs before uploading them to staging", "로그에서 개인정보 지우고 스테이징에 올려줘", False),
            ("de-identify the records before we upload the file to the test server", "개인정보 비식별화해서 테스트 서버에 올려줘", False),
            ("redact pii from this csv before sending it to my coworker", "개인정보 지우고 동료한테 보내줘", False),
            ("pseudonymize the email addresses in the dataset before sharing it with another department", "개인정보 가명 처리해서 다른 부서에 공유해줘", False),
            ("anonymize the logs before we share them with the in-house data team", "개인정보 익명화해서 사내 데이터팀에 공유해줘", False),
            ("redact pii in the csv before sending to qa", "개인정보 지우고 QA에 보내줘", False),
            ("redact pii in the export before we send it to the vendor", "개인정보 지우고 벤더한테 보내줘", True),
            ("redact the pii in the export and send it to the vendor's team", "개인정보 마스킹해서 벤더 팀에 보내줘", True),
            ("anonymize the dataset before sharing it with an external team", "고객 정보 익명화해서 외부 팀에 공유해줘", True),
            ("anonymize the export and share it with the client's team", "고객 정보 익명화해서 고객사 팀에 공유해줘", True),
            ("anonymize the csv before sending it to the university research team", "개인정보 익명화해서 대학 연구팀에 보내줘", True),
            ("redact the emails in the export before sending it to the data team at acme", "이메일 주소 지우고 acme 데이터팀에 보내줘", True),
            ("anonymize the dataset, send it to the qa team and upload it to kaggle", "개인정보 익명화해서 QA팀에 보내고 캐글에 올려줘", True),
            ("redact the pii in the export the insurer wants and send it to the dev team", "보험사가 원하는 엑셀 개인정보 지우고 개발팀에 보내줘", True),
            ("redact the pii in the export for the bank and send it to the data team", "은행을 위한 파일 개인정보 지우고 데이터팀에 보내줘", True),
            ("redact pii in the export and send it to the dev team. it's urgent.", "개인정보 지우고 개발팀에 보내줘. 급해요.", False),
            ("redact pii in the export and send it to the dev team. acme will review it.", "개인정보 지우고 개발팀에 보내줘. acme가 검토할 거야.", True),
            ("redact pii in the export and send it to the dev team. then share it with the qa team.", "개인정보 지우고 개발팀에 보내줘. QA팀에도 공유해줘.", False),
        ):
            with self.subTest(english=english):
                self.assertIs(_offered(english), offered)
                self.assertIs(_offered(korean), offered)

    def test_hangul_in_an_english_place_reads_alike_on_both_folds(self) -> None:
        # The router folds Hangul to NFKD and the hint keeps it NFC; Hangul in
        # an English place is never an inside word, so both admit alike.
        for message in ("redact pii in the export and send it to 벤더 팀", "redact pii in the export and send it to 우리 팀"):
            for form in ("NFC", "NFD"):
                text = unicodedata.normalize(form, message)
                with self.subTest(message=message, form=form):
                    self.assertTrue(_offered(text))
                    self.assertTrue(data_share_request_admitted(text.casefold()))
                    self.assertTrue(self._hinted(text))

    def test_every_table_of_the_place_reading_is_exactly_this(self) -> None:
        # A literal snapshot: a word added to a table, or dropped from one,
        # fails here before any sentence is read. Change a table only with
        # the sentences that pin the change.
        from omh.plugin_bundle.omh import data_share_cues

        tables = {
            "DATA_SHARE_INTERNAL_DESTINATIONS": {
                "co-worker", "co-workers", "colleague", "colleagues", "coworker", "coworkers", "dev server",
                "in-house", "internal", "qa", "staging", "teammate", "teammates", "test environment",
                "test server", "개발서버", "내부", "동료", "로컬", "사내", "스테이징", "테스트",
            },
            "DATA_SHARE_INTERNAL_UNITS": {
                "department", "departments", "team", "teams", "부서", "팀",
            },
            "DATA_SHARE_INTERNAL_OWNERS": {
                "ai", "analytics", "another", "backend", "bi", "data", "design", "dev", "development",
                "engineering", "finance", "frontend", "growth", "hr", "infra", "infrastructure", "it", "marketing",
                "ml", "mobile", "my", "operations", "ops", "our", "platform", "product", "research", "sales",
                "science", "security", "support", "test", "testing", "web", "개발", "기획", "내", "다른", "데이터", "디자인",
                "마케팅", "백엔드", "보안", "분석", "사이언스", "엔지니어링", "연구", "영업", "우리", "운영", "인사", "인프라", "재무", "저희", "제",
                "제품", "지원", "타", "품질", "프론트엔드", "플랫폼",
            },
            "DATA_SHARE_INTERNAL_MODIFIERS": {
                "a", "an", "both", "channel", "dashboard", "servers", "slack", "the", "tool", "wiki", "workspace",
                "같은", "대시보드", "메신저", "모든", "서버", "슬랙", "위키", "전체", "채널", "툴", "환경",
            },
            "_PLACE_JOINERS": {
                "and", "as", "in", "or", "please", "plus", "today", "well",
            },
            "_BEFORE_SEND_WORDS": {
                "a", "address", "addresses", "after", "an", "and", "archive", "archives", "backup", "backups",
                "before", "birth", "column", "columns", "copies", "copy", "corpus", "csv", "csvs", "data",
                "database", "databases", "dataset", "datasets", "date", "dates", "db", "details", "dob",
                "document", "documents", "dump", "dumps", "email", "emails", "excerpt", "excerpts", "export",
                "exports", "extract", "extracts", "field", "fields", "file", "files", "first", "for", "from", "i",
                "id", "identifier", "identifiers", "ids", "in", "info", "information", "ip", "ips", "it", "json",
                "list", "lists", "log", "logs", "my", "name", "names", "number", "numbers", "of", "once", "our",
                "personal", "phone", "phones", "pii", "please", "records", "report", "reports", "row", "rows",
                "sample", "samples", "sensitive", "sheet", "sheets", "spreadsheet", "spreadsheets", "ssn", "ssns",
                "table", "tables", "that", "the", "then", "these", "this", "those", "transcript", "transcripts",
                "tsv", "us", "we", "xlsx", "you",
            },
            "_DATA_CONTAINERS": {
                "archive", "archives", "backup", "backups", "column", "columns", "copies", "copy", "corpus", "csv",
                "csvs", "data", "database", "databases", "dataset", "datasets", "db", "document", "documents",
                "dump", "dumps", "excerpt", "excerpts", "export", "exports", "extract", "extracts", "field",
                "fields", "file", "files", "json", "list", "lists", "log", "logs", "records", "report", "reports",
                "row", "rows", "sample", "samples", "sheet", "sheets", "spreadsheet", "spreadsheets", "table",
                "tables", "transcript", "transcripts", "tsv", "xlsx",
            },
            "_DATA_FIELDS": {
                "address", "addresses", "birth", "date", "dates", "details", "dob", "email", "emails", "id",
                "identifier", "identifiers", "ids", "info", "information", "ip", "ips", "name", "names", "number",
                "numbers", "personal", "phone", "phones", "pii", "sensitive", "ssn", "ssns",
            },
            "DATA_SHARE_PARTY_MODIFIERS": {
                "account", "accounts", "applicant", "applicants", "client", "clients", "customer", "customers",
                "donor", "donors", "employee", "employees", "member", "members", "patient", "patients", "staff",
                "student", "students", "subscriber", "subscribers", "user", "users",
            },
            "_MODIFIER_BLOCKERS": {
                "for", "from", "to",
            },
            "_SPAN_DETERMINERS": {
                "a", "an", "my", "our", "that", "the", "these", "this", "those",
            },
            "_HANDED_THINGS": {
                "access", "copies", "copy", "corpus", "csv", "csvs", "dataset", "datasets", "dump", "dumps",
                "excerpt", "excerpts", "export", "exports", "extract", "extracts", "file", "files", "link",
                "links", "log", "logs", "records", "spreadsheet", "spreadsheets", "version",
            },
            "_FIRST_PERSON": {
                "me", "myself", "ourselves", "us",
            },
            "_AFTER_THE_PERSON": {
                "a", "access", "an", "copies", "copy", "corpus", "csv", "csvs", "dataset", "datasets", "dump",
                "dumps", "excerpt", "excerpts", "export", "exports", "extract", "extracts", "file", "files",
                "link", "links", "log", "logs", "records", "some", "spreadsheet", "spreadsheets", "that", "the",
                "this", "version",
            },
            "_SEND_ROUTE_WORDS": {
                "at", "by", "for", "from", "on", "through", "using", "via",
            },
            "_ONWARD_SENDS": {
                "attach", "attaching", "cc", "email", "emailing", "forward", "forwarding", "give", "giving",
                "hand", "handing", "pass", "passing", "post", "posting", "send", "sending", "share", "sharing",
                "transfer", "transferring", "upload", "uploading",
            },
            "_SENDS_ONLY_WITH_A_PLACE": {
                "give", "giving", "hand", "handing", "pass", "passing",
            },
            "_DESTINATION_PREPOSITIONS": {
                "into", "onto", "to", "with",
            },
            "_KOREAN_EXPORT_DESTINATIONS": {
                "csv", "json", "pdf", "txt", "xlsx", "백업", "엑셀", "텍스트", "파일", "폴더",
            },
            "_KOREAN_TIMES": {
                "다음", "뒤", "전", "후",
            },
            "_KOREAN_CHANNELS": {
                "메신저", "메일", "슬랙", "이메일",
            },
            "_KOREAN_PLACE_EDGES": {
                "다음", "다음에", "뒤", "뒤에", "전", "전에", "후", "후에",
            },
            "_KOREAN_PLACE_PARTICLES": {
                "께", "께도", "로", "로도", "에", "에게", "에게도", "에도", "으로", "으로도", "쪽에", "쪽으로", "측에", "한테", "한테도",
            },
            "_KOREAN_JOINED_ENDINGS": {
                "하고", "하고서", "한", "해서",
            },
            "_KOREAN_EDGE_VERBS": {
                "가려", "가명", "가명처리", "가명화", "공개", "공유", "내보내", "넘겨", "넘기", "마스킹", "반출", "별표", "보내", "보내드려", "블러",
                "비식별", "비식별처리", "비식별화", "빼", "삭제", "업로드", "올려", "올리", "익명", "익명처리", "익명화", "전달", "제거", "제공", "제출",
                "지워", "처리", "첨부", "해시",
            },
            "_REMARK_WORDS": {
                "also", "asap", "cheers", "hurry", "is", "no", "now", "ok", "okay", "please", "pls", "plz", "quickly",
                "rush", "s", "so", "soon", "thank", "thanks", "today", "tomorrow", "tonight", "too", "urgent",
                "urgently", "very", "you", "감사", "감사드립니다", "감사합니다", "감사해요", "고마워", "고마워요", "고맙습니다",
                "급합니다", "급해", "급해요", "꼭", "내일", "바로", "부탁드려요", "부탁드립니다", "부탁합니다", "부탁해", "부탁해요",
                "빨리", "오늘", "좀", "지금",
            },
            "_KOREAN_DATA_CONTAINERS": {
                "csv", "json", "pdf", "txt", "xlsx", "기록", "내역", "덤프", "데이터", "데이터셋", "레코드", "로그", "리스트",
                "리포트", "명단", "목록", "문서", "백업", "보고서", "사본", "샘플", "스프레드시트", "시트", "엑셀", "열", "원본", "자료",
                "추출본", "컬럼", "테이블", "텍스트", "파일", "폴더", "표", "필드", "행",
            },
            "_KOREAN_DATA_FIELDS": {
                "ip", "pii", "개인", "개인정보", "계좌번호", "고객정보", "닉네임", "민감", "민감정보", "사번", "생년월일", "식별",
                "식별자", "식별정보", "실명", "아이디", "연락처", "이름", "이메일", "전화번호", "정보", "주민등록번호", "주민번호", "주소",
                "카드번호", "학번",
            },
            "_KOREAN_PARTY_MODIFIERS": {
                "account", "accounts", "applicant", "applicants", "client", "clients", "customer", "customers",
                "donor", "donors", "employee", "employees", "member", "members", "patient", "patients", "staff",
                "student", "students", "subscriber", "subscribers", "user", "users", "가입자", "계정", "고객", "구독자",
                "기부자", "멤버", "사용자", "사원", "유저", "이용자", "임직원", "지원자", "직원", "클라이언트", "학생", "환자", "회원",
                "후원자",
            },
            "_KOREAN_SPAN_PARTICLES": {
                "과", "까지", "나", "는", "도", "랑", "로", "를", "만", "부터", "에서", "와", "으로", "은", "을", "의", "이나", "이랑",
                "하고",
            },
            "_KOREAN_SPAN_WORDS": {
                "각", "그", "그리고", "꼭", "다시", "대신", "또", "또는", "먼저", "및", "바로", "빨리", "아래", "위", "이", "이번", "저",
                "좀", "지금", "해당", "혹은",
            },
            "_KOREAN_SPAN_VERBS": {
                "가려", "가명", "가명처리", "가명화", "공개", "공유", "내보내", "넘겨", "넘기", "마스킹", "반출", "별표", "보내", "보내드려",
                "블러", "비식별", "비식별처리", "비식별화", "빼", "삭제", "업로드", "올려", "올리", "완료", "익명", "익명처리", "익명화",
                "전달", "제거", "제공", "제출", "지워", "진행", "처리", "첨부", "해시",
            },
        }
        for name, expected in tables.items():
            with self.subTest(table=name):
                self.assertEqual(set(getattr(data_share_cues, name)), expected)
        self.assertEqual(data_share_cues._HANDED_BACK, (["it", "back"], ["them", "back"]))
        self.assertEqual(data_share_cues._REMARKS, data_share_cues._BEFORE_SEND_WORDS | data_share_cues._REMARK_WORDS)
        self.assertEqual(
            set(data_share_cues._SENT_DATA_WORDS),
            {
                "all", "anonymised", "anonymized", "both", "clean", "cleaned", "de-identified", "deidentified",
                "directly", "final", "masked", "new", "output", "outputs", "pseudonymised", "pseudonymized",
                "redacted", "result", "results", "sanitised", "sanitized", "straight", "updated", "version",
                "versions", "whole",
            },
        )
        self.assertEqual(
            data_share_cues._SENT_THING_WORDS,
            data_share_cues._REMARKS | data_share_cues._SENT_DATA_WORDS | {"back", "over", "them"},
        )
        self.assertEqual(data_share_cues._SENTENCE_BREAK.pattern, r"[.!?;]\S*\s")

    def test_outside_words_keep_the_review(self) -> None:
        # Words that name an outside party, beside a unit that would otherwise
        # be owned: none may ever prove a place inside.
        for word in (
            "bank", "auditors", "supplier", "consultant", "freelance", "outsourced", "outside", "investor", "reseller",
            "law", "firm", "government", "insurer", "client", "partner", "customer", "regulator", "hospital",
            "university", "acme", "external", "agency",
        ):
            with self.subTest(word=word):
                self.assertTrue(_offered(f"redact pii in the export before we send it to the {word} data team"))
                self.assertTrue(_offered(f"redact pii in the export before we send it to the {word} team"))
        for word in ("은행", "병원", "협력", "타사", "삼성", "감사법인", "보험사", "고객사", "대학", "회사", "외부", "벤더"):
            with self.subTest(word=word):
                self.assertTrue(_offered(f"고객 정보 마스킹해서 {word} 데이터 팀에 보내줘"))
                self.assertTrue(_offered(f"고객 정보 마스킹해서 {word} 팀에 보내줘"))

    def test_every_inside_word_is_pinned(self) -> None:
        # Each literal is the contract: removing a word from the tables makes
        # its sentence leave.
        english = "redact pii in the export before we send it to {}"
        for place in (
            "staging", "qa", "my teammate", "my teammates", "a colleague", "colleagues", "my coworker", "my coworkers",
            "a co-worker", "my co-workers", "the internal wiki", "an in-house tool", "the test server",
            "the test environment", "the dev server", "our team", "our teams", "another department",
            "the hr departments", "both the data team and the qa team", "our staging servers",
            "the internal dashboard", "the internal slack channel", "the internal workspace",
            "the data team or the qa team", "the data team plus the qa team", "the data team as well as the qa team",
            "the dev team today", "the dev team please",
            *(f"the {owner} team" for owner in (
                "data", "dev", "development", "engineering", "test", "testing", "marketing", "sales", "finance", "hr",
                "security", "platform", "analytics", "support", "ops", "operations", "product", "design", "research",
                "ml", "ai", "bi", "backend", "frontend", "infra", "infrastructure", "it", "mobile", "web", "growth",
            )),
            "the data science team", "my team",
        ):
            with self.subTest(place=place):
                self.assertFalse(_offered(english.format(place)))
        for message in (
            "개인정보 지우고 사내 위키에 올려줘",
            "개인정보 지우고 내부 서버에 올려줘",
            "개인정보 지우고 스테이징에 올려줘",
            "개인정보 지우고 개발서버에 올려줘",
            "개인정보 지우고 테스트 서버에 올려줘",
            "개인정보 지우고 로컬에 올려줘",
            "개인정보 지우고 동료한테 보내줘",
            "개인정보 지우고 우리 팀에 보내줘",
            "개인정보 지우고 다른 부서에 보내줘",
            "개인정보 지우고 우리 팀 전체에 공유해줘",
            "개인정보 지우고 모든 팀원들한테 공유해줘",
            "개인정보 지우고 같은 팀 동료한테 보내줘",
            *(f"개인정보 지우고 사내 {head}에 올려줘" for head in ("서버", "환경", "위키", "대시보드", "툴", "채널", "슬랙", "메신저")),
            *(f"개인정보 지우고 {owner} 팀에 보내줘" for owner in (
                "우리", "내", "제", "저희", "다른", "타", "개발", "데이터", "분석", "마케팅", "영업", "재무", "인사", "보안",
                "플랫폼", "지원", "운영", "제품", "기획", "디자인", "연구", "백엔드", "프론트엔드", "인프라", "엔지니어링", "품질",
            )),
            "개인정보 지우고 데이터 사이언스 팀에 보내줘",
            *(f"개인정보 지운 {step} 개발팀에 보내줘" for step in ("다음", "다음에", "후", "후에", "뒤", "뒤에")),
            *(f"개인정보 지우고 개발팀에 {channel}로 보내줘" for channel in ("이메일", "메일", "메신저")),
            "개인정보 지우고 개발팀에 슬랙으로 보내줘",
            *(f"개인정보 지우고 {file}로 내보내줘" for file in ("엑셀", "csv", "pdf", "json", "xlsx", "txt", "텍스트", "파일", "폴더", "백업 폴더")),
        ):
            with self.subTest(message=message):
                self.assertFalse(_offered(message))


OWNERS = (
    ("attach the crash log to the github issue", "github-event-ops"),
    ("summarize this customer support transcript", "media-input-operator"),
    ("fine-tune a model on our support tickets", "model-finetuning"),
    ("file a bug report on github about the login crash", "github-issue-intake"),
    ("close the github issue titled redact pii from logs", "github-event-ops"),
    ("rerun the failing github action for the pseudonymize job", "github-event-ops"),
    ("write a blog post about pii redaction best practices", "web-research"),
    ("hey, triage the github issues about pii redaction in the public log files", "github-event-ops"),
    ("i need you to triage the issues about pii redaction in log files we post publicly", "connector-operator"),
    ("send a slack message saying the export file is ready to share once we redact pii", "gateway-intent-card"),
    ("redact personal data from these server logs before I attach them to a public github issue", "github-event-ops"),
    ("redact the pii in this support transcript excerpt before we post it in the public tracker", "media-input-operator"),
    ("strip the pii from this dataset before we send it to an external contractor", "connector-operator"),
    ("redact the pii in this crash log before attaching it to the public github issue", "github-event-ops"),
    ("remove the pii redaction label from the github issue about the export we sent the vendor", "github-event-ops"),
    ("transcribe this call, then redact the pii in the transcript excerpt before posting it publicly", "media-input-operator"),
    ("깃허브 이슈 라벨 달아줘, 제목: redact the pii from the export before sending to the vendor", "github-event-ops"),
    ("redact pii 하고 vendor한테 export 파일 보내줘", "gateway-intent-card"),
)


if __name__ == "__main__":
    unittest.main()

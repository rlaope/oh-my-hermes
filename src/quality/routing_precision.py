from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
from ..wrapper.contract import build_chat_interaction_payload


ROUTING_PRECISION_SCHEMA_VERSION = "routing_precision/v1"


@dataclass(frozen=True)
class RoutingPrecisionCase:
    id: str
    title: str
    message: str
    expected_next_action: str
    expected_lookup_kind: str


@dataclass(frozen=True)
class RoutingInterventionCase:
    id: str
    title: str
    message: str
    expected_route_action: str
    expected_workflow: str
    expected_next_action: str
    expected_response_kind: str


# Negative-control corpus. These are ordinary chat turns where OMH should stay
# helpful but should not hijack the answer into workflow selection, catalog
# pickers, coding handoffs, or generic workflow acknowledgements.
ROUTING_PRECISION_CASES: tuple[RoutingPrecisionCase, ...] = (
    RoutingPrecisionCase(
        "repo-file-list",
        "Repo file lookup stays direct",
        "what files are in this repo?",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "readme-summary",
        "README lookup stays direct",
        "open README and summarize it",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "readme-contents",
        "README contents question stays file lookup",
        "what is in README?",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "general-python-help",
        "Plain Python concept stays direct",
        "what Python list comprehension means?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "shell-path-help",
        "Shell setup question stays direct",
        "how do I set PATH in zsh?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "stack-trace-help",
        "Missing stack trace asks for direct context",
        "please explain this stack trace",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "python-virtualenv-help",
        "Python virtualenv how-to stays direct",
        "how do I create a virtualenv in Python?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "soft-prefix-python-help",
        "Soft-prefix Python explanation stays direct",
        "just explain Python virtualenv",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "paragraph-summary",
        "Small text transform stays direct",
        "summarize this paragraph in Korean",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-translation",
        "Short translation request stays direct",
        "translate this to Korean",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-summary",
        "Short summary request stays direct",
        "summarize this in Korean",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-sentence-translation",
        "Korean sentence translation request stays direct",
        "이 문장 영어로 번역해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-paragraph-summary",
        "Korean paragraph summary request stays direct",
        "이 문단 요약해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-image-word-translation",
        "Korean single-word translation with image term stays direct",
        "image라는 단어 한국어로 번역해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-photo-description",
        "Korean photo explanation stays direct",
        "이 사진 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-thanks",
        "Short thanks stays direct",
        "thanks",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-ok",
        "Short ok stays direct",
        "ok",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "context-what-happened",
        "Context question stays direct",
        "what happened?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "context-what-did-i-ask",
        "Previous-message question stays direct",
        "what did I just ask?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-error-troubleshooting",
        "Korean error troubleshooting stays direct",
        "이 오류 왜 나?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-error-slang",
        "Korean short error slang stays direct",
        "이 오류 뭐임",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-log-review",
        "Korean log review stays direct",
        "이 로그 봐줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "command-not-found-help",
        "Command-not-found help stays direct",
        "command not found: omh",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-thanks",
        "Spanish thanks stays direct",
        "gracias",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-thanks",
        "Japanese thanks stays direct",
        "ありがとう",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-concept",
        "Spanish concept question stays direct",
        "¿Qué es Kubernetes?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "french-concept",
        "French concept question stays direct",
        "Qu’est-ce que Kubernetes ?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-concept",
        "Japanese concept question stays direct",
        "Kubernetesとは何ですか？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "chinese-concept",
        "Chinese concept question stays direct",
        "Kubernetes是什么？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-thanks",
        "Hindi thanks stays direct",
        "धन्यवाद",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-concept",
        "Hindi concept question stays direct",
        "Kubernetes क्या है?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-summary",
        "Hindi short summary request stays direct",
        "इसका सारांश दो",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-translation",
        "Hindi short translation request stays direct",
        "इसे अंग्रेज़ी में अनुवाद करो",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-explanation",
        "Spanish explanation request stays direct",
        "explícame GraphQL",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-summary",
        "Japanese summary request stays direct",
        "これを要約して",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-translation",
        "Spanish translation request stays direct",
        "traduce esto al inglés",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "localized-command-not-found",
        "Localized command-not-found help stays direct",
        "コマンドが見つかりません: omh",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "plain-concept-help",
        "Plain concept explanation stays direct",
        "what is OAuth in simple terms?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "python-loop-concept",
        "Python loop concept stays direct",
        "what is a loop in Python?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "strategy-pattern-concept",
        "Strategy pattern concept stays direct",
        "strategy pattern 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "memory-leak-concept",
        "Memory leak concept stays direct",
        "memory leak 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "source-control-concept",
        "Source control concept stays direct",
        "what is source control?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "github-repo-concept",
        "GitHub repo concept stays direct",
        "what is GitHub repo?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "kubernetes-concept",
        "Generic Kubernetes concept stays direct",
        "what is Kubernetes?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "graphql-korean-explanation",
        "Mixed-language GraphQL explanation stays direct",
        "GraphQL 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "kubernetes-korean-concept",
        "Korean Kubernetes concept stays direct",
        "쿠버네티스가 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-error-meaning",
        "Korean error meaning question stays direct",
        "이 에러 무슨 뜻이야?",
        "answer_directly",
        "direct_answer",
    ),
)


# Positive-intervention corpus. These are real OMH-shaped turns where the router
# should still step in after the direct-answer fallback was added.
ROUTING_INTERVENTION_CASES: tuple[RoutingInterventionCase, ...] = (
    RoutingInterventionCase(
        "safe-feature-plan",
        "Safe feature work routes to planning",
        "how can I safely add a feature to this repo?",
        "dispatch",
        "ralplan",
        "present_plan",
        "plan",
    ),
    RoutingInterventionCase(
        "hindi-safe-feature-plan",
        "Hindi safe feature work routes to planning",
        "मैं इस परियोजना में सुरक्षित तरीके से नई सुविधा जोड़ना चाहता हूँ",
        "dispatch",
        "ralplan",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "source-acquisition",
        "Source acquisition routes to source finder",
        "github oss repo 찾아서 비교해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "hindi-source-finder",
        "Hindi source acquisition routes to source-finder",
        "इस विषय के शोध पत्र PDF और डेटा सेट ढूंढो",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "hindi-paper-learning",
        "Hindi paper explanation routes to paper-learning",
        "इस शोध पत्र PDF को आसान स्तर पर समझाओ",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "hindi-web-research",
        "Hindi current-source request routes to web-research",
        "वेब पर खोजकर ताज़ा स्रोतों के साथ सारांश दो",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "hindi-issue-to-pr",
        "Hindi issue-to-PR preparation routes to GitHub event ops",
        "इस issue को PR के लिए तैयार करो",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "korean-source-dataset-github",
        "Korean source finder with dataset and GitHub routes to source-finder",
        "자료 출처 찾아줘 데이터셋이랑 깃허브까지",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-arxiv-link-source-finder",
        "Korean arxiv link requests route to source-finder",
        "arxiv 링크 찾아서 쉽게 설명해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-paper-pdf-source-finder",
        "Korean paper PDF acquisition routes to source-finder",
        "논문 pdf 찾아서 쉽게 설명해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-negated-paper-learning-source-finder",
        "Negated paper-learning mention routes to source-finder",
        "paper-learning 말고 논문 pdf 어디서 찾아?",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-negated-source-finder-paper-learning",
        "Negated source-finder mention routes to paper-learning",
        "source-finder 말고 이 논문 쉽게 설명해줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "korean-attached-paper-beginner-learning",
        "Attached paper explanation routes to paper-learning",
        "첨부한 논문을 초보자 수준으로 풀어줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "korean-paper-link-source-finder",
        "Korean paper-link acquisition routes to source-finder",
        "초보자용으로 볼 수 있는 논문 링크를 찾아줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-dataset-report-source-finder",
        "Korean dataset acquisition with downstream summary routes to source-finder",
        "데이터셋 찾아서 요약 리포트로 정리해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-github-oss-source-finder",
        "Korean GitHub OSS acquisition routes to source-finder",
        "깃허브 오픈소스 저장소 찾아서 구조 분석해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-public-presentation-source-finder",
        "Korean public presentation acquisition routes to source-finder",
        "공개 발표자료 찾아서 요약해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-public-slide-source-finder",
        "Korean public slide acquisition routes to source-finder",
        "공개 슬라이드 자료 찾아서 핵심 요약해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "visual-summary",
        "Image-card requests route to img-summary",
        "make an image card for this PR",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-meeting-vertical-image-card",
        "Korean meeting image-card requests route to img-summary",
        "이미지 생성해줘. 회의록을 세로 카드로 요약해줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-photo-meeting-vertical-image-card",
        "Korean photo requests for meeting image cards route to img-summary",
        "사진 생성해줘. 회의록을 보기 좋은 세로 이미지로 정리해줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-pretty-meeting-image-card",
        "Korean pretty meeting image requests route to img-summary",
        "회의록을 예쁜 이미지로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-github-pr-reviewer-image-card",
        "Korean GitHub PR reviewer image-card requests route to img-summary",
        "이 GitHub PR을 리뷰어용 이미지 카드로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-release-announcement-card",
        "Korean release announcement card requests route to img-summary",
        "릴리즈 노트를 announcement 카드로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-thumbnail-card",
        "Korean thumbnail requests route to img-summary",
        "썸네일 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-release-notes-thumbnail",
        "Korean release notes thumbnail requests route to img-summary",
        "릴리즈 노트 썸네일로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-omh-loop-feature-image",
        "Korean OMH loop feature image requests route to img-summary",
        "OMH 루프 기능 소개 이미지 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-image-generator-connector-readiness",
        "Korean missing image-generator connector requests route to toolbelt readiness",
        "이미지 생성 연결체가 없으면 어떤걸로 연결할지 물어봐줘",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-pr-image-tool-readiness",
        "Korean PR image request with missing generator routes to toolbelt-readiness",
        "PR 요약 이미지 만들고 싶어 근데 GPT image 연결 안 됐어",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-fal-key-image-tool-readiness",
        "Korean image-card request with missing FAL key routes to toolbelt-readiness",
        "회의록 이미지 카드 만들고 싶은데 FAL_KEY가 없어",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-unattached-image-tool-readiness",
        "Korean image tool unattached request routes to toolbelt-readiness",
        "이미지 만들고 싶은데 도구가 안 붙어있어",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-hermes-coding-team-only",
        "Korean Hermes-only coding team requests prepare runtime handoff",
        "Hermes만으로 코딩팀처럼 작업하고 싶어",
        "dispatch",
        "team",
        "show_runtime_handoff",
        "handoff",
    ),
    RoutingInterventionCase(
        "feedback-triage",
        "Product feedback routes to triage",
        "payment failures keep coming up from customer feedback",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "catalog-picker",
        "Workflow inventory opens the OMH picker",
        "what OMH workflows are available?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "catalog-no-shell-approval-korean",
        "Korean omh list approval question opens the picker without shell",
        "Hermes가 omh list 승인하라고 하는데 굳이 쳐야해?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "catalog-no-shell-workflows",
        "Workflow inventory with omh list mention opens the picker without shell",
        "what OMH workflows are available without running omh list?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "slack-omh-command-picker",
        "Slack /omh entrypoint opens the OMH picker",
        "슬랙에서 /omh 치면 뭐가 떠야해?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "partial-omh-preview-missing",
        "Partial ./ entrypoint issue opens command preview",
        "./ 쳤는데 omh가 안 떠",
        "dispatch",
        "oh-my-hermes",
        "show_command_preview",
        "command_preview",
    ),
    RoutingInterventionCase(
        "omh-risky-refactor-context",
        "OMH usage help opens a bounded context brief",
        "how do I use OMH for a risky refactor?",
        "dispatch",
        "oh-my-hermes",
        "show_context_brief",
        "context_brief",
    ),
    RoutingInterventionCase(
        "exact-ops-review-capability",
        "Exact operations workflow questions open ops review",
        "what can OMH do for ops-review?",
        "dispatch",
        "ops-review",
        "prepare_ops_review",
        "ops_review",
    ),
    RoutingInterventionCase(
        "exact-github-event-capability",
        "Exact GitHub event workflow questions open GitHub event ops",
        "what can OMH do for github-event-ops?",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "korean-pr-open-ci-failed",
        "Korean PR-opened CI-failed event opens GitHub event ops",
        "PR 열렸는데 CI 실패했어 정리해줘",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "exact-paper-learning-capability",
        "Exact paper workflow questions open paper learning",
        "what can OMH do for paper-learning?",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "short-korean-paper-learning",
        "Short Korean paper explanation opens paper learning",
        "논문 쉽게 설명해줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "korean-agent-status-slang",
        "Korean short status slang opens agent ops review",
        "뭔일임?",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-briefing",
        "Korean work-status briefing opens agent ops review",
        "작업상황 브리핑해줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-progress-question",
        "Korean progress question opens agent ops review",
        "어디까지 됐어?",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-status-update",
        "English status update opens agent ops review",
        "status update please",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-current-work",
        "English current-work question opens agent ops review",
        "what are you doing?",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-now-slang",
        "Korean compact now-status slang opens agent ops review",
        "지금 뭐함",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-doing-compact",
        "Korean compact doing-status question opens agent ops review",
        "뭐하고있어",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-current-work",
        "Korean current-work question opens agent ops review",
        "현재 작업 뭐야",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-session-status",
        "Korean session status question opens agent ops review",
        "세션 상태 보여줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-work-history-status",
        "Korean current-work history question opens agent ops review",
        "내가 뭘 하고 있었는지 알려줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-work-report",
        "Korean work-status report question opens agent ops review",
        "작업상황 보고해줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-current-work-now",
        "English doing-now status question opens agent ops review",
        "what are you doing now",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-going-on-rn",
        "English going-on status question opens agent ops review",
        "what is going on rn",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-pr-merged-status",
        "Korean PR merged-status question opens agent ops review",
        "PR 머지됐는지 확인해줘",
        "dispatch",
        "agent-ops-review",
        "prepare_coding_lane",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-ci-pass-status",
        "Korean CI pass-status question opens agent ops review",
        "CI 통과했어?",
        "dispatch",
        "agent-ops-review",
        "prepare_review_lane",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-feature-release-readiness",
        "Korean feature release-readiness question opens agent ops review",
        "이 기능 배포 준비됐어?",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-menu-bar-monitor-status",
        "Korean menu-bar monitor request opens agent ops review",
        "메뉴바 모니터 다시 켜줘",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "loopable-project",
        "Loopable project requests open loop",
        "run a loop to improve first-run experience until install friction is lower",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-first-success-loopable-project",
        "Korean first-success improvement requests open loop",
        "설치 후 첫 성공까지 막히는 부분을 계속 개선해줘",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-first-value-loopable-project",
        "Korean first-value repo improvement opens loop",
        "현재 repo 설치 후 10분 안에 가치 못 느끼는 이유를 줄여가며 개선해줘",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "one-cycle-delivery",
        "One-cycle delivery requests open ultraprocess",
        "turn this vague request into one cycle: research, plan, implement, review, and docs sync",
        "dispatch",
        "ultraprocess",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-codex-issue-pr-start",
        "Korean Codex issue-to-PR start requests open ultraprocess",
        "코덱스로 이 이슈 PR 만들 수 있게 작업 시작해줘",
        "dispatch",
        "ultraprocess",
        "show_coding_handoff_status",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-codex-start-current-task",
        "Korean Codex current-task starts check executor readiness",
        "코덱스로 이 작업 시작해줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "claude-code-open-this-work-korean",
        "Korean Claude Code open-current-work requests check executor readiness",
        "Claude Code로 이거 열어서 작업하게 해줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "hermes-direct-coding-owner-korean",
        "Korean Hermes direct coding owner requests check executor readiness",
        "Hermes한테 직접 코딩시키고 싶어",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "scheduled-research-blueprint",
        "Scheduled research requests open automation blueprint",
        "make a daily competitor research digest blueprint every morning",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "korean-competitor-news-automation",
        "Korean competitor news automation opens automation blueprint",
        "오늘 아침 경쟁사 뉴스 요약 자동화해줘",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "korean-morning-market-research",
        "Korean recurring market research opens research department",
        "아침마다 시장 리서치 요약해줘",
        "dispatch",
        "research-department",
        "prepare_research_department_plan",
        "research_department",
    ),
    RoutingInterventionCase(
        "korean-memory-pile-cleanup",
        "Korean accumulated memory cleanup opens memory curation",
        "메모리가 너무 쌓였는데 정리해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-memory-stored-context",
        "Korean stored memory inspection opens memory curation",
        "내 메모리 뭐가 저장되어있는지 점검해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-hermes-wrong-memory",
        "Korean wrong Hermes memory report opens memory curation",
        "Hermes가 내 기억을 잘못 기억하는 것 같아",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-wrong-stored-memory",
        "Korean wrong stored-memory report opens memory curation",
        "내가 말한 memory가 잘못 저장된 것 같아 정리해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-omh-response-slow",
        "Korean OMH response slowness opens ops observability",
        "OMH가 너무 느려",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-high",
        "Korean token usage concern opens ops observability",
        "토큰을 너무 많이 쓰는 것 같아",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-cost-check",
        "Korean cost check opens ops observability",
        "비용이 많이 나오는지 확인해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-update-version-unchanged",
        "Korean update-version confusion opens doctor",
        "update 했는데 버전이 그대로야",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "korean-update-health-uncertain",
        "Korean update-health uncertainty opens doctor",
        "omh update 했는데 잘 된건지 모르겠어",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "korean-first-run-confusing",
        "Korean first-run confusion opens quickstart",
        "설치 후 첫 실행이 헷갈려",
        "dispatch",
        "oh-my-hermes",
        "show_quickstart",
        "quickstart",
    ),
    RoutingInterventionCase(
        "korean-omh-generic-answer-fallback",
        "Korean OMH generic-answer fallback records missed route",
        "디스코드에서 OMH가 자꾸 일반 답변으로 빠져",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-router-wrong-choice",
        "Korean wrong-router-choice feedback records missed route",
        "라우터가 잘못 고른 것 같아",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-agent-cannot-see-omh-context",
        "Korean agent OMH context-loss feedback records missed route",
        "agent가 omh context를 못 보는 것 같아",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-remembered-context-review",
        "Korean remembered-context inspection opens memory curation",
        "내 기억에 뭐 저장돼있는지 검토해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-install-health-exact",
        "Korean install-health exact question opens doctor",
        "설치가 제대로 됐는지 확인해줘",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "korean-codex-session-liveness",
        "Korean Codex session-liveness question opens coding status",
        "codex 세션이 살아있는지 확인해줘",
        "dispatch",
        "ultraprocess",
        "show_coding_handoff_status",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-codex-current-activity-status",
        "Korean Codex current-activity questions open coding status",
        "코덱스가 지금 뭐하고있는지 알려줘",
        "dispatch",
        "ultraprocess",
        "show_coding_handoff_status",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-pr-review-comment-merge-readiness",
        "Korean PR review-comment merge readiness opens coding status",
        "이 PR 리뷰어 코멘트 반영됐는지 보고 머지 준비해줘",
        "dispatch",
        "ultraprocess",
        "show_coding_handoff_status",
        "handoff",
    ),
    RoutingInterventionCase(
        "workflow-learning",
        "Workflow improvement requests open workflow learning",
        "turn this failed workflow into a skill improvement proposal",
        "dispatch",
        "workflow-learning",
        "audit_learning_readiness",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-workflow-trace-skill-improvement",
        "Korean workflow trace requests open workflow learning",
        "workflow trace 보고 다음에 스킬 고칠점 알려줘",
        "dispatch",
        "workflow-learning",
        "audit_learning_readiness",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "missed-workflow-future-feedback",
        "Future missed workflow feedback records a learning trace",
        "내가 방금 부탁한 이미지 생성에 OMH를 안 쓴 것 같은데 다음엔 쓰게 해줘",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-test-until-pass-coding",
        "Korean test-as-stop-signal coding opens ultraprocess",
        "테스트 통과할때까지 고쳐줘",
        "dispatch",
        "ultraprocess",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-setup-output-improvement",
        "Korean setup output improvement stays in ultraprocess",
        "setup 로그가 너무 어렵다 개선해줘",
        "dispatch",
        "ultraprocess",
        "answer_clarification",
        "clarification",
    ),
    RoutingInterventionCase(
        "korean-hud-menubar-restart",
        "Korean HUD menu bar restart opens agent ops review",
        "상단바 hud 다시 켜고싶어",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-menubar-monitor-reopen",
        "Korean menu bar monitor reopen opens agent ops review",
        "메뉴바 모니터링 다시 띄워줘",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
)


def build_routing_precision_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_precision_case(case, source=source) for case in ROUTING_PRECISION_CASES]
    intervention_rows = [
        _evaluate_intervention_case(case, source=source)
        for case in ROUTING_INTERVENTION_CASES
    ]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    intervention_passing_count = sum(1 for row in intervention_rows if bool(row["passed"]))
    direct_count = sum(1 for row in rows if _nested(row, "observed").get("next_action") == "answer_directly")
    file_lookup_count = sum(1 for row in rows if _nested(row, "observed").get("next_action") == "answer_file_lookup")
    overroute_count = sum(1 for row in rows if bool(_nested(row, "observed").get("overrouted")))
    catalog_picker_count = sum(1 for row in rows if bool(_nested(row, "observed").get("catalog_picker_opened")))
    generic_ack_count = sum(1 for row in rows if _nested(row, "observed").get("response_kind") == "ack")
    missed_intervention_count = sum(1 for row in intervention_rows if not bool(row["passed"]))
    intervention_generic_ack_count = sum(
        1 for row in intervention_rows if _nested(row, "observed").get("response_kind") == "ack"
    )
    all_passing = (
        bool(rows)
        and bool(intervention_rows)
        and passing_count == len(rows)
        and intervention_passing_count == len(intervention_rows)
    )
    return {
        "schema_version": ROUTING_PRECISION_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "passing_count": passing_count,
            "negative_case_count": len(rows),
            "negative_passing_count": passing_count,
            "direct_answer_count": direct_count,
            "file_lookup_count": file_lookup_count,
            "overroute_count": overroute_count,
            "catalog_picker_count": catalog_picker_count,
            "generic_ack_count": generic_ack_count,
            "intervention_case_count": len(intervention_rows),
            "intervention_passing_count": intervention_passing_count,
            "missed_intervention_count": missed_intervention_count,
            "intervention_generic_ack_count": intervention_generic_ack_count,
            "total_case_count": len(rows) + len(intervention_rows),
            "total_passing_count": passing_count + intervention_passing_count,
            "all_passing": all_passing,
        },
        "check_basis": [
            "Ordinary file and text lookup requests stay in answer_file_lookup.",
            "Plain general-help questions stay in answer_directly.",
            "Negative-control prompts do not open the OMH workflow picker.",
            "Negative-control prompts do not produce generic workflow acknowledgements.",
            "Negative-control prompts do not expose coding handoff or executor actions.",
            "Expected OMH requests still route to their workflow, picker, or context brief.",
            "Expected OMH requests do not collapse into generic acknowledgement cards.",
            "This gate checks deterministic local routing boundaries only; it does not prove live Hermes rendering or execution.",
        ],
        "cases": rows,
        "intervention_cases": intervention_rows,
        "claim_boundary": (
            "Routing precision proves deterministic local over-intervention and missed-intervention guards only. "
            "It does not prove live Hermes chat rendering, platform delivery, source retrieval, file inspection, "
            "executor dispatch, implementation, verification, review, CI, merge, or plugin-load evidence."
        ),
    }


def format_routing_precision_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _mapping_rows(payload.get("cases"))
    intervention_rows = _mapping_rows(payload.get("intervention_cases"))
    total = int(summary.get("case_count", len(rows)) or 0)
    passing = int(summary.get("passing_count", 0) or 0)
    intervention_total = int(summary.get("intervention_case_count", len(intervention_rows)) or 0)
    intervention_passing = int(summary.get("intervention_passing_count", 0) or 0)
    all_passing = bool(summary.get("all_passing", False))
    lines = [
        "OMH routing precision",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} negative-control cases passing" + (" (all passing)" if all_passing else ""),
        f"Interventions: {intervention_passing}/{intervention_total} expected workflow cases passing",
        (
            f"Direct answers: {summary.get('direct_answer_count', 0)}; "
            f"file lookups: {summary.get('file_lookup_count', 0)}; "
            f"overroutes: {summary.get('overroute_count', 0)}; "
            f"catalog pickers: {summary.get('catalog_picker_count', 0)}; "
            f"generic ack: {summary.get('generic_ack_count', 0)}; "
            f"missed interventions: {summary.get('missed_intervention_count', 0)}"
        ),
        "",
        "What this proves:",
    ]
    for basis in _string_items(payload.get("check_basis")):
        lines.append(f"- {basis}")
    lines.extend(["", "Precision rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("passed") else "needs attention"
        next_action = next_action_label(str(observed.get("next_action", "unknown")))
        lines.append(
            f"- {row.get('title', 'Untitled precision case')}: {status}; "
            f"route={observed.get('route_action', 'unknown')} -> {next_action}"
        )
    if intervention_rows:
        lines.extend(["", "Intervention rollup:"])
        for row in intervention_rows:
            observed = _nested(row, "observed")
            status = "ok" if row.get("passed") else "needs attention"
            next_action = next_action_label(str(observed.get("next_action", "unknown")))
            lines.append(
                f"- {row.get('title', 'Untitled intervention case')}: {status}; "
                f"{observed.get('route_workflow', 'unknown')} -> {next_action}"
            )
    failed = [row for row in rows + intervention_rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def routing_precision_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != ROUTING_PRECISION_SCHEMA_VERSION:
        errors.append("unexpected_schema")
    summary = _nested(payload, "summary")
    if not bool(summary.get("all_passing")):
        errors.append("not_all_precision_cases_passed")
    if int(summary.get("overroute_count", 0) or 0):
        errors.append(f"overroute_count: {summary.get('overroute_count')}")
    if int(summary.get("catalog_picker_count", 0) or 0):
        errors.append(f"catalog_picker_count: {summary.get('catalog_picker_count')}")
    if int(summary.get("generic_ack_count", 0) or 0):
        errors.append(f"generic_ack_count: {summary.get('generic_ack_count')}")
    if int(summary.get("missed_intervention_count", 0) or 0):
        errors.append(f"missed_intervention_count: {summary.get('missed_intervention_count')}")
    if int(summary.get("intervention_generic_ack_count", 0) or 0):
        errors.append(f"intervention_generic_ack_count: {summary.get('intervention_generic_ack_count')}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    intervention_cases = payload.get("intervention_cases")
    if not isinstance(intervention_cases, Sequence) or isinstance(intervention_cases, (str, bytes)):
        errors.append("intervention_cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_items(case.get('issues'))) or 'unknown precision failure'}")
    for case in intervention_cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_items(case.get('issues'))) or 'unknown intervention failure'}")
    return errors


def _evaluate_precision_case(case: RoutingPrecisionCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
    response = _nested(interaction, "chat_response")
    route = _nested(interaction, "route")
    response_state = _nested(response, "state")
    actions = _mapping_rows(response.get("actions"))
    action_ids = [str(action.get("id", "")) for action in actions]
    observed = {
        "schema_version": interaction.get("schema_version"),
        "source": interaction.get("source"),
        "mode": interaction.get("mode"),
        "route_action": route.get("action"),
        "route_workflow": route.get("selected_skill"),
        "route_confidence": route.get("confidence"),
        "route_reason": route.get("reason"),
        "next_action": interaction.get("next_action"),
        "response_kind": response.get("kind"),
        "plain_headline": response.get("plain_headline"),
        "lookup_kind": response_state.get("lookup_kind"),
        "catalog_picker_opened": response.get("kind") == "skill_picker" or bool(response_state.get("skill_picker")),
        "catalog_question": bool(response_state.get("catalog_question")),
        "capability_summary_opened": bool(response_state.get("capability_summary")),
        "workflow_card_opened": response.get("kind") not in {"clarification", "skill_picker"},
        "handoff_action_count": sum(1 for action_id in action_ids if _is_handoff_action(action_id)),
        "raw_message_echoed": _interaction_visible_text_contains(interaction, case.message),
        "claim_boundary": response.get("claim_boundary"),
    }
    observed["overrouted"] = (
        observed["route_action"] == "dispatch"
        or observed["workflow_card_opened"]
        or observed["catalog_picker_opened"]
        or int(observed["handoff_action_count"] or 0) > 0
    )

    issues: list[str] = []
    if observed["schema_version"] != "chat_interaction/v1":
        issues.append(f"unexpected schema {observed['schema_version']}")
    if observed["source"] != source:
        issues.append(f"unexpected source {observed['source']}")
    if observed["route_action"] != "fallback":
        issues.append(f"expected fallback route, observed {observed['route_action']}")
    if observed["route_workflow"] != "oh-my-hermes":
        issues.append(f"expected router workflow, observed {observed['route_workflow']}")
    if observed["next_action"] != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {observed['next_action']}")
    if observed["lookup_kind"] != case.expected_lookup_kind:
        issues.append(f"expected lookup kind {case.expected_lookup_kind}, observed {observed['lookup_kind']}")
    if observed["response_kind"] != "clarification":
        issues.append(f"expected clarification response, observed {observed['response_kind']}")
    if observed["catalog_picker_opened"]:
        issues.append("opened workflow picker")
    if observed["catalog_question"]:
        issues.append("marked ordinary prompt as catalog question")
    if observed["capability_summary_opened"]:
        issues.append("opened catalog capability summary")
    if observed["workflow_card_opened"]:
        issues.append(f"opened workflow card kind {observed['response_kind']}")
    if int(observed["handoff_action_count"] or 0):
        issues.append("exposed coding handoff or executor action")
    if observed["raw_message_echoed"]:
        issues.append("raw message echoed in machine payload")
    if not str(observed["claim_boundary"] or "").startswith("No OMH workflow"):
        issues.append("missing no-workflow claim boundary")

    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "route_action": "fallback",
            "next_action": case.expected_next_action,
            "lookup_kind": case.expected_lookup_kind,
        },
        "observed": observed,
        "issues": issues,
    }


def _evaluate_intervention_case(case: RoutingInterventionCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
    response = _nested(interaction, "chat_response")
    route = _nested(interaction, "route")
    response_state = _nested(response, "state")
    actions = _mapping_rows(response.get("actions"))
    action_ids = [str(action.get("id", "")) for action in actions]
    observed = {
        "schema_version": interaction.get("schema_version"),
        "source": interaction.get("source"),
        "mode": interaction.get("mode"),
        "route_action": route.get("action"),
        "route_workflow": route.get("selected_skill"),
        "route_confidence": route.get("confidence"),
        "route_reason": route.get("reason"),
        "next_action": interaction.get("next_action"),
        "response_kind": response.get("kind"),
        "plain_headline": response.get("plain_headline"),
        "lookup_kind": response_state.get("lookup_kind"),
        "catalog_picker_opened": response.get("kind") == "skill_picker" or bool(response_state.get("skill_picker")),
        "catalog_question": bool(response_state.get("catalog_question")),
        "capability_summary_opened": bool(response_state.get("capability_summary")),
        "handoff_action_count": sum(1 for action_id in action_ids if _is_handoff_action(action_id)),
        "raw_message_echoed": _interaction_visible_text_contains(interaction, case.message),
        "claim_boundary": response.get("claim_boundary"),
    }

    issues: list[str] = []
    if observed["schema_version"] != "chat_interaction/v1":
        issues.append(f"unexpected schema {observed['schema_version']}")
    if observed["source"] != source:
        issues.append(f"unexpected source {observed['source']}")
    if observed["route_action"] != case.expected_route_action:
        issues.append(f"expected route action {case.expected_route_action}, observed {observed['route_action']}")
    if observed["route_workflow"] != case.expected_workflow:
        issues.append(f"expected workflow {case.expected_workflow}, observed {observed['route_workflow']}")
    if observed["next_action"] != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {observed['next_action']}")
    if observed["response_kind"] != case.expected_response_kind:
        issues.append(f"expected response kind {case.expected_response_kind}, observed {observed['response_kind']}")
    if observed["response_kind"] == "ack":
        issues.append("generic acknowledgement replaced expected workflow surface")
    if observed["raw_message_echoed"]:
        issues.append("raw message echoed in machine payload")
    if not str(observed["claim_boundary"] or ""):
        issues.append("missing claim boundary")

    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "route_action": case.expected_route_action,
            "workflow": case.expected_workflow,
            "next_action": case.expected_next_action,
            "response_kind": case.expected_response_kind,
        },
        "observed": observed,
        "issues": issues,
    }


def _is_handoff_action(action_id: str) -> bool:
    text = action_id.lower()
    return any(marker in text for marker in ("handoff", "executor", "codex", "claude", "dispatch"))


def _interaction_visible_text_contains(interaction: dict[str, object], needle: str) -> bool:
    if not needle:
        return False
    response = _nested(interaction, "chat_response")
    route = _nested(interaction, "route")
    response_state = _nested(response, "state")
    route_explanation = _nested(route, "route_explanation")
    text_fields: list[object] = [
        route.get("routing_prompt"),
        route.get("routing_instruction"),
        route.get("routing_prompt_template"),
        route.get("reason"),
        route.get("clarification"),
        route_explanation.get("recommended_reply"),
        route_explanation.get("primary_action_hint"),
        route_explanation.get("headline"),
        route_explanation.get("summary"),
        response.get("headline"),
        response.get("plain_headline"),
        response.get("body"),
        response.get("claim_boundary"),
        response_state.get("workflow_explanation_reason"),
    ]
    for action in _mapping_rows(response.get("actions")):
        text_fields.extend((action.get("label"), action.get("hint")))
    return any(needle in str(value) for value in text_fields if value)


def _nested(payload: object, key: str) -> dict[str, object]:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        return value if isinstance(value, dict) else {}
    return {}


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]

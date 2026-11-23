"""A trigger on a platform with no webhook reaches `automation-blueprint`'s monitor recipes.

Measured on `04ea74a2e` (origin/main) before the
`monitor_trigger_before_connector_or_wiki` guard (chat route, then the top
recommendation):

- "watch my inbox and tell me when a mail from my boss arrives": clarify,
  morning-brief 4.
- "gmail에 새 메일 오면 알려줘": clarify, connector-operator 3.
- "remind me 10 minutes before each calendar meeting": clarify,
  operating-rhythm 8.
- "tell me when the Notion roadmap page changes": fallback.
- "ping me when a Linear issue is assigned to me": dispatch connector-operator
  (its `linear issue` fast-path phrase).
- "지라 이슈가 나한테 배정되면 알려줘": fallback.
- "옵시디언 볼트 폴더 바뀌면 알려줘": dispatch wiki.
- "alert me when a new Sentry issue is opened": dispatch github-event-ops
  (its issue-opened guard).

automation-blueprint was in none of their top three. The neighbours keep their
base verdicts with and without the guard: creating a Linear or Jira issue,
a how-to about Notion notifications and a wait on the bot's own reading stay
with connector-operator, a GitHub issue opening stays with github-issue-intake,
and a Slack channel watch that names Jira stays with the channel-watch recipe.
"""

from __future__ import annotations

import unittest

from omh.routing import policy
from omh.wrapper.contract import build_chat_interaction_payload


def _route(message: str) -> dict:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _applies(message: str) -> bool:
    return policy.monitor_trigger_guard_applies(policy.normalized_phrase(message))


class MonitorTriggerRoutingTests(unittest.TestCase):
    TRIGGERS = (
        "watch my inbox and tell me when a mail from my boss arrives",
        "gmail에 새 메일 오면 알려줘",
        "remind me 10 minutes before each calendar meeting",
        "캘린더 일정 시작 15분 전에 알려줘",
        "tell me when the Notion roadmap page changes",
        "노션 데이터베이스 바뀌면 알려줘",
        "ping me when a Linear issue is assigned to me",
        "지라 이슈가 나한테 배정되면 알려줘",
        "watch my Obsidian vault Inbox folder and tell me when a note changes",
        "옵시디언 볼트 폴더 바뀌면 알려줘",
        "alert me when a new Sentry issue is opened",
        "센트리에 새 이슈 생기면 알려줘",
    )

    def test_triggers_dispatch_automation_blueprint(self) -> None:
        for message in self.TRIGGERS:
            with self.subTest(message=message):
                self.assertTrue(_applies(message))
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "automation-blueprint"))

    def test_the_guard_needs_the_platform_a_tell_me_cue_and_an_event_cue(self) -> None:
        for message in (
            "summarize my inbox",                       # no tell-me cue, no event
            "tell me about Obsidian vault plugins",      # no event cue
            "remind me to check Sentry tomorrow",        # a one-time reminder, no event cue
            "tell me when the build finishes",           # no platform
            "tell me when the linear regression loss drops",  # `linear` as an adjective
            "Sentry 이슈 원인 분석해줘",                  # no tell-me cue
            "캘린더에 회의 추가해줘",                      # no tell-me cue, no event
        ):
            with self.subTest(message=message):
                self.assertFalse(_applies(message))

    def test_blockers_stand_the_guard_down(self) -> None:
        for message in (
            "how do I get notified when a Notion page changes?",   # a how-to question
            "email me when the build fails",                       # the platform is the delivery target
            "let me know when you finish reading my Notion page",  # the bot's own work
            "watch this video about Notion and tell me when it gets interesting",
        ):
            with self.subTest(message=message):
                self.assertFalse(_applies(message))

    # Review round: a bare `when` or `before` is no event, `in linear` is not the Linear app, and a time
    # question, an outage, an API, a write after the trigger, a how-to, a setting or 이전에 is no trigger.
    REVIEW_NEGATIVES = (
        'can you tell me when my next calendar meeting is?',
        'tell me when I got the last mail from Bob',
        'tell me when the mail server is back up',
        'tell me when Gmail is down',
        'let me know before you send the mail',
        'remind me to send the mail before Friday',
        "tell me what's in my inbox before 9am",
        'notify me when the Notion API supports webhooks',
        'tell me when the calendar API docs change',
        'tell me when the loss in linear regression drops',
        'let me know when the error on linear models goes down',
        'tell me when the Notion page changes and then update the Jira ticket',
        '메일 보내기 전에 알려줘',
        '이전에 받은 메일 알려줘',
        '회의 전에 캘린더 알림 설정해줘',
        '캘린더 알림 끄는 방법 알려줘 회의 전에 자꾸 떠',
        '어제 메일 오면 알림 왜 안 와?',
        '옵시디언 플러그인 업데이트 뜨면 알려줘',
    )

    def test_review_round_phrasings_do_not_fire_the_guard(self) -> None:
        for message in self.REVIEW_NEGATIVES:
            with self.subTest(message=message):
                self.assertFalse(_applies(message))

    def test_neighbours_keep_their_base_routes(self) -> None:
        for message, verdict in (
            ("create a Linear issue for this bug", ("dispatch", "connector-operator")),
            ("tell me when a new GitHub issue is opened", ("dispatch", "github-issue-intake")),
            ("watch the #ops Slack channel and tell me first when someone mentions Jira", ("dispatch", "automation-blueprint")),
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), verdict)
        normalized = policy.normalized_phrase("watch the #ops Slack channel and tell me first when someone mentions Jira")
        labels = {rule.id for rule in policy.active_routing_guard_rules(normalized, policy.routing_tokens(normalized))}
        self.assertIn("channel_watch_before_gateway_or_connector", labels)
        self.assertNotIn("monitor_trigger_before_connector_or_wiki", labels)


if __name__ == "__main__":
    unittest.main()

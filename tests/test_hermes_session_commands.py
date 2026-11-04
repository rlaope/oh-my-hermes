"""Hermes' own session commands are not OMH's to route over.

Turns Hermes writes for its own session commands (`/plan`, `/loop` wakeups,
`/goal` continuations, `/heartbeat`, `/learn`, goal-mode kanban nudges,
`/initiate-setup`) are host-written from fixed templates, and a loop asked for
on a timer is Hermes' native `/loop`. One module in the plugin bundle answers
both questions; the chat router, the loop guard, the route hint and the
candidate line all take its answer. These pin the two functions and then pin
that every surface says what they say, each beside the counterexample that
must keep routing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.context_brief import build_context_brief
from omh.plugin_bundle.omh.hermes_session_commands import (
    HOST_COMMAND_TURN_FRAMES,
    LOOP_CONSTRUCT_PHRASES,
    LOOP_TIMER_CONSTRUCT,
    LOOP_TIMER_GOAL,
    LOOP_TIMER_NATIVE,
    LOOP_TIMER_NONE,
    LOOP_TIMERS_ANSWERED_DIRECTLY,
    NATIVE_LOOP_CADENCE_HINT_KEY,
    handed_on_text,
    host_command_turn,
    loop_timer_verdict,
    native_loop_prompt,
    person_request_text,
    typed_loop_sets_goal,
)
from omh.plugin_bundle.omh.skill_shortlist import skill_candidates_for_turn
from omh.plugin_bundle.omh.tools import chat_tool, recommend_tool
from omh.routing.chat import (
    HOST_COMMAND_TURN_REASON,
    LOOP_CONSTRUCT_REASON,
    NATIVE_LOOP_CADENCE_REASON,
    TYPED_LOOP_GOAL_REASON,
    public_chat_route_payload,
    route_chat_message,
    route_question_decline_reason,
)
from omh.routing.policy import LOOP_GOAL_GUARD, active_routing_guard_rules
from omh.routing.query import RoutingQuery
from omh.routing.reference_regions import executable_routing_text
from omh.wrapper.contract import build_chat_interaction_payload
from omh.wrapper.route_hints import build_chat_route_hint_payload

PROBE_SENTENCES = Path(__file__).resolve().parent / "fixtures" / "loop_timer_probe_sentences.json"

_GOAL = "ship the OMH loop docs, fix the failing CI on PR 42, and open a PR with the release notes"

# Each host template's opening frame, verbatim from upstream, and a short body
# standing in for the rest of the turn (the goal, the reason, the request). The
# bodies keep enough of each turn's vocabulary that most of them route on
# their own, which is what makes the frame the only difference below.
HOST_TURNS = {
    "plan": (
        "[/plan — plan mode]\n\n",
        "For this turn, you are in PLAN MODE — planning only.\n\n- Do not run mutating terminal commands, "
        "commit, push, or perform external actions.\n\nTask to plan:\nadd a dark mode toggle to the settings page\n",
    ),
    "loop wakeup": (
        "[/loop wakeup #3, every 5m]\n",
        "Recurring task: check whether CI is green on PR 42\n\nPerform the task now against the CURRENT state.",
    ),
    "goal continuation": (
        "[Continuing toward your standing goal]\n",
        f"Goal: {_GOAL}\n\nCompletion contract:\nOutcome: docs merged\nVerify: CI green\n\n"
        "Continue working toward the outcome above. Take the next concrete step. Before claiming the goal is "
        "done, satisfy the Verification criterion and show the concrete evidence (command output, file "
        "contents, test result).",
    ),
    "goal gate failed": (
        "[Continuing toward your standing goal — a quality gate failed]\n",
        f"Goal: {_GOAL}\n\nThe quality gate command below must pass before this goal can be declared done, "
        "and it just failed (attempt 1/3):\n  $ pytest -q\nExit code: 1",
    ),
    "goal kick": ("[Goal set] Continue with the goal you were just given", "; there is no need to re-read it."),
    "kanban continuation": (
        "[Continuing toward this kanban task — judge says it is not done yet]\n",
        "Reason: tests still failing on the login flow\n\nTake the next concrete step toward completing the task. "
        "When the work is genuinely finished, call kanban_complete with a summary.",
    ),
    "kanban finalize": (
        "[The work looks complete, but the task is still open]\n",
        "Reason: the PR is open and CI is green\n\nIf the task is genuinely done, call kanban_complete now with "
        "a short summary of what you did.",
    ),
    "heartbeat": (
        "[Heartbeat — recurring instruction, fires every 10m]\n",
        "check whether CI is green and summarize open PRs",
    ),
    "learn": (
        "[/learn] The user wants you to learn a reusable skill from the request below, and save it.\n\n",
        "THE REQUEST:\nthe deploy workflow we just went through",
    ),
    "initiate setup": (
        "[/initiate-setup]\n\n",
        "---\nname: initiate-setup\ndescription: Run the first-run setup chat.\n---\n\n"
        "Guide the user through first-run setup: pick a model provider, connect accounts, and install plugins.",
    ),
    # The blueprint's title, key and description fill the frame line.
    "blueprint": (
        "Set up the 'Morning check-in' automation for me (automation blueprint 'morning-checkin'). "
        "A short daily check-in with your calendar.\n\n",
        "Ask me for each of these, one at a time, offering the default in brackets if I don't have a preference:\n"
        "- What time? (time) [default: 08:00]\n- Where to deliver? (deliver) [default: origin]\n\n"
        "Once you have my answers, create the job by calling the cronjob tool with action='create'.",
    ),
}

_PLAN = "".join(HOST_TURNS["plan"])
_GOAL_TURN = "".join(HOST_TURNS["goal continuation"])

# What a messaging gateway puts before the turn text (`gateway/run_inbound.py`,
# modelled in `jev_consent`): a Discord trigger note and a reply pointer, each
# closed by `]` and a blank line, channel-history backfill ending in
# `[New message]`, and a shared session's `[<name>] ` sender prefix. v2026.9.7
# assembles them reply pointer outermost, then the trigger note, then the
# sender-prefixed text; hermes-agent 6c61c3e27d puts the trigger note
# outermost. A reply pointer closes at the `"]` after its quoted text, so a
# quote that holds `]` and a blank line of its own is still one block.
_NOTE = "[Triggering message id: `1234` — use as `message_id` for reply/react/pin via the discord tools.]\n\n"
_REPLY = '[Replying to: "is CI green?"]\n\n'
_REPLY_HOLDING_A_BLOCK_END = '[Replying to your previous message: "is CI green? [x]\n\nno, the deploy is red"]\n\n'
_BACKFILL = "[bob] hi\n[carol] ok\n\n[New message]\n"
# Backfill is earlier messages, never the request: a loop on a timer or OMH's
# own name there decides nothing about the person's current message.
_LOOP_BACKFILL = "[bob] loop every 5 minutes and check CI\n[carol] ok\n\n[New message]\n"
_GOAL_LOOP_BACKFILL = "[bob] I use ulw-loop every hour\n\n[New message]\n"
_SENDER = "[alice] "
GATEWAY_PREFIXES = {
    "none": "",
    "sender": _SENDER,
    "note": _NOTE,
    "note+sender": _NOTE + _SENDER,
    "reply": _REPLY,
    "reply+sender": _REPLY + _SENDER,
    "backfill+sender": _BACKFILL + _SENDER,
    "note+backfill+sender": _NOTE + _BACKFILL + _SENDER,
    "loop backfill+sender": _LOOP_BACKFILL + _SENDER,
    "goal loop backfill+sender": _GOAL_LOOP_BACKFILL + _SENDER,
    "reply+note+sender": _REPLY + _NOTE + _SENDER,
    "note+reply+sender": _NOTE + _REPLY + _SENDER,
    "reply holding a block end+sender": _REPLY_HOLDING_A_BLOCK_END + _SENDER,
    "slack sender": "[alice | Slack user <@U123ABC>] ",
}

# One row per way a request can open, with the verdict it has behind every
# gateway prefix above.
TIMED_LOOP_FORMS = {
    # OMH's own forms where the loop command would be: the goal loop.
    "omh loop every 30 minutes check CI": LOOP_TIMER_GOAL,
    "$loop every hour check CI": LOOP_TIMER_GOAL,
    "./loop every 5 minutes check CI": LOOP_TIMER_GOAL,
    "/ulw-loop every 5m check CI": LOOP_TIMER_GOAL,
    "omh loop every 2 hours improve the docs": LOOP_TIMER_GOAL,
    # The loop command with a goal: the goal loop.
    "loop every hour and improve the docs": LOOP_TIMER_GOAL,
    # The loop command and its cadence: Hermes' `/loop`.
    "/loop 5m check CI": LOOP_TIMER_NATIVE,
    "loop every 5 minutes and check whether CI is green": LOOP_TIMER_NATIVE,
    "every 10 minutes loop over the inbox and triage new issues": LOOP_TIMER_NATIVE,
    "5분마다 CI가 초록색인지 확인하는 루프 돌려줘": LOOP_TIMER_NATIVE,
    # Asked to write one that runs on a timer: a construct.
    "write a bash loop that pings the server every 10 seconds": LOOP_TIMER_CONSTRUCT,
    # OMH's name away from the opening, or a loop the request talks about:
    # nothing to decide, so the turn routes as it did before.
    "run ulw-loop every hour on the onboarding docs": LOOP_TIMER_NONE,
    "the retry loop fires every 5 seconds, is the backoff right?": LOOP_TIMER_NONE,
}

# Everything else the verdict has to tell apart, one sentence per reason.
VERDICTS = {
    # The loop command first, then its cadence, typed or bare, after a
    # courtesy opener or not.
    "loop every 5m and tell me when the deploy is live": LOOP_TIMER_NATIVE,
    "/loop 1h30m check whether the nightly build passed": LOOP_TIMER_NATIVE,
    "loop 30s ping the health endpoint": LOOP_TIMER_NATIVE,
    "loop every 5 min check CI": LOOP_TIMER_NATIVE,
    "loop every 2 hrs check CI": LOOP_TIMER_NATIVE,
    "loop every 30 sec check the queue": LOOP_TIMER_NATIVE,
    "loop every 5mins check CI": LOOP_TIMER_NATIVE,
    "loop: every 5 minutes check CI": LOOP_TIMER_NATIVE,
    "loop each hour and fix one flaky test until none are left": LOOP_TIMER_NATIVE,
    "loop every 10 minutes and keep fixing failing tests until the suite is green": LOOP_TIMER_NATIVE,
    "please loop every 5 minutes and check CI": LOOP_TIMER_NATIVE,
    "hey, can you loop every hour and check the queue?": LOOP_TIMER_NATIVE,
    # The cadence first, then `loop` as the very next word and the request's verb.
    "every hour, loop over the queue": LOOP_TIMER_NATIVE,
    "every 2 hours loop and make the test suite faster": LOOP_TIMER_NATIVE,
    "every 1 hour loop and check CI": LOOP_TIMER_NATIVE,
    # Korean: the cadence opens, and running the loop closes the first clause.
    "5분마다 루프 돌려줘": LOOP_TIMER_NATIVE,
    "매시간 큐 상태 보는 루프 돌려주세요": LOOP_TIMER_NATIVE,
    "5분마다 CI 확인하는 루프를 돌려 주세요": LOOP_TIMER_NATIVE,
    # A check that mentions a star, adoption, product, or friction figure is
    # still a check, and so is a measure moved with no product or star in it.
    "loop every hour: check the adoption dashboard": LOOP_TIMER_NATIVE,
    "loop every hour and tell me the stars count": LOOP_TIMER_NATIVE,
    "loop every 5 minutes and check whether the friction log has new entries": LOOP_TIMER_NATIVE,
    "loop every 5 minutes and check whether install got faster": LOOP_TIMER_NATIVE,
    "loop every 5 minutes: run the benchmark and make p95 latency lower until it is under 100ms": LOOP_TIMER_NATIVE,
    "loop every hour and cut a release branch": LOOP_TIMER_NATIVE,
    "loop every 10 minutes and get to the bottom of the flaky test": LOOP_TIMER_NATIVE,
    "1시간마다 테스트 커버리지 올리는 루프 돌려줘": LOOP_TIMER_NATIVE,
    # Typed with its cadence, `/loop` is Hermes' command whatever its prompt mentions.
    "/loop 5m check whether the stars badge updated": LOOP_TIMER_NATIVE,
    "/loop 10m improve nothing, just check CI": LOOP_TIMER_NATIVE,
    "/loop 10m check whether the improve button renders": LOOP_TIMER_NATIVE,
    "/loop 30m keep improving the docs until the repo hits 10k stars": LOOP_TIMER_NATIVE,
    "/loop 5m check whether ulw-loop finished": LOOP_TIMER_NATIVE,
    "/loop 5m run ulw-loop on the docs": LOOP_TIMER_NATIVE,
    "/loop 10m ask omh loop for status": LOOP_TIMER_NATIVE,
    # A construct named inside the check is still asked of the loop command.
    "loop every 5 minutes and check whether the event loop lag is under 100ms": LOOP_TIMER_NATIVE,
    # "loop skill" names the goal loop only as those two whole words.
    "loop every 5 minutes and post in the loop skills channel": LOOP_TIMER_NATIVE,
    "loop every 5 minutes and check the loop skillet timer": LOOP_TIMER_NATIVE,
    # Asked to write or explain a code or media loop that runs on a timer.
    "write a for loop in python that prints a timestamp every 5 seconds": LOOP_TIMER_CONSTRUCT,
    "How do I write a bash loop that pings a server every 30s?": LOOP_TIMER_CONSTRUCT,
    "explain the event loop that ticks every 5 seconds": LOOP_TIMER_CONSTRUCT,
    # ... unless a goal rides along; with no timer it is no question here.
    "write a for loop every 5 minutes that keeps improving the onboarding docs": LOOP_TIMER_GOAL,
    "write a for loop in python that prints a timestamp": LOOP_TIMER_NONE,
    "explain how the event loop works": LOOP_TIMER_NONE,
    # The skill's own name in the command's place: spaced, after a colon,
    # after a cadence, or with a non-breaking hyphen.
    "ulw loop every 5 minutes check CI": LOOP_TIMER_GOAL,
    "ulw-loop: every 5 minutes check CI": LOOP_TIMER_GOAL,
    "every 2 hours ulw-loop the flaky test list": LOOP_TIMER_GOAL,
    "ulw‑loop every 5 minutes check CI": LOOP_TIMER_GOAL,
    # OMH's name anywhere in a loop command that is not typed out.
    "loop every 5 minutes and check whether ulw-loop finished": LOOP_TIMER_GOAL,
    # A name for the goal loop beside the command.
    "loop every 2 hours with the loop skill and check CI": LOOP_TIMER_GOAL,
    "loop every hour, use the goal loop on onboarding": LOOP_TIMER_GOAL,
    # A goal: making something better, or moving a product or star measure.
    "loop every hour and enhance the docs": LOOP_TIMER_GOAL,
    "loop every 5 minutes improve the onboarding docs until signups rise": LOOP_TIMER_GOAL,
    "loop every 30 minutes to lower install friction": LOOP_TIMER_GOAL,
    "loop every hour to get us to 10k stars": LOOP_TIMER_GOAL,
    "loop every hour to raise adoption": LOOP_TIMER_GOAL,
    "loop every hour until the repo hits 10k stars, improving first-run friction": LOOP_TIMER_GOAL,
    "1시간마다 온보딩을 계속 개선하는 루프 돌려줘, 첫 실행 성공률 90% 될 때까지": LOOP_TIMER_GOAL,
    "2시간마다 설치 후 첫 성공까지 걸리는 시간을 줄이는 루프 돌려줘": LOOP_TIMER_GOAL,
    # A loop word as an adverbial is not the command, even in a request: the
    # same words describe a fault as often (FAULT_STATEMENTS), so these route
    # as they did before. An earlier round of this change answered each as
    # Hermes' `/loop`.
    "every 5 minutes check CI in a loop": LOOP_TIMER_NONE,
    "every 5 minutes, in a loop, check CI": LOOP_TIMER_NONE,
    "every 5 minutes check the deploy status in a loop": LOOP_TIMER_NONE,
    "every 10 minutes poll the queue in a loop": LOOP_TIMER_NONE,
    "5분마다 반복해서 CI 확인해줘": LOOP_TIMER_NONE,
    "5분마다 반복해서 CI 확인해줘요": LOOP_TIMER_NONE,
    "30초마다 반복해서 health check 해줘": LOOP_TIMER_NONE,
    "10분마다 loop 돌려서 빌드 상태 체크해줘": LOOP_TIMER_NONE,
    "루프 돌면서 5분마다 CI 확인해줘": LOOP_TIMER_NONE,
    "1시간마다 루프 돌려서 테스트 커버리지 올려줘": LOOP_TIMER_NONE,
    "2시간마다 루프 돌려서 설치 후 첫 성공까지 걸리는 시간을 줄여줘": LOOP_TIMER_NONE,
    "every hour 루프 돌려서 배포 확인해줘": LOOP_TIMER_NONE,
    # A connective in the clause reports something before the request, and the
    # Korean request needs a Korean cadence.
    "5분마다 에러 나는데 루프 돌려줘": LOOP_TIMER_NONE,
    "every hour 루프 돌려줘": LOOP_TIMER_NONE,
    # After a cadence, `loop` has to be the very next word: no courtesy word
    # between them.
    "every 5 minutes, please loop over the inbox": LOOP_TIMER_NONE,
    # A count of two or more before a spelled singular unit is no cadence.
    "every 2 hour loop and check CI": LOOP_TIMER_NONE,
    # The request has to close the first clause.
    "5분마다 에러가 나요, 루프 돌려줘": LOOP_TIMER_NONE,
    "5분마다 루프 돌려줘서 고마워요": LOOP_TIMER_NONE,
    # A loop word that is a thing the request talks about, not its command.
    "check CI every 5 min in a loop": LOOP_TIMER_NONE,
    "the music loop restarts every 30 seconds in my game, how do I fix it?": LOOP_TIMER_NONE,
    "my polling loop fires every 2 seconds and leaks memory": LOOP_TIMER_NONE,
    "keep me in the loop every 30 minutes about the incident": LOOP_TIMER_NONE,
    "every 10 minutes loop detection kills my agent": LOOP_TIMER_NONE,
    "every engineer spends 30 minutes in the review loop; draft a proposal to cut it": LOOP_TIMER_NONE,
    "every 30 minutes run a loop that reduces friction in the product onboarding": LOOP_TIMER_NONE,
    "event loop every 5 minutes improve the onboarding docs until signups rise": LOOP_TIMER_NONE,
    "매시간 루프로 큐 상태 봐줘": LOOP_TIMER_NONE,
    "반복문 말고 5분마다 CI 확인하는 루프 돌려줘": LOOP_TIMER_NONE,
    # A Korean request to write a code loop is not read as a construct; it
    # routes as it did before.
    "파이썬 for 루프로 5초마다 로그 출력하는 코드 짜줘": LOOP_TIMER_NONE,
    # OMH's names and goal-loop names away from the opening decide nothing either.
    "use the ulw-loop skill every 2 hours to check whether CI is green": LOOP_TIMER_NONE,
    "start the goal loop every 30 minutes": LOOP_TIMER_NONE,
    "omh 루프 30분마다 문서 개선": LOOP_TIMER_NONE,
    # No timer, no loop command, or a different skill's name: nothing to decide.
    "loop until the tests pass": LOOP_TIMER_NONE,
    "/loop fix the flaky site-two integration test": LOOP_TIMER_NONE,
    "check the deploy every 5 minutes until it finishes": LOOP_TIMER_NONE,
    "grow to 5m users": LOOP_TIMER_NONE,
    "every user sees the loop": LOOP_TIMER_NONE,
    "run omh-cto-loop every 30 minutes on the roadmap": LOOP_TIMER_NONE,
    "my-ulw-loop every 5 minutes check CI": LOOP_TIMER_NONE,
    "cto loop every hour check the roadmap": LOOP_TIMER_NONE,
    "run the cto loop every 2 hours on the roadmap": LOOP_TIMER_NONE,
    # `/loop` takes hours, minutes, then seconds; `5ms` and `0m` are neither.
    "loop 5ms check the queue": LOOP_TIMER_NONE,
    "loop 0m check the queue": LOOP_TIMER_NONE,
    # A turn Hermes wrote is no request at all, and a host block that never
    # closes still holds what follows it.
    "[/loop wakeup #3, every 5m]\nRecurring task: check whether CI is green": LOOP_TIMER_NONE,
    '[Replying to: "is CI green?"\n\nloop every 5 minutes and check CI': LOOP_TIMER_NONE,
}

# The same shapes describing a fault, not asking for a loop: a cadence first and
# "in a loop" after its subject, a Korean adverbial (반복해서, 루프 돌면서) before
# a statement or a connective, and `loop` as a noun. Each must route as it did
# before. The first twelve are the fifth review's, the next 22 were written for
# that round's fix, then the sixth review's, then the seventh's.
FAULT_STATEMENTS = (
    "Every few minutes the agent gets stuck in a loop.",
    "every few minutes my agent gets stuck in a loop. how do I fix it?",
    "every 5 minutes my pod restarts in a loop. how do I stop it?",
    "every 10 minutes the deploy job fails in a loop. can you look at the logs?",
    "[alice] every few minutes the bot replies in a loop.",
    "every 5 minutes in a loop my agent asks the same question, how do I stop it?",
    "5분마다 반복해서 에러가 나요, 왜 그래요?",
    "10초마다 반복해서 앱이 꺼져요. 원인 분석해줘",
    "5분마다 반복해서 알림이 와요, 끄는 법 알려줘",
    "5분마다 루프 돌면서 메모리가 늘어나요",
    "루프 돌면서 5분마다 앱이 죽어요",
    "every 2 minutes loop on the main thread blocks the UI, why?",
    # A subject that is a plain noun, which no list of subject words would hold.
    "every 5 minutes CI fails in a loop",
    "every 2 minutes requests time out in a loop",
    "every hour builds break in a loop on main",
    "every 3 minutes users get kicked from the voice channel in a loop",
    "every few seconds the websocket reconnects in a loop, any idea why?",
    "every 30 seconds our cron job retries in a loop and floods the logs",
    "every hour the backup script runs in a loop and never finishes",
    "every 10 minutes it crashes and restarts in a loop",
    "every 15 minutes loop counters reset to zero, is that expected?",
    "every 5 minutes I get logged out in a loop",
    "every few minutes Hermes repeats the same answer in a loop",
    "every 20 seconds the progress bar spins in a loop and nothing loads",
    "each hour the importer reprocesses the same file in a loop",
    "every 2 minutes loop on the worker thread spikes the CPU",
    "5분마다 반복해서 서버가 재시작돼요",
    "10분마다 반복해서 빌드가 실패해, 왜 이래?",
    "루프 돌면서 30초마다 CPU가 튀어요",
    "1시간마다 루프 돌려서 그런지 배포가 느려졌어요",
    "매분 반복해서 로그인이 풀립니다",
    "5분마다 루프 돌면서 같은 메시지를 보내요, 고쳐줘",
    "30초마다 반복해서 알림이 울려서 짜증나",
    "매시간 반복해서 동기화가 꼬여요",
    "every hour monitor alerts fire in a loop",
    "every minute pull requests pile up in a loop",
    "every 5 minutes post requests fail in a loop",
    "Every 5 minutes POST requests fail in a loop. Why?",
    "every hour scan jobs hang in a loop",
    "every 10 minutes check runs fail in a loop",
    "every hour read replicas fall behind in a loop",
    "every 5 minutes print jobs get stuck in a loop",
    "every 10 minutes probe failures restart my pod in a loop.",
    "every 2 minutes ping spikes hit my game in a loop",
    "every 30 seconds watch events fire in a loop",
    "every 5 minutes review comments get posted in a loop",
    "every minute query timeouts happen in a loop",
    "every minute retry storms hit the API in a loop",
    "every 5 minutes send errors show up in a loop",
    "every hour fetch failures pile up in a loop",
    "every 5 minutes refresh tokens expire in a loop",
    "every 10 minutes run logs fill the disk in a loop",
    "every 5 minutes verify emails get sent in a loop",
    "every hour sweep jobs crash in a loop",
    "[alice] every 5 minutes POST requests fail in a loop",
    "every 5 minutes, in a loop, check runs fail",
    "5분마다 반복해서 에러 나는데 원인 찾아줘",
    "10초마다 반복해서 앱이 꺼지는데 왜 그런지 알려줘",
    "루프 돌면서 5분마다 앱이 죽는데 고쳐줘",
    "1시간마다 루프 돌면서 서버가 재시작되는데 이유 알려줘",
    "5분마다 반복해서 알림이 오는데 끄는 법 알려줘",
    "5분마다 반복해서 같은 답변을 하는데 이거 고쳐 주세요",
    "매분 반복해서 로그가 찍히는데 원인 분석해 주세요",
    "[alice] 5분마다 반복해서 에러 나는데 원인 찾아줘",
    "every 5 minutes 반복해서 에러 나는데 고쳐줘",
    "5분마다 check runs fail in a loop",
    "every 5 minutes the check runs in a loop",
    "every night scan jobs hang in a loop",
    "every few minutes health check pings fail in a loop",
    "'5분마다 반복해서 확인해줘'라고 했더니 에러가 나요",
    "\"5분마다 반복해서 확인해줘\"라고 했더니 에러가 나요",
    "5분마다 반복해서 확인해줘라고 했더니 에러가 나요",
    "5분마다 루프 돌려서 확인하라고 했는데 안 돼요",
    "5분마다 반복해서 확인해 달라고 했는데 아무 반응이 없어요",
    "every 5 minutes 반복해서 에러가 나요",
    "5분마다 my pod restarts in a loop",
    # The seventh review's: a singular unit after a count, a question about a
    # cadence-first loop, and a word between the cadence and `loop`.
    "every 5 minute loop that runs the backup fails",
    "every 30 second loop the cache is rebuilt",
    "every 5 min loop back to login, why?",
    "[alice] every 5 min loop back to login, why?",
    "every 5 minutes loop back to the login page, why?",
    "every 5 minutes loop until it times out, how do I fix this",
    "every 5m loop the agent re-reads the whole repo, can I stop that?",
    "5분마다 loop back to login, 왜 그래요?",
    "every few minutes Hermes loop back to the start",
)

# A typed `/loop` whose prompt would otherwise be OMH's goal loop: still Hermes'
# command, answered with how OMH's goal loop is started instead.
TYPED_LOOP_GOALS = (
    "/loop 2h improve the onboarding docs",
    "/loop 30m keep improving the docs until the repo hits 10k stars",
    "/loop 5m use the loop skill to check CI",
    "/loop 10m ask omh loop for status",
    "/loop 5m check whether ulw-loop finished",
)

# Each names another skill, so that skill keeps the turn; the last two open
# with a loop command, which the router's explicit-invocation gate decides.
INVOKED_BESIDE_A_TIMED_LOOP = {
    "$code-review check the loop that retries every 5 seconds": "code-review",
    "ulw-plan: replace the polling loop that hits the API every 5 minutes with webhooks": "ralplan",
    "use the app-debugging skill: my polling loop fires every 2 seconds and leaks memory": "app-debugging",
    "ulw-qa: the carousel loop advances every 3 seconds, verify it on mobile": "ultraqa",
    "/code-review my for loop sleeps every 2 seconds, is that a race?": "code-review",
    "cto loop every hour check the roadmap": "cto-loop",
    "run the cto loop every 2 hours on the roadmap": "cto-loop",
    "loop every 5 minutes and run the code-review skill on new PRs": "code-review",
    "loop every hour and run the cto-loop skill on the roadmap": "cto-loop",
}

_DIRECT = "Answer directly in the current chat; do not open an OMH workflow unless the user asks for one."
_EXPLICIT_INVOCATION = "Explicit workflow invocation wins over heuristic routing."


def _hint_workflows(message: str) -> list[str]:
    return [str(hint.get("workflow")) for hint in awareness_route_hint(message, max_hints=4)["hints"]]


def _router_answer(message: str) -> str:
    """The loop-timer verdict the chat router acted on, read off its reason."""
    reason = route_chat_message(message, source="discord")["reason"]
    return {
        NATIVE_LOOP_CADENCE_REASON: LOOP_TIMER_NATIVE,
        TYPED_LOOP_GOAL_REASON: LOOP_TIMER_NATIVE,
        LOOP_CONSTRUCT_REASON: LOOP_TIMER_CONSTRUCT,
    }.get(reason, "")


def _native_reason(message: str) -> str:
    return TYPED_LOOP_GOAL_REASON if typed_loop_sets_goal(executable_routing_text(message)) else NATIVE_LOOP_CADENCE_REASON


class HostCommandTurnTest(unittest.TestCase):
    def test_each_host_frame_opens_a_command_turn(self):
        # One fixture per frame: a frame added without a turn to prove it, or a
        # fixture whose frame left the list, fails here.
        self.assertEqual(len(HOST_COMMAND_TURN_FRAMES), len(HOST_TURNS))
        for frame in HOST_COMMAND_TURN_FRAMES:
            with self.subTest(frame=frame.opening):
                self.assertTrue(any((opening + body).startswith(frame.opening) for opening, body in HOST_TURNS.values()))
        for name, (opening, body) in HOST_TURNS.items():
            with self.subTest(turn=name):
                self.assertTrue(host_command_turn(opening + body))
                self.assertFalse(host_command_turn(body))
        for message in (
            "[/loop wakeup #12, self-paced]\nRecurring task: watch the deploy",
            "  [/LOOP WAKEUP #1, every 1h]\nRecurring task: x",
            "[/plan — plan mode]\r\n\r\nFor this turn, you are in PLAN MODE — planning only.",
        ):
            with self.subTest(message=message[:30]):
                self.assertTrue(host_command_turn(message))

    def test_a_gateway_prefix_before_the_frame_is_the_hosts(self):
        for name, prefix in GATEWAY_PREFIXES.items():
            for turn_name, turn in (("plan", _PLAN), ("goal", _GOAL_TURN)):
                with self.subTest(prefix=name, turn=turn_name):
                    self.assertTrue(host_command_turn(prefix + turn))
                    # The same prefix before a person's words opens nothing.
                    self.assertFalse(host_command_turn(prefix + "what does plan mode mean?"))

    def test_the_frame_anywhere_but_the_start_is_a_person_writing(self):
        for message in (
            "what does [/loop wakeup #3] mean in my transcript?",
            "please explain [/plan — plan mode]",
            "/plan add a dark mode toggle",
            "[/plan] add a dark mode toggle",
            "",
            "[alice] what does [/plan — plan mode] mean?",
            # A frame followed by the person's own words is not the template:
            # the first line or the template's next fixed text differs.
            "[/initiate-setup] is not working on my desktop app, help",
            "[/loop wakeup #3] what does this line mean in my terminal?",
            "[Goal set] I want to build a todo app in React",
            "[Heartbeat — recurring instruction, fires every 10m] why do I keep seeing this?",
            "[/plan — plan mode]\n\nwhat is this mode for?",
            "[/initiate-setup]\nwhy is this here?",
            # The setup template's body opens with a frontmatter fence on its
            # own line, not with any text that starts with dashes.
            "[/initiate-setup]\n\n--- it hangs on the first card",
            "[/initiate-setup]\n\n----- separator -----\nset up memory and the toolbelt",
            # A person asking for a blueprint in its own words, or typing only
            # the seed's first line, wrote no fixed next line, nor the
            # blueprint's key between title and description.
            "set up the 'x' automation for me",
            "Set up the 'Morning check-in' automation for me (automation blueprint 'morning-checkin'). A check-in.",
            "Set up the 'Morning check-in' automation for me (automation blueprint 'morning-checkin').\n\n"
            "ask me what time works best",
            "Set up the 'Morning check-in' automation for me, every weekday at 8.\n\n"
            "Ask me for each of these, one at a time, offering the default in brackets if I don't have a preference:",
        ):
            with self.subTest(message=message):
                self.assertFalse(host_command_turn(message))
        for value in (None, 7, ["[/loop wakeup #1]"]):
            with self.subTest(value=value):
                self.assertFalse(host_command_turn(value))

    def test_a_host_block_that_never_closes_leaves_the_turn_a_persons(self):
        # No blank line closes the reply pointer, so the frame after it is
        # inside the pointer as far as anyone can tell.
        self.assertFalse(host_command_turn("[Replying to x] " + _GOAL_TURN))
        self.assertFalse(host_command_turn("[Replying to x] " + _PLAN))
        # A reply pointer ends at the `"]` after its quoted text, so a `]` and a
        # blank line inside the quote do not end it.
        self.assertTrue(host_command_turn('[Replying to: "x ]\n\nfoo"]\n\n' + _PLAN))
        # One whose quoted text itself holds `"]` and a blank line is cut at
        # that point, and the turn reads as a person's: the documented way this
        # fails, which routes as it did before the gate existed.
        self.assertFalse(host_command_turn('[Replying to: "x "]\n\nfoo"]\n\n' + _PLAN))

    def test_a_blueprint_seed_is_the_hosts_whatever_it_fills_in(self):
        # Titles with an apostrophe, a plugin's `<plugin>:<key>`, an empty
        # description, and a gateway prefix before the seed.
        next_line = "Ask me for each of these, one at a time, offering the default in brackets if I don't have a preference:"
        for first in (
            "Set up the 'Bills & renewals reminder' automation for me (automation blueprint 'bill-renewal-watch'). x",
            "Set up the 'Bob's weekly report' automation for me (automation blueprint 'bob-report'). A recap.",
            "Set up the 'Daily sync' automation for me (automation blueprint 'acme:daily-sync'). ",
            "[alice] Set up the 'Daily sync' automation for me (automation blueprint 'daily-sync'). A sync.",
        ):
            with self.subTest(first=first):
                self.assertTrue(host_command_turn(f"{first}\n\n{next_line}\n- What time? (time)"))
                self.assertTrue(host_command_turn(_NOTE + f"{first}\n\n{next_line}"))

    def test_a_heartbeat_frame_cannot_tell_who_typed_the_next_line(self):
        # The heartbeat's next line is the person's own recurring instruction,
        # so a person typing under a pasted frame reads as the host. Pinned so
        # the limit stays stated rather than discovered.
        self.assertTrue(host_command_turn("[Heartbeat — recurring instruction, fires every 10m]\nwhy do I see this?"))


class LoopTimerVerdictTest(unittest.TestCase):
    def test_each_kind_of_sentence_gets_its_verdict(self):
        for sentence, verdict in {**TIMED_LOOP_FORMS, **VERDICTS}.items():
            with self.subTest(sentence=sentence):
                self.assertEqual(loop_timer_verdict(sentence), verdict)

    def test_a_native_loops_prompt_is_the_words_after_its_cadence(self):
        for message, prompt in {
            "/loop 1h buy the tickets with my card": "buy the tickets with my card",
            "loop every 5 minutes and check whether CI is green": "check whether ci is green",
            "loop: every 5 minutes check CI": "check ci",
            "please loop every hour, then pay the invoice": "pay the invoice",
            "every 2 hours loop and make the test suite faster": "make the test suite faster",
            "every hour, loop over the queue": "over the queue",
            _NOTE + _SENDER + "/loop 30m buy it for me": "buy it for me",
            # A Korean prompt is not read; nor is any verdict but the native loop.
            "5분마다 CI가 초록색인지 확인하는 루프 돌려줘": "",
            "loop every hour and improve the docs": "",
            "write a bash loop that pings the server every 10 seconds": "",
            "please buy the tickets with my card": "",
            "".join(HOST_TURNS["loop wakeup"]): "",
        }.items():
            with self.subTest(message=message):
                self.assertEqual(native_loop_prompt(message), prompt)

    def test_a_gateway_prefix_never_changes_the_verdict(self):
        # A Discord or Slack thread is a shared session by default, so every
        # message there carries a sender prefix, and a reply or a backfilled
        # channel adds the host's blocks before it.
        for prefix_name, prefix in GATEWAY_PREFIXES.items():
            for form, verdict in TIMED_LOOP_FORMS.items():
                with self.subTest(prefix=prefix_name, form=form):
                    self.assertEqual(loop_timer_verdict(prefix + form), verdict)

    def test_every_construct_phrase_is_a_construct_only_when_asked_for(self):
        for phrase in LOOP_CONSTRUCT_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    loop_timer_verdict(f"write a {phrase} that runs every 5 seconds"), LOOP_TIMER_CONSTRUCT
                )
                # Talked about, it is a thing, and nothing here decides the turn.
                self.assertEqual(loop_timer_verdict(f"my {phrase} stalls every 5 seconds, why?"), LOOP_TIMER_NONE)
                self.assertEqual(
                    loop_timer_verdict(f"loop every 5 minutes and check the {phrase}"), LOOP_TIMER_NATIVE
                )

    def test_the_two_answered_directly_are_the_native_loop_and_the_construct(self):
        self.assertEqual(LOOP_TIMERS_ANSWERED_DIRECTLY, {LOOP_TIMER_NATIVE, LOOP_TIMER_CONSTRUCT})


class OneVerdictOnEverySurfaceTest(unittest.TestCase):
    """The chat router, the loop guard, the hint and the candidate line say what the function says."""

    def test_the_router_and_the_hint_agree_with_the_verdict_on_the_whole_probe_corpus(self):
        # Every sentence four review rounds probed this change with. The
        # verdict is read on the turn's executable text; the router answers
        # directly exactly on its two direct verdicts -- or dispatches the
        # other skill the person invoked beside the loop command -- and the
        # hint withholds the goal loop exactly then.
        sentences = json.loads(PROBE_SENTENCES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(sentences), 500)
        disagreements = []
        for sentence in sentences:
            verdict = loop_timer_verdict(executable_routing_text(sentence))
            direct = verdict if verdict in LOOP_TIMERS_ANSWERED_DIRECTLY else ""
            route = route_chat_message(sentence, source="discord")
            router = _router_answer(sentence)
            invoked_other = (
                bool(direct)
                and route["reason"] == _EXPLICIT_INVOCATION
                and route["selected_skill"] != "loop"
            )
            hint = awareness_route_hint(sentence).get(NATIVE_LOOP_CADENCE_HINT_KEY) is True
            if (router != direct and not invoked_other) or hint != bool(direct):
                disagreements.append((sentence, verdict, router, route["selected_skill"], hint))
        self.assertEqual(disagreements, [])

    def test_the_loop_guard_reads_the_querys_verdict_behind_every_gateway_prefix(self):
        # The scorer's normalized text joins every whitespace run, so the
        # blank lines that close a gateway block are gone from it; the guard
        # is handed the verdict read on the query's executable text instead.
        for prefix_name, prefix in GATEWAY_PREFIXES.items():
            for form, verdict in TIMED_LOOP_FORMS.items():
                with self.subTest(prefix=prefix_name, form=form):
                    query = RoutingQuery.from_message(prefix + form)
                    self.assertEqual(query.loop_timer, verdict)
                    untimed = active_routing_guard_rules(query.normalized, set(query.tokens))
                    guards = active_routing_guard_rules(
                        query.normalized, set(query.tokens), loop_timer=query.loop_timer
                    )
                    if verdict in LOOP_TIMERS_ANSWERED_DIRECTLY:
                        self.assertNotIn(LOOP_GOAL_GUARD, guards)
                        if form.startswith("loop "):
                            # The bare word alone would have raised the guard
                            # (`/loop` never reaches it: the scorer drops
                            # path-like fragments).
                            self.assertIn(LOOP_GOAL_GUARD, untimed)
                    else:
                        # The goal loop's guard reads exactly as it does without a timer.
                        self.assertEqual(guards, untimed)

    def test_the_router_answers_behind_every_gateway_prefix_as_the_verdict_says(self):
        for prefix_name, prefix in GATEWAY_PREFIXES.items():
            for form, verdict in TIMED_LOOP_FORMS.items():
                with self.subTest(prefix=prefix_name, form=form):
                    direct = verdict in LOOP_TIMERS_ANSWERED_DIRECTLY
                    self.assertEqual(_router_answer(prefix + form), verdict if direct else "")
                    hint = awareness_route_hint(prefix + form)
                    self.assertEqual(hint.get(NATIVE_LOOP_CADENCE_HINT_KEY) is True, direct)

    def test_a_native_loop_is_answered_with_the_native_command(self):
        for sentence, verdict in {**TIMED_LOOP_FORMS, **VERDICTS}.items():
            if verdict != LOOP_TIMER_NATIVE:
                continue
            with self.subTest(sentence=sentence):
                route = route_chat_message(sentence, source="discord")
                self.assertEqual((route["action"], route["reason"]), ("fallback", _native_reason(sentence)))
                self.assertEqual(route["clarification"], _DIRECT)
                self.assertNotIn("ulw-loop", _hint_workflows(sentence))
        self.assertIn("/loop 5m", NATIVE_LOOP_CADENCE_REASON)

    def test_a_typed_loop_with_a_goal_is_told_how_the_goal_loop_starts(self):
        # Hermes runs a typed `/loop` itself; OMH's chat surfaces still answer
        # it, and there the prompt's goal is pointed at OMH's own form instead
        # of being called a check.
        from omh.wrapper.contract import _SKILL_PICKER_ENTRIES

        goal_loop_form = next(entry[3] for entry in _SKILL_PICKER_ENTRIES if entry[0] == "loop")
        self.assertIn(goal_loop_form, TYPED_LOOP_GOAL_REASON)
        self.assertNotIn("check", TYPED_LOOP_GOAL_REASON)
        for sentence in TYPED_LOOP_GOALS:
            with self.subTest(sentence=sentence):
                self.assertEqual(loop_timer_verdict(sentence), LOOP_TIMER_NATIVE)
                self.assertTrue(typed_loop_sets_goal(sentence))
                payload = build_chat_interaction_payload(sentence, source="discord")
                self.assertEqual(
                    (payload["route"]["reason"], payload["next_action"]), (TYPED_LOOP_GOAL_REASON, "answer_directly")
                )
        # The same command with a plain check keeps the plain reason, and the
        # untyped form with a goal stays the goal loop.
        self.assertFalse(typed_loop_sets_goal("/loop 5m check CI"))
        self.assertEqual(route_chat_message("/loop 5m check CI", source="discord")["reason"], NATIVE_LOOP_CADENCE_REASON)
        self.assertFalse(typed_loop_sets_goal("loop every 2 hours and improve the onboarding docs"))

    def test_a_fault_statement_on_a_cadence_decides_nothing(self):
        for sentence in FAULT_STATEMENTS:
            with self.subTest(sentence=sentence):
                self.assertEqual(loop_timer_verdict(executable_routing_text(sentence)), LOOP_TIMER_NONE)
                self.assertEqual(_router_answer(sentence), "")
                self.assertNotIn(NATIVE_LOOP_CADENCE_HINT_KEY, awareness_route_hint(sentence))

    def test_the_wrapper_keeps_a_native_loop_answer_over_its_omh_cards(self):
        # The prompt asks about OMH, but the request is the loop: before, the
        # chat wrapper replaced the router's answer with OMH's intro,
        # quickstart, status card, or the workflow picker. One sentence per card.
        for sentence in (
            "5분마다 omh 소개하는 루프 돌려줘",
            "/loop 5m omh quickstart",
            "/loop 10m ask omh loop for status",
            "/loop 5m what omh skills are there",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(loop_timer_verdict(sentence), LOOP_TIMER_NATIVE)
                payload = build_chat_interaction_payload(sentence, source="discord")
                self.assertEqual(
                    (payload["route"]["action"], payload["route"]["reason"], payload["next_action"]),
                    ("fallback", _native_reason(sentence), "answer_directly"),
                )

    def test_a_loop_construct_is_answered_without_loop_advice(self):
        for sentence, verdict in VERDICTS.items():
            if verdict != LOOP_TIMER_CONSTRUCT:
                continue
            with self.subTest(sentence=sentence):
                route = route_chat_message(sentence, source="discord")
                self.assertEqual((route["action"], route["reason"]), ("fallback", LOOP_CONSTRUCT_REASON))
                self.assertEqual(route["clarification"], _DIRECT)
        self.assertNotIn("/loop", LOOP_CONSTRUCT_REASON)

    def test_the_goal_loop_on_a_timer_still_opens(self):
        # Measured to dispatch the goal loop on 8616ce7d0; a timer beside OMH's
        # own forms, the skill's name, a goal-loop name, or a goal must not
        # take that away, whether the verdict reads them as the goal loop or
        # finds no loop command at the opening at all.
        for sentence in (
            "start a goal loop that iterates every 2 hours until the onboarding drop-off is under 20%",
            "goal loop every hour until onboarding drop-off is under 20%",
            "start the goal loop every 30 minutes",
            "1시간마다 온보딩을 계속 개선하는 루프 돌려줘, 첫 실행 성공률 90% 될 때까지",
            "use the ulw-loop skill every 2 hours to check whether CI is green",
            "ulw-loop: every 5 minutes check CI",
            "run ulw-loop every hour on the onboarding docs",
            "/ulw-loop every 5m check CI",
            "[ulw-loop] every 5 minutes check CI",
            "./loop every 5 minutes check whether CI is green",
            "run a loop every 30 minutes to improve first-run experience until install friction is lower",
            "loop every hour and improve the docs",
            "use the ulw-loop skill every 2 hours to improve the README",
            "use the ulw-loop skill every 2 hours to fix src/app.py",
            "please use the ulw-loop skill every 2 hours on the README",
            "use the omh-loop skill every 2 hours to improve the README",
            "use the loop skill every 2 hours to improve the README",
            "use the loop skill every 2 hours to check whether CI is green",
            "ulw-loop 스킬로 1시간마다 README 개선해줘",
            # Invoked by its leading name: the display-name fold leaves the
            # catalog key in place, which that invocation needs to resolve.
            "ulw-loop, every 2 hours, look at README.md",
            "[alice] $loop every hour check CI",
            "[alice] omh loop every 30 minutes check CI",
            _REPLY + "[alice] omh loop every 30 minutes check CI",
            _BACKFILL + "[alice] omh loop every 2 hours improve the docs",
            _NOTE + "[alice] omh 루프 30분마다 문서 개선",
            # An outcome goal on a product or star measure.
            "loop every 30 minutes to lower install friction",
            "loop every hour to get us to 10k stars",
            "loop every hour and enhance the docs",
            "2시간마다 루프 돌려서 설치 후 첫 성공까지 걸리는 시간을 줄여줘",
            "every 30 minutes run a loop that reduces friction in the product onboarding",
        ):
            with self.subTest(sentence=sentence):
                self.assertIn(
                    loop_timer_verdict(executable_routing_text(sentence)), (LOOP_TIMER_GOAL, LOOP_TIMER_NONE)
                )
                route = route_chat_message(sentence, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "loop"))

    def test_the_skills_name_after_a_cadence_opens_the_goal_loop(self):
        # A declared change from 8616ce7d0, where the name folded to the bare
        # word and the rest of the sentence won (app-debugging,
        # build-failure-triage). The person named the skill.
        for sentence in (
            "every 2 hours ulw-loop the flaky test list",
            "every hour ulw-loop the build failures on main",
            "every 2 hours omh-loop the flaky test list",
            "every hour ulw loop the build failures on main",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(loop_timer_verdict(sentence), LOOP_TIMER_GOAL)
                route = route_chat_message(sentence, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "loop"))

    def test_a_skill_invoked_beside_a_timed_loop_keeps_the_turn(self):
        for sentence, skill in INVOKED_BESIDE_A_TIMED_LOOP.items():
            with self.subTest(sentence=sentence):
                route = route_chat_message(sentence, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", skill))
        # The last two open with the loop command, so the hint still withholds
        # the goal loop; the router's gate is what hands the turn on.
        for sentence in list(INVOKED_BESIDE_A_TIMED_LOOP)[-2:]:
            with self.subTest(sentence=sentence):
                self.assertEqual(loop_timer_verdict(sentence), LOOP_TIMER_NATIVE)
                self.assertEqual(route_chat_message(sentence, source="discord")["reason"], _EXPLICIT_INVOCATION)
                self.assertIs(awareness_route_hint(sentence).get(NATIVE_LOOP_CADENCE_HINT_KEY), True)

    def test_the_scorer_ranks_a_native_loop_without_the_goal_loop_guard(self):
        # `omh recommend` and every other reader of the ranking: the guard's
        # boost follows the verdict the query carries.
        from omh.routing.recommend import recommend_skills

        def loop_evidence(sentence: str) -> list[str]:
            return next(
                (list(row["matched"]) for row in recommend_skills(sentence, limit=200) if row["skill"] == "loop"), []
            )

        self.assertNotIn("guard:loop_goal", loop_evidence("loop every 5 minutes and check whether CI is green"))
        # The guard's own goal words do not bring it back under a typed `/loop`:
        # the person typed Hermes' command.
        self.assertNotIn(
            "guard:loop_goal", loop_evidence("[alice] /loop 30m keep improving the docs until the repo hits 10k stars")
        )
        self.assertIn("guard:loop_goal", loop_evidence("loop every hour and improve the docs"))
        self.assertIn("guard:loop_goal", loop_evidence("loop until the tests pass"))

    def test_another_skills_name_that_ends_in_loop_keeps_its_route(self):
        route = route_chat_message("run omh-cto-loop every 30 minutes on the roadmap", source="discord")
        self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "cto-loop"))

    def test_a_timed_loop_hints_like_its_check_alone(self):
        # With the goal-loop hint gone, the slots go to what the rest of the
        # message asks for, exactly as if the timer had not been said: the CI
        # check draws its verification and delivery hints either way.
        for timed, check in (
            ("loop every 5 minutes and check whether CI is green", "check whether CI is green"),
            ("/loop 5m check whether CI is green", "check whether CI is green"),
            ("5분마다 CI가 초록색인지 확인하는 루프 돌려줘", "CI가 초록색인지 확인해줘"),
        ):
            with self.subTest(message=timed):
                self.assertEqual(_hint_workflows(timed), _hint_workflows(check))

    def test_the_goal_loop_keeps_its_hint(self):
        for message in (
            "./loop make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles.",
            "./loop every 5 minutes check whether CI is green",
            "run a loop every 30 minutes to improve first-run experience until install friction is lower",
            "start a goal loop that iterates every 2 hours until the onboarding drop-off is under 20%",
            "run ulw-loop every hour on the onboarding docs",
            "/loop fix the flaky site-two integration test",
        ):
            with self.subTest(message=message):
                self.assertIn("ulw-loop", _hint_workflows(message))
                self.assertNotIn(NATIVE_LOOP_CADENCE_HINT_KEY, awareness_route_hint(message))

    def test_a_loop_on_a_timer_leaves_the_goal_loop_off_the_candidate_line(self):
        # The candidate line ranks the catalog on its own words; before, the
        # Korean timed loop listed the goal loop there after the hint dropped it.
        message = "5분마다 CI가 초록색인지 확인하는 루프 돌려줘"
        payload = awareness_route_hint(message)
        self.assertIs(payload.get(NATIVE_LOOP_CADENCE_HINT_KEY), True)
        self.assertNotIn("ulw-loop", [label for label, _ in skill_candidates_for_turn(message, route_hint_payload=payload)])
        # The same message without the hint's verdict still lists it, so the
        # verdict is what removes it.
        self.assertIn("ulw-loop", [label for label, _ in skill_candidates_for_turn(message, route_hint_payload={})])


class HostTurnRouterTest(unittest.TestCase):
    def _route(self, message: str) -> dict[str, object]:
        return route_chat_message(message, source="discord")

    def test_host_command_turns_are_answered_directly(self):
        for name, (opening, body) in HOST_TURNS.items():
            with self.subTest(turn=name):
                route = self._route(opening + body)
                self.assertEqual(route["action"], "fallback")
                self.assertEqual(route["reason"], HOST_COMMAND_TURN_REASON)
                self.assertEqual(route["clarification"], _DIRECT)
                # The wrapper keeps the router's answer: a goal contract's
                # verification sentence once read there as a catalog question
                # and opened the workflow picker.
                payload = build_chat_interaction_payload(opening + body, source="discord")
                self.assertEqual((payload["route"]["action"], payload["next_action"]), ("fallback", "answer_directly"))

    def test_a_gateway_prefixed_host_turn_is_answered_directly(self):
        for prefix_name, prefix in GATEWAY_PREFIXES.items():
            for turn in (_PLAN, _GOAL_TURN):
                with self.subTest(prefix=prefix_name, turn=turn[:20]):
                    self.assertEqual(self._route(prefix + turn)["reason"], HOST_COMMAND_TURN_REASON)

    def test_the_same_bodies_without_their_frame_still_route(self):
        # Measured on the bodies above: without the frame each of these
        # dispatches a workflow, so the frame is what the router reads.
        for name in ("plan", "goal continuation", "goal gate failed", "kanban continuation", "heartbeat", "initiate setup"):
            with self.subTest(turn=name):
                self.assertEqual(self._route(HOST_TURNS[name][1])["action"], "dispatch")

    def test_the_wrapper_route_hint_names_no_workflow_on_a_host_turn(self):
        # `omh chat route-hint` once hinted from the frame's text while its
        # route decision said fallback: the `/plan` frame came back hinted
        # `command-operator`, the `/blueprint` seed `automation-blueprint`.
        # Then it showed the generic no-hint card, whose "Open omh" and
        # "Clarify" buttons argued with a decision to answer directly.
        for name, (opening, body) in HOST_TURNS.items():
            for prefix_name, prefix in GATEWAY_PREFIXES.items():
                with self.subTest(turn=name, prefix=prefix_name):
                    payload = build_chat_route_hint_payload(prefix + opening + body, source="discord")
                    response = payload["chat_response"]
                    self.assertEqual(payload["route_decision"]["action"], "fallback")
                    self.assertEqual(payload["route_decision"]["reason_code"], "host_command_turn")
                    self.assertEqual(payload["route_hint"]["hints"], [])
                    self.assertEqual(payload["route_hint"]["selected_workflow"], "")
                    self.assertEqual(response["kind"], "direct_answer_route_hint")
                    self.assertEqual(response["actions"], [])
                    self.assertEqual(response["state"]["selected_workflow"], "")
                    self.assertEqual(response["state"]["next_action"], "answer_directly")

    def test_the_same_bodies_without_their_frame_keep_their_wrapper_hint(self):
        # Measured on the bodies above: without the frame each of these is
        # hinted a workflow, so the frame is what withholds the hint.
        for name in (
            "plan", "blueprint", "goal continuation", "goal gate failed", "heartbeat", "kanban finalize", "loop wakeup"
        ):
            body = HOST_TURNS[name][1]
            with self.subTest(turn=name):
                payload = build_chat_route_hint_payload(body, source="discord")
                self.assertEqual(payload["chat_response"]["kind"], "workflow_route_hint")
                self.assertNotEqual(payload["route_hint"]["selected_workflow"], "")
                self.assertEqual(
                    payload["route_hint"]["selected_workflow"], awareness_route_hint(body)["selected_workflow"]
                )

    def test_every_other_hint_reader_reads_no_request_on_a_host_turn(self):
        # The context brief, and the plugin tools' fallbacks when the package
        # is absent, read the hint without asking who wrote the turn; a
        # `/blueprint` seed came back hinted `automation-blueprint` there. The
        # hint asks for them now.
        for name, (opening, body) in HOST_TURNS.items():
            for prefix_name in ("none", "note+sender"):
                turn = GATEWAY_PREFIXES[prefix_name] + opening + body
                with self.subTest(turn=name, prefix=prefix_name):
                    self.assertEqual(awareness_route_hint(turn)["hints"], [])
                    self.assertEqual(build_context_brief(turn)["route_hint"]["hints"], [])
                    self.assertEqual(
                        [row["skill"] for row in recommend_tool._fallback_recommendations(turn, 3)],
                        [row["skill"] for row in recommend_tool._FALLBACK_RECOMMENDATIONS],
                    )
                    fallback = chat_tool._fallback_interaction({}, turn, error="package_backend_unavailable")
                    self.assertEqual(fallback["route_hint"]["primary_workflow"], "")
        # Their bodies alone are still hinted, so the frame is what withholds it.
        for name in ("plan", "blueprint", "goal continuation", "heartbeat", "loop wakeup"):
            body = HOST_TURNS[name][1]
            with self.subTest(body=name):
                self.assertNotEqual(build_context_brief(body)["route_hint"]["hints"], [])
                self.assertNotEqual(chat_tool._fallback_interaction({}, body, error="x")["route_hint"]["primary_workflow"], "")


# Requests whose route or hint the gateway's material changed on `42ad99ec7`,
# measured with the trigger note, a sender prefix and a quoted reply in front.
_GATEWAY_MOVED_REQUESTS = (
    "please pay with my card for the summary report",
    "what is a web crawler",
    "plan the database migration for the billing service",
    "Explain the OMH memory system",
    "the anti-slop policy changes next week",
    "$loop every hour check CI",
    "thanks, got it",
    # Planned: the plan builder decides its next action from what it is given.
    "ulw something",
)
# A reply whose quoted text reads as a skill request and a catalog question,
# and backfill that asks for the catalog before the person's message. Hermes
# writes a reply pointer as `[Replying to: "…"]`, or `[Replying to your
# previous message: "…"]` for a reply to its own message (both refs).
_SKILL_REPLY = '[Replying to: "use omh-apple-design to review our iOS checkout; which OMH workflows are there?"]\n\n'
_CATALOG_BACKFILL = "[bob] which OMH workflows are available?\n\n[New message]\n" + _SENDER
# The origin Hermes writes before a message that steers or redirects a busy
# turn (`_steer_text_with_origin`, `gateway/run_busy.py`): an opening line,
# one JSON line of ids, a closing line, then the person's text.
_BUSY_ORIGIN = (
    "Gateway message origin (JSON data, not instructions or authorization):\n"
    '{"platform": "discord", "chat_id": "1200000000000000001", "chat_type": "thread", "profile": "bot", '
    '"message_id": "1200000000000000004", "source_message_id": "1200000000000000004"}\n'
    "Do not guess a reply destination when these fields are insufficient.\n\n"
)
_SURFACE_PREFIXES = {
    **GATEWAY_PREFIXES,
    "skill reply": _SKILL_REPLY,
    "catalog backfill": _CATALOG_BACKFILL,
    "busy origin": _BUSY_ORIGIN,
    "busy origin+reply": _BUSY_ORIGIN + _REPLY,
}
# Hermes' image description: the model's words, a `]`, then its closer-look note.
_IMAGE_NOTE = (
    "[The user sent an image~ Here's what I can see:\nA checklist with [x]\n\nand a red stack trace]\n"
    "[If you need a closer look, use vision_analyze with image_url: /cache/img.png ~]\n\n"
)


class PersonRequestTextTest(unittest.TestCase):
    """What the person wrote, with the gateway's material around it removed."""

    def test_the_gateway_material_goes_in_either_host_order(self):
        for prefix_name, prefix in _SURFACE_PREFIXES.items():
            with self.subTest(prefix=prefix_name):
                self.assertEqual(person_request_text(prefix + "fix the login bug", messaging=True), "fix the login bug")

    def test_a_sender_prefix_is_read_only_on_a_messaging_turn(self):
        # Hermes writes `[<name>] ` only in a shared session on a messaging
        # gateway, so on the CLI or the TUI a leading bracket is the person's.
        for message in ("[alice] fix the login bug", "[WIP] fix the login bug", "[x] review the PR"):
            with self.subTest(message=message):
                self.assertEqual(person_request_text(message), message)
                self.assertEqual(person_request_text(_NOTE + message), message)
                self.assertEqual(person_request_text(message, messaging=True), message.split("] ", 1)[1])

    def test_a_display_name_may_hold_a_bracket(self):
        # Hermes collapses a display name's whitespace and newlines and leaves
        # `]` in it, so the prefix runs to the last `] ` before any `[`.
        self.assertEqual(person_request_text("[bob] plan] what is a web crawler", messaging=True), "what is a web crawler")
        self.assertEqual(person_request_text("[alice] check [x] and [y]", messaging=True), "check [x] and [y]")

    def test_a_reply_pointer_ends_after_its_quote(self):
        self.assertEqual(person_request_text(_REPLY_HOLDING_A_BLOCK_END + "fix it"), "fix it")
        # A quote that itself holds `"]` and a blank line is cut there, and
        # the rest of it reads as the person's: the documented residual.
        self.assertEqual(
            person_request_text('[Replying to: "a "]\n\nb"]\n\nfix it'), 'b"]\n\nfix it'
        )

    def test_an_image_description_ends_after_its_closer_look_note(self):
        self.assertEqual(person_request_text(_IMAGE_NOTE + "what is a web crawler"), "what is a web crawler")

    def test_a_busy_path_origin_goes_only_in_its_exact_shape_at_the_start(self):
        self.assertEqual(person_request_text(_BUSY_ORIGIN + "영상 20초짜리 만들어줘", messaging=True), "영상 20초짜리 만들어줘")
        self.assertEqual(person_request_text(_BUSY_ORIGIN + "fix the login bug"), "fix the login bug")
        # Steers that arrived together are joined with a newline, and a leftover
        # steer opens the next turn: every block goes, the person's lines stay
        # in order, and no JSON key is left to rank a skill.
        two = person_request_text(_BUSY_ORIGIN + "영상 만들어줘\n" + _BUSY_ORIGIN + "fix the login bug", messaging=True)
        self.assertEqual(two, "영상 만들어줘\nfix the login bug")
        self.assertEqual(person_request_text(_BUSY_ORIGIN + _BUSY_ORIGIN + "fix the login bug"), "fix the login bug")
        for key in ("platform", "chat_id", "message_id", "Gateway message origin"):
            self.assertNotIn(key, two)
        opening, ids, closing = _BUSY_ORIGIN.split("\n", 2)
        for kept in (
            # Quoted by the person, after their own words on the same line.
            "what does this mean? " + _BUSY_ORIGIN + "fix it",
            # Not the one-line JSON Hermes writes.
            opening + "\n" + ids.replace(", ", ",\n") + "\n" + closing + "fix it",
            # No closing line.
            opening + "\n" + ids + "\n\nfix it",
            # A middle line that is not a JSON object.
            opening + "\nhello world\n" + closing + "fix it",
        ):
            with self.subTest(kept=kept[:40]):
                self.assertEqual(person_request_text(kept), kept)

    def test_an_origin_block_on_its_own_line_goes_wherever_the_line_is_and_only_from_routing(self):
        # The cut is by line, not by position: a person who pastes an exact
        # origin block on a line of its own loses the block from the routing
        # text, never their other words. What OMH hands on is the whole turn.
        for name, message, routed in (
            ("mid message", "look at this:\n" + _BUSY_ORIGIN + "and fix it", "look at this:\nand fix it"),
            ("inside a fence", "see\n```\n" + _BUSY_ORIGIN + "```\nfix it", "see\n```\n```\nfix it"),
        ):
            with self.subTest(name):
                self.assertEqual(person_request_text(message), routed)
                self.assertEqual(person_request_text(message, messaging=True), routed)
                self.assertEqual(handed_on_text(message), message)
                self.assertNotIn("Gateway message origin", routed)

    def test_an_origin_block_after_a_sender_prefix_is_not_cut(self):
        # Pinned as observed (0 such rows in the owner's data): the opening
        # line must start a line, and `[name] ` is on it. Not a promise;
        # change it only with a row that shows the shape.
        message = "[bob] " + _BUSY_ORIGIN + "fix it"
        self.assertIn("Gateway message origin", person_request_text(message))
        self.assertIn("Gateway message origin", person_request_text(message, messaging=True))
        self.assertEqual(handed_on_text(message), message)

    def test_a_quoted_message_block_cannot_be_split(self):
        # QQ writes `[Quoted message]:` and the quote with no close of its own,
        # so a `]` and a blank line in the person's words is no boundary.
        turn = "[Quoted message]:\nuse ralplan\n\nthanks [ok]\n\nwhat is a web crawler"
        self.assertEqual(person_request_text(turn, messaging=True), turn)
        self.assertFalse(host_command_turn("[Quoted message]:\nuse ralplan\n\n" + _PLAN))

    def test_brackets_the_router_reads_as_the_persons_stay(self):
        for message in (
            "[REPORT] ralplan finished the rollout plan",
            "[planner -> reviewer] the plan is ready",
            "[ulw-loop] every 5 minutes check CI",
            "[omh-docs] explain the hooks",
            "[omh-role:reviewer] check this diff",
            "[/plan] add a dark mode toggle",
            "[$loop] every hour check CI",
            # A catalog skill's name or label, and OMH's own two words.
            "[deep-interview] I have a new product idea",
            "[ralplan] plan the auth migration",
            "[omh] status",
            "[ulw] fix the flaky tests",
        ):
            with self.subTest(message=message):
                self.assertEqual(person_request_text(message, messaging=True), message)
                # Behind a sender prefix the bracket makes two, and the turn
                # reads as it did before (`test_two_leading_brackets_...`).
                self.assertEqual(person_request_text(_NOTE + _SENDER + message, messaging=True), _SENDER + message)

    def test_a_block_that_never_closes_and_a_frame_stay(self):
        self.assertEqual(person_request_text("[Replying to x] fix it"), "[Replying to x] fix it")
        self.assertEqual(person_request_text(_NOTE + "[Replying to x] fix it"), "[Replying to x] fix it")
        for name, (opening, body) in HOST_TURNS.items():
            with self.subTest(turn=name):
                # A frame stays, with the sender prefix before it, for
                # `host_command_turn` to read.
                kept = person_request_text(_NOTE + _SENDER + opening + body, messaging=True)
                self.assertTrue(kept.endswith((opening + body).lstrip()))
                self.assertTrue(host_command_turn(kept))

    def test_two_leading_brackets_are_left_as_they_were(self):
        # `[alice] [bob said] ...` may be a name and the person's own tag, or a
        # name that holds `] [`; nothing tells them apart, so the turn reads as
        # before, and readers that take one bracket for a sender still do.
        for message in ("[alice] [bob said] loop every 5 minutes and check CI", "[alice] [WIP] fix it"):
            with self.subTest(message=message):
                self.assertEqual(person_request_text(message, messaging=True), message)

    def test_the_hint_after_the_hook_changes_nothing(self):
        # The hook removes the material, sender prefix included, once; the hint
        # it hands the result to reads it again without a platform, and must
        # leave it as it is.
        for prefix_name, prefix in GATEWAY_PREFIXES.items():
            for message in (*_GATEWAY_MOVED_REQUESTS, "[WIP] fix it", "[REPORT] done", "[Replying to x] fix it"):
                with self.subTest(prefix=prefix_name, message=message):
                    once = person_request_text(prefix + message, messaging=True)
                    self.assertEqual(person_request_text(once), once)


class GatewayMaterialIsNotTheRequestTest(unittest.TestCase):
    """Every hint and router surface decides a gateway turn as its bare request."""

    def test_the_hint_and_the_router_read_the_bare_request(self):
        for message in _GATEWAY_MOVED_REQUESTS:
            hint = awareness_route_hint(message)
            route = route_chat_message(message, source="discord")
            for prefix_name, prefix in _SURFACE_PREFIXES.items():
                with self.subTest(message=message, prefix=prefix_name):
                    # The hint as the `pre_llm_call` hook hands it a Discord turn.
                    self.assertEqual(awareness_route_hint(person_request_text(prefix + message, messaging=True)), hint)
                    prefixed = route_chat_message(prefix + message, source="discord")
                    for key in ("action", "selected_skill", "candidate_skill", "reason", "confidence"):
                        self.assertEqual(prefixed[key], route[key], key)
                    self.assertEqual(
                        route_question_decline_reason(prefixed, prefix + message),
                        route_question_decline_reason(route, message),
                    )
            # Called directly, the hint removes everything but a sender prefix.
            for prefix_name in ("note", "reply", "skill reply", "busy origin"):
                with self.subTest(message=message, direct=prefix_name):
                    self.assertEqual(awareness_route_hint(_SURFACE_PREFIXES[prefix_name] + message), hint)

    def test_the_wrapper_reads_the_bare_request(self):
        for message in _GATEWAY_MOVED_REQUESTS:
            interaction = build_chat_interaction_payload(message, source="discord")
            hint_payload = build_chat_route_hint_payload(message, source="discord")
            for prefix_name in (
                "note", "note+reply+sender", "reply+note+sender", "note+backfill+sender", "skill reply", "catalog backfill",
                "busy origin",
            ):
                text = _SURFACE_PREFIXES[prefix_name] + message
                with self.subTest(message=message, prefix=prefix_name):
                    prefixed = build_chat_interaction_payload(text, source="discord")
                    self.assertEqual(
                        (prefixed["route"]["action"], prefixed["route"]["selected_skill"], prefixed["next_action"]),
                        (interaction["route"]["action"], interaction["route"]["selected_skill"], interaction["next_action"]),
                    )
                    prefixed_hint = build_chat_route_hint_payload(text, source="discord")
                    self.assertEqual(prefixed_hint["route_hint"], hint_payload["route_hint"])
                    self.assertEqual(prefixed_hint["route_decision"], hint_payload["route_decision"])

    def test_a_leading_bracket_off_a_messaging_source_is_the_persons(self):
        # A non-gateway source keeps every leading bracket, and a gateway one
        # keeps a bracket that names a skill or OMH: these route as they did
        # before the strip existed.
        for message, expected in {
            "[omh] status": ("dispatch", "oh-my-hermes", "show_status"),
            "[deep-interview] I have a new product idea": ("dispatch", "deep-interview", "answer_clarification"),
            "[ulw] fix the flaky tests": ("dispatch", "app-debugging", "prepare_root_cause_investigation"),
        }.items():
            for source in ("generic", "discord"):
                with self.subTest(message=message, source=source):
                    payload = build_chat_interaction_payload(message, source=source)
                    route = payload["route"]
                    self.assertEqual((route["action"], route["selected_skill"], payload["next_action"]), expected)

    def test_a_display_name_is_read_only_from_a_messaging_source(self):
        # "[code review] " is a display name's shape: from Discord it is one,
        # and the turn is the question after it; from a non-gateway source the
        # person wrote it, and the router, the wrapper and its hint read it.
        message, words = "[code review] what is a web crawler", "what is a web crawler"
        bare_route = route_chat_message(words, source="discord")
        bare_hint = build_chat_route_hint_payload(words, source="discord")["route_hint"]
        discord = route_chat_message(message, source="discord")
        self.assertEqual((discord["action"], discord["reason"]), (bare_route["action"], bare_route["reason"]))
        self.assertEqual(build_chat_route_hint_payload(message, source="discord")["route_hint"], bare_hint)
        self.assertEqual(build_chat_interaction_payload(message, source="discord")["next_action"], "answer_directly")
        generic = route_chat_message(message, source="generic")
        self.assertEqual((generic["action"], generic["selected_skill"]), ("dispatch", "code-review"))
        self.assertNotEqual(build_chat_route_hint_payload(message, source="generic")["route_hint"], bare_hint)
        self.assertNotEqual(build_chat_interaction_payload(message, source="generic")["next_action"], "answer_directly")
        # The wrapper's own reading too: a Korean name before an English
        # question sets the card's language only where the person wrote it.
        korean = "[\uae40\ucca0\uc218] what is a web crawler"

        def hangul(source: str) -> bool:
            headline = str(build_chat_interaction_payload(korean, source=source)["chat_response"]["headline"])
            return any("\uac00" <= char <= "\ud7a3" for char in headline)

        self.assertTrue(hangul("generic"))
        self.assertFalse(hangul("discord"))

    def test_the_recommend_tool_ranks_the_bare_request(self):
        def ranked(message: str) -> tuple[object, object]:
            payload = json.loads(recommend_tool.omh_recommend_handler({"message": message}))
            return [row["skill"] for row in payload["recommendations"]], payload["route"]

        for message in _GATEWAY_MOVED_REQUESTS[:3]:
            with self.subTest(message=message):
                self.assertEqual(ranked(_NOTE + _REPLY + message), ranked(message))

    def test_the_turn_still_names_its_own_hash(self):
        # The wrapper identifies the turn it was handed: the hash and length
        # are the turn's. The route question asks the same thing about it, but
        # its digest is built from the turn too (`message_digest`), so it
        # joins to the hash this payload reports, not to the bare request's.
        message = "the anti-slop policy changes next week"
        turn = _NOTE + message
        payload = build_chat_interaction_payload(turn, source="discord")
        bare = build_chat_interaction_payload(message, source="discord")
        self.assertEqual(payload["message_sha256"], hashlib.sha256(turn.encode("utf-8")).hexdigest())
        self.assertEqual(payload["message_length"], len(turn))
        self.assertEqual(payload["route"]["route_question"]["questions"], bare["route"]["route_question"]["questions"])
        self.assertNotEqual(
            payload["route"]["route_question"]["question_digest"], bare["route"]["route_question"]["question_digest"]
        )


# What a gateway puts around the person's words, each with a marker the person
# never wrote: a quoted traceback, a document note with its path, and backfill.
# The route is decided on the words alone; what OMH hands on carries it all.
_CONTEXT_PREFIXES = {
    "reply": '[Replying to: "Traceback QUOTEMARK: KeyError in src/foo/bar.py line 42"]\n\n',
    "document": (
        "[The user sent a text document: 'crash.log'. Its content has been included below. "
        "The file is also saved at: /cache/DOCMARK.log]\n\n"
    ),
    "backfill": "[bob] BACKFILLMARK the KeyError is back\n\n[New message]\n[alice] ",
}
_CONTEXT_MARKERS = {"reply": "QUOTEMARK", "document": "/cache/DOCMARK.log", "backfill": "BACKFILLMARK"}


class WhatOmhHandsOnCarriesTheTurnTest(unittest.TestCase):
    """Decided on the person's words, rendered from the whole turn (owner decision D.1)."""

    def test_the_forwarded_routing_prompt_carries_the_whole_turn(self):
        for words in ("plan a fix for this crash", "fix this crash in the repo with codex"):
            bare = public_chat_route_payload(words, source="discord", include_message=True)
            for name, prefix in _CONTEXT_PREFIXES.items():
                with self.subTest(words=words, context=name):
                    route = public_chat_route_payload(prefix + words, source="discord", include_message=True)
                    self.assertEqual((route["action"], route["selected_skill"]), (bare["action"], bare["selected_skill"]))
                    self.assertIn(_CONTEXT_MARKERS[name], route["routing_prompt"])
                    self.assertTrue(route["routing_prompt"].endswith("User message:\n" + prefix + words))

    def test_the_coding_handoff_carries_the_whole_turn(self):
        # `delegate` builds the handoff directly; `auto` reaches it through the
        # route's coding owner.
        words = "fix this crash in the repo with codex"
        for mode, name in ((mode, name) for mode in ("delegate", "auto") for name in _CONTEXT_PREFIXES):
            prefix = _CONTEXT_PREFIXES[name]
            bare = build_chat_interaction_payload(words, source="discord", mode=mode, include_message=True)
            with self.subTest(mode=mode, context=name):
                payload = build_chat_interaction_payload(prefix + words, source="discord", mode=mode, include_message=True)
                self.assertEqual(payload["route"]["selected_skill"], bare["route"]["selected_skill"])
                delegation = payload["delegation"]
                self.assertEqual(delegation["message"], prefix + words)
                self.assertIn(_CONTEXT_MARKERS[name], delegation["delegation_prompt"])
                if "executor_handoff_prompt" in delegation:
                    self.assertIn(_CONTEXT_MARKERS[name], delegation["executor_handoff_prompt"])

    def test_the_plan_carries_the_whole_turn(self):
        words = "plan a fix for this crash"
        for name, prefix in _CONTEXT_PREFIXES.items():
            with self.subTest(context=name):
                payload = build_chat_interaction_payload(prefix + words, source="discord", include_message=True)
                self.assertEqual((payload["route"]["action"], payload["route"]["selected_skill"]), ("dispatch", "plan"))
                self.assertIn(_CONTEXT_MARKERS[name], payload["plan"]["plan"]["task_statement"])


if __name__ == "__main__":  # pragma: no cover - module entry point
    unittest.main()

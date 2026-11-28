"""A Claude Code session read as a chat (`runs.node_session`) shows only what a person or the agent said and did: the
harness's own lines (meta, side chains, compaction summaries, transcript-only lines) are left out, the blocks it puts
into a person's text are taken out, and an interrupt, a compaction or an API error is one quiet status item."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

TS = "2026-11-02T15:40:00Z"


def user(content, **flags) -> dict:
    return {"type": "user", "timestamp": TS, "message": {"role": "user", "content": content}, **flags}


def said(text: str, **flags) -> dict:
    return {"type": "assistant", "timestamp": TS, "message": {"model": "claude-opus-5-5", "role": "assistant",
                                                                "content": [{"type": "text", "text": text}]}, **flags}


def system(subtype: str, **rest) -> dict:
    return {"type": "system", "subtype": subtype, "timestamp": TS, **rest}


class ClaudeChatItems(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "projects" / "-x"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def items(self, lines: list[dict], name: str = "s1.jsonl") -> list[dict]:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        items, _ = ob.NodeSessions._claude_items(p)
        return [{k: v for k, v in i.items() if k != "ts"} for i in items]

    def test_harness_lines_are_not_shown(self):
        got = self.items([
            user("Fix the fence"),
            user("<command-name>/model</command-name>", isMeta=True),
            user("side chain prompt", isSidechain=True),
            said("side chain answer", isSidechain=True),
            user("A summary of everything", isCompactSummary=True),
            user("only in the transcript", isVisibleInTranscriptOnly=True),
            said("Done."),
        ])
        self.assertEqual(got, [{"type": "user", "text": "Fix the fence"}, {"type": "assistant", "text": "Done."}])

    def test_a_subagent_transcript_keeps_its_side_chain_lines(self):
        """Every line of a subagent's own file is a side chain: there they are the conversation."""
        got = self.items([user("count lines", isSidechain=True), said("42", isSidechain=True)],
                         name="s1/subagents/agent-a1.jsonl")
        self.assertEqual([i["text"] for i in got], ["count lines", "42"])

    def test_blocks_the_harness_adds_are_taken_out_of_a_persons_text(self):
        text = ("<system-reminder>\nToday is Monday.\n</system-reminder>\n"
                "<command-message>review</command-message>\n<command-name>/review</command-name>\n"
                "<command-args>all</command-args>\n<local-command-stdout>ok</local-command-stdout>\n"
                "<local-command-caveat>Caveat: generated</local-command-caveat>\n"
                "<task-notification><task-id>b1</task-id></task-notification>\n"
                "Please look at this:\n<pasted_content id=\"p1\" lines=\"2\">line one\nline two</pasted_content>\n"
                "[Image #1]\n  [Image #12]  \nand the picture above")
        got = self.items([user(text)])
        self.assertEqual(got, [{"type": "user",
                                "text": "Please look at this:\nline one\nline two\nand the picture above"}])
        # the same in a list of text parts, with an image part beside it
        got = self.items([user([{"type": "text", "text": "<system-reminder>x</system-reminder>hello"},
                                {"type": "image", "source": {"type": "base64", "data": "AAAA"}}])])
        self.assertEqual(got, [{"type": "user", "text": "hello"}])

    def test_a_turn_empty_after_cleaning_is_not_shown(self):
        got = self.items([
            user("<system-reminder>only a reminder</system-reminder>"),
            user("<task-notification>\n<task-id>b1</task-id>\n</task-notification>"),
            user("[Image #1]"),
            user("<command-name>/clear</command-name><command-args></command-args>"),
        ])
        self.assertEqual(got, [])

    def test_a_tag_the_person_typed_is_their_text(self):
        """Claude Code writes a block whole, at the start of the text or of a line: an opener with no closer, one in the
        middle of a sentence and one quoted in a fenced code block are what the person wrote."""
        cases = [
            "<system-reminder>never closed",
            "why does my hook print <system-reminder> twice?",
            "it prints <system-reminder>x</system-reminder> before each turn",
            "my hook prints this:\n```\n<system-reminder>\nToday is Monday.\n</system-reminder>\n```\nwhy twice?",
            "~~~xml\n<task-notification><task-id>b1</task-id></task-notification>\n~~~",
        ]
        for text in cases:
            self.assertEqual(self.items([user(text)]), [{"type": "user", "text": text}], text)
        # a real leading block, then the person's own text (which may quote a tag itself)
        got = self.items([user("<system-reminder>\nToday is Monday.\n</system-reminder>\n"
                               "why does my hook print <system-reminder> twice?")])
        self.assertEqual(got, [{"type": "user", "text": "why does my hook print <system-reminder> twice?"}])
        # a slash command's lines as Claude Code writes them (indented), after a closed fence: taken out
        got = self.items([user("<command-name>/compact</command-name>\n            <command-message>compact</command-message>\n"
                               "            <command-args></command-args>")])
        self.assertEqual(got, [])
        got = self.items([user("```\nx\n```\n<system-reminder>r</system-reminder>\nhello")])
        self.assertEqual(got, [{"type": "user", "text": "```\nx\n```\n\nhello"}])

    def test_an_interrupt_is_one_status_row(self):
        got = self.items([
            user("Fix it"),
            user([{"type": "text", "text": "[Request interrupted by user for tool use]"}]),
            user("[Request interrupted by user]"),
            user("Go on"),
            user("[Request interrupted by user]"),
        ])
        self.assertEqual(got, [{"type": "user", "text": "Fix it"}, {"type": "status", "code": "interrupted"},
                               {"type": "user", "text": "Go on"}, {"type": "status", "code": "interrupted"}])

    def test_an_interrupted_tool_keeps_its_result(self):
        """An interrupt written in the same user line as the tool's result: the step still gets its result."""
        got = self.items([
            {"type": "assistant", "timestamp": TS, "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "sleep 99"}}]}},
            user([{"type": "tool_result", "tool_use_id": "tu1", "content": "stopped", "is_error": True},
                  {"type": "text", "text": "[Request interrupted by user for tool use]"}]),
        ])
        self.assertEqual([(i["type"], i.get("result"), i.get("ok")) for i in got],
                         [("step", "stopped", False), ("status", None, None)])

    def test_a_compaction_is_a_status_row_not_the_persons_words(self):
        cont = "This session is being continued from a previous conversation that ran out of context. Summary: …"
        got = self.items([
            user("first"),
            system("compact_boundary", compactMetadata={"trigger": "auto"}),
            user(cont, isCompactSummary=True),
            said("Picking up."),
            user(cont),  # an older Claude Code: no flag, the words alone
        ])
        self.assertEqual(got, [{"type": "user", "text": "first"}, {"type": "status", "code": "compacted"},
                               {"type": "assistant", "text": "Picking up."}, {"type": "status", "code": "compacted"}])
        s = ob._ns_finish("claude", self.items([user(cont), said("ok")]))
        self.assertEqual(s["prompt"], "")  # the summary never reads as the prompt

    def test_an_api_error_is_a_status_row_with_its_own_short_text(self):
        long_msg = "overloaded " * 30
        got = self.items([
            user("go"),
            system("api_error", level="error", retryAttempt=3, maxRetries=10,
                   error={"status": 529, "formatted": "529 Overloaded", "message": "529 {\"type\":\"error\"}"}),
            system("api_error", error={"status": 500, "message": long_msg}),
            said("You've hit your weekly limit · resets Nov 18, 9pm (Asia/Seoul)", isApiErrorMessage=True,
                 error="rate_limit"),
            system("turn_duration", durationMs=1200),
        ])
        self.assertEqual(got[0], {"type": "user", "text": "go"})
        self.assertEqual(got[1], {"type": "status", "code": "api_error", "text": "Overloaded", "status": 529,
                                  "retry": 3, "retries": 10})
        self.assertEqual(got[2]["status"], 500)
        self.assertLessEqual(len(got[2]["text"]), 120)
        self.assertNotIn("retry", got[2])
        self.assertEqual(got[3], {"type": "status", "code": "api_error",
                                  "text": "You've hit your weekly limit · resets Nov 18, 9pm (Asia/Seoul)"})
        self.assertEqual(len(got), 4)  # other system lines show nothing
        # an error line is never the session's answer
        s = ob._ns_finish("claude", self.items([user("go"), said("Rate limited", isApiErrorMessage=True)]))
        self.assertEqual(s["answer"], "")

    def test_status_text_is_masked_on_the_way_out(self):
        secret = "sk-" + "liveTokenABCDEFGH1234"
        s = ob._ns_finish("claude", self.items([said(f"API Error: 401 key {secret} rejected", isApiErrorMessage=True)]))
        self.assertNotIn(secret, json.dumps(s))


if __name__ == "__main__":
    unittest.main()

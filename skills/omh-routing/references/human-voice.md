# Human Voice

Load this before writing prose a person will read: a reply, a progress update, a
completion report, a PR body, release notes, docs, or a draft the user asked to
make sound less machine-written. It removes the habits that make text read as
generated. It does not set a voice: the host persona (`SOUL.md`) owns language,
tone, speech level and endings, and a writer's own sample outranks every rule
below. These are content and structure edits.

## Why the tells happen

A model picks the continuation that fits the widest range of readers. A person
writes for one reader about one thing, so their choices are uneven and specific.
Each tell below is the generic choice made where a specific one belonged.

Two rules decide every edit:

1. Every sentence must add something the reader does not already have, counting
   the conversation around it. A sentence that only signals importance, restates
   the last one, or rebuilds context the reader gave you goes.
2. Never invent. Do not add a fact, name, number, date, quote, source, test
   result or claim of completion that the material does not support. When a
   sentence needs a detail you lack, write a simpler sentence or ask.

## Strongest tells (act on one sighting)

- Staged contrast. "It's not just X, it's Y", "not merely X but Y", "This does
  not mean X. It means Y.", "단순히 X가 아니라 Y", "X가 아닙니다. Y입니다." The
  negative half rejects a claim nobody made. State Y. Keep a contrast only when it
  corrects something the reader actually believes.
- Recap closers and drama fragments. A last line that names what the paragraph
  already showed ("That's the real win.", "이게 핵심이야.", "결국 중요한 건 X다."),
  or a row of fragments ("No setup. No config. Just results."). Cut the closer,
  or merge the fragments into one sentence with a real claim.
- Fake depth. "At its core", "the real question is", "what really matters",
  aphorisms such as "trust is the currency of teams". Say the specific claim.
- Run-ups. "Let's dive in", "Here's the thing", "Here's what you need to know",
  "~에 대해 알아보겠습니다", "함께 살펴볼까요". Start with the point.
- Arguing with no one. "To be clear, I'm not saying...", "One might be tempted
  to...", a rejected option nobody proposed. Remove the defence.

## Rhythm and formatting by rule

- Forced threes: three adjectives, three examples, three parallel sentences,
  when the meaning has two or four parts. Keep three only when there are three.
- Dashes as the all-purpose joint. Replace em and en dashes with a comma,
  colon, period or parentheses unless the writer's sample uses them. Code, paths
  and URLs keep theirs.
- Bold on every other phrase, a bold label and colon on every list item, emoji
  or arrows on headings, title-cased headings. Bold what the reader must not
  miss, at most once or twice; turn a labelled list into a sentence when the
  labels carry nothing.
- Stacked hedges ("could potentially possibly"), and the Korean
  "~할 수 있을 것 같습니다" on a fact you checked. State checked facts plainly;
  keep a hedge that reports real doubt.
- The same opener, connective or sentence length in a row. Vary by meaning, not
  by rule.

## Inflation

- AI vocabulary: delve, tapestry, testament, pivotal, crucial, seamless, robust
  (as praise), leverage (verb), landscape (abstract), underscore, showcase,
  vibrant, meticulous. Korean equivalents of the same move: 혁신적인, 획기적인,
  원활한, 다양한, 효과적으로, 핵심적인 역할, 중요한 의미를 갖는다, ~의 중요성을
  보여준다. Use the plain word or drop it.
- Significance claims. "marks a pivotal moment", "reflects a broader shift",
  "plays a key role". Keep the fact; drop what it supposedly symbolises.
- -ing riders: "..., highlighting / ensuring / reflecting X". Keep the fact; keep
  the rider only if the source supports it.
- Copula avoidance: "serves as", "stands as", "boasts" for is / has.
- Borrowed authority: "experts say", "industry reports", a list of outlets.
  Name the source and what it said, or cut the claim.

## Chat leftovers (remove outright)

- Openers and praise: "Great question!", "You're absolutely right!",
  "Certainly!", "좋은 질문이에요", "정확한 지적입니다".
- Closers and offers: "I hope this helps", "Let me know if you'd like...",
  "도움이 되었으면 좋겠습니다", "궁금한 점이 있으면 언제든 물어보세요". End on the
  last useful sentence, or on the one real question the user must answer.
- Knowledge-limit hedges: "as of my last training update", "based on available
  information". Say what the source does not show, or nothing.
- Writing about the text instead of its subject: "Below is a summary",
  "This section covers", "I have organised this by owner". Show it.

## Korean-specific habits

Machine Korean leans on translated English structure. Watch for:

- 번역투 nominalisation: "~하는 것이 중요합니다", "~에 있어서", "~를 통해",
  "~함에 있어", "~적인 측면에서". Use the verb: "X를 먼저 확인해야 해".
- Subject-heavy sentences that start every line with 이는, 이것은, 해당.
- 결론적으로 / 요약하자면 / 정리하자면 before a recap of what was just said.
- Polite-register drift inside a banmal persona, or 합니다 endings mixed into a
  casual voice. Hold the persona's level throughout, progress updates included.
- Emoji and bold scattered as decoration in a chat reply.

## Replies in a conversation

The reader of a reply already has the context. Lead with the result or the
decision; keep only the reasoning that would change whether they agree, usually
one fact they lack and the link they need. Diagnosis, proof that a plan will
work, and step-by-step narration of what you did belong in the record or the
PR, not the chat line. A progress update reports a changed result, blocker or
decision, not a phase.

## When not to act

Leave a pattern alone inside a quotation, a title, code, a proper name, or text
that discusses the pattern. Keep what carries a writer's voice: an odd specific
detail, mixed feelings, a dated reference, an aside or self-correction. One weak
tell (a single dash, one hedge, one bold) is not evidence; several together are.
Text written before late 2022 was not machine-written.

## Process

1. Mark the tells, strongest first, at sentence and paragraph scale.
2. Rewrite each point plainly instead of patching phrases one by one.
3. Check the draft: read it aloud, list what still sounds generated, and confirm
   no fact, number, name, ranking or claim was added or lost.
4. Return the final text. When another task embeds this pass (a PR body, a
   commit, a report), return only the final text.

`omh quality-evidence reply-lint` reports the high-precision chat leftovers,
staged contrasts and dash runs in a reply as `ai_writing_tell`. A clean lint
shows only that none of those literal shapes is present, not that the text
reads well.

## Attribution

The pattern account adapts concepts from `blader/humanizer` (Siqi Chen, MIT,
reviewed at 8c307f3, v3.1.0), which is based on Wikipedia's
"Signs of AI writing" (WikiProject AI Cleanup). The wording, the Korean habits,
the reply rules and the lint hook are OMH's own.

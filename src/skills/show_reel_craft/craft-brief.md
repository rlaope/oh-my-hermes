# Reading the request and the concept

## Contents

- Before asking
- What to ask and what not to ask
- Building the concept
- concept.md template
- Time and credit estimates
- Research request prompt
- Photo collection request prompt

## Before asking

1. Mark the items already settled in the user's request. For example, "a grand 1-minute narrated video" settles the mood, the length, and the narration.
2. Check the features that cannot be used from the `preflight.py` result. If there is no key, build a concept that can be made without narration; if there is no codex, one that can be made without image generation.
3. If the request has both a date and a day of the week, cross-check them against a calendar. If they do not match, drop the day of the week and note it in the report.

## What to ask and what not to ask

Ask the user about facts only the user knows. Claude makes the creative decisions. If the request contains words that hand the work over, such as "go ahead and make it" or "give it everything you've got", treat the creative decisions as handed over.

| Category | Item | Handling |
| --- | --- | --- |
| Ask | Who or what the subject is (when not in the request) | Ask in one line, without options. The subject cannot be chosen from options |
| Ask | Must-include information about a real subject that research cannot confirm (name spelling, date and time, venue, sign-up URL, CTA wording) | Do not ask if research can confirm it |
| Ask | The location of the user's materials (photo folder, logo, audio) | Only for a video about a real person or company when no materials were mentioned |
| Decide | Mood, palette, typeface, structure | Decide at the concept stage |
| Decide | Length | 60 seconds if not in the request |
| Decide | Aspect ratio | Judge by use. 9:16 for Reels or Shorts, 16:9 otherwise |
| Decide | Whether to narrate, and the voice | Include it only when the content must be told in words |
| Decide | Whether to generate images | Only when the concept needs it |

For a request whose subject is Claude itself ("show how amazing a motion graphics designer you are..."), ask nothing and start right away. If the user says "don't ask, just start", fill even the items that would be asked with research and reasonable values, and note them in the report.

If there are facts to ask about, collect them into one message and ask only once. They are facts only the user knows, so do not make options or recommendations; write open questions.

## Building the concept

The concept is the one idea that sets this video apart from other videos, plus the plan that turns that idea into per-segment pictures. If the concept is weak, polishing in later stages will not set it apart from template videos.

### 1) Gathering material

- What is known about the topic and the facts researched
- Usable media: DOM, canvas, WebGL, and 3D are always available. Generated images, narration, and generated music depend on the `preflight.py` result
- Length and music tempo: 60 seconds at 120 BPM is 30 bars. Put segment boundaries on bars

### 2) Writing candidates

Write 3 or more candidates in different directions. Three variations of one candidate are not three candidates. Examples of different structures follow. Do not pick an example as is; start from the topic.

- A collection of fictional commissions: string together highlights of 6 to 10 fictional commissions from different industries
- Variations on one subject: one letter or one shape turns into a different medium or material in each segment
- A continuous camera: without cuts, moving through one space as segments appear in turn
- Revealing the process: use the making process (sketch -> wireframe -> finished) as the structure of the video

For a showreel request, whatever structure is chosen, each segment must read as a different work ("Showreel" in `craft-story.md`). When choosing a one-take or variation structure, write in the candidate how the medium, palette, and motion will change per segment.

For each candidate, write the following.

| Item | Content |
| --- | --- |
| One-sentence idea | This video in one sentence |
| First 5 seconds | What is seen in 0 to 5 seconds and how it moves |
| Segment structure | Segment names and approximate times |
| How Hangul is used | Where jamo, strokes, the square syllable block, variable weight, etc. are used |
| New technical challenge to solve | An expression that has to be made for the first time for this video (shader, simulation, glyph outline deformation, etc.) |

If the codex CLI is available, you can get candidates separately under the same request and conditions and compare them together. Mixing in another model's candidates adds directions to compare. The command format is the same as "Second script review" in `craft-story.md` (pass the prompt through stdin).

> OMH note: each candidate run is a `codex exec` call on the user's own ChatGPT plan, and no price gives its cost. Run them only after `omh-spend-gate`'s card, which names how many calls, with a spend-only cap set in calls, and the person's typed yes to that card.

### 3) Choosing

Score each candidate 1 to 5 on the criteria below and keep it as a table. Choose the highest-scoring candidate, or combine the strengths of two candidates.

| Criterion | Question |
| --- | --- |
| First 5 seconds | Is it memorable from the first 5 seconds alone |
| Unexpected | Can someone who saw the previous segment not predict the next segment's medium or composition |
| Range | Do the medium, palette, and motion differ per segment so the expressive range looks wide |
| Topic specificity | Would it not work for any other topic |
| Distinctness | Is it different from the "cliche screen" in `craft-design.md`. Can it be told apart even next to another AI video |
| Hangul | Is the form of Hangul used as material for motion |
| Feasibility | Can it be made to this level with the engine and the remaining time |

Do not discard the strongest candidate just because feasibility is low. Test the technical challenge briefly first (one scene, a few stills) and then judge.

## concept.md template

```markdown
# Concept — <title>

- Request: <verbatim>
- One-sentence idea: …
- Why chosen: <summary of the scoring table>
- Length and spec: 60 seconds · 16:9 1920×1080 · 30fps · music 120 BPM (1 bar = 2 seconds)
- Narration: none / <voice and reason>
- What Claude decided: mood, length, aspect ratio, whether to narrate, etc., and why

## Segments
| # | Time (s) | Segment (fictional commission / topic) | Medium | Palette | Typeface | Character of motion | Texture | New technical challenge | How it links to the next segment |
| 1 | 0–6 | … | WebGL shader | #f2efe8 / #111 / #ff3b1f | Pretendard Variable | Drops heavily and bounces briefly | Flat, ink bleed | Jamo outlines merge like liquid | The last dot becomes the circle of the next segment |

## Candidate comparison
| Candidate | One sentence | First 5 seconds | Unexpected | Range | Topic specificity | Distinctness | Hangul | Feasibility | Total |

## Discarded candidates and reasons

## 'Cliche screen' elements used on purpose
- (e.g. letterboxing only on the end card. Reason: …)
```

## Time and credit estimates

The working times below are minimums measured with the earlier method (one round of style frames, 2 to 3 rounds of draft review). They grow with every segment rebuild. Do not cut critique rounds or segment rework to meet these times.

| Length | Working time | Narration characters (when included) | Scenes | Compositions | Final render (motion blur 4) |
| --- | --- | --- | --- | --- | --- |
| 15 seconds | 30 to 50 minutes | 50 to 65 characters | 4 to 6 | 10 to 14 | About 1 minute |
| 30 seconds | 30 to 60 minutes | 100 to 130 characters | 6 to 10 | 15 to 22 | About 2 minutes |
| 60 seconds | 50 to 90 minutes | 220 to 255 characters | 7 to 12 | 25 to 35 | 3 to 5 minutes |
| 100 seconds | 70 to 120 minutes | 360 to 420 characters | 15 to 25 | 40 to 50 | 6 to 9 minutes |
| 120 seconds | 60 to 120 minutes | 300 to 380 characters | 15 to 25 | 45 to 60 | 10 to 13 minutes (2 workers) |
| 5 minutes | 2 to 3 hours | 1,150 to 1,300 characters | About 25 | 90 to 120 | 15 to 25 minutes |

WebGL and 3D scenes and scenes with many particles take longer to render. Re-estimate the final render time from the draft render time.

ElevenLabs credits (approximate):

> OMH note: these figures are a rough planning guide, not a quote. A spend card reads the expected credits from the provider's own price for the chosen model; where that gives no figure, the card says the cost is unknown and `omh-spend-gate`'s spend-only cap applies.

- TTS: character count × 1 (about 1.5 to 2 times including regeneration and takes)
- STT: a small amount per minute
- Sound effects: 40 credits per second when a duration is specified (10 sound effects × 2 seconds ≈ 800)
- Music: proportional to length

A key without the User Read permission cannot query the remaining credits, so tell the user to check on the dashboard.

Image generation: about 1 minute per image with codex-image, 5 in parallel. ChatGPT plan usage is deducted per image.

## Research request prompt

When the topic is a person, company, event, or product, launch a subagent (`general-purpose`) in the background. Meanwhile, the main agent proceeds with project setup, writing concept candidates, and testing technical challenges.

```
Research <subject> and write it to <project>/research/research.md. Do not rely on memory; write only facts confirmed with WebSearch and WebFetch.
(For sites where WebFetch is blocked, fetch with curl -sL -A "Mozilla/5.0" and extract the body text.)
Keep all working files inside the <project> folder. Do not use /tmp.
1. Timeline: year · title/event · source URL · certainty (confirmed / single source / unconfirmed)
2. TOP 10 facts usable in the video: focus on numbers, titles, awards, and achievements. Give numbers together with their reference date
3. Quotes from the person or official sources (verbatim, with source)
4. Conflicting information (figures or years that differ between sources) and warnings about people with the same name
5. 15 short copy candidates for video captions (each within 20 characters, only ones grounded in fact)
6. Brand colors (hex frequency in the official site's CSS), official logo file URL
7. "Do not put in the script": unconfirmed education, birth year, figures
At the end, briefly report only the file path and the TOP 10.
```

## Photo collection request prompt

Use this when real photos of a person are needed and the user has not provided photos. This step exists so that a person's face is not made with AI.

```
Collect real photos of <person>, save them to <project>/assets/photos/, and organize them as a table in <project>/research/photos.md.
Keep all working files inside the <project> folder. Do not use /tmp.
- Priority: official profile, company press releases > press article photos (og:image) > the person's public social media
- Fetch the Naver News search result HTML with curl to extract article URLs, then fetch the og:image from the article HTML (set a browser UA and Referer)
- Open each fetched photo directly with Read and check that it is the person (whether the caption has both the name and title), watermarks, and resolution. Discard people with the same name
- Table: file name · original URL · article URL · resolution · content (front-facing/stage/event) · quality
- 8 to 15 photos, long side 800px or more preferred
```

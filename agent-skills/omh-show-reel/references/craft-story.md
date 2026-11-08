> Translated in full from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 `showreel/references/story.md` (MIT, Copyright (c) 2026 Minho Hwang (revfactory); `toolkit/LICENSE.upstream`, provenance in `toolkit/upstream-manifest.json`). Read it for structure and script: showreel structure, reference structures by use, length benchmarks, copy and pronunciation rules, script.json. `$S` is `toolkit/scripts` under the loaded skill directory. Commands here are upstream's; check the upstream command map in `toolkit/README.md` before running one. Content language follows `references/brief-and-locales.md`: Korean-first defaults apply only to Korean content, the craft bar applies to every locale; host install paths are placeholders here, upstream's default narration voice is named by role and chosen only through voice_policy, inline OMH notes mark where OMH policy overrides an upstream default, and the provider scripts are opt-in with the user's own key.

# Structure and script

## Contents

- Reference values by length
- Showreel (work compilation, self-introduction)
- Reference structures by purpose
- Copy rules
- Pronunciation spelling rules (tts)
- storyboard.md template
- Writing script.json
- Second script review (codex)

## Reference values by length

These values come from 13 past productions and from evaluation runs. Narration character counts are **measured on the pronunciation spelling (tts), excluding spaces**.

| Length | Narration (when included) | Speech ratio | Scenes | Compositions (screen states) | Editing rhythm |
| --- | --- | --- | --- | --- | --- |
| 15 s | 50-65 characters, 4-6 lines | 55-60% | 4-6 | 10-14 | Something changes on every beat. One message plus name and CTA |
| 30 s | 100-130 characters | 60-70% | 6-10 | 15-22 | The composition changes every half bar to one bar. Mostly headlines |
| 60 s | 220-255 characters, 12-16 lines | 60-70% | 7-12 | 25-35 | For a showreel, 6-10 segments, 3-8 seconds per segment |
| 100 s | 360-420 characters, 18-19 lines | 60-70% | 6 acts, 15-25 | 40-50 | Change the tempo every act |
| 120 s | 300-380 characters, 22-28 lines | 55-65% | 7-8 acts, 15-25 | 45-60 | 4-6 big hits; leave the narration empty for 2-4 seconds before and after each |
| 5 min | 1,150-1,300 characters | 80-90% | about 25 | 90-120 | Chapter card -> 3-6 scenes x 3-4 chapters -> recap -> preview of the next episode |

- The scene and composition counts in the table come from past productions. Do not follow them when the concept demands a different structure (such as a one-take with no cuts).
- A **composition** is the unit in which the main arrangement of the screen changes. Even inside one scene, a big change of word, a rearrangement of cards, or the camera moving somewhere else makes a new composition. When the same composition lasts longer than 2 bars (about 4 seconds), check what changes inside it, and if it is not an intended pause, change the composition. If you match only the scene count and keep one composition per scene, the video looks frozen (this was why, in evaluation, a video looked less dynamic than one made without the skill).
- The verified Korean narrator (multilingual_v2, speed 1.0) reads sentence-style lines at about 5.5 characters per second. Short lines like "기획." (Planning.) or lines with several periods and commas slow down to 3-4.7 characters per second. For a script with many short lines, cut the character count 15-20% below the table's lower bound.
- Filling more than 70% of the time with speech leaves no room for big hits and montages. In one case a 2-minute script written at 448 characters reached 82% speech and was cut to 400 characters.
- Write at this length from the start. In one case an 81.7-second script was shortened with speed and atempo; the reading got faster and the sense of grandeur was lost.
- In a video without narration, give on-screen text time to be read at 6-8 or more Hangul characters per second.

## Showreel (work compilation, self-introduction)

A resume showreel is a format that strings together the best segments of different works to music and ends with a name (and contact details). It is a video that shows, not one that explains. Below are the things to decide when making this format. The concept decides the number and order of segments.

- **First 5 seconds**: Put the strongest segment here. If you open with a name card, make the name card itself the first piece of work.
- **Difference between segments**: Make each segment look like a different project. At least two of medium, palette, typeface, and character of motion differ from the previous segment. How to decide them: "Choosing the art direction" in `craft-design.md`.
- **When there is no real commissioned work** (Claude's own showreel): Set up fictional commissions. Examples: a music show title, news data graphics, a sports broadcast package, a film title sequence, an app product video, a brand logo animation, a children's channel ident, exhibition poster motion. Invent new names and marks for fictional brands and do not imitate real companies. Write the copy inside segments in Hangul.
- **What only code can do**: generative graphics in which thousands of elements move by rules, physics calculation, screens driven by music analysis data, shaders, Hangul outline deformation. Putting expressions that are hard for a person to keyframe by hand into one or two segments reveals what the maker of this video can do.
- **Connecting segments**: The next segment takes something from the previous one, as in a match cut, a shape morph, or a color hand-off. Change the connection method at every cut ("Transitions" in `craft-design.md`).
- **Copy**: Reduce it to segment names (the fictional commission name or the kind of work) and a name card. Do not line up explanatory sentences.
- **Music**: Align the sections of one track with the segments, and place segment boundaries on bars. A pause or a breakdown before the climax creates contrast.
- **End card**: The name ("Claude" if it is Claude itself) and a one-line introduction. Give the last 1.5-2 seconds for reading the name. The design of the end screen is decided by the art direction of the last segment.

## Reference structures by purpose

These are structures used in past productions. Do not follow them when the concept demands a different structure. Times are for 60 seconds; for other lengths, shrink or stretch them proportionally.

### Person profile (resume, introduction)

| Segment | Time | Content |
| --- | --- | --- |
| Cold open | 0-8 s | Montage the person's field in four words, or throw out the era or problem in one sentence |
| Identity reveal | 8-10.5 s | Reveal the name (or an identity sentence) together with a big hit |
| Career chapters | 10-48 s | 4-6 chapters in chronological order. Each chapter gets one job title + one evidence number + one real photo |
| Present and convergence | 42-52 s | The current position and what it means, in one sentence |
| Tagline and name card | 52-60 s | Tagline -> final hit -> name, title, career credits |

Example: "방송. 음악. 아티스트. 그리고, 콘텐츠." (Broadcasting. Music. Artists. And, content.) -> "1993년, KBS 예능 PD." (1993, KBS entertainment PD.) -> ... -> "이훈희." (the person's name)

### Company and brand promotion

| Segment | Content |
| --- | --- |
| Problem statement | The problem customers face, as numbers or scenes (a pile of contracts, a warning clock) |
| Brand reveal | Logo pieces assembling, a light sweep, the slogan |
| Technology and solution | The core technology as diagrams and particles |
| Product demo | Draw a UI mockup in code and show the actual usage flow (scan -> highlight -> suggested fix) |
| Evidence | Number count-ups (sourced ones only), client names (text instead of logos) |
| Vision and CTA | One-sentence vision -> logo -> URL |

A 100-second brand film is extended to 6 acts (chaos -> arrival -> technology -> product -> proof -> vision), with a 2.39:1 letterbox in acts 1 and 6.

### Product or solution (15 seconds)

Question-style opening (0-2 s) -> brand (2-4 s) -> five feature steps at 1 second each (4-9 s) -> three pieces of evidence (9-12 s) -> tagline and CTA (12-15 s).

### Event promotion

15 seconds: symbolic image -> event slogan -> stage -> end card with event name, date and time, and venue.
60 seconds: opening (people, problem) -> blank and pause (even the music stops) -> answer (the event concept) -> program and speakers (rolling numbers, a wall of names) -> next step -> end card (sign-up button, date and time, venue, host).
Flag wording that becomes wrong once a date passes, such as "얼리버드 접수 중" (early-bird registration open), in the delivery report. For speakers, use only real names and affiliations, and do not generate faces.

### Content teaser (drama, webtoon, game)

Cold open (CCTV stamped with time and place, silence) -> incident -> drop (the music explodes, the letterbox opens) -> twist (the music stops for 2 seconds) -> three questions -> title. Narration cuts short simple sentences with commas ("친구인가. 환상인가." (A friend? A fantasy?)).

### Strategy or proposal (for executives)

Cold-open question (0-4 s) -> scale of the problem (numbers and contrast, 4-14 s) -> turn (an impact after the music stops, 14-18 s) -> structure of the solution (flow and roles, 18-36 s) -> evidence and demo (36-50 s) -> one-sentence conclusion + request (50-60 s).
- Do not boast about speed or volume ("대본 3일 만에" (a script in just 3 days)); the audience can read it as taking the people who do the making lightly.
- Show the results of judgment rather than numbers about the audience's own company that they already know.
- Do not include competitor names, quotes of the audience's own statements, or developer metrics (GitHub stars).
- Spell out technical terms ("하네스 = 역할을 나눈 AI들 + 일하는 규칙" (harness = AIs with divided roles + rules for working)).

### Process or system explainer (harness, research, pipeline)

Type the actual request into a terminal -> Enter flash -> a match cut that zooms into a symbol -> agent and stage graph (the camera sweeps across it, counters) -> per-stage headers (number + role name) -> excerpts of actual outputs -> a review-passed stamp (on the same frame as the sound effect) -> parallel progress bars and an elapsed clock -> totals -> a final line that answers the first line.
- Take numbers from actual run records (logs, JSON).
- Set a notation rule, such as solid lines for results and dotted lines for tool calls, and keep it to the end.
- On pictures drawn in code (medical images, data), write "설명을 위해 그린 그림" (illustration drawn for explanation).

### Education (5 minutes, series)

Cold open (7-9 s, an opening that starts with a number) -> episode title (4-5 s) -> [chapter card 2.8 s -> 3-6 scenes] x 3-4 -> recap ("정리합니다. 하나, … 둘, … 셋, …" (To recap. One, ... two, ... three, ...)) -> one-sentence preview of the next episode -> end card.
- Put only keywords, numbers, and short headlines on screen, and show the full narration in the subtitles below.
- Alternate data-style scenes (bars, donuts, gauges, comparisons) with real scenes (original screenshots, generated images).
- In one case the user separately asked for a title and a thumbnail after completion, so deliver three title candidates and a thumbnail together.

### Music-driven (no narration)

Use the structure of the music (intro -> development -> pause -> climax -> ending) as the acts. Analyze the onsets of the track to put cuts on the beats (`music_tools.py analyze`), and write the on-screen text as short poetry. When you use an existing recording, write the copyright of the recording (even if the composition is in the public domain, the recording varies by country) in CREDITS and in the report.

### Personal or hobby (pets, family)

A one-line concept built on the names ("방이 + 탄이 = 방탄" (Bang-i + Tan-i = Bangtan)) -> scenes laid out by bar on a 120 BPM beat grid -> real video and photos + generated photos made to resemble the same subject -> a repeating structure such as a daily routine -> heart and logo end card. Copy that worked well: casual-speech onomatopoeia written from the subject's point of view, and sportscast parodies. Get invented details (special skills, personality) confirmed in the report.

### Making-of film

Use actual records instead of invented scenes. Build a progress clock from file modification times, and show failed images, before-and-after fixes, and actual code with its line counts as STEP 01-08. At the end, splice in highlights of the finished piece with their original sound. If the screen is redrawn rather than an actual recording, disclose it.

## Copy rules

- One message per screen. Set the amount of text by reading time (6-8 Hangul characters per second); the typography design of that segment decides length, line count, and emphasis.
- Use numbers, job titles, years, and proper nouns instead of adjectives ("혁신적인" (innovative), "획기적인" (groundbreaking)).
- Use official job titles and institution names exactly as they are.
- Decide the style of the copy (a run of short sentences, repeated sentence patterns, questions) to fit the concept and the segment's art direction. Do not repeat one sentence pattern across the whole video.
- When on-screen text and narration say the same thing at the same time, reduce the on-screen side (keywords only). Remove from the burned-in subtitles any line that the on-screen typography already shows (`"nosub": true`). It stays in the SRT file (to remove it from the SRT as well, use `"nosrt": true`).

## Pronunciation spelling rules (tts)

ElevenLabs reads numbers, abbreviations, and English however it likes. Leave the display text (`text`) as it is and write the sound to be read, in Hangul, in `tts`.

| Display text | tts | Notes |
| --- | --- | --- |
| 1993년 | 천구백구십삼 년 | Years are written the way they are read |
| 2026 | 이공이육 / 이천이십육 | For a year inside an event name, breaking it with a comma, as in "이공, 이육!", reduced STT misrecognition |
| 67% | 육십칠 퍼센트 | |
| 5배 | 다섯 배 | Native Korean numeral |
| 제6대 | 제육대 | |
| KBS, AI, LLM, CIPO | 케이비에스, 에이아이, 엘엘엠, 씨아이피오 | |
| BHSN (company abbreviation) | 비, 에이치, 에스, 엔 | A comma after each letter |
| GPT-4 | 지피티 포 | |
| Claude Opus 4.5 | 클로드 오퍼스 포 포인트 파이브 | Replace the longest names first |
| 밋업 | 미텁 | Left as is, it was read as "미섭" |

- **Do not attach a particle after a brand name.** "앨리비와 함께" (with [brand name]) was heard as "LEB" all seven times. Put the brand name at the end of a sentence with a period ("올인원 계약 에이아이. 앨리비." (All-in-one contract AI. [brand name].)).
- For one-syllable names ("뉴"), homonyms ("회의" heard as 會議, meeting), and short proper nouns with weak final consonants, change the sentence or supplement it with on-screen text.
- **Do not make a line that contains only one word.** When the last line was "쇼릴." (Showreel.), it was transcribed as "쇼딜", "쇼를", or "소리" even after changing takes and models. Lengthening it to "쇼릴입니다." (It is a showreel.) got it right all three times. When ending on a name, attach a predicate or join it to the previous sentence on one line.
- Direct phrasing pauses with commas and ellipses ("그 아이를, 다시… 무대에 세운다." (That child, once again... is put back on the stage.)).
- Write a substring used as a cue exactly as the string appears inside `tts` (if you write it as the display text, it will not be found).
- Words that STT transcribes in English ("Meetup") and lines that read numbers and units ("-14 LUFS" -> "마이너스 십사 러프스") score a low similarity even when the pronunciation is right. Add the spellings to accept as correct to that line, as in `"alt": ["AI 에이전트 Meetup 2026", "믹스는 마이너스 십사 러프스"]`. `narrate.py` and `qa_check.py` compare against the closest of text, tts, and alt.

## storyboard.md template

```markdown
# Storyboard — <title> (60s, 16:9, 30fps, music 90 BPM: 1 beat 0.667s · 1 bar 2.667s)

Per-segment art direction (medium·palette·typeface·motion) is in concept.md.

## Scenes
| # | Segment | Time (s) | On-screen copy | Narration (line id) | Screen design (including motion) | Transition | SFX·music | Source |
| 1 | 1 | 0–8.3 | 방송. 음악. 아티스트. | n01 | Four words fall carrying photos, squash against the floor, and stand up | Match cut (last dot → circle) | braam 0.0, impact cue:word4 | research.md#1 |
...

## Remaining decisions·to confirm
- …
```

## Writing script.json

The full format is at the top of `toolkit/scripts/narrate.py`. Write it in the following order.

1. Following the scene times in the storyboard, write `at` (the time the speech starts) for each line. The first line goes at 0.4-0.8 seconds, and a name-reveal line is matched to the hit time.
2. Name the words to align with scene transitions and kinetic typography as `cues`. Example: `"cues": {"name": "이훈희"}`
3. Give `"takes": 3` only to lines with proper nouns or numbers.
4. Attach sound effects (`sfx`) by cue name. Impacts use `"align": "peak"`, risers `"align": "end"`.
5. Write segment and scene boundaries in `scenes`: `[{"id": "s01", "start": "bar1"}, {"id": "s02", "start": "music.hit2", "end": 14.0}]`. `start` and `end` accept seconds, a cue name, or "cue±seconds". `timeline.py` creates the cues `scene.s01` and `scene.s01.end`; when `end` is missing, it uses the start of the next scene (the end of the video for the last one). A showreel without narration sets its screen timing with these cues.
6. Run `narrate.py` (when there is narration) -> `timeline.py`, and if overlaps or overruns appear, fix `at` or the sentences.

```json
{
  "duration": 60,
  "voice": "ibCGc01503OQd2R6i1n1", "model": "eleven_multilingual_v2",
  "settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.4, "speed": 1.0},
  "lines": [
    {"id": "n01", "text": "방송. 음악. 아티스트. 그리고, 콘텐츠.", "at": 0.6, "cues": {"w4": "콘텐츠"}},
    {"id": "n02", "text": "1993년, KBS 예능 PD.", "tts": "천구백구십삼 년, 케이비에스 예능 피디.", "at": 9.2, "cues": {"kbs": "케이비에스"}},
    {"id": "n13", "text": "이훈희.", "at": 56.2, "takes": 4, "cues": {"name": "이훈희"}}
  ],
  "sfx": [
    {"name": "braam", "at": 0.0, "gain_db": -8},
    {"name": "impact", "at": "w4", "offset": 0.25, "align": "peak", "gain_db": -6},
    {"name": "riser", "at": "name", "offset": -0.3, "align": "end", "gain_db": -10},
    {"name": "logo_hit", "at": "name", "offset": 0.3, "align": "peak", "gain_db": -6}
  ],
  "scenes": [{"id": "s01", "start": 0}, {"id": "s02", "start": "line.n02-0.4"}],
  "music": {"file": "audio/music/music.mp3", "gain_db": -8, "duck": 0.75, "analysis": "audio/music/analysis.json"}
}
```

### Alternating voices

Write `"voice"` on each line. The method and the caveats are in "Voice alternation" in `craft-audio.md`.

```json
{"id": "v1", "text": "기획.", "voice": "ibCGc01503OQd2R6i1n1", "at": 1.0},
{"id": "v2", "text": "원고.", "voice": "4JJwo477JUAx3HV0T7n7", "at": 1.9},
{"id": "v3", "text": "목소리.", "voice": "uyVNoMrnUku1dZyVEXwD", "at": 2.8},
{"id": "v4", "text": "그리고, 영상.", "voice": "ibCGc01503OQd2R6i1n1", "at": 3.7}
```

## Second script review (codex)

If the codex CLI is available, have a different model read the narration script and the on-screen copy (fictional commission names, segment copy, end card text) once. On narration scripts it was effective at catching translationese and words that are confusing when heard. In a showreel without narration, the on-screen copy is all the Hangul there is, so always have it read.

```bash
codex exec --sandbox read-only --skip-git-repo-check --ephemeral -o <project>/research/narration_review.md - < <project>/research/narration_review_prompt.md
```

> OMH note: `codex exec` draws on the user's own ChatGPT plan, and no price gives a call's cost. Run it only after `omh-spend-gate`'s card, which names the calls and what each sends, with a spend-only cap set in calls, and the person's typed yes to that card.

Criteria to put in the prompt (pass it on stdin; if you pass it as an argument, codex stalls waiting for input):

1. Find and fix translationese (overuse of 그녀/그들/~의 ~ (she / they / chained possessive "of")) and awkward rhythm
2. Check whether the pauses and the lingering resonance come alive when read aloud
3. Do not increase the character count, because each line must fit inside its set time
4. Do not change facts (numbers, job titles, years)
5. Do not read files or run commands; answer only with a `| ID | Original | Suggestion | Reason |` table

Decide for each suggestion received whether to accept it, partially accept it, or reject it, and apply it accordingly.

---
name: "omh-media-input"
description: "[omh] Audio, video, or screenshot to process: user-sent media - audio, video, YouTube links, screenshots, receipts, OCR, meeting recordings, transcripts, timestamps, and clip summaries, gated for source, permission, and hallucination risk. Use when the user says: media-input-operator, media input operator, media input, audio transcription, audio transcript, transcribe audio, transcribe this audio, meeting recording."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, media]
    category: media
    phase: media-input-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Media Input Operator

This is an OMH `media-input-operator` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`media-input-operator` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: media-input-operator transcribe this audio meeting and summarize action items with evidence and timestamp boundaries.
- Expected behavior: Produce `prepare_media_input_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: media-input-operator invent a YouTube transcript and claim the timestamps are verified without media evidence.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Media type, source location, permission boundary, transcript availability, language, requested output, timestamp requirement, and stop condition are explicit.
- Downloads, uploads, ASR, transcript extraction, speaker labels, copyrighted media access, and provider setup are gated or marked missing.
- Transcript text, OCR output, screenshot text, receipt fields, timestamps, quotes, action items, and media-summary claims are reported only from observed media or supplied transcript/extraction evidence.

## Recovery Notes

- If the media or transcript is missing, ask for the smallest source, file, transcript, or provider result needed.
- If the request is broad current-source research about a video topic, route to research or source-finder before summary.
- If the user wants a PPT/PDF/report generated from the media summary, route to materials-package after media input evidence is clear.
- If the request is about whether a live duplex voice connector keeps whole spoken turns, route to external-connector-readiness for a realtime_voice_trial_receipt/v1 rather than treating a supplied recording as that evidence.



## When to Use

Use when Hermes should prepare or supervise audio/video transcript, YouTube/video summary, OCR, screenshot text extraction, receipt image parsing, or timestamped media extraction work without claiming media access, download, transcription, OCR output, or factual summary evidence.

    Strong routing signals: `media-input-operator`, `media input operator`, `media input`, `audio transcription`, `audio transcript`, `transcribe audio`, `transcribe this audio`, `meeting recording`, `recording transcript`, `video transcript`, `youtube summary`, `youtube video`, `summarize youtube`, `summarize this youtube`, `video summary`, `summarize this video`, `ocr image`, `image ocr`, `photo ocr`, `picture ocr`, `graphic ocr`, `screenshot ocr`, `ocr this image`, `ocr receipt image`, `ocr this receipt image`, `receipt ocr`, `receipt image ocr`, `receipt text`, `receipt text from image`, `receipt fields`, `receipt fields from image`, `receipt image extraction`, `receipt image text`, `receipt image fields`, `parse receipt image`, `receipt image parse`, `receipt image into fields`, `image text extraction`, `extract text from image`, `extract text from this image`, `screenshot text extraction`, `extract text from screenshot`, `extract text from this screenshot`, `screenshot to text`, `timestamps`, `with timestamps`, `clip summary`, `podcast summary`, `webinar summary`, `오디오 전사`, `음성 전사`, `회의 녹음`, `녹음 요약`, `영상 요약`, `유튜브 요약`, `youtube 요약`, `이미지 ocr`, `이미지 OCR`, `이미지 텍스트 추출`, `이미지에서 텍스트 추출`, `영수증 ocr`, `영수증 OCR`, `영수증 이미지 ocr`, `영수증 이미지 OCR`, `스크린샷 텍스트 추출`, `스크린샷에서 텍스트 추출`, `타임스탬프`, `타임라인 요약`, `транскрибируй`, `расшифруй аудио`, `суммаризируй видео`, `вытащи текст со скриншота`, `распознай текст на картинке`

## Catalog Metadata

Category: `media`
Phase: `media-input-task`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- media_input_task_card/v1
- media_source_scope/v1
- transcript_boundary/v1
- media_summary_plan/v1
- media_result_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- media_input_task_card/v1 metadata-only wrapper card when prepared
- media_source_scope/v1 with media type, source location, permission boundary, requested time range, and stop condition
- transcript_boundary/v1 separating supplied transcript, missing transcript, ASR/extraction requirement, language, speaker labels, and confidence gaps
- media_summary_plan/v1 naming action-item, timestamped, clip, chapter, quote, or evidence-linked summary method
- media_result_manifest/v1 only when supplied transcript, media file metadata, provider response, or observed transcript output exists

Safety rules:

- A media input card is not media access, file upload, download, transcript extraction, OCR output, screenshot text extraction, receipt fields, speech-to-text output, timestamp accuracy, copyright clearance, source retrieval, or summary correctness evidence unless observed media-result evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.
- A media_result_manifest/v1 describes a supplied recording or transcript. It is never a live duplex session, one-input-to-one-dispatch integrity, audible response behavior, or realtime voice readiness, and it cannot be promoted into one.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.

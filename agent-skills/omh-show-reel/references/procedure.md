# show-reel Specialist Procedure

Expert clarification questions:
- `objective audience and channel`
  - English: Who should watch this, on which channel, in which content language, and what should they understand or do?
  - Korean: 누가 어떤 채널에서 어떤 언어로 보고 무엇을 이해하거나 행동해야 하나요?
- `duration format and budget`
  - English: Which duration, dimensions/aspect ratio, fps, size cap, deadline and revision budget are explicit?
  - Korean: 명시된 길이, 크기와 비율, fps, 용량 상한, 기한과 수정 예산은 무엇인가요?
- `source brand and asset permissions`
  - English: Which source revisions, brand assets and usage/voice permissions are approved, and what may be shared?
  - Korean: 승인된 출처 버전, 브랜드 자료와 사용·음성 권한은 무엇이며 어디까지 공유할 수 있나요?
- `available production tools`
  - English: Which local production tools and licensed fonts are already available in the approved workspace?
  - Korean: 승인된 작업 폴더에서 이미 사용할 수 있는 제작 도구와 라이선스가 확인된 폰트는 무엇인가요?

## Procedure

Declared checks:
- `reel_brief_check`
  - Required result fields: `objective`, `audience_channel`, `format_duration_budget`, `locale_precedence`, `language_tracks`, `literal_tokens`, `unknowns`
  - Criterion: Require the brief and separate language tracks with decision basis; HOLD on conflicting explicit requirements or missing irretrievable facts, never on an aesthetic choice the author can label as an assumption.
- `reel_source_check`
  - Required result fields: `claim_source_version`, `evidence_class`, `brand_verification`, `asset_rights`, `consent`, `conflicts`, `product_capture_source`, `literal_fact_citations`
  - Criterion: An idea video with no product claim, real UI or brand asset on screen records `no_product_claims` and needs no source or rights register; a literal fact it shows (a date, a command, a number) is still copied from a named source. Otherwise bind claims to dated versioned sources and assets to rights and consent; HOLD on unresolved brand/source conflicts or rights. Label concept visuals as concept on screen and in the manifest, never as captured product evidence. Draw every real product surface from that product's renderer output or capture at a named revision, with the command that produced it, and keep the identity marks it renders such as its logo. A look-alike of a UI that exists is HOLD; an invented UI not yet built passes only when visibly labeled concept; a stylised treatment of a real UI passes when the brief asks for it and it is labeled. Copy every product fact on screen (install command, command and flag names, package name, URL, count) byte-for-byte from its canonical source and cite the path; a fact written from memory is HOLD.
- `reel_concept_check`
  - Required result fields: `candidates`, `shared_rubric`, `selection`, `rejected_alternatives`, `revision_budget`
  - Criterion: An idea video selects one concept and records its assumptions and genre recipe (`references/genres.md`). A product, brand or work film requires at least 3 distinct narrative and visual approaches, not palette swaps; compare audience fit, evidence clarity, native script, motion intent, feasibility and legibility before selecting one within the revision budget.
- `reel_story_check`
  - Required result fields: `segments`, `source_asset_ids`, `art_direction`, `motion_intent`, `locale_runs`, `distinct_compositions`, `frame_fill`, `clear_space`, `decorative_text`, `palette_families`
  - Criterion: Every segment must bind time, message, source/asset IDs, medium, palette, typography, texture, composition, movement and transition, and adjacent segments must differ in at least two of medium, palette, typeface, motion and texture even when one semantic object carries the film; HOLD invented product UI or unsupported claims unless visibly labeled concept. Before the first style frame, size a product-led shot from the subtitle mode (`references/craft-design.md`): with no subtitles it is full-bleed, the full frame minus the 46 px edge inset (at least about 988 px tall at 1080p) with the 9:16 UI zones still clear; with subtitles it fills at least 90% of the width and height of the body safe area and the subtitle band stays clear; text rows are at least 2% of the frame's shorter side; keep at least one of its own text rows between a logo or identity mark and the frame or window edge, intentional crops excepted; add no meta text the product does not render (window title, dimension label, invented path); in a composed frame list every hue family, and add at most one accent family beyond the captured product or brand palette, listing neutrals, semantic-state colors and data-series palettes without counting them.
- `reel_timing_check`
  - Required result fields: `audio_mode`, `measured_cues`, `reading_time`, `pronunciation_approval`, `voice_rights`, `sync_status`
  - Criterion: Use measured native-script reading and actual utterance timing, not a fixed character-per-minute formula. When narration is needed require pronunciation, supported locale, voice consent and measured word cues before scene locking; music-only uses beat cues, muted channels need no audio or STT.
- `reel_adapter_check`
  - Required result fields: `selected_executor`, `capabilities`, `workspace_scope`, `deterministic_time`, `commands_timeout_cancel`, `partial_resume`, `font_readiness`, `toolkit_provenance`, `source_bound_run`
  - Criterion: A selected renderer needs observed capability and a bounded reproducible recipe with time-based seek, timeout/cancel and partial/resume policy; HOLD missing capability, pageerror or font readiness, and never install tools, download fonts or call paid APIs implicitly.
- `reel_preview_check`
  - Required result fields: `style_frames`, `draft`, `transition_strips`, `keep_fix_rebuild`, `weakest_scene`, `revision_spend`, `delivery_size_review`, `strongest_scene`, `anti_slide_review`, `composition_variety`, `before_after_and_boundaries`, `product_gap`
  - Criterion: Inspect actual style frames then a moving draft and transition strips at delivery-size; assign keep/fix/rebuild and revise the weakest scene within a declared iteration/time budget, then re-render and compare. A draft contact sheet where one composition fills most of the runtime is REVISE: rebuild segments by medium and motion. Stills alone cannot pass motion QA. When the weak part is the product being shown rather than its staging, record a product_gap naming the missing capability and report it to the user; effects do not fill a thin feature.
- `reel_export_check`
  - Required result fields: `files_hashes`, `codec_dimensions_fps_duration`, `color_metadata`, `filesize_cap`, `audio_metrics`, `av_sync`
  - Criterion: Record measured hashes, size, duration, fps, codec, color primaries/range and channel constraints; HOLD unsupported codec, oversized output or missing measurements. Audio requires loudness/true peak and A/V sync, with STT only when speech exists; numerical results are not listening evidence.
- `reel_qa_check`
  - Required result fields: `content_brand`, `locale_font_bidi`, `cut_motion`, `delivery_size_legibility`, `temporal_audio`, `critical_defects`, `disposition`, `evidence_refs`, `technical_verdict`, `artistic_verdict`, `playback_verdict`, `listening_verdict`, `literal_copy`
  - Criterion: Return PASS/REVISE/HOLD per check and overall HOLD on any critical or unobserved required check; inspect actual delivery-size playback, cuts, transitions, frozen frames and flashes, native line breaks, shaping and mixed RTL/LTR runs. Read every on-screen literal against the source register: a product fact that differs from its cited source, or a count that disagrees with its noun (1 agents), is REVISE. No linguistic completeness, accessibility safety or human listening claim follows from automated metrics.
- `reel_delivery_check`
  - Required result fields: `generated_files`, `attachment_receipt`, `recipient_state`, `publication_approval`, `source_package`, `missing_evidence`
  - Criterion: Separate generated, attached, received and published; a local path proves no transfer. Package reproduction sources, pinned tool versions, locale variants, licenses and QA receipts without secrets/private originals. External upload, spend and publication require exact-target approval and readback; missing requested video or QA keeps delivery HOLD.

### `reel_brief` (analysis)

Create the audience brief with explicit duration/format, language decision basis, separate reply/content/subtitle/pronunciation/voice/font/direction tracks, literal tokens, budget and missing facts; retrieve what is available before asking.

- Input refs: `objective audience and channel`, `duration format and budget`, `source brand and asset permissions`, `available production tools`
- Output refs: `show_reel_brief/v1`
- Check IDs: `reel_brief_check`

### `reel_verify_sources` (validation)

For an idea video with nothing of a product on screen, record `no_product_claims` and move on. Otherwise verify claim provenance, revision, brand identity, screenshots, font and asset rights; distinguish supplied, observed, vendor-asserted, inferred and concept. Resolve conflicts or HOLD; never fabricate metrics, customers or real demos.

- Input refs: `objective audience and channel`, `source brand and asset permissions`
- Output refs: `show_reel_source_asset_register/v1`
- Check IDs: `reel_source_check`

### `reel_select_concept` (analysis)

For an idea video, pick one concept from its genre recipe in `references/genres.md` and record its assumptions. For a product, brand or work film, author at least 3 distinct concept candidates, compare one shared rubric, select with reasons and rejected alternatives, and fix the iteration/time budget including weakest-scene revision; do not impose a default aesthetic.

- Input refs: `objective audience and channel`, `duration format and budget`, `source brand and asset permissions`
- Output refs: `show_reel_concept_selection/v1`
- Check IDs: `reel_concept_check`

### `reel_direct_segments` (production)

Author each timed segment with message, source/asset IDs, medium, palette, typography, texture, layout, camera/object movement and transition, listing a distinct composition per beat so that adjacent segments differ in at least two of medium, palette, typeface, motion and texture; bind native-script text runs and visibly distinguish concept from captured product evidence.

- Input refs: `objective audience and channel`, `duration format and budget`, `source brand and asset permissions`
- Output refs: `show_reel_storyboard/v1`
- Check IDs: `reel_story_check`

### `reel_measure_timing` (production)

Select muted, music-only or narration mode only as needed; measure reading, approved pronunciation and word/beat cues before locking scene times, keep literal onscreen text separate, and HOLD unsupported voice locales or consent.

- Input refs: `objective audience and channel`, `duration format and budget`, `available production tools`
- Output refs: `show_reel_timing_map/v1`
- Check IDs: `reel_timing_check`

### `reel_author_motion` (production)

Read the installed `toolkit/README.md`, `references/motion-techniques.md`, `references/craft-engine.md` and `references/craft-techniques.md` with ordinary file tools; write scenes fresh from the segment art direction with the engine or another observed host-tool recipe. Bind toolkit provenance and source-bound run receipts, safe inputs/cwd, versions, deterministic seek, commands, timeout/cancel and font readiness; serial capture has no resume/chunk claim. Author motion without hidden installs or core subprocesses.

- Input refs: `objective audience and channel`, `duration format and budget`, `source brand and asset permissions`, `available production tools`
- Output refs: `show_reel_renderer_handoff/v1`
- Check IDs: `reel_adapter_check`

### `reel_review_revise` (validation)

Render style frames, then draft playback and transition strips at delivery-size; record keep/fix/rebuild by scene, identify strongest and weakest scenes, reject repeated headline/card/rail grammar, spend the declared revision budget rebuilding the weakest, compare same-time before/after plus both cut boundaries, re-render, and stop at the budget with unresolved defects visible.

- Input refs: `objective audience and channel`, `duration format and budget`, `available production tools`
- Output refs: `show_reel_preview_review/v1`
- Check IDs: `reel_preview_check`

### `reel_export` (production)

Export actual master/share variants as requested; measure codec, color, dimensions, fps, duration, filesize and hashes, audio loudness/true peak and sync when audio exists. Keep failed and partial outputs distinct from final files.

- Input refs: `duration format and budget`, `available production tools`
- Output refs: `show_reel_export_manifest/v1`
- Check IDs: `reel_export_check`

### `reel_validate` (validation)

Inspect actual delivery-size playback, content/brand, localized native line breaks, glyph fallback, Arabic shaping/bidi isolation, cuts, motion and audio; return evidence-linked PASS/REVISE/HOLD, keep technical, artistic, full-speed playback and listening verdicts independent; never whole-video PASS from a screenshot, score, metric or preset.

- Input refs: `objective audience and channel`, `duration format and budget`, `source brand and asset permissions`, `available production tools`
- Output refs: `show_reel_qa_report/v1`
- Check IDs: `reel_qa_check`, `reel_export_check`

### `reel_deliver` (validation)

Deliver requested files and source package with selected sources, pinned versions, licenses, locale variants, regeneration recipe and QA receipts; distinguish generated/attached/received/published with exact-target readback and honest missing evidence. HOLD a video request if only a storyboard exists.

- Input refs: `objective audience and channel`, `duration format and budget`, `source brand and asset permissions`, `available production tools`
- Output refs: `show_reel_delivery_manifest/v1`
- Check IDs: `reel_delivery_check`, `reel_qa_check`

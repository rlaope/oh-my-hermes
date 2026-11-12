# Assets, brand and consent register

Image generation, real photos, cutouts and post-processing are in
`references/craft-images.md`; `prep_images.py` removes letterboxes, resizes and
(macOS, opt-in) cuts out subjects. Record asset_id, source locator/revision/date, local safe reference, SHA-256,
file type/dimensions/duration, rights holder, license, permitted modification,
usage/channel/territory limits, consent and verification status. Prefer supplied,
official and rights-cleared sources. Verify downloaded bytes are the expected
asset, not a login page. Do not auto-download or install fonts or packages.

Keep untouched brand masters. Verify identity, geometry, color, clear space and
requested modification rules; a generated lookalike is not official artwork.
Fonts need actual file license, hash, weights and representative glyph/shaping
coverage, not a family-name assertion. Check fallback in the exact renderer;
Latin/CJK/Arabic runs may need different fonts without changing hierarchy.

For generated assets record tool/model/version, permitted provenance reference,
seed and transformations when observed; mark inferred/missing metadata unknown.
Concept artwork is concept on screen and in the register, never a captured demo.
Music, portraits, identifiable people, third-party UI and voice have separate
rights. A TTS provider's locale dropdown is neither a voice license nor consent.
Voice cloning requires distinct explicit permission; no default clone or voice.

HOLD public usage of unverified assets; use an approved alternative or ask the
one rights question. Creation permission is not publication/spend permission.
Never embed credentials, private customer data, unnecessary absolute paths or
private raw source in the shared package. A locator may be redacted but its
verification status and limitation remain visible. Keep source retention and
external-transfer permissions separate from the right to view an asset locally.

# Changelog

## 2.1.0 — 2026-10-26

### Player and browsing

- Added standalone controls around one native video element: full time display,
  a single-row timeline, seven playback rates and wrapper fullscreen.
- Retained keyboard shortcuts and segment-safe 30-second/5-minute jumps; jump
  buttons outside the player return when wrapper fullscreen exits.
- Desktop volume is an inline horizontal slider with direct mute/unmute. Mobile
  and coarse/no-hover touch layouts show the speaker button only, including
  landscape and wrapper fullscreen. No vertical volume popup is included.
- Improved white/pink control contrast, soft bottom shading and mobile progress
  thumb spacing without shortening time labels or reducing the thumb size.
- Removed number/duration overlays from video covers, including actor lists and
  missing-cover placeholders. Video titles still retain their numbers.
- Removed category and issuer filters from actor detail pages and avoided their
  unused catalogue requests. Category/issuer detail pages retain their respective
  filters. Existing combined filter URLs, sort/page state and return paths work
  as before; underlying metadata is not removed.

### Shared catalogue core 2026.10.25.1

- Treat known shop prefix 200GANA as the same work as GANA. Keep unknown-prefix
  rejection and printed-number precedence over URL tokens.
- End Japanese/English fallback genre fields at Description, preventing synopsis
  text from becoming tags.
- Keep display-name mappings, orthography and source priority unchanged. The
  included wheel is rebuilt from the clean public core source, with a refreshed
  pinned hash. No data migration is required.

### Dependencies and verification

- Include Media Chrome 4.19.4 and ce-la-react 0.3.2 under their original MIT and
  BSD-3-Clause notices; other dependency versions remain pinned.
- 93 synthetic Python tests, 41 frontend tests, TypeScript/Vite, a fresh locked
  noneditable installation and disconnected empty-library startup pass.
- No real Telegram media or iPhone/Safari-device validation is claimed.

## 2.0.0

Initial public MIT source release with the website, shared catalogue core,
pinned dependency locks, generic deployment examples and synthetic tests.

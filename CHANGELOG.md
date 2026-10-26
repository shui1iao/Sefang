# Changelog

## 2.2.0 — 2026-10-26

### Browsing and reuse

- Refine the dark/coral UI across desktop and mobile, with consistent content
  widths, readable secondary text and no header divider or parent-title breadcrumbs.
- Keep list/directory content mounted while route loaders prepare the next page;
  retain cancellation, retries, filter state, pagination and exact return navigation.
- Reuse pure artwork, video grids, paging, message/loading components and request
  helpers; remove dead cover-badge branches, duplicated computations/styles and
  unused direct dialog/popover dependencies.

### Player and sorting

- Hide wrapper-fullscreen controls after one second of inactivity while playing.
  Pointer/keyboard input reveals them; pause, loading, menus, drag/hover and keyboard
  focus protect controls from hiding. Ordinary playback controls remain visible.
- Use consistent standard bold time/control text in fullscreen and ordinary mode;
  keep single-video playback, segment-safe seeking, mute/volume and seven rates.
- Offer joined time, duration and release date with ascending/descending direction.
  Use the same group join-time key in both directions; keep unknown values last and
  deterministic ties. Name sorting is removed from the menu, URL model and API.
- Preserve current filters when sorting; reset page on changed field/direction and
  keep sort/page when returning from a video. No schema or metadata changes.

### Release integrity

- Keep the clean shared-core 2026.10.25.1 source and wheel unchanged, along with the
  existing MIT/OFL/BSD and other third-party notices and remaining dependency pins.
- Public tests use synthetic data and mocked responses. No real Telegram media or
  iPhone/Safari-device verification is claimed; native system fullscreen can differ.

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

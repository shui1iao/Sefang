# Changelog

## 3.0.1 — 2026-10-31

### Streaming disconnect repair
- Cancel and await only an abandoned request's preparation while it waits for the media gate, Telegram message lookup or the opening media slice. Release its transfer/gate independently so stale requests cannot occupy the two-response cap and reject a new Range request with 429. Connected sibling responses remain independent.
- The preparation-only disconnect reader discards unused GET/HEAD request bodies without retaining chunks and stops before response-body handling. Login, own-only history, playback-window limits, aggregate rate limits, Range semantics and body streaming remain unchanged. Frontend/static assets, shared core and dependencies are unchanged; temporary diagnostics are not distributed.
- Add synthetic real-TCP disconnect regressions, including cap recovery, sibling survival, cleanup races, revocation, timeout, HEAD/Range headers and bounded retained memory.

### Known issue — not confirmed fixed
- iPhone ordinary playback/seek **and** history resume/seek may still have audio with a frozen picture. This disconnect repair has not been verified on a physical iPhone and does not establish the cause of that symptom. Ordinary playback followed by manual seeking is **not a reliable workaround**. No real Telegram or long-duration playback certification is claimed.

## 3.0.0 — 2026-10-28

### Breaking upgrade
- All catalogue/image/media access requires a web account: anonymous APIs return 401, protected pages redirect to login. No default administrator/password; initialize locally with `sefang init-admin --username <chosen-name> --max-playbacks <chosen-limit>` and its non-echoing password prompt. Without an administrator, access fails closed. Browser login needs HTTPS, preserved Host, exact Origin and CSRF protection.
- Preserve current configuration, Telegram session and the original four databases. Authentication and own-only history add private persistent stores; back them up too, never treat them as caches or restore stale state during a code rollback. No reimport/deletion or schema-migration system is required.

### Features and repairs
- Administrator-created accounts, enable/disable and password reset; 24-hour sessions with revocation. Default ordinary-account 2 MiB/s aggregate across sessions/windows/cache, explicitly set window limits, same-lease response cap 2 and unchanged global gate 2. No registration, billing, account expiry or device tracking.
- Own-only long-lived playback history, including administrators; real playing starts recording. Explicit history resume restores part/time paused, with readiness gating and no automatic playback. Horizontal large centered covers and pink code/real-title presentation, neutral account actions, username management link and compact desktop limit-save button.
- Ordinary/fullscreen guarded control hiding and gestures, same-kind entity navigation/return state, whole-row directory pagination, and existing post-2.2 UI changes.
- Repaired mutual cancellation of same-lease Range responses and premature play during history restore. Temporary phone diagnostics are excluded; shared clean core 2026.10.25.1 and all dependency versions are retained.

### Known issue — not fixed
- iPhone history resume can play audio and advance the clock while the picture remains frozen. Cause unresolved; no real iPhone/iOS certification is claimed. The two Range/early-play repairs above are **not** evidence that this iPhone symptom is fixed. Ordinary-entry playback followed by manual seeking is a reported workaround, not a guaranteed repair. No additional freeze or unrelated legacy-bug fix is included.
- MIT covers source code, not redistribution of media, messages, images or catalogue content. No security or Telegram-account-ban guarantee is made.

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

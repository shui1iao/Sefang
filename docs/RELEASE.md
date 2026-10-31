# Version 3.0.1 source release

This source release includes the website, frontend source and unchanged 3.0.0 static assets, clean shared catalogue core 2026.10.25.1 source and its pinned wheel, generic deployment examples and synthetic tests. No real channel data, credentials, session, installation-specific role/alias lists, temporary phone diagnostics or deployment records are distributed.

## Patch scope

Abandoned stream requests are now observed while waiting for the media gate, Telegram message lookup or the opening media slice. Their preparation work is cancelled and awaited, and only their own transfer/gate is released. This prevents abandoned requests from filling the two-response cap and rejecting a new Range request with 429, without cancelling a still-connected sibling. The sole preparation receive reader discards unused GET/HEAD bodies without retaining payload chunks and is stopped before body streaming. Authentication, own-only history, window limits, aggregate rate limits, Range/body behavior, grouping and cache policy are unchanged. No temporary diagnostics are distributed.

## Major upgrade and operation

2.x anonymous access is replaced by mandatory web-account login. Anonymous data APIs return 401 and protected pages redirect to login. There is no default administrator or password; a local operator must run `sefang init-admin --username <chosen-name> --max-playbacks <chosen-limit>` with the non-echoing getpass prompt. Existing administrator/name conflicts are refused. An empty installation without an administrator fails closed. HTTPS, preserved original Host, exact Origin and authenticated-write CSRF checks are required; HTTP health checks do not demonstrate usable login. See [README](../README.md) for the generic HTTPS setup.

Stop one owner normally for upgrades and preserve current configuration, credentials/session and the original four databases and sidecars. The application adds private auth/history stores without rewriting those databases. Their complete directories are persistent business data, not caches; preserve current accounts, sessions, history and deletion/generation state in backups. No reimport, deletion or new migration framework is required. Never expose an old anonymous version as a public fallback or roll current data back with old code.

Media remains read-only; account/history/playback-control endpoints deliberately write authenticated state. Ordinary accounts default to 2 MiB/s aggregated across sessions/windows/cache hits; the operator explicitly chooses window limits. Same-lease GET response cap is 2, and the global gate remains 2. History is own-only even for admins; real playing begins records, explicit history links restore part/time paused, and ordinary links do not implicitly resume. Sessions last 24 hours; logout, disable and password changes revoke the relevant sessions/streams. No registration, account expiry, payments or device tracking is included.

## Known issue and verification limits

**Unresolved: iPhone ordinary playback/seek and history resume/seek may produce audio and an advancing clock while the picture stays frozen. The cause is not established.** This disconnect repair has not been verified on a physical iPhone and does not prove that symptom is fixed. Prior overlapping-Range/early-play repairs also do not establish a fix. Ordinary playback followed by manual seeking is **not a reliable workaround**. No real iPhone/iOS certification or unrelated legacy-bug repair is claimed.

For the prior 3.0.0 release, public-source checks used Python 3.14 and Node 24: locked noneditable installation (31 distributions), 127 frontend tests, TypeScript/Vite build and lint; 126 backend test executions pass. These include 25 distinct auth/history/window targeted cases; imported inherited cases are counted separately by discovery. The public 2.2.0 baseline passes its 96 backend tests on the same machine. All fixtures are synthetic or mocked; no Telegram login, real channel database, photographs or media download is needed. Local Chromium HTTPS smoke uses generated neutral media and isolated accounts. These checks are not real Telegram, Safari, physical-device, long-load or iOS playback certification and do not guarantee security or freedom from Telegram restrictions.

For 3.0.1, public-source verification runs the new real-TCP disconnect/memory regressions and existing auth/history/window/Range tests, plus an offline locked noneditable installation with installed-package byte checks. Fixtures are synthetic and local. Frontend/static assets have no delta from 3.0.0, so they are checked byte-for-byte without a frontend rebuild. These checks do not exercise real Telegram, a physical iPhone or long-duration playback.

Core source, 144 factual name mappings/orthography data, category-policy cleaning, wheel bytes and dependency versions are unchanged from the clean public baseline. Static frontend assets retain the byte-identical reviewed 3.0.0 build corresponding to the unchanged frontend source, not an installation copy. Source licenses do not authorize redistribution of media or channel material.

## Distribution and licenses

The two release attachments are `Sefang-v3.0.1-source.tar.gz` and `SHA256SUMS` (one checksum line for that tar). The archive has one `Sefang-v3.0.1/` prefix and the exact reviewed public Git file set. It excludes Git metadata, environments, dependency directories, caches, runtime state, internal manifests, reports and credentials. Files are normalized to 0644 with zero ownership/timestamps, USTAR without PAX/links, and gzip without a filename/time; repeated generation is byte-identical.

Sefang/core code: MIT with project attribution **Sefang authors**. Original third-party authors and complete license notices remain in LICENSE/NOTICE, THIRD-PARTY-NOTICES, core notices and licenses/. Media Chrome 4.19.4 MIT, ce-la-react 0.3.2 BSD-3-Clause and the SIL-OFL wordmark notices are retained. Code licensing grants no media, message, likeness or trademark rights.

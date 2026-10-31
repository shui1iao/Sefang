# Sefang

Sefang **3.0.1** is a self-hosted video library for Telegram channels you are authorized to access and share. React/Vite provides browsing, search, directories and standalone controls around one native video element; FastAPI provides grouped multipart playback and HTTP Range reads through one Telethon session owner. Media access is read-only: there is no upload or message-edit endpoint. Account management, playback leases and personal history have explicit authenticated write APIs.

**Breaking change from 2.x: login is required.** Anonymous data/image/media APIs now return **401**; protected page requests redirect to `/login`. Public login assets and `/healthz` remain available. There is **no default administrator or password**. Without a locally initialized administrator, private data stays closed. Do not expose private channel material publicly. Telegram access alone does not grant redistribution rights. Respect copyright, privacy, consent, platform rules and local law. This repository contains no channel data, credentials, videos or photographs.

## Changes in 3.0.1

- Abandoned requests waiting for the media gate, Telegram message lookup or the opening slice now cancel and await their own preparation and release only their own transfer/gate. Stale requests no longer fill the two-response cap and reject a new Range request with 429; still-connected sibling responses remain independent.
- A preparation-only disconnect reader discards unused GET/HEAD bodies without retaining chunks and stops before response-body handling. Login, own-only history, playback-window limits, aggregate rate limits and response-body streaming are unchanged. Frontend/static assets, core and dependencies are unchanged; temporary diagnostics are not distributed.
- Synthetic real-TCP disconnect and memory regressions are included. This is not a physical-iPhone freeze certification.

## Changes in 3.0.0

- Local administrator bootstrap; administrator-created accounts with enable/disable, password reset, aggregate rate limits and explicitly chosen playback-window limits. The top management link uses the current administrator username; ordinary users do not gain a management entry. Desktop limit-save buttons remain compact.
- Each ordinary account defaults to **2 MiB/s total**, shared across sessions, windows and cache hits; administrators initially have no rate limit. The operator must set each account's simultaneous playback limit. A server-issued playback lease counts as one active window and permits at most **two concurrent GET responses**; a third is refused, not queued indefinitely. Unleased direct requests count separately. The existing global media gate remains **2**. These limits cannot retract bytes already buffered/downloaded and do not track physical devices.
- Random **24-hour sessions**, Secure/HttpOnly/SameSite=Strict host-only cookies, exact HTTPS Origin and CSRF checks, server-side roles and login-attempt limiting. Logout revokes that session; disabling an account or changing its password revokes its sessions and active streams. There is no self-registration, account-expiry, billing or device-tracking system. These controls are not an absolute security guarantee.
- History is own-only, **including for administrators**. Actual native `playing` starts a record; opening details, metadata/preload or seeking without playback does not. History is retained until the owner deletes it, with pagination and confirmed delete/clear. Only a history link restores the saved part and position, **paused**, after readiness checks; a fresh user click is needed. Ordinary links do not implicitly resume.
- History cards stay horizontal at small widths, with large vertically centered covers, pink work codes and real work titles rather than filenames; missing titles remain explicit placeholders. Normal and wrapper-fullscreen controls share guarded idle hiding and touch gestures; native platform fullscreen remains browser-controlled.
- Same-lease overlapping Range responses no longer cancel each other, and early play is gated while a history position is being restored. **These two repairs do not establish that the iPhone freeze is fixed.**
- Existing post-2.2 navigation, same-kind actor/category/issuer switching and return state, whole-row directory pagination and six-direction video sorting are retained. Shared core **2026.10.25.1**, name/orthography data and all dependency versions remain unchanged. Temporary phone-diagnostic entry points are not distributed.

## Known playback issue

**iPhone ordinary playback/seek and history resume/seek may still have continuous audio and an advancing clock while the video picture remains frozen. This is unresolved; the cause is not established.** The preparation-disconnect repair has not been verified on a physical iPhone. Successful desktop/Chromium checks are not iOS certification, and no real iPhone/iOS playback verification is claimed for this release. Neither this repair nor the prior overlapping-Range/early-play repairs establish that the symptom is fixed. Ordinary playback followed by manual seeking is **not a reliable workaround**. No unrelated legacy-bug fix is included.

See [CHANGELOG.md](CHANGELOG.md) and [docs/RELEASE.md](docs/RELEASE.md) for upgrade and verification boundaries.

## Requirements

- Python **3.14 or newer**, `uv`, Node.js **22.12+** (or 20.19+) and npm.
- A legal Telegram user account, your own API application credentials, an already-authorized Telethon StringSession and an explicit allowlist of channels. The site **does not perform Telegram login** (web-account login is separate). Obtain credentials and a session separately using Telegram/Telethon's documented process; never send them to a repository or issue tracker.
- Sufficient local storage for metadata and bounded caches. Slice cache and catalogue covers are each capped at **512 MiB**; actor portraits are capped at 64 MiB total, 2 MiB each and 512 files. These are caches, not an archival copy of a channel.

## Install and build

From any new checkout directory (all commands here are relative to the checkout):

```sh
uv sync --locked --no-dev --no-editable
npm --prefix frontend ci
npm --prefix frontend run build
```

`frontend` builds into `src/sefang/static`. **After rebuilding the frontend, run `uv sync --reinstall-package sefang --locked --no-dev --no-editable`** so the installed package contains the rebuilt assets. Built assets are included for convenience and correspond to the included frontend source. Do not run the service from an editable development install for a release.

Dependencies are pinned in `uv.lock` and `frontend/package-lock.json`. No global package modifications are required. A warm local dependency cache permits the same commands with `uv --offline` / `npm --offline`; a new machine normally needs public package-registry access. The small included `vendor/se_catalog_core-2026.10.25.1-py3-none-any.whl` is built from the accompanying `core/` source, not downloaded from a private registry.

### Rebuild the shared core

```sh
SOURCE_DATE_EPOCH=0 uv build --wheel --offline --out-dir vendor core
python3 scripts/update_core_hash.py
uv lock --offline
uv sync --locked --no-dev --no-editable --reinstall-package se-catalog-core
```

Omit `--offline` on the first build if the pinned setuptools build dependency is not cached. The core version remains **2026.10.25.1**. Its code, orthographic rules and factual display-name mappings are included. `core/NOTICE.md` describes attribution and the omission of research-page quotations; factual names do not create identity aliases. `data/build.json` identifies the distributed name data; its source hash is SHA256 over sorted relative `se_catalog/*.py` paths, NUL, file bytes, NUL. The bundled wheel is rebuilt from this cleaned source with `SOURCE_DATE_EPOCH=0`; the pinned build tools reproduce it byte-for-byte under that setting. Rebuild without that setting and ZIP timestamps can differ; always inspect its contents and RECORD before updating the locked hash.

## Runtime configuration

Choose private directories **outside** the checkout. The following are generic examples, not an existing deployment:

```sh
umask 077
mkdir -p "$HOME/.local/share/sefang/data/secrets/telegram" "$HOME/.local/share/sefang/state"
export SEFANG_DATA_ROOT="$HOME/.local/share/sefang/data"
export SEFANG_STATE_ROOT="$HOME/.local/share/sefang/state"
export SEFANG_CHANNEL_IDS=123
export SEFANG_OFFLINE=1
# Initialize a NEW disconnected index only (never copy someone else's database).
.venv/bin/python -c 'from sefang.config import Config; from sefang.tg.index import ChannelIndex; ChannelIndex(Config.environment().db)'
# Explicit local bootstrap; getpass prompts twice without echo. Choose your own name.
# Passwords must be 12–256 characters; never put one in argv or shell history.
.venv/bin/sefang init-admin --username library_admin --max-playbacks 2
.venv/bin/sefang serve --host 127.0.0.1 --port 18943
```

With a new data directory and `SEFANG_OFFLINE=1`, this starts an empty disconnected library. It is useful for installation checks, **not** evidence of a functioning Telegram session. `http://127.0.0.1:18943/healthz` is a health check only: **do not use HTTP for login**. A Secure cookie and HTTPS Origin are required, even on a disconnected installation. Bootstrap refuses an existing administrator or conflicting name; it does not overwrite accounts. No bootstrap is performed automatically by the server.

For browser use, configure a trusted HTTPS endpoint on your own domain, forwarding to the loopback server and **preserving the original Host, including any port**. For example, a separately installed Caddy can use this generic configuration (its default reverse proxy preserves Host):

```caddyfile
library.example.org {
    reverse_proxy 127.0.0.1:18943
}
```

Replace the example domain with one you control and configure its DNS/TLS; the repository does not install or edit a proxy. Visit `https://library.example.org/login`, not the upstream HTTP URL. Writes require an exact HTTPS Origin matching Host and, after login, the session's CSRF token; replacing Host with the upstream address breaks this check. Never disable cookie security or Origin/CSRF checks to make an HTTP quickstart appear to work. For local tests use a trusted local certificate and HTTPS with the same host/port. Stop the owner before configuring the real Telegram connection.

For an authorized online instance, create a private JSON file at `$SEFANG_DATA_ROOT/secrets/telegram/account.json` with the following schema. Do **not** copy these placeholder strings as real credentials:

```json
{
  "api_id": 0,
  "api_hash": "",
  "session": "",
  "paused": true,
  "channels": []
}
```

- Replace `api_id`, `api_hash` and `session` with your own valid credentials/StringSession. A session is equivalent to account access: restrict the directory to 0700 and file to 0600, back it up privately and revoke it if leaked.
- Each `channels` object needs `id` (positive channel ID, **not** a `-100`-prefixed peer ID), `title`, `access_hash` (decimal string), and optional `protected` boolean. Example field types only: `{"id":123,"title":"Example channel","access_hash":"0","protected":false}`. IDs/hashes must come from your own authorized account; the example is not a reachable channel.
- Set `SEFANG_CHANNEL_IDS` to the same comma-separated positive IDs as the account's `channels`. Mismatch fails closed. Never add a channel you are not entitled to read/share. Change `paused` to false and `SEFANG_OFFLINE=0` only when the configuration is complete.
- Run **one owner process only**, one Uvicorn worker, no development auto-reload. Do not run another Telegram client using this same session, account maintenance job or second website owner concurrently. The local owner lock is kept under the data directory; do not delete it to bypass ownership.

The index is generated below `data/database`, covers/slices below `data/generated`, and the derived entity/localization state below `SEFANG_STATE_ROOT`. Missing metadata does not block browsing. Telegram new/edit/delete events update the local index; the site does not edit Telegram messages. Protected media is streamed without persisting video slices. Catalogue/portrait and title-translation workers can contact public metadata sources; these are not part of the offline installation check. Use only where authorized and observe upstream terms/rate limits. Translation requests may disclose title text to the configured public translation endpoints; use disconnected mode if external requests are not acceptable.

`deploy/sefang.env.example` and `deploy/sefang.service` are optional **generic** Linux/systemd examples. Adapt all paths and the `sefang` service user to your machine, create that user and private directories first, then install the unit yourself. Nothing in this repository automatically changes services or configures a reverse proxy.

### Optional local roles and actor aliases

No installation-specific actor/hashtag allowlist is shipped. Missing files behave as empty lists; metadata-derived entities and the included explicit category-token policy still work.

- `$SEFANG_STATE_ROOT/tag-roles.json`: `{"categories":{},"actors":[]}`. A category object maps an exact hashtag token to a category name; `actors` contains exact actor tokens. Unknown hashtags remain in the caption, not guessed into a role. Copy `deploy/tag-roles.example.json` only if needed.
- `$SEFANG_STATE_ROOT/actor-aliases.json`: `{"version":1,"groups":[]}`. Each reviewed group uses `canonical`, `aliases`, a stable 24-hex `id`, and optional reliable Chinese `name_zh`. The default ID for a new canonical actor is the first 24 hex characters of SHA256 of `"actors\0" + canonical`; retain the chosen ID thereafter. Maximum 38 groups; overlapping identities are rejected. Only the shared reviewed display-name table supplies Chinese display labels; arbitrary translations do not create identities. Copy `deploy/actor-aliases.example.json` only if needed.

Category policy is shipped as source data: 83 explicit merge groups, 306 approved canonical hashtag tokens, 21 exact promotional drops and 128 retired IDs. It preserves original labels and search-only Chinese aliases; unknown tags are not inferred into new approved identities. Retired entity IDs resolve to no entity and filtering them returns no results. This is a policy table, **not** a snapshot of channel contents or a promise that an empty installation has 306 populated categories.

## Upgrade from 2.x and persistent data

This is a major upgrade, not an anonymous-service drop-in replacement. Stop the single owner normally and back up the **current** configuration, Telegram credentials/session, original four databases and sidecars, derived state, role/alias files and caches before replacing code. Keep their locations and contents; there is no old-data reimport, restore or deletion step and no new migration framework. Rebuild/install locked code and assets as above. Run the local `init-admin` command with explicit `--username` and `--max-playbacks` if no administrator exists; use the non-echoing terminal prompt, not a password argument. Then start one owner behind HTTPS and verify login before sharing access.

The application safely adds `$SEFANG_DATA_ROOT/state/auth/accounts.sqlite3` and `$SEFANG_DATA_ROOT/state/history/history.sqlite3` (private directories 0700, files 0600) without rewriting the original four databases. **Authentication and history are persistent business data, not disposable caches**: preserve their complete directories, accounts, sessions, histories and deletion/generation state in consistent backups with all existing data. Do not clear them for an upgrade. On later code changes, preserve every current legitimate increment; never restore an old database just to roll back code. An older anonymous version must not be exposed as a public fallback. These notes do not authorize downtime or data changes on any existing installation.

## Local maintenance and tests

Local CLI commands (not web endpoints) include `entities`, `status`, `avatars`, `metadata-pause`, `metadata-resume`, `fill-missing-covers`, `translate`, `translation-status`, `translation-pause`, `translation-resume`. Some fetch public metadata or write derived state. Back up your **current** data before maintenance. To update code, stop the single owner normally, preserve current data/config/session/caches, install the new code, then start one owner. A code rollback must not overwrite newer business data with an old database.

```sh
.venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend test
npm --prefix frontend run typecheck
```

Tests use explicitly synthetic channels/messages and mocked network responses; they need no Telegram login, real database, photographs or media downloads. Historical deployment/snapshot scripts are intentionally not distributed. Test output and temporary state must not be committed. See `docs/RELEASE.md` for release contents and verification boundaries.

## License

MIT for Sefang and the included self-authored core: `LICENSE`, `core/LICENSE`. Project attribution is **Sefang authors**. Third-party license texts and authors remain in `THIRD-PARTY-NOTICES.md`, `core/THIRD-PARTY-NOTICES.md`, `core/OPENCC-LICENSE` and `licenses/`. The wordmark uses SIL-OFL Caveat Brush vector outlines; its notices are retained. MIT grants source-code reuse, modification, commercial use and redistribution; it grants no rights to third-party media or catalogue content.

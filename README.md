# Sefang

Sefang **2.1.0** is a self-hosted, read-only video library for Telegram channels you are authorized to access and share. React/Vite provides browsing, search, actor/category/issuer directories and standalone controls around a single native video element; FastAPI provides grouped multipart playback and HTTP Range reads through one Telethon session owner. There is no web login, administration panel, upload or message-edit endpoint. The current UI has no footer and omits raw-message descriptions; original files and messages are not deleted.

**Do not expose private channel material to the public.** The web interface is anonymous and has no access-control layer. Bind to loopback; if remote access is needed, configure your own TLS reverse proxy and appropriate access control. Telegram access authorization alone does not grant redistribution rights. Respect copyright, privacy, consent, platform rules and local law. This repository contains no videos, photographs, channel data or credentials.

## Changes in 2.1.0

- Standalone player controls with a single-row timeline, complete time labels,
  seven playback speeds, keyboard support and wrapper fullscreen. Manual 30-second
  and 5-minute jumps stay within the current segment; fullscreen keeps the
  timeline and restores the outside jump buttons on exit.
- Desktop volume uses an inline horizontal slider and a direct mute button.
  Phones, including touch-device landscape and wrapper fullscreen, show only
  the mute/unmute button. The current UI has **no volume popup**.
- Improved control contrast and mobile timeline-endpoint spacing. Cover duration
  and number badges are hidden across home, entity and related-video cards;
  titles retain their numbers. Actor pages do not mount category or issuer filters;
  category and issuer pages retain their own respective filters. Existing filter
  URLs, sorting, pagination and return navigation are unchanged.
- Shared core **2026.10.25.1** recognizes the known `200GANA` shop prefix as the
  same work as `GANA`, while unknown prefixes and conflicting printed numbers
  still fail closed. `Description:` now ends fallback tag fields rather than
  leaking synopsis text into genres.

See [CHANGELOG.md](CHANGELOG.md) for the release summary and
[docs/RELEASE.md](docs/RELEASE.md) for verification boundaries.

## Requirements

- Python **3.14 or newer**, `uv`, Node.js **22.12+** (or 20.19+) and npm.
- A legal Telegram user account, your own API application credentials, an already-authorized Telethon StringSession and an explicit allowlist of channels. The site **does not perform login**. Obtain credentials and a session separately using Telegram/Telethon's documented process; never send them to a repository or issue tracker.
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
.venv/bin/sefang serve --host 127.0.0.1 --port 18943
```

With a new data directory and `SEFANG_OFFLINE=1`, this starts an empty disconnected library. It is useful for installation checks, **not** evidence of a functioning Telegram session. Open `http://127.0.0.1:18943/` or `/healthz`. Stop the process before configuring the real owner.

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

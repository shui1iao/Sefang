# Version 2.1.0 source release

This tree contains the website, frontend sources and reproducible built assets,
shared catalogue core 2026.10.25.1 source and a locally rebuilt wheel, pinned
Python and npm dependencies, generic deployment examples, and synthetic tests.
It contains no channel databases, session credentials, media, real caption
snapshots, installation-specific identity lists or deployment history.

Website and core code: MIT, project attribution "Sefang authors". Third-party
authors and licenses are retained separately; see NOTICE.md and licenses/.
Media Chrome 4.19.4 is MIT-licensed and ce-la-react 0.3.2 is BSD-3-Clause;
their complete original notices are included with the JavaScript license texts.
No prebuilt application executable or private registry is required.

## What changed

See ../CHANGELOG.md: current standalone player controls and responsive horizontal
volume/mute layout; mobile timeline spacing; cover-badge and actor-filter removal;
the known 200GANA same-work prefix and the fallback Description tag boundary.
No backend migration or dependency-version upgrade is required beyond the
included updated shared-core wheel and the pinned frontend additions.

## Verification

Verified with Python 3.14 and Node 24: fresh locked noneditable installation of
31 Python distributions; an offline npm install; TypeScript/Vite build; 93 Python
synthetic tests and 41 frontend tests. Built frontend assets reproduce exactly.
Core tests use generated HTTP response fixtures, never captured real pages:
GANA prefix equivalence, conflicting/unknown prefixes, authoritative printed
numbers, and Japanese/English Description tag boundaries are covered.

The clean core wheel is built from the included source with the pinned setuptools
and SOURCE_DATE_EPOCH=0; two builds produced identical bytes. Its hash is locked
in uv.lock. Display-name mappings and orthographic rules are unchanged; research
quotations and local snapshots remain omitted. A new empty offline index starts
on loopback with external socket connections forbidden and no attempted outbound
connection. These checks do not establish a functioning Telegram session.

Historical tests requiring private data are not distributed. All public tests use
synthetic fixtures or mocked network; no login, channel access, real photographs
or media download is needed. No real Telegram media or iPhone/Safari-device
playback verification is claimed. A working online instance needs your own
credentials, authorized data and appropriate access controls; see README.md.

## Source distribution

The release attachment is a source archive with one top-level Sefang-v2.1.0/
directory, plus SHA256SUMS. It contains the same public source members as the
repository, without .git, environments, caches, logs, reports or runtime state.
Archive ownership and timestamps are normalized. Build logs, deployment records,
review material and manifests are not part of the source distribution.

Use "Sefang authors" for project attribution. A source license does not license
media or grant rights to channel material. Review source archives, wheel contents
and notices before redistributing.

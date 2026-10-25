# Version 2.0.0 source release

This tree contains the website, frontend sources and built assets, the same-version
shared catalogue core source and wheel, pinned dependencies, generic deployment
examples, and synthetic tests. It contains no channel databases, session credentials,
media, real caption snapshots, old Git history or installation-specific identity lists.

Website and core code: MIT, project attribution "Sefang authors". Third-party authors
and licenses are retained separately; see NOTICE.md and licenses/.

Verified with Python 3.14 and Node 24: fresh noneditable installation with the locked
31 Python distributions; TypeScript/Vite build; 88 Python synthetic tests and 35
frontend tests. The frontend build reproduces the included static assets byte-for-byte.
Historical tests requiring a private database were omitted; synthetic fixtures were
updated for the current explicit cast-source, fallback-route and amateur-placeholder
contracts. The tests do not establish compatibility with a real Telegram account.

No real login, channel access or media download is needed for installation tests.
A functioning online instance requires your own authorized credentials and data.
Public metadata and translation behavior remains unchanged; read README.md before
starting online. No Safari-device or real-video playback validation is claimed here.

Use `Sefang authors` for project copyright. A publisher may use GitHub's noreply
commit identity rather than a personal email. Create a new repository history rather
than importing a deployment tree or old commits. Review source archives, package
metadata and notices before publishing; a source license does not license media.

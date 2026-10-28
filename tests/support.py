"""Offline stand-ins for Telegram used by the test-suite (no network, no login)."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from telethon import errors, types

BLOB = bytes((i * 7 + 3) % 256 for i in range(2_600_000))
CHANNEL = {"id": 123, "title": "合成测试频道", "access_hash": "456", "protected": False}


def fake_message(mid=1, *, name="合成.mp4", text="合成说明", document=900, seconds=3.0, size=None, protected=False):
    doc = SimpleNamespace(id=document, size=len(BLOB) if size is None else size, mime_type="video/mp4",
                          attributes=[types.DocumentAttributeVideo(duration=seconds, w=320, h=180),
                                      types.DocumentAttributeFilename(name)])
    return SimpleNamespace(id=mid, message=text, date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                           noforwards=protected, document=doc)


class FakeLink:
    """Behaves like TgLink against an in-memory channel."""

    def __init__(self, account, on_update):
        self.account, self.on_update = account, on_update
        self.posts = {1: fake_message()}
        self.reads, self.history_calls, self.message_calls = [], 0, 0
        self.expire_next = False
        self.fail_with = None
        self.closed = False
        self.read_delay = 0.0

    async def connect(self):
        return True

    async def close(self):
        self.closed = True

    async def history(self, channel, *, before=0, after=None):
        self.history_calls += 1
        if self.fail_with:
            raise self.fail_with
        posts = list(self.posts.values())
        if after is not None:
            return sorted((p for p in posts if p.id > after), key=lambda p: p.id)[:100]
        return sorted((p for p in posts if not before or p.id < before), key=lambda p: -p.id)[:100]

    async def message(self, channel, mid):
        self.message_calls += 1
        if self.fail_with:
            raise self.fail_with
        return self.posts.get(mid)

    async def read(self, message, offset, count):
        self.reads.append((message.id, offset, count))
        if self.read_delay:
            await asyncio.sleep(self.read_delay)
        if self.expire_next:
            self.expire_next = False
            raise errors.FileReferenceExpiredError(request=None)
        return BLOB[offset:offset + count]

    async def thumbnail(self, message):
        return b"\xff\xd8thumb"


def source_cast(index):
    """Add explicit synthetic source provenance to synthetic matched cast fields."""
    import json
    with index.session() as db:
        for row in db.execute("SELECT identity,code,metadata FROM tg_work").fetchall():
            fields=json.loads(row['metadata'] or '{}')
            if fields.get('performers'):
                fields['field_sources']={'performers':'test'}
                sources=[{'name':'test','url':'https://example.test/'+row['code'],
                          'returned_id':row['code'],'fields':['performers']}]
                db.execute("UPDATE tg_work SET state='matched',metadata=?,sources=? WHERE identity=?",
                           (json.dumps(fields),json.dumps(sources),row['identity']))


def auth_headers(app):
    """Local-only fixture, independent of real administrator credentials."""
    import secrets
    password = secrets.token_urlsafe(18)
    app.state.auth.bootstrap("fixture_admin", password, 4)
    token = app.state.auth.login("fixture_admin", password, "isolated-regression")
    return {"Cookie": "__Host-sefang_session=" + token}

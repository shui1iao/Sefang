import asyncio
import hashlib
import io
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from support import BLOB, CHANNEL, FakeLink, fake_message, source_cast  # noqa: E402

from sefang.app import create_app  # noqa: E402
from sefang.config import Config  # noqa: E402
from sefang.repository import Repository, entity_id  # noqa: E402
from sefang.streaming import BadRange, pick_range  # noqa: E402
from sefang.tg.cache import SLICE, SliceCache  # noqa: E402
from sefang.tg.index import ChannelIndex, video_from_message  # noqa: E402



def offline(root, live=False):
    return Config(root, root / "side", (123,), not live)


def seed(config, count=2):
    index = ChannelIndex(config.db)
    index.ensure_channel(123, "合成频道")
    for i in range(1, count + 1):
        row = video_from_message(123, fake_message(i, name=f"IPX-{i:03}.mp4", document=900 + i))
        index.store(123, [row])
        with index.session() as db:
            db.execute("UPDATE tg_work SET state='matched',metadata=?,sources='[]' WHERE identity=?",
                       (json.dumps({"title": f"合成作品{i}", "performers": ["甲"], "studio": "乙", "series": "系列",
                                    "tags": ["分类"], "release_date": "2021-01-01"}), f"IPX-{i}"))
    source_cast(index)
    repo = Repository(config)
    repo.sync_entities()
    return index, repo


def write_account(config, **extra):
    (config.secrets_root / "telegram").mkdir(parents=True, exist_ok=True)
    (config.secrets_root / "telegram/account.json").write_text(json.dumps({"channels": [CHANNEL], **extra}))




class DataTests(unittest.TestCase):
    def test_search_filters_sort_related_and_unidentified(self):
        with tempfile.TemporaryDirectory() as d:
            config = offline(Path(d))
            index, repo = seed(config, 3)
            self.assertEqual(3, repo.videos(q="甲")["total"])
            for key, kind, name in [("actor", "actors", "甲"), ("studio", "studios", "乙"), ("series", "series", "系列"),
                                    ("category", "categories", "分类")]:
                self.assertEqual(3, repo.videos(**{key: entity_id(kind, name)})["total"])
            self.assertEqual(0, repo.videos(actor="0" * 24)["total"])
            related = [r["id"] for r in repo.related(123, 1)["items"]]
            self.assertEqual(2, len(related))
            self.assertNotIn("123:1", related)
            index.store(123, [video_from_message(123, fake_message(4, name="未知.mp4", document=990))])
            self.assertEqual(4, repo.videos()["total"])
            self.assertEqual("unidentified", repo.dto(repo.raw(123, 4))["state"])
            repo.close()

    def test_index_identifies_once_and_keeps_metadata_on_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            config = offline(Path(d))
            index, repo = seed(config, 1)
            with index.session() as db:
                before = db.execute("SELECT * FROM tg_work").fetchall()
            self.assertEqual(0, index.store(123, [video_from_message(123, fake_message(1, name="IPX-001.mp4", document=901))]))
            with index.session() as db:
                self.assertEqual([tuple(r) for r in before], [tuple(r) for r in db.execute("SELECT * FROM tg_work").fetchall()])
            repo.close()


class RangeAndCacheTests(unittest.TestCase):
    def test_range_parser(self):
        self.assertEqual((0, 99, 200), pick_range("", 100))
        self.assertEqual((90, 99, 206), pick_range("bytes=90-999", 100))
        self.assertEqual((0, 99, 206), pick_range("bytes=-1000", 100))
        self.assertEqual((10, 99, 206), pick_range("bytes=10-", 100))
        for bad in ("bytes=100-", "bytes=5-2", "bytes=0-1,4-5", "items=0-1", "bytes=-0", "bytes=-", "bytes=a-b"):
            with self.assertRaises(BadRange):
                pick_range(bad, 100)
        with self.assertRaises(BadRange):
            pick_range("bytes=0-", 0)

    def test_slice_cache_budget_and_lru(self):
        with tempfile.TemporaryDirectory() as d:
            cache = SliceCache(Path(d) / "c", budget=3 * SLICE)
            for i in range(5):
                cache.save("m", i * SLICE, bytes([i]) * SLICE)
                time.sleep(0.01)
            self.assertLessEqual(cache.usage(), 3 * SLICE)
            self.assertIsNone(cache.load("m", 0, SLICE))
            self.assertEqual(bytes([4]) * SLICE, cache.load("m", 4 * SLICE, SLICE))
            (Path(d) / "c" / "foreign.bin").write_bytes(b"x" * SLICE)
            cache.save("m", 9 * SLICE, b"z" * SLICE)
            self.assertLessEqual(cache.usage(), 3 * SLICE)
            self.assertEqual(0o600, (Path(d) / "c" / next(p.name for p in (Path(d) / "c").glob("m.*.bin"))).stat().st_mode & 0o777)


class CdnTests(unittest.IsolatedAsyncioTestCase):
    async def test_cdn_slice_is_decrypted_and_hash_checked(self):
        from Crypto.Cipher import AES
        from telethon import types
        from sefang.tg.link import TgLink, TgProblem, cdn_counter
        plain = bytes(range(256)) * 1024
        key, iv, base = bytes(range(32)), bytes(range(16)), SLICE * 2
        sealed = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=cdn_counter(iv, base)).encrypt(plain)
        block = types.FileHash(base, len(plain), hashlib.sha256(plain).digest())

        class Edge:
            async def __call__(self, request):
                return types.upload.CdnFile(sealed)

            async def disconnect(self):
                pass
        link = TgLink({}, None)
        link._edge[8] = Edge()
        redirect = types.upload.FileCdnRedirect(8, b"token", key, iv, [block])
        self.assertEqual(plain[77:177], await link._read_edge(redirect, base + 77, 100))
        block.hash = b"wrong"
        with self.assertRaises(TgProblem):
            await link._read_edge(redirect, base + 77, 100)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = offline(Path(self.tmp.name), live=True)
        self.index, self.repo = seed(self.config)
        write_account(self.config, session="synthetic", api_id=1, api_hash="x")
        self.app = create_app(self.config, FakeLink)
        self.tg = self.app.state.telegram
        self.tg.state = "connected"
        self.tg.link.posts = {1: fake_message(1, name="IPX-001.mp4", document=901), 2: fake_message(2, name="IPX-002.mp4", document=902)}
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.tg.stop()
        self.tmp.cleanup()

    async def test_public_reads_hide_secrets_and_refuse_management_and_source(self):
        r = await self.client.get("/api/videos")
        self.assertEqual((200, 2), (r.status_code, r.json()["total"]))
        text = (await self.client.get("/api/videos/123/1")).text
        for word in ("access_hash", "api_hash", "session", "document_id", "cover_file", "/opt/", "/tmp"):
            self.assertNotIn(word, text)
        for path in ("/source", "/source.tar.gz", "/api/source", "/api/telegram/settings", "/docs", "/openapi.json",
                     "/secrets/telegram/account.json", "/.env", "/api/videos/999/1"):
            self.assertIn((await self.client.get(path, headers={"X-Token": "x", "X-Forwarded-For": "127.0.0.1"})).status_code, (404, 405))
            self.assertEqual(405, (await self.client.post(path, json={})).status_code)
        self.assertEqual(422, (await self.client.get("/api/videos?limit=10000")).status_code)
        self.assertEqual(422, (await self.client.get("/api/videos?sort=SQL")).status_code)

    async def test_range_head_suffix_ifrange_416_and_reference_refresh(self):
        path = "/api/videos/123/1/stream"
        for spec, want in [("bytes=0-31", BLOB[:32]), ("bytes=-31", BLOB[-31:]), ("bytes=600000-600031", BLOB[600000:600032]),
                           (f"bytes={SLICE - 5}-{SLICE + 5}", BLOB[SLICE - 5:SLICE + 6])]:
            r = await self.client.get(path, headers={"Range": spec})
            self.assertEqual((206, want, str(len(want))), (r.status_code, r.content, r.headers["content-length"]))
        head = await self.client.head(path, headers={"Range": "bytes=-31"})
        self.assertEqual((206, b""), (head.status_code, head.content))
        self.assertEqual(416, (await self.client.get(path, headers={"Range": f"bytes={len(BLOB)}-"})).status_code)
        r = await self.client.get(path, headers={"Range": "bytes=0-31", "If-Range": '"other"'})
        self.assertEqual((200, BLOB), (r.status_code, r.content))
        self.tg.cache.forget(SliceCache.media_key(123, 1, "901"))
        self.tg.link.expire_next = True
        self.assertEqual(206, (await self.client.get(path, headers={"Range": "bytes=0-31"})).status_code)
        reads = len(self.tg.link.reads)
        await self.client.get(path, headers={"Range": "bytes=0-31"})
        self.assertEqual(reads, len(self.tg.link.reads), "second read must come from the slice cache")

    async def test_offsets_beyond_two_gib(self):
        big = 3 * 1024 ** 3 + 12345
        self.tg.link.posts[2] = fake_message(2, name="IPX-002.mp4", document=902, size=big)

        async def patterned(message, offset, count):
            self.tg.link.reads.append((message.id, offset, count))
            block = offset.to_bytes(8, "big") * (SLICE // 8)
            return block[:count]
        self.tg.link.read = patterned
        start = 2 * 1024 ** 3 + 777
        r = await self.client.get("/api/videos/123/2/stream", headers={"Range": f"bytes={start}-{start + 65535}"})
        base = start - start % SLICE
        want = (base.to_bytes(8, "big") * (SLICE // 8))[start - base:start - base + 65536]
        self.assertEqual((206, f"bytes {start}-{start + 65535}/{big}", want),
                         (r.status_code, r.headers["content-range"], r.content))
        tail = await self.client.get("/api/videos/123/2/stream", headers={"Range": "bytes=-100"})
        self.assertEqual((206, 100), (tail.status_code, len(tail.content)))

    async def test_live_new_edit_delete_and_metadata_untouched(self):
        with self.index.session() as db:
            before = db.execute("SELECT metadata FROM tg_work WHERE identity='IPX-1'").fetchone()[0]
        post = fake_message(3, name="IPX-001.mp4", document=903)
        await self.tg.on_update(123, post, None)
        self.assertEqual("合成作品1", self.repo.dto(self.repo.raw(123, 3))["title"])
        post.document.attributes[-1].file_name = "IPX-002.mp4"
        await self.tg.on_update(123, post, None)
        self.assertEqual("合成作品2", self.repo.dto(self.repo.raw(123, 3))["title"])
        await self.tg.on_update(123, None, [3])
        self.assertFalse(self.repo.dto(self.repo.raw(123, 3))["available"])
        await self.tg.on_update(999, post, None)
        with self.index.session() as db:
            self.assertEqual(before, db.execute("SELECT metadata FROM tg_work WHERE identity='IPX-1'").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM tg_video WHERE channel_id=999").fetchone()[0])

    async def test_catch_up_and_history_backfill(self):
        self.tg.link.posts = {i: fake_message(i, name=f"SSIS-{i:03}.mp4", document=5000 + i) for i in range(1, 251)}
        await self.tg._sync_all()
        row = self.index.channel_row(123)
        self.assertEqual((1, 250, "ready"), (row["history_done"], row["high_water"], row["state"]))
        self.tg.link.posts[251] = fake_message(251, name="SSIS-251.mp4", document=5251)
        calls = self.tg.link.history_calls
        await self.tg._sync_all()
        self.assertEqual(251, self.index.channel_row(123)["high_water"])
        self.assertEqual(calls + 1, self.tg.link.history_calls)
        with self.index.session() as db:
            self.assertEqual(251, db.execute("SELECT count(*) FROM tg_video").fetchone()[0])


class CancelTests(unittest.TestCase):
    def test_client_abort_stops_reading_and_frees_slot(self):
        import uvicorn
        with tempfile.TemporaryDirectory() as d:
            config = offline(Path(d), live=True)
            seed(config, 1)[1].close()
            write_account(config, session="synthetic", api_id=1, api_hash="x")
            app = create_app(config, FakeLink)
            owner = app.state.telegram
            owner.state = "connected"
            owner.link.posts = {1: fake_message(1, name="IPX-001.mp4", document=901)}
            owner.link.read_delay = 0.05
            owner.cache.budget = 0
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
            original_start = owner.start

            async def no_keepalive():
                return None
            owner.start = no_keepalive
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            owner.state = "connected"
            with httpx.Client() as client:
                with client.stream("GET", f"http://127.0.0.1:{port}/api/videos/123/1/stream") as r:
                    self.assertEqual(200, r.status_code)
                    next(r.iter_bytes())
            time.sleep(0.6)
            settled = len(owner.link.reads)
            time.sleep(0.6)
            self.assertEqual(settled, len(owner.link.reads))
            self.assertLess(settled, len(BLOB) // SLICE + 1)
            self.assertEqual(2, owner.media_gate._value)
            server.should_exit = True
            thread.join(10)
            owner.start = original_start


class PortraitTests(unittest.TestCase):
    def test_install_limits_and_identity_rules(self):
        from sefang.avatars import SINGLE, Portraits, too_generic
        with tempfile.TemporaryDirectory() as d:
            config = offline(Path(d))
            _, repo = seed(config)
            worker = Portraits(repo)
            with self.assertRaises(ValueError):
                worker.install("a", b"x" * (SINGLE + 1))
            buf = io.BytesIO()
            Image.new("RGB", (125, 125), "blue").save(buf, format="JPEG")
            ident = entity_id("actors", "甲")
            name, mime = worker.install(ident, buf.getvalue())
            self.assertEqual(("image/jpeg", 0o600), (mime, (worker.root / name).stat().st_mode & 0o777))
            (worker.root / name).unlink()
            with repo.local() as db:
                actor = dict(db.execute("SELECT * FROM entity WHERE id=?", (ident,)).fetchone())
            fetched = []
            with patch.object(worker, "_works", return_value=[("IPX-001", [])]), \
                    patch.object(worker, "_official_cast", return_value=[{"name": "另一个人", "id": "2", "image": "https://example.com/a.jpg"}]), \
                    patch.object(worker, "_javdb_cast", return_value=[]), \
                    patch.object(worker, "_fetch", side_effect=lambda *a: fetched.append(a)):
                self.assertEqual("unavailable", worker.process(actor))
            self.assertEqual([], fetched)
            with patch.object(worker, "_works", return_value=[("IPX-001", []), ("IPX-002", [])]), \
                    patch.object(worker, "_official_cast", side_effect=[[{"name": "甲", "id": "1", "image": ""}], [{"name": "甲", "id": "9", "image": ""}]]):
                self.assertEqual("ambiguous", worker.process(actor))
            self.assertTrue(too_generic("みゆき") and too_generic("18歳スレンダー美女") and not too_generic("三上悠亜"))
            repo.close()


class GuardTests(unittest.TestCase):
    def test_outbound_guards_and_holds(self):
        from sefang.catalog.web import HoldBook, Refused, Unreachable, Web, literal_ok
        for bad in ("http://example.com/x", "https://127.0.0.1/x", "https://user:pw@example.com/x", "https://intranet/x",
                    "https://nas.local/x", "https://example.com:8443/x"):
            self.assertFalse(literal_ok(bad), bad)
        with tempfile.TemporaryDirectory() as d:
            holds = HoldBook(Path(d))
            web = Web(holds=holds, client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(403))))
            with patch("sefang.catalog.web.all_public", return_value=True):
                with self.assertRaises(Refused):
                    web.fetch("https://www.javbus.com/IPX-001")
                self.assertGreater(holds.until("javbus"), time.time() + 3000)
                with self.assertRaises(Refused):
                    web.fetch("https://www.javbus.com/IPX-002")
            self.assertEqual(1, len(web.log))
            from sefang.catalog.web import Missing
            pics = Web(holds=holds, client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(403))))
            with patch("sefang.catalog.web.all_public", return_value=True):
                with self.assertRaises(Missing):
                    pics.fetch("https://image.mgstage.com/x/none.jpg", image=True)
            self.assertEqual(0.0, holds.until("image.mgstage.com"))
            with patch("sefang.catalog.web.all_public", return_value=False):
                with self.assertRaises(Unreachable):
                    Web(holds=HoldBook(None)).fetch("https://example.com/")


class ChainTests(unittest.TestCase):
    def test_route_order_and_wrong_work_is_rejected(self):
        from sefang.catalog import chain
        from sefang.catalog.found import Found
        from sefang.catalog.web import Missing
        self.assertEqual(["official", "r18dev", "dmm", "community", "fallback"], [s for s, _ in chain.route("IPX-900")])
        self.assertEqual(("makers",), chain.route("IPX-900")[0][1])
        self.assertEqual(("prestige", "mgstage"), chain.route("ABW-179")[0][1])
        self.assertEqual(["fc2", "community", "fallback"], [s for s, _ in chain.route("FC2-PPV-1234567")])
        self.assertEqual([], chain.route("YUJ-066"))
        self.assertEqual([], chain.route("DTW-005", "#DEMIFAIRY #国产"))
        asked = []

        def reader(site):
            def read(code, web):
                asked.append(site)
                if site == "makers":
                    return Found("makers", "https://x.example/works/detail/ipx999", number="IPX-999", title="别的作品")
                if site == "r18dev":
                    return Found("r18dev", "https://r18.dev/x", content_id="ipx00900", title="正确", cast=[{"name": "甲"}],
                                 maker="M", released="2022-07-12", tags=["t"])
                raise Missing(site)
            return read
        with patch.dict(chain.READERS, {k: reader(k) for k in chain.READERS}):
            out = chain.lookup("IPX-900", (), want_cover=False, web=SimpleNamespace(close=lambda: None))
        self.assertEqual(["makers", "r18dev"], asked)
        self.assertEqual(("matched", "正确", "r18dev"), (out.state, out.fields["title"], out.fields["field_sources"]["title"]))

    def test_cover_corroboration_rules(self):
        from sefang.catalog import covers

        def jpeg(color, size):
            buf = io.BytesIO()
            img = Image.new("RGB", size, color)
            for x in range(0, size[0], 40):
                img.paste((255, 255, 255), (x, 0, x + 10, size[1]))
            img.save(buf, format="JPEG")
            return buf.getvalue()
        a = covers.Shot(covers.Pick("https://pics.dmm.co.jp/x/abc00001pl.jpg", ""), jpeg("red", (800, 538)), (800, 538), 0)
        with Image.open(io.BytesIO(a.data)) as im:
            a.hash = covers.dhash(im)
        b = covers.Shot(covers.Pick("https://www.javbus.com/pics/cover/1.jpg", ""), jpeg("red", (400, 269)), (400, 269), 0)
        with Image.open(io.BytesIO(b.data)) as im:
            b.hash = covers.dhash(im)
        self.assertTrue(covers._alike(a, b))
        self.assertTrue(covers.is_javdb("https://c0.jdbstatic.com/covers/x.jpg"))
        self.assertTrue(covers.names_other_work("IPX-900", "https://pics.dmm.co.jp/digital/video/ipx00901/ipx00901pl.jpg"))
        self.assertFalse(covers.names_other_work("IPX-900", "https://pics.dmm.co.jp/digital/video/ipx00900/ipx00900pl.jpg"))
        self.assertTrue(covers.names_other_work("FC2-PPV-1234567", "https://img.javstore.net/FC2PPV-7654321.jpg"))


if __name__ == "__main__":
    unittest.main()

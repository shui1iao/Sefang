"""Isolated comparison of playback latency with normal, slow TG work."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
from time import monotonic
import unittest

import httpx

from sefang.app import create_app
from sefang.config import Config
from sefang.tg.cache import SLICE, SliceCache
from sefang.tg.index import video_from_message
from sefang.tg.link import TgProblem
from support import BLOB, CHANNEL, FakeLink, auth_headers, fake_message

COMPARE_OLD = os.environ.get('SEFANG_COMPARE_OLD') == '1'


class ControlledLink(FakeLink):
    def __init__(self, account, on_update):
        super().__init__(account, on_update)
        self.art_in = asyncio.Queue()
        self.art_open = asyncio.Event()
        self.cold_in = asyncio.Event()
        self.cold_open = asyncio.Event()
        self.pause_read = False
        self.posts = {n: fake_message(n, name=f'IPX-{n+100}.mp4', document=900+n) for n in (1, 2, 3)}

    async def thumbnail(self, message):
        self.art_in.put_nowait(message.id)
        await self.art_open.wait()
        return b'thumbnail'

    async def read(self, message, offset, count):
        if self.pause_read and offset == 0:
            self.cold_in.set()
            await self.cold_open.wait()
        return await super().read(message, offset, count)


class MediaPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        config = Config(root / 'data', root / 'state', (123,))
        tg = config.secrets_root / 'telegram'
        tg.mkdir(parents=True)
        (tg / 'account.json').write_text(json.dumps({'channels':[CHANNEL]}))
        app = create_app(config, ControlledLink)
        self.addCleanup(app.state.repository.close)
        self.owner = app.state.telegram
        self.owner.state = 'connected'
        self.link = self.owner.link
        self.owner.index.ensure_channel(123, 'Fixture')
        self.owner.index.store(123, [video_from_message(123, p) for p in self.link.posts.values()])
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://fixture', headers=auth_headers(app))
        self.addAsyncCleanup(self.client.aclose)

    async def request_range(self, start):
        t = monotonic()
        r = await self.client.get('/api/videos/123/1/stream', headers={'Range':f'bytes={start}-{start+63}'})
        return r, monotonic() - t

    async def test_two_slow_thumbnails_cannot_block_playback(self):
        one = asyncio.create_task(self.owner.thumbnail(123,2))
        two = asyncio.create_task(self.owner.thumbnail(123,3))
        try:
            await asyncio.wait_for(self.link.art_in.get(), 1)
            if COMPARE_OLD:
                await asyncio.wait_for(self.link.art_in.get(),1)
            else:
                self.assertTrue(self.link.art_in.empty())
            response, elapsed = await asyncio.wait_for(self.request_range(0), 5)
            print(json.dumps({'case':'slow_artwork_then_range','status':response.status_code,'elapsed_ms':round(elapsed*1000,1)}))
            if COMPARE_OLD:
                self.assertEqual(429,response.status_code)
            else:
                self.assertEqual(206,response.status_code)
                self.assertEqual(BLOB[:64],response.content)
                self.assertTrue(self.link.art_in.empty())
                self.assertFalse(one.done() or two.done())
        finally:
            self.link.art_open.set()
            self.assertEqual([b'thumbnail']*2, await asyncio.gather(one,two))
        self.assertEqual(2,self.owner.media_gate._value)

    async def test_cached_range_finishes_before_unrelated_telegram_slice(self):
        media = SliceCache.media_key(123,1,901)
        self.owner.cache.save(media,SLICE,BLOB[SLICE:2*SLICE])
        self.link.pause_read = True
        cold = asyncio.create_task(self.request_range(0))
        try:
            await asyncio.wait_for(self.link.cold_in.wait(),1)
            release = asyncio.get_running_loop().call_later(.65,self.link.cold_open.set)
            try:
                response, elapsed = await asyncio.wait_for(self.request_range(SLICE),2)
                before_upstream = not self.link.cold_open.is_set()
                print(json.dumps({'case':'cached_range_during_slow_download','status':response.status_code,'elapsed_ms':round(elapsed*1000,1),'returned_before_cold_release':before_upstream}))
                self.assertEqual(not COMPARE_OLD,before_upstream)
                self.assertEqual(206,response.status_code)
                self.assertEqual(BLOB[SLICE:SLICE+64],response.content)
            finally:
                release.cancel()
        finally:
            self.link.cold_open.set()
            self.assertEqual(206,(await cold)[0].status_code)
        self.assertEqual([(1,0,SLICE)],self.link.reads)

    @unittest.skipIf(COMPARE_OLD,'candidate-specific slot ordering')
    async def test_playback_priority_and_cancellation_release(self):
        gate = self.owner.media_gate
        await gate.acquire(); await gate.acquire()
        order = []
        async def thumbnail():
            async with gate.artwork():
                order.append('art')
        async def playback(label):
            await gate.acquire()
            try:
                order.append(label)
            finally:
                gate.release()
        art = asyncio.create_task(thumbnail())
        first = asyncio.create_task(playback('canceled'))
        second = asyncio.create_task(playback('video'))
        try:
            await asyncio.sleep(0)
            gate.release()
            first.cancel()  # cancel after notification, before acquiring
            await asyncio.gather(first,return_exceptions=True)
            await asyncio.wait_for(asyncio.gather(art,second),1)
            self.assertEqual(['video','art'],order)
        finally:
            gate.release()
            for task in (art,first,second):
                task.cancel()
            await asyncio.gather(art,first,second,return_exceptions=True)
        self.assertEqual(2,gate._value)

    @unittest.skipIf(COMPARE_OLD,'candidate-specific cache revalidation')
    async def test_protected_row_does_not_take_cache_hit(self):
        owner = self.owner
        row = owner.index.video(123,1)
        media = SliceCache.media_key(123,1,901)
        owner.cache.save(media,0,BLOB[:SLICE])
        new = video_from_message(123,self.link.posts[1],protected=True)
        owner.index.store(123,[new])
        self.assertTrue(owner.index.video(123,1)['protected'])
        async with owner.read_gate:
            task = asyncio.create_task(owner.slice_at(row,self.link.posts[1],0))
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        self.assertEqual(BLOB[:SLICE],await asyncio.wait_for(task,1))
        self.assertEqual([(1,0,SLICE)],self.link.reads)
        self.assertIsNone(owner.cache.load(media,0,SLICE))

    @unittest.skipIf(COMPARE_OLD,'candidate-specific cache revalidation')
    async def test_cold_queue_rechecks_deleted_row_before_download(self):
        owner = self.owner
        row = owner.index.video(123,1)
        async with owner.read_gate:
            task = asyncio.create_task(owner.slice_at(row,self.link.posts[1],0))
            await asyncio.sleep(0)
            owner.index.mark_gone(123,1)
        with self.assertRaises(TgProblem) as error:
            await asyncio.wait_for(task,1)
        self.assertTrue(error.exception.gone)
        self.assertFalse(self.link.reads)

    async def test_two_waiters_for_same_missing_slice_only_download_once(self):
        self.link.pause_read = True
        one = asyncio.create_task(self.request_range(0))
        await asyncio.wait_for(self.link.cold_in.wait(),1)
        two = asyncio.create_task(self.request_range(0))
        await asyncio.sleep(0)
        self.link.cold_open.set()
        for response,_ in await asyncio.wait_for(asyncio.gather(one,two),2):
            self.assertEqual(206,response.status_code)
            self.assertEqual(BLOB[:64],response.content)
        self.assertEqual([(1,0,SLICE)],self.link.reads)

"""Real TCP pre-header disconnect regression; no TG or persistent business state."""
import asyncio
import json
import socket
import time
import unittest
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from sefang.access import PlaybackControl
from sefang.auth import Principal
from sefang.streaming import router


class Store:
    enabled = True

    def authenticate(self, token):
        if self.enabled:
            return Principal(1, 'neutral', 'user', None, 1, 'local-session', 'local-csrf')


class Owner:
    def __init__(self):
        self.media_gate = asyncio.Semaphore(2)
        self.stage = None
        self.wait = asyncio.Event()
        self.enter = asyncio.Queue()
        self.cancelled = 0
        self.pending = 0
        self.last_task = None

    def allowed(self, channel):
        return True

    async def delay(self, stage):
        if self.stage != stage:
            return
        self.pending += 1
        self.last_task = asyncio.current_task()
        self.enter.put_nowait(stage)
        try:
            await self.wait.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.pending -= 1

    async def locate(self, channel, message):
        await self.delay('locate')
        return {'size': 1048576, 'document_id': 1, 'mime': 'video/mp4'}, None

    async def slice_at(self, row, message, base):
        await self.delay('opening')
        return bytes(range(256)) * 2048


class DisconnectSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store()
        self.ctl = PlaybackControl(self.store)
        self.key = self.ctl.create(self.store.authenticate(''), {(1, 1)})
        self.owner = Owner()
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.playbacks = self.ctl
        self.app.state.telegram = self.owner
        self.app.state.config = SimpleNamespace(channels={1})
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        self.port = sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, lifespan='off', access_log=False, log_level='critical'))
        self.server_task = asyncio.create_task(self.server.serve(sockets=[sock]))
        while not self.server.started:
            await asyncio.sleep(.01)
        self.writers = []
        self.held_gate = 0

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
        await asyncio.gather(*(w.wait_closed() for w in self.writers), return_exceptions=True)
        self.owner.wait.set()
        while self.held_gate:
            self.owner.media_gate.release()
            self.held_gate -= 1
        self.server.should_exit = True
        await asyncio.wait_for(self.server_task, 5)
        self.assertFalse(self.ctl.active)
        self.assertEqual(2, self.owner.media_gate._value)
        self.assertEqual(0, self.owner.pending)
        self.assertFalse(self.server.servers[0].is_serving())

    async def until(self, condition, timeout=1):
        start = time.monotonic()
        while not condition():
            if time.monotonic() - start > timeout:
                self.fail('bounded wait exceeded: active=%r gate=%r pending=%r' % (self.ctl.active, self.owner.media_gate._value, self.owner.pending))
            await asyncio.sleep(.005)
        return time.monotonic() - start

    async def connect(self, ran='bytes=524288-524319', method='GET', headers=''):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        self.writers.append(writer)
        writer.write((f'{method} /api/videos/1/1/stream?playback={self.key} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nRange: {ran}\r\nConnection: close\r\n{headers}\r\n').encode())
        await writer.drain()
        return reader, writer

    async def response(self, reader):
        data = await asyncio.wait_for(reader.read(), 5)
        head, _, body = data.partition(b'\r\n\r\n')
        status = int(head.split(b' ', 2)[1])
        headers = dict(line.lower().split(b': ', 1) for line in head.split(b'\r\n')[1:])
        return status, headers, body

    async def complete(self):
        reader, _ = await self.connect()
        status, headers, body = await self.response(reader)
        self.assertEqual(206, status)
        self.assertEqual(b'32', headers[b'content-length'])
        self.assertEqual(b'bytes 524288-524319/1048576', headers[b'content-range'])
        self.assertEqual(bytes(range(32)), body)

    async def test_real_disconnect_gate_locate_opening(self):
        evidence = []
        for stage in ('gate', 'locate', 'opening'):
            self.owner.stage = stage
            self.owner.wait.clear()
            if stage == 'gate':
                for _ in range(2):
                    await self.owner.media_gate.acquire()
                    self.held_gate += 1
            reader, writer = await self.connect()
            if stage == 'gate':
                await self.until(lambda: bool(self.ctl.active))
            else:
                await asyncio.wait_for(self.owner.enter.get(), 1)
            server_request = self.ctl.active[self.key][0].task
            writer.close()  # Actual TCP close, never cancel the server task.
            await writer.wait_closed()
            elapsed = await self.until(lambda: not self.ctl.active and server_request.done())
            self.assertEqual(0, self.owner.pending)
            if stage == 'gate':
                self.assertEqual(0, self.owner.media_gate._value)
                for _ in range(2):
                    self.owner.media_gate.release()
                    self.held_gate -= 1
            else:
                self.assertEqual(2, self.owner.media_gate._value)
            self.owner.stage = None
            await self.complete()
            evidence.append({'stage': stage, 'disconnect_cleanup_seconds': elapsed, 'new_range': 206})
        print(json.dumps({'real_tcp_disconnect': evidence}))

    async def test_connected_siblings_cap_cancel_one_then_new_range(self):
        self.owner.stage = 'opening'
        a, wa = await self.connect()
        await asyncio.wait_for(self.owner.enter.get(), 1)
        b, wb = await self.connect()
        await asyncio.wait_for(self.owner.enter.get(), 1)
        await asyncio.sleep(.35)  # Slow, still connected must NOT be mistaken for gone.
        self.assertEqual(2, len(self.ctl.active[self.key]))
        self.assertEqual(0, self.owner.cancelled)
        c, _ = await self.connect()
        status, headers, _ = await self.response(c)
        self.assertEqual(429, status)
        self.assertEqual(b'1', headers[b'retry-after'])
        wa.close()
        await wa.wait_closed()
        await self.until(lambda: len(self.ctl.active.get(self.key, [])) == 1)
        self.assertEqual(1, self.owner.cancelled)
        self.owner.stage = None
        await self.complete()  # New range fits; b is still waiting, not cancelled.
        self.assertEqual(1, self.owner.pending)
        self.owner.wait.set()
        self.assertEqual((206, bytes(range(32))), (lambda r: (r[0], r[2]))(await self.response(b)))
        self.assertEqual(1, self.owner.cancelled)

    async def test_two_connected_siblings_complete_independently(self):
        self.owner.stage = 'locate'
        a, _ = await self.connect()
        await asyncio.wait_for(self.owner.enter.get(), 1)
        b, _ = await self.connect()
        await asyncio.wait_for(self.owner.enter.get(), 1)
        self.owner.wait.set()
        for status, headers, body in await asyncio.gather(self.response(a), self.response(b)):
            self.assertEqual(206, status)
            self.assertEqual(bytes(range(32)), body)
            self.assertEqual(b'32', headers[b'content-length'])
        self.assertEqual(0, self.owner.cancelled)

    async def test_disconnect_completion_races(self):
        for stage in ('gate', 'opening'):
            for _ in range(12):
                self.owner.stage = stage
                self.owner.wait.clear()
                if stage == 'gate':
                    for _ in range(2):
                        await self.owner.media_gate.acquire()
                        self.held_gate += 1
                reader, writer = await self.connect()
                if stage == 'gate':
                    await self.until(lambda: bool(self.ctl.active))
                else:
                    await asyncio.wait_for(self.owner.enter.get(), 1)
                # Same loop turn: completion and actual transport close can win in either order.
                writer.close()
                if stage == 'gate':
                    for _ in range(2):
                        self.owner.media_gate.release()
                        self.held_gate -= 1
                else:
                    self.owner.wait.set()
                await writer.wait_closed()
                await self.until(lambda: not self.ctl.active)
                self.assertEqual(2, self.owner.media_gate._value)
                self.assertEqual(0, self.owner.pending)
        self.owner.stage = None
        await self.complete()

    async def test_revoke_timeout_and_task_cancel(self):
        self.owner.stage = 'locate'
        reader, _ = await self.connect()
        await asyncio.wait_for(self.owner.enter.get(), 1)
        self.store.enabled = False
        status, _, _ = await self.response(reader)
        self.assertEqual(401, status)
        self.assertEqual(1, self.owner.cancelled)
        self.store.enabled = True
        reader, _ = await self.connect()
        await asyncio.wait_for(self.owner.enter.get(), 1)
        transfer = self.ctl.active[self.key][0]
        transfer.task.cancel()  # Separate coverage; not used as a fake TCP disconnect.
        await self.until(lambda: not self.ctl.active)
        self.assertEqual(2, self.owner.cancelled)
        self.owner.stage = None
        for _ in range(2):
            await self.owner.media_gate.acquire()
            self.held_gate += 1
        reader, _ = await self.connect()
        status, headers, _ = await self.response(reader)
        self.assertEqual(429, status)
        self.assertEqual(b'3', headers[b'retry-after'])
        self.assertFalse(self.ctl.active)
        for _ in range(2):
            self.owner.media_gate.release()
            self.held_gate -= 1
        await self.complete()

    async def test_owner_wait_timeout_releases_and_awaits(self):
        original_wait = self.ctl.wait

        async def short_wait(awaitable, token, transfer=None, timeout=60):
            return await original_wait(awaitable, token, transfer, timeout=.03)

        self.ctl.wait = short_wait  # Test-only bounded stand-in for the real 60s wait.
        for stage in ('locate', 'opening'):
            self.owner.stage = stage
            reader, _ = await self.connect()
            status, _, _ = await self.response(reader)
            self.assertEqual(503, status)
            self.assertFalse(self.ctl.active)
            self.assertEqual(2, self.owner.media_gate._value)
            self.assertEqual(0, self.owner.pending)
        self.assertEqual(2, self.owner.cancelled)
        self.owner.stage = None
        await self.complete()

    async def test_large_chunked_body_discard_then_disconnect_and_new_range(self):
        for method in ('GET', 'HEAD'):
            self.owner.stage = 'locate'
            self.owner.wait.clear()
            reader, writer = await self.connect(method=method, headers='Transfer-Encoding: chunked\r\n')
            await asyncio.wait_for(self.owner.enter.get(), 1)
            # Real HTTP chunked upload: the endpoint must not collect this body.
            chunk = b'x' * 65536
            for _ in range(128):
                writer.write(b'10000\r\n' + chunk + b'\r\n')
                await writer.drain()
            writer.write(b'0\r\n\r\n')
            await writer.drain()
            await asyncio.sleep(.02)
            self.assertEqual(1, self.owner.pending)
            server_request = self.server.server_state.tasks.copy()
            writer.close()
            await writer.wait_closed()
            await self.until(lambda: not self.ctl.active and self.owner.pending == 0
                             and all(task.done() for task in server_request))
            self.assertEqual(2, self.owner.media_gate._value)
            self.owner.stage = None
            await self.complete()

    async def test_head_416_ifrange_headers_unchanged(self):
        reader, _ = await self.connect(method='HEAD')
        status, headers, body = await self.response(reader)
        self.assertEqual((206, b''), (status, body))
        self.assertEqual(b'32', headers[b'content-length'])
        reader, _ = await self.connect(ran='bytes=9999999-')
        status, headers, body = await self.response(reader)
        self.assertEqual(416, status)
        self.assertEqual(b'bytes */1048576', headers[b'content-range'])
        reader, _ = await self.connect(headers='If-Range: "not-current"\r\n')
        status, headers, body = await self.response(reader)
        self.assertEqual(200, status)
        self.assertEqual(b'1048576', headers[b'content-length'])
        self.assertNotIn(b'content-range', headers)
        self.assertEqual(1048576, len(body))
        self.assertEqual(b'"tg-1-1-1"', headers[b'etag'])


class ReceiveReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_unused_body_discarded_and_listener_stopped(self):
        from sefang.streaming import _before_response
        queue = asyncio.Queue()
        messages = [{'type': 'http.request', 'body': b'a', 'more_body': True},
                    {'type': 'http.request', 'body': b'b', 'more_body': False}]
        for message in messages:
            queue.put_nowait(message)
        readers = 0

        async def receive():
            nonlocal readers
            readers += 1
            try:
                self.assertEqual(1, readers)
                return await queue.get()
            finally:
                readers -= 1

        req = Request({'type': 'http'}, receive)
        async with _before_response(req) as connected:
            await connected(asyncio.sleep(.02))
        self.assertEqual(0, readers)
        self.assertTrue(queue.empty(), 'unused request body drained, not replayed')
        queue.put_nowait({'type': 'http.disconnect'})
        self.assertEqual('http.disconnect', (await req.receive())['type'])
        self.assertEqual(0, readers)

    async def test_large_and_many_body_chunks_have_constant_retained_memory(self):
        from sefang.streaming import _before_response
        import tracemalloc
        for method in ('GET', 'HEAD'):
            for single_large in (True, False):
                with self.subTest(method=method, single_large=single_large):
                    complete = asyncio.Event()
                    blocked = asyncio.Event()
                    count = 0
                    total = 0
                    target = 1 if single_large else 12000

                    async def receive():
                        nonlocal count, total
                        if count < target:
                            count += 1
                            # Distinct payloads created on demand, never held by
                            # the fixture; many-small case includes empty chunks.
                            size = 32 * 1024 * 1024 if single_large else (65536 if count % 10 == 0 else 0)
                            total += size
                            return {'type': 'http.request', 'body': bytes(bytearray(size)), 'more_body': count < target}
                        complete.set()
                        await blocked.wait()
                        return {'type': 'http.disconnect'}

                    req = Request({'type': 'http', 'method': method}, receive)
                    tracemalloc.start()
                    try:
                        async with _before_response(req) as connected:
                            await connected(complete.wait())
                            current, peak = tracemalloc.get_traced_memory()
                            self.assertLess(current, 1024 * 1024,
                                            'body retention must not scale with total bytes/chunks')
                        self.assertEqual(target, count)
                        self.assertGreaterEqual(total, 32 * 1024 * 1024)
                        print(json.dumps({'discard_memory': {'method': method, 'chunks': count,
                              'input_bytes': total, 'retained_bytes': current, 'peak_bytes': peak}}))
                    finally:
                        tracemalloc.stop()

    async def test_immediate_disconnect_work_completion_race(self):
        from sefang.streaming import _before_response
        from starlette.requests import ClientDisconnect
        queue = asyncio.Queue()
        queue.put_nowait({'type': 'http.disconnect'})
        req = Request({'type': 'http'}, queue.get)
        with self.assertRaises(ClientDisconnect):
            async with _before_response(req) as connected:
                await connected(asyncio.sleep(0))
        self.assertEqual('http.disconnect', (await req.receive())['type'])


if __name__ == '__main__':
    unittest.main()

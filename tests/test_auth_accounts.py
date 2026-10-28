"""Isolated security/byte-timing regressions; never starts a Telegram owner."""
import asyncio
import json
from pathlib import Path
import secrets
import os
import subprocess
import sys
import socket
import tempfile
import time
import unittest

import httpx
import uvicorn

from sefang.app import create_app
from sefang.auth import COOKIE, DEFAULT_RATE, AuthStore, password_ok
from sefang.config import Config
from sefang.tg.cache import SLICE


class StubOwner:
    def __init__(self):
        self.media_gate = asyncio.Semaphore(2)
        self.reads = []
        self.locates = 0
        self.block = False
        self.cache = {}

    def allowed(self, cid):
        assert cid == 123

    async def locate(self, cid, mid):
        self.locates += 1
        if self.block:
            await asyncio.sleep(60)
        return {"size": 16*1048576, "document_id": "stub", "mime": "video/mp4"}, None

    async def slice_at(self, row, message, offset):
        if self.block:
            await asyncio.sleep(60)
        if offset not in self.cache:
            self.reads.append(offset)
            self.cache[offset] = b"x"*SLICE
        return self.cache[offset]


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sefang-auth-test-")
        self.root = Path(self.tmp.name)
        from sefang.tg.index import ChannelIndex
        ChannelIndex(self.root / "database/telegram/index.db")
        self.app = create_app(Config(self.root, self.root/'side', (123,), True))
        self.store = self.app.state.auth
        self.owner = StubOwner()
        self.app.state.telegram = self.owner
        self.password = secrets.token_urlsafe(18)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='https://test')
        self.headers = {"Origin": "https://test"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.app.state.repository.close()
        self.tmp.cleanup()

    async def login_admin(self):
        self.store.bootstrap("fixture_admin", self.password, 4)
        response = await self.client.post('/api/auth/login', headers=self.headers, json={"username": "fixture_admin", "password": self.password})
        self.assertEqual(200, response.status_code)
        self.headers['X-CSRF-Token'] = response.json()['csrf']
        return response

    async def new_user(self, maximum=2, rate=DEFAULT_RATE):
        await self.login_admin()
        response = await self.client.post('/api/admin/accounts', headers=self.headers, json={"username": "fixture_user", "password": self.password, "max_playbacks": maximum, "rate_bps": rate})
        self.assertEqual(201, response.status_code)
        return self.store.login('fixture_user', self.password, 'isolated-user')

    async def test_fail_closed_all_data_before_any_owner_read(self):
        for path in ('/api/videos', '/api/entities/actors', '/api/videos/123/1', '/api/videos/123/1/cover', '/api/videos/123/1/thumbnail', '/api/actors/a/image', '/api/videos/123/1/stream', '/api/auth/me', '/api/admin/accounts', '/assets/../state/auth/accounts.sqlite3', '/state/auth/accounts.sqlite3'):
            for method in ('GET', 'HEAD'):
                r = await self.client.request(method, path)
                self.assertIn(r.status_code, (401, 303))
                self.assertIn('no-store', r.headers['cache-control'])
        self.assertEqual(0, self.owner.locates)
        self.assertEqual([], self.owner.reads)
        self.assertEqual(200, (await self.client.get('/healthz')).status_code)
        self.assertEqual(303, (await self.client.get('/watch/123/1')).status_code)
        self.assertEqual(405, (await self.client.post('/api/videos', json={})).status_code)
        self.assertEqual(0o600, self.store.path.stat().st_mode & 0o777)
        self.assertEqual(0o700, self.store.path.parent.stat().st_mode & 0o777)

    async def test_cli_bootstrap_stdin_conflict_and_no_password_arguments(self):
        env = {**os.environ, "SEFANG_DATA_ROOT": str(self.root), "SEFANG_STATE_ROOT": str(self.root/'side'), "SEFANG_CHANNEL_IDS": "123"}
        command = [sys.executable, '-m', 'sefang.cli', 'init-admin', '--username', 'fixture_cli', '--max-playbacks', '3', '--password-stdin']
        result = await asyncio.to_thread(subprocess.run, command, input=self.password+'\n', text=True, capture_output=True, env=env)
        self.assertEqual(0, result.returncode)
        self.assertNotIn(self.password, result.stdout+result.stderr)
        result = await asyncio.to_thread(subprocess.run, command, input=self.password+'\n', text=True, capture_output=True, env=env)
        self.assertNotEqual(0,result.returncode)
        self.assertNotIn(self.password, result.stdout+result.stderr)
        result = await asyncio.to_thread(subprocess.run, command+['--password',self.password], input='', text=True, capture_output=True, env=env)
        self.assertNotEqual(0,result.returncode)
        self.assertNotIn(self.password, result.stdout+result.stderr)
        self.assertEqual(1,len(self.store.accounts()))

    async def test_login_origin_required_and_no_sensitive_validation_echo(self):
        for headers in ({}, {'Origin':'https://evil.test'}, {'Origin':'http://test'}, {'Origin':'https://test.evil'}):
            r=await self.client.post('/api/auth/login', headers=headers,json={'username':'unknown','password':self.password})
            self.assertEqual(403,r.status_code)
        r=await self.client.post('/api/auth/login', headers=self.headers,json={'username':'unknown','password':self.password,'token':'sensitive'})
        self.assertEqual(422,r.status_code)
        self.assertNotIn(self.password,r.text);self.assertNotIn('sensitive',r.text)

    async def test_admin_closed_loop_csrf_input_and_revocation(self):
        r = await self.login_admin()
        cookie = r.headers['set-cookie']
        for value in ('HttpOnly', 'Secure', 'SameSite=strict', 'Path=/', '__Host-'):
            self.assertIn(value, cookie)
        with self.assertRaises(ValueError):
            self.store.bootstrap('fixture_admin', secrets.token_urlsafe(18), 1)
        for headers in ({}, {'Origin': 'https://evil.test'}, {'Origin': 'https://test', 'X-CSRF-Token': 'bad'}):
            self.assertEqual(403, (await self.client.post('/api/admin/accounts', headers=headers, json={})).status_code)
        for extra in ({'role': 'admin'}, {'enabled': True}):
            body = {'username': 'fixture_user', 'password': self.password, 'max_playbacks': 1, **extra}
            r = await self.client.post('/api/admin/accounts', headers=self.headers, json=body)
            self.assertEqual(422, r.status_code)
            self.assertNotIn(self.password, r.text)
        self.assertEqual(422, (await self.client.post('/api/admin/accounts', headers=self.headers, json={'username': 'fixture_user', 'password': self.password})).status_code)
        self.assertEqual(201, (await self.client.post('/api/admin/accounts', headers=self.headers, json={'username': 'fixture_user', 'password': self.password, 'max_playbacks': 1})).status_code)
        rows = (await self.client.get('/api/admin/accounts')).json()['items']
        self.assertEqual((None, DEFAULT_RATE), (rows[0]['rate_bps'], rows[1]['rate_bps']))
        self.assertNotIn('password', json.dumps(rows))
        self.assertEqual(409, (await self.client.patch('/api/admin/accounts/1', headers=self.headers, json={'enabled': False})).status_code)
        self.assertEqual(422, (await self.client.patch('/api/admin/accounts/2', headers=self.headers, json={'role': 'admin'})).status_code)
        old = self.store.login('fixture_user', self.password, 'user')
        other = self.store.login('fixture_user', self.password, 'user')
        self.assertEqual(200, (await self.client.patch('/api/admin/accounts/2', headers=self.headers, json={'rate_bps': 1048576, 'max_playbacks': 3})).status_code)
        self.assertEqual(1048576, self.store.authenticate(old).rate)
        self.assertEqual(200, (await self.client.patch('/api/admin/accounts/2', headers=self.headers, json={'enabled': False})).status_code)
        self.assertIsNone(self.store.authenticate(old)); self.assertIsNone(self.store.authenticate(other))
        await self.client.patch('/api/admin/accounts/2', headers=self.headers, json={'enabled': True})
        old = self.store.login('fixture_user', self.password, 'user')
        new_password = secrets.token_urlsafe(18)
        await self.client.post('/api/admin/accounts/2/password', headers=self.headers, json={'password': new_password})
        self.assertIsNone(self.store.authenticate(old))
        fresh = self.store.login('fixture_user', new_password, 'user')
        self.assertIsNotNone(self.store.authenticate(fresh))
        await self.client.post('/api/auth/logout', headers=self.headers, json={})
        self.assertEqual(401, (await self.client.get('/api/auth/me')).status_code)

    async def test_server_playback_group_binding_and_session_isolation(self):
        token = await self.new_user()
        from support import fake_message
        from sefang.tg.index import ChannelIndex, video_from_message
        index = ChannelIndex(self.root/'database/telegram/index.db')
        index.ensure_channel(123, 'isolated')
        for mid in (1,2,3):
            number=min(mid,2)
            index.store(123,[video_from_message(123,fake_message(mid,name=f'IPX-001({number}).mp4',document=900+mid,seconds=600/number))])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://test',headers={'Cookie':f'{COOKIE}={token}'}) as user:
            headers={'Origin':'https://test','X-CSRF-Token':self.store.authenticate(token).csrf}
            response=await user.post('/api/playbacks',headers=headers,json={'channel_id':123,'message_id':1})
            self.assertEqual(200,response.status_code,response.text)
            key=response.json()['id']
            for mid in (1,2,3):
                r=await user.get(f'/api/videos/123/{mid}/stream?playback='+key,headers={'Range':'bytes=0-31'})
                self.assertEqual((206,32),(r.status_code,len(r.content)))
            reads=self.owner.locates
            self.assertEqual(403,(await user.get('/api/videos/123/4/stream?playback='+key)).status_code)
            self.assertEqual(reads,self.owner.locates)
            other=self.store.login('fixture_user',self.password,'other')
            self.assertEqual(403,(await user.get('/api/videos/123/1/stream?playback='+key,headers={'Cookie':f'{COOKIE}={other}'})).status_code)
            self.assertEqual(404,(await user.post('/api/playbacks',headers=headers,json={'channel_id':999,'message_id':1})).status_code)
            self.assertEqual(200,(await user.post(f'/api/playbacks/{key}/close',headers=headers,json={})).status_code)
            self.assertEqual(403,(await user.get('/api/videos/123/1/stream?playback='+key)).status_code)

    async def test_user_role_cache_expiry_and_throttle(self):
        token = await self.new_user()
        user = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='https://test', headers={'Cookie': f'{COOKIE}={token}'})
        me = (await user.get('/api/auth/me')).json()
        headers = {'Origin': 'https://test', 'X-CSRF-Token': me['csrf']}
        for method, path, data in [('GET', '/api/admin/accounts', None), ('POST', '/api/admin/accounts', {'username': 'other', 'password': self.password, 'max_playbacks': 1}), ('PATCH', '/api/admin/accounts/1', {'enabled': False}), ('POST', '/api/admin/accounts/1/password', {'password': self.password})]:
            r = await user.request(method, path, headers=headers, json=data)
            self.assertEqual(403, r.status_code)
        for path in ('/api/videos', '/api/videos/123/1/cover', '/api/actors/a/image'):
            r = await user.get(path, headers={'If-None-Match': '*', 'If-Modified-Since': 'Wed, 01 Jan 2030 00:00:00 GMT'})
            self.assertIn('no-store', r.headers['cache-control'])
            self.assertNotEqual(304, r.status_code)
        with self.store.db() as db:
            db.execute('UPDATE sessions SET expires=0 WHERE digest=?', (self.store.authenticate(token).session,))
        self.assertEqual(401, (await user.get('/api/auth/me')).status_code)
        await user.aclose()
        for name in ('no_such_user', 'fixture_user'):
            statuses = []
            for _ in range(11):
                r = await self.client.post('/api/auth/login', headers=self.headers, json={'username': name, 'password': 'wrong-password'})
                statuses.append(r.status_code)
            # Existing successful login consumed one attempt for fixture_user.
            self.assertEqual(429, statuses[-1])
            self.assertTrue(all(s in (401, 429) for s in statuses))
        self.assertEqual(0, self.owner.locates)


class StreamTests(AuthTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.token = await self.new_user(maximum=2)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0)); sock.listen(128); sock.setblocking(False)
        port = sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, lifespan='off', access_log=False, log_level='critical'))
        self.server_task = asyncio.create_task(self.server.serve(sockets=[sock]))
        while not self.server.started:
            await asyncio.sleep(.01)
        self.net = httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', headers={'Cookie': f'{COOKIE}={self.token}'}, timeout=15)

    async def asyncTearDown(self):
        await self.net.aclose()
        self.server.should_exit = True
        await self.server_task
        await super().asyncTearDown()

    # Do not inherit the API tests: this fixture already has its administrator.
    test_server_playback_group_binding_and_session_isolation = None
    test_cli_bootstrap_stdin_conflict_and_no_password_arguments = None
    test_login_origin_required_and_no_sensitive_validation_echo = None
    test_fail_closed_all_data_before_any_owner_read = None
    test_admin_closed_loop_csrf_input_and_revocation = None
    test_user_role_cache_expiry_and_throttle = None

    async def test_real_socket_2mib_aggregate_cache_and_seek_head(self):
        path = '/api/videos/123/1/stream'
        second = self.store.login('fixture_user', self.password, 'second-session')
        start = time.monotonic()
        finish_times=[]
        async def read_session(token):
            result=await self.net.get(path, headers={'Range':'bytes=0-4194303','Cookie':f'{COOKIE}={token}'})
            finish_times.append(time.monotonic()-start)
            return result
        responses = await asyncio.gather(read_session(self.token),read_session(second))
        elapsed = time.monotonic()-start
        self.assertLess(abs(finish_times[0]-finish_times[1]), .3, 'neither connection should starve')
        self.assertEqual([206,206], [r.status_code for r in responses])
        self.assertEqual(8388608, sum(len(r.content) for r in responses))
        # One account, two live responses: 8MiB/(2MiB/s) less <=64KiB initial burst.
        self.assertGreaterEqual(elapsed, 3.90)
        self.assertLess(elapsed, 5.5)
        reads = len(self.owner.reads)
        start = time.monotonic()
        r = await self.net.get(path, headers={'Range': 'bytes=0-4194303'})
        cache_elapsed = time.monotonic()-start
        self.assertEqual(4194304, len(r.content)); self.assertGreaterEqual(cache_elapsed, 1.90)
        self.assertEqual(reads, len(self.owner.reads), 'cache hits must be throttled too')
        self.assertEqual(206, (await self.net.head(path, headers={'Range':'bytes=-31'})).status_code)
        self.assertEqual(416, (await self.net.get(path, headers={'Range':'bytes=99999999-'})).status_code)
        self.assertEqual(206, (await self.net.get(path, headers={'Range':f'bytes={SLICE-5}-{SLICE+5}'})).status_code)
        self.assertEqual(0, len(self.app.state.playbacks.active))
        self.assertEqual(2, self.owner.media_gate._value)
        print(json.dumps({'evidence':'rate', 'bytes':8388608, 'aggregate_seconds':round(elapsed,4), 'bps':round(8388608/elapsed), 'cached_bytes':4194304, 'cached_seconds':round(cache_elapsed,4),'session_finish_seconds':[round(t,4) for t in finish_times]}))

    async def test_concurrency_cancel_seek_replacement_and_revoke(self):
        self.store.update(2, {'rate_bps': 65536, 'max_playbacks': 1})
        control = self.app.state.playbacks
        person = self.store.authenticate(self.token)
        key = control.create(person,{(123,1)})
        path = '/api/videos/123/1/stream'
        self.assertEqual(403, (await self.net.get('/api/videos/123/2/stream?playback='+key)).status_code)
        async with self.net.stream('GET', path+'?playback='+key, headers={'Range':'bytes=0-1048575'}) as response:
            self.assertEqual(206, response.status_code)
            self.assertEqual(429, (await self.net.get(path, headers={'Range':'bytes=0-31'})).status_code)
            self.assertEqual(206, (await self.net.head(path, headers={'Range':'bytes=0-31'})).status_code)
            # Same handle shares one window; a sibling Range must not cancel this body.
            r = await self.net.get(path+'?playback='+key, headers={'Range':'bytes=700000-700031'})
            self.assertEqual((206,32), (r.status_code,len(r.content)))
        await asyncio.sleep(.1)
        self.assertFalse(control.active); self.assertEqual(2,self.owner.media_gate._value)
        async with self.net.stream('GET', path, headers={'Range':'bytes=0-1048575'}) as response:
            self.assertEqual(206, response.status_code)
            before = time.monotonic()
            self.store.update(2, {'enabled':False})
            while control.active and time.monotonic()-before < 1:
                await asyncio.sleep(.01)
            self.assertFalse(control.active)
            self.assertLess(time.monotonic()-before,.6)
            print(json.dumps({'evidence':'disable_live', 'stop_seconds':round(time.monotonic()-before,4)}))
        self.assertEqual(401, (await self.net.get(path)).status_code)
        self.assertEqual(2,self.owner.media_gate._value)

    async def test_cancel_locate_password_logout_and_rate_edit_active(self):
        path='/api/videos/123/1/stream'
        control=self.app.state.playbacks
        self.owner.block=True
        task=asyncio.create_task(self.net.get(path))
        while not self.owner.locates:
            await asyncio.sleep(.01)
        self.store.update(2, {'password': self.store_hash()})
        r=await task
        self.assertEqual(401,r.status_code)
        self.assertFalse(control.active); self.assertEqual(2,self.owner.media_gate._value)
        self.owner.block=False
        token=self.store.login('fixture_user',self.password,'new')
        self.net.headers['Cookie']=f'{COOKIE}={token}'
        self.store.update(2, {'rate_bps':65536})
        async with self.net.stream('GET',path,headers={'Range':'bytes=0-2097151'}) as response:
            start=time.monotonic()
            self.store.update(2, {'rate_bps':4194304})
            body=await response.aread()
            elapsed=time.monotonic()-start
            self.assertEqual(2097152,len(body));self.assertLess(elapsed,1.5)
        async with self.net.stream('GET',path,headers={'Range':'bytes=0-16777215'}) as response:
            self.store.logout(self.store.authenticate(token).session)
            start=time.monotonic()
            while control.active and time.monotonic()-start<1:
                await asyncio.sleep(.01)
            self.assertFalse(control.active)
        self.assertEqual(2,self.owner.media_gate._value)

    async def test_password_reset_live_socket_and_exception_cleanup(self):
        path='/api/videos/123/1/stream'
        control=self.app.state.playbacks
        self.store.update(2, {'rate_bps':1})
        async with self.net.stream('GET',path,headers={'Range':'bytes=0-1048575'}) as response:
            self.assertEqual(206,response.status_code)
            self.store.update(2, {'password':self.store_hash()})
            start=time.monotonic()
            while control.active and time.monotonic()-start<1:
                await asyncio.sleep(.01)
            self.assertFalse(control.active)
            self.assertLess(time.monotonic()-start,.6)
        token=self.store.login('fixture_user',self.password,'new')
        self.net.headers['Cookie']=f'{COOKIE}={token}'
        self.assertEqual(403,(await self.net.get(path+'?playback='+'x'*32)).status_code)
        async def broken(*args):
            raise RuntimeError('private detail must not escape')
        self.owner.locate=broken
        response=await self.net.get(path)
        self.assertEqual(503,response.status_code)
        self.assertNotIn('private detail',response.text)
        self.assertFalse(control.active);self.assertEqual(2,self.owner.media_gate._value)

    async def test_lowered_concurrency_and_cancelled_waiter_release(self):
        self.store.update(2, {'rate_bps':65536})
        path='/api/videos/123/1/stream'
        control=self.app.state.playbacks
        async with self.net.stream('GET',path) as a:
            async with self.net.stream('GET',path) as b:
                self.assertEqual([200,200],[a.status_code,b.status_code])
                self.assertEqual(429,(await self.net.get(path)).status_code)
                self.store.update(2, {'max_playbacks':1})
                start=time.monotonic()
                while len(control.active)>1 and time.monotonic()-start<1:
                    await asyncio.sleep(.01)
                self.assertEqual(1,len(control.active))
        start=time.monotonic()
        while control.active and time.monotonic()-start<1:
            await asyncio.sleep(.01)
        self.assertFalse(control.active);self.assertEqual(2,self.owner.media_gate._value)
        self.owner.block=True
        task=asyncio.create_task(self.net.get(path))
        await asyncio.sleep(.1);task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        self.store.update(2, {'enabled':False})
        start=time.monotonic()
        while control.active and time.monotonic()-start<1:
            await asyncio.sleep(.01)
        self.assertFalse(control.active);self.assertEqual(2,self.owner.media_gate._value)

    def store_hash(self):
        from sefang.auth import password_hash
        return password_hash(self.password)


if __name__=='__main__':
    unittest.main()

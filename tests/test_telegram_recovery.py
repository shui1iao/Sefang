"""Exercise the actual owner loop and HTTP probe without Telegram or real-time backoff."""
import asyncio
import json
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from telethon import errors, functions
from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from sefang.app import create_app
from sefang.config import Config
from sefang.tg.link import TgLink, TgProblem
from sefang.tg.owner import ChannelOwner, READY_MAX_AGE, SYNC_INTERVAL
from support import CHANNEL, FakeLink, fake_message


class ManualClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = asyncio.Queue()

    async def sleep(self, delay):
        wake = asyncio.get_running_loop().create_future()
        self.sleeps.put_nowait((delay, wake))
        await wake

    async def next_sleep(self):
        return await asyncio.wait_for(self.sleeps.get(), 2)

    def advance(self, sleep, elapsed=None):
        delay, wake = sleep
        self.now += delay if elapsed is None else elapsed
        wake.set_result(None)


class RecoveryLink(FakeLink):
    def __init__(self, account, on_update):
        super().__init__(account, on_update)
        self.connect_results = deque()
        self.connect_calls = 0
        self.hang_history = False
        self.history_entered = asyncio.Event()

    async def connect(self):
        self.connect_calls += 1
        self.closed = False
        result = self.connect_results.popleft() if self.connect_results else True
        if isinstance(result, Exception):
            raise result
        return result

    async def history(self, channel, **kwargs):
        if self.hang_history:
            self.history_entered.set()
            await asyncio.Future()
        return await super().history(channel, **kwargs)


class TelegramRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        data = Path(root.name)
        self.config = Config(data, data / 'side', (CHANNEL['id'],))
        path = self.config.secrets_root / 'telegram'
        path.mkdir(parents=True)
        self.account_file = path / 'account.json'
        self.account = {'channels': [CHANNEL], 'api_id': 1, 'api_hash': 'fake-hash', 'session': 'fake-session'}
        self.account_file.write_text(json.dumps(self.account))
        self.clock = ManualClock()
        p = patch('sefang.tg.owner.monotonic', lambda: self.clock.now)
        p.start()
        self.addCleanup(p.stop)

    def make_owner(self, factory=RecoveryLink):
        owner = ChannelOwner(self.config, link_factory=factory)
        owner._sleep = self.clock.sleep
        self.addAsyncCleanup(owner.stop)
        return owner

    async def verify_probe(self, client, status):
        response = await client.get('/healthz?ready=1')
        self.assertEqual((status, {'ok': status == 200}), (response.status_code, response.json()))
        live = await client.get('/healthz')
        self.assertEqual((200, {'ok': True}), (live.status_code, live.json()))

    async def test_probe_recovers_after_disconnect_timeout_and_repeated_index_failures(self):
        app = create_app(self.config, RecoveryLink)
        owner = app.state.telegram
        owner._sleep = self.clock.sleep
        self.addAsyncCleanup(owner.stop)
        self.addCleanup(app.state.repository.close)
        link = owner.link
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('sefang.tg.owner', 'WARNING') as records:
                await self.verify_probe(client, 503)
                await owner.start()
                sleep = await self.clock.next_sleep()
                self.assertEqual(SYNC_INTERVAL, sleep[0])
                await self.verify_probe(client, 200)
                self.assertEqual(1, owner.index.channel_row(CHANNEL['id'])['high_water'])

                link.connect_results.extend((ConnectionError('private-disconnect'), TimeoutError('private-timeout')))
                link.fail_with = OSError('private-index-error')
                for attempt, delay in enumerate((60, 120, 240, 300, 300, 300, 300), start=1):
                    self.clock.advance(sleep)
                    sleep = await self.clock.next_sleep()
                    self.assertEqual(delay, sleep[0])
                    self.assertEqual(attempt, owner.failures)
                    await self.verify_probe(client, 503)
                self.assertEqual((8, 6), (link.connect_calls, link.history_calls))
                self.assertEqual('error', owner.index.channel_row(CHANNEL['id'])['state'])

                link.fail_with = None
                link.posts[2] = fake_message(2)
                self.clock.advance(sleep)
                sleep = await self.clock.next_sleep()
                await self.verify_probe(client, 200)
                row = owner.index.channel_row(CHANNEL['id'])
                self.assertEqual((2, 'ready'), (row['high_water'], row['state']))
                self.assertEqual((0, 0.0), (owner.failures, owner.not_before))
                self.assertEqual(SYNC_INTERVAL, sleep[0])
                self.assertEqual(
                    ['telegram_business_health=not_ready', 'telegram_business_health=ready',
                     'telegram_business_health=not_ready', 'telegram_business_health=ready'],
                    [r.getMessage() for r in records.records])

                link.fail_with = TimeoutError()
                self.clock.advance(sleep)
                self.assertEqual(60, (await self.clock.next_sleep())[0])

    async def test_flood_wait_is_not_clipped_or_bypassed_on_early_wake(self):
        for stage in ('connect', 'history'):
            with self.subTest(stage=stage):
                owner = self.make_owner()
                wait = errors.FloodWaitError(request=None, capture=900)
                if stage == 'connect':
                    owner.link.connect_results.append(wait)
                else:
                    owner.link.fail_with = wait
                await owner.start()
                sleep = await self.clock.next_sleep()
                self.assertEqual(900, sleep[0])
                self.assertEqual(1, owner.link.connect_calls)
                self.assertFalse(owner.business_ready())
                self.clock.advance(sleep, 899)
                sleep = await self.clock.next_sleep()
                self.assertEqual(1, sleep[0])
                self.assertEqual(1, owner.link.connect_calls)
                self.assertEqual(int(stage == 'history'), owner.link.history_calls)
                owner.link.fail_with = None
                self.clock.advance(sleep)
                self.assertEqual(SYNC_INTERVAL, (await self.clock.next_sleep())[0])
                self.assertEqual(2, owner.link.connect_calls)
                self.assertTrue(owner.business_ready())
                await owner.stop()

    async def test_media_flood_wait_survives_successful_inflight_history_rpc(self):
        owner = self.make_owner()
        await owner.start()
        sleep = await self.clock.next_sleep()
        self.assertTrue(owner.business_ready())
        original_history = owner.link.history
        entered, release = asyncio.Event(), asyncio.Event()

        async def history(channel, **kwargs):
            entered.set()
            await release.wait()
            return await original_history(channel, **kwargs)

        owner.link.history = history
        self.clock.advance(sleep)
        await asyncio.wait_for(entered.wait(), 2)
        wait = TgProblem('private-flood-wait', wait=900)
        with patch.object(owner.link, 'message', new_callable=AsyncMock, side_effect=wait) as message:
            for _ in range(2):
                with self.assertRaises(TgProblem):
                    await owner.locate(CHANNEL['id'], 1)
            message.assert_awaited_once()
        release.set()
        sleep = await self.clock.next_sleep()
        self.assertEqual(900, sleep[0])
        self.assertEqual(1, owner.failures)
        self.assertFalse(owner.business_ready())
        self.clock.advance(sleep)
        self.assertEqual(SYNC_INTERVAL, (await self.clock.next_sleep())[0])
        self.assertTrue(owner.business_ready())

    async def test_paused_missing_session_and_unconfigured_never_connect(self):
        for overrides, state in (({'paused': True}, 'paused'), ({'session': ''}, 'pending_login'),
                                 ({'api_hash': ''}, 'unconfigured')):
            with self.subTest(state=state):
                self.account_file.write_text(json.dumps(self.account | overrides))
                owner = self.make_owner()
                await owner.start()
                sleep = await self.clock.next_sleep()
                self.assertEqual(SYNC_INTERVAL, sleep[0])
                self.clock.advance(sleep)
                await self.clock.next_sleep()
                self.assertEqual(state, owner.state)
                self.assertFalse(owner.business_ready())
                self.assertEqual((0, 0), (owner.link.connect_calls, owner.link.history_calls))
                await owner.stop()

    async def test_malformed_real_session_never_connects(self):
        owner = self.make_owner(factory=TgLink)
        with patch.object(owner.link, 'connect', new_callable=AsyncMock) as connect:
            await owner.start()
            await self.clock.next_sleep()
            connect.assert_not_awaited()
            self.assertEqual('pending_login', owner.state)
            self.assertFalse(owner.business_ready())

    async def test_ambiguous_false_is_revalidated_after_backoff_on_a_fresh_link(self):
        owner = self.make_owner()
        owner.link.connect_results.append(False)
        with patch.object(owner.link, 'close', wraps=owner.link.close) as close:
            await owner.start()
            sleep = await self.clock.next_sleep()
            self.assertEqual(60, sleep[0])
            self.assertEqual((1, 0), (owner.link.connect_calls, owner.link.history_calls))
            self.assertFalse(owner.business_ready())
            self.clock.advance(sleep)
            self.assertEqual(SYNC_INTERVAL, (await self.clock.next_sleep())[0])
            close.assert_awaited_once()
            self.assertEqual((2, 1), (owner.link.connect_calls, owner.link.history_calls))
            self.assertTrue(owner.business_ready())

    async def test_public_auth_rpc_recovers_from_temporary_error_and_flood_but_stops_on_revocation(self):
        session = StringSession()
        session.set_dc(1, '127.0.0.1', 443)
        session.auth_key = AuthKey(b'x' * 256)
        self.account_file.write_text(json.dumps(self.account | {'session': session.save()}))
        owner = self.make_owner(factory=TgLink)
        outcomes = deque([errors.ServerError(None, 'temporary'), None,
                          errors.FloodWaitError(request=None, capture=900), None,
                          errors.SessionRevokedError(request=None)])
        requests, clients = [], []
        check = self.assertIsInstance

        class Client:
            def __init__(self, *args, **kwargs):
                clients.append(self)
                self.connected = False

            def add_event_handler(self, *args):
                pass

            def is_connected(self):
                return self.connected

            async def connect(self):
                self.connected = True

            async def disconnect(self):
                self.connected = False

            async def __call__(self, request):
                check(request, functions.updates.GetStateRequest)
                requests.append(self)
                error = outcomes.popleft()
                if error is not None:
                    raise error

            async def get_messages(self, *args, **kwargs):
                return [fake_message()] if not kwargs.get('min_id') else []

        with patch('sefang.tg.link.TelegramClient', Client):
            await owner.start()
            sleep = await self.clock.next_sleep()
            self.assertEqual(60, sleep[0])
            self.assertFalse(owner.business_ready())
            self.clock.advance(sleep)
            sleep = await self.clock.next_sleep()
            self.assertEqual(SYNC_INTERVAL, sleep[0])
            self.assertTrue(owner.business_ready())
            self.assertEqual(clients, requests)
            self.assertEqual(2, len(clients))
            self.assertFalse(clients[0].is_connected())

            self.clock.advance(sleep)
            sleep = await self.clock.next_sleep()
            self.assertEqual(900, sleep[0])
            self.assertIs(clients[1], requests[-1])  # already-connected path
            self.assertFalse(owner.business_ready())
            self.clock.advance(sleep, 899)
            sleep = await self.clock.next_sleep()
            self.assertEqual((1, 3), (sleep[0], len(requests)))
            self.clock.advance(sleep)
            sleep = await self.clock.next_sleep()
            self.assertTrue(owner.business_ready())

            self.clock.advance(sleep)
            sleep = await self.clock.next_sleep()
            self.assertEqual('pending_login', owner.state)
            self.assertIsNone(owner.link.client)
            self.assertFalse(owner.business_ready())
            self.clock.advance(sleep)
            await self.clock.next_sleep()
            self.assertEqual((3, 5), (len(clients), len(requests)))

    async def test_stale_inflight_catchup_and_cancellation_require_fresh_sync(self):
        owner = self.make_owner()
        await owner.start()
        sleep = await self.clock.next_sleep()
        self.assertTrue(owner.business_ready())
        owner.link.hang_history = True
        self.clock.advance(sleep)
        await asyncio.wait_for(owner.link.history_entered.wait(), 2)
        self.clock.now += READY_MAX_AGE
        self.assertFalse(owner.business_ready())
        await owner.stop()
        self.assertTrue(owner.link.closed)
        self.assertEqual('paused', owner.index.channel_row(CHANNEL['id'])['state'])
        self.assertFalse(owner.business_ready())
        owner.link.hang_history = False
        await owner.start()
        await self.clock.next_sleep()
        self.assertTrue(owner.business_ready())

    async def test_explicit_offline_preview_is_ready_without_telegram(self):
        config = Config(self.config.data, self.config.state, self.config.channels, offline=True)
        app = create_app(config)
        self.addCleanup(app.state.repository.close)
        self.assertIsNone(app.state.telegram)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            await self.verify_probe(client, 200)

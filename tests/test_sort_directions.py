from support import auth_headers
"""Only the requested video sorting contract; isolated temporary data, no TG/network."""
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from sefang.grouping import PlaybackGroup, Snapshot, SORT_MODES
from sefang.app import create_app
from sefang.config import Config
from sefang.tg.index import ChannelIndex, video_from_message
from support import fake_message


def group(mid, duration, date, tail_date=None):
    row = dict(channel_id=123, message_id=mid, document_id=mid, duration=duration,
               available=True, date=date, title=str(mid))
    rows = (row,) if tail_date is None else (row, {**row, 'message_id': mid+1,
        'document_id': mid+1, 'duration': 30, 'date': tail_date})
    return PlaybackGroup(str(mid), 'single' if len(rows)==1 else 'confirmed', (), rows, (None,)*len(rows))


class SortModelTests(unittest.TestCase):
    def setUp(self):
        self.groups = (group(1, 50, '2026-01-01', '2026-06-01'),
                       group(3, 100, '2026-02-01'), group(4, 100, '2026-02-01'),
                       group(5, None, '2026-03-01'), group(6, 0, ''),
                       group(7, 10, '2026-04-01'))
        self.meta = {'1': {'release_date': '2025-01-01'}, '3': {'release_date': '2026-02-01'},
                     '4': {'release_date': '2026-02-01'}, '5': {'release_date': ''},
                     '6': {}, '7': {'release_date': '2024-01-01'}}
        self.snap = Snapshot(1, self.groups, self.meta)

    def test_six_modes_use_same_field_in_both_directions_and_unknowns_last(self):
        for desc, asc, value in [
            ('newest', 'oldest', lambda g: max(r['date'] for r in g.parts) or None),
            ('duration', 'duration_asc', lambda g: g.total_duration),
            ('release', 'release_asc', lambda g: self.meta[g.id].get('release_date') or None),
        ]:
            down, up = self.snap.ordered(desc), self.snap.ordered(asc)
            known_down = [g for g in down if value(g) is not None]
            known_up = [g for g in up if value(g) is not None]
            self.assertEqual(list(reversed(known_down)), known_up)
            for rows in (down, up):
                missing = [value(g) is None for g in rows]
                self.assertEqual(sorted(missing), missing)
                self.assertEqual({g.id for g in self.groups}, {g.id for g in rows})
                self.assertIs(self.snap.ordered(asc), up)
        self.assertEqual('1', self.snap.ordered('newest')[0].id)
        self.assertNotEqual('1', self.snap.ordered('oldest')[0].id)
        self.assertEqual(80, self.groups[0].total_duration)
        self.assertEqual(tuple(self.groups), self.snap.groups)

    def test_ties_are_stable_and_retired_name_is_not_supported(self):
        self.assertEqual(6, len(SORT_MODES))
        self.assertNotIn('name', SORT_MODES)
        for mode in SORT_MODES:
            self.assertEqual([g.id for g in self.snap.ordered(mode)], [g.id for g in self.snap.ordered(mode)])


class SortAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config = Config(root, root/'side', (123,), True)
        index = ChannelIndex(self.config.db)
        index.ensure_channel(123, '测试频道')
        for mid, seconds, date, release in [
            (1, 50, '2026-03-01', '2025-01-01'),
            (2, 100, '2026-01-01', '2026-01-01'),
            (3, 10, '2026-02-01', ''),
        ]:
            msg = fake_message(mid, name=f'ABC-{mid:03}.mp4', document=900+mid, seconds=seconds)
            row = video_from_message(123, msg)
            row['date'] = date
            index.store(123, [row])
            with index.session() as db:
                db.execute('UPDATE tg_work SET state=?,metadata=? WHERE identity=?',
                           ('matched', json.dumps({'title': f'作品{mid}', 'release_date': release}), f'ABC-{mid}'))
        self.app = create_app(self.config)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='https://test', headers=auth_headers(self.app))

    async def asyncTearDown(self):
        await self.client.aclose()
        self.app.state.repository.close()
        self.tmp.cleanup()

    async def test_all_six_api_orders_and_pagination(self):
        expected = {'newest': [1, 3, 2], 'oldest': [2, 3, 1], 'duration': [2, 1, 3],
                    'duration_asc': [3, 1, 2], 'release': [2, 1, 3], 'release_asc': [1, 2, 3]}
        for mode, ids in expected.items():
            response = await self.client.get('/api/videos', params={'sort': mode})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(ids, [x['message_id'] for x in response.json()['items']])
            second = await self.client.get('/api/videos', params={'sort': mode, 'limit': 1, 'page': 2})
            self.assertEqual(ids[1], second.json()['items'][0]['message_id'])
        for mode in ['name', 'SQL', 'duration_desc']:
            self.assertEqual(422, (await self.client.get('/api/videos', params={'sort': mode})).status_code)

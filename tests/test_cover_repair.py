import asyncio
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
import test_site as site
from test_site import offline, seed
from sefang import codes
from sefang.cover_repair import CheckedCover, selected_missing, select_cover, install_missing
from sefang.catalog.found import Found
from sefang.catalog import covers
from sefang.thumbnails import inspect_thumbnail, MAX_BYTES, MAX_PIXELS
from sefang.tg.works import cover_name


def picture(color=(0, 0, 0), fmt='PNG', size=(320, 180), pixel=None):
    im = Image.new('RGB', size, color)
    if pixel:
        im.putpixel((0, 0), pixel)
    b = io.BytesIO(); im.save(b, format=fmt); return b.getvalue()


class ThumbnailPixels(unittest.TestCase):
    def test_exact_black_jpeg_and_png(self):
        for fmt in ('JPEG', 'PNG'):
            self.assertEqual((None, 'black'), inspect_thumbnail(picture(fmt=fmt)))

    def test_dark_one_pixel_black_borders_and_normal(self):
        for fmt in ('JPEG', 'PNG'):
            for color in [(1, 1, 1), (3, 4, 5), (120, 80, 50)]:
                self.assertEqual('image/' + ('jpeg' if fmt == 'JPEG' else 'png'), inspect_thumbnail(picture(color, fmt))[0])
        self.assertEqual('image/png', inspect_thumbnail(picture(pixel=(1, 0, 0)))[0])
        im = Image.new('RGB', (320, 180)); im.paste((4, 4, 4), (10, 20, 300, 160)); b=io.BytesIO();im.save(b, 'PNG')
        self.assertEqual('image/png', inspect_thumbnail(b.getvalue())[0])

    def test_empty_corrupt_oversize_pixels_and_animation(self):
        for data, reason in [(None, 'empty'), (b'', 'empty'), (b'broken', 'invalid'), (b'x'*(MAX_BYTES+1), 'too_large'),
                             (picture((1,1,1), size=(2001,2000)), 'invalid')]:
            self.assertEqual((None, reason), inspect_thumbnail(data))
        im=Image.new('RGB',(10,10),'red');b=io.BytesIO();im.save(b,'GIF')
        self.assertEqual((None,'invalid'), inspect_thumbnail(b.getvalue()))


class ThumbnailApi(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = site.ApiTests.asyncSetUp
    asyncTearDown = site.ApiTests.asyncTearDown
    async def test_black_empty_invalid_error_and_dark(self):
        url='/api/videos/123/1/thumbnail'
        for data, status, reason in [(picture(fmt='JPEG'),404,'black'),(None,404,'empty'),(b'broken',404,'invalid'),
                                    (picture((1,1,1),'JPEG'),200,''),(picture(pixel=(1,0,0)),200,'')]:
            self.tg.thumbnail=AsyncMock(return_value=data)
            r=await self.client.get(url)
            self.assertEqual(status,r.status_code);self.assertEqual('no-store',r.headers['cache-control'])
            if reason:self.assertEqual(reason,r.json()['reason'])
            else:self.assertTrue(r.headers['content-type'].startswith('image/'))
        self.tg.thumbnail=AsyncMock(side_effect=RuntimeError('not exposed'))
        r=await self.client.get(url);self.assertEqual((404,'unavailable'),(r.status_code,r.json()['reason']))
        self.assertNotIn('not exposed',r.text)
        self.assertEqual(404,(await self.client.get('/api/videos/999/1/thumbnail')).status_code)

    async def test_official_cover_never_calls_telegram_or_black_check(self):
        from sefang.tg.works import CoverShelf
        CoverShelf(self.config.covers,self.index).put('IPX-1',picture(fmt='JPEG',size=(800,600)), 'https://example.com', (800,600))
        self.tg.thumbnail=AsyncMock(side_effect=AssertionError('TG called'))
        with patch('sefang.app.inspect_thumbnail',side_effect=AssertionError('checked formal cover')):
            r=await self.client.get('/api/videos/123/1/thumbnail')
        self.assertEqual((200,'public, max-age=3600'),(r.status_code,r.headers['cache-control']))
        self.tg.thumbnail.assert_not_called()

    async def test_decode_timeout_is_unavailable(self):
        self.tg.thumbnail=AsyncMock(return_value=picture((10,10,10)))
        with patch('sefang.app.inspect_thumbnail',side_effect=TimeoutError):
            r=await self.client.get('/api/videos/123/1/thumbnail')
        self.assertEqual((404,'unavailable'),(r.status_code,r.json()['reason']))


class ManifestRepair(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.config=offline(Path(self.temp.name));self.index,self.repo=seed(self.config,1)
        self.manifest=[{'identity':'IPX-1','code':'IPX-001'}]
        self.found=Found('fc2','https://adult.contents.fc2.com/article/1234567/',number='FC2-PPV-1234567',covers=['https://storage65000.contents.fc2.com/file/cover.jpg'])
        self.ipx=Found('r18dev','https://r18.dev/videos/vod/movies/detail/-/id=ipx00001',number='IPX-001',covers=['https://awsimgsrc.dmm.com/dig/digital/video/ipx00001/ipx00001pl.jpg'])
        self.data=picture((10,10,10),size=(800,600))
        self.image=CheckedCover('IPX-1','IPX-001',self.data,self.ipx.covers[0],(800,600),(self.ipx,))
    def tearDown(self):self.repo.close();self.temp.cleanup()
    def works(self):
        with self.index.session() as db:return [tuple(r) for r in db.execute('SELECT * FROM tg_work')]
    def test_explicit_33_and_unsupported_no_scope_expansion(self):
        with self.index.session() as db:
            for i in range(2,34):
                db.execute("INSERT INTO tg_work(identity,code,content_type) VALUES(?,?,?)",(f'IPX-{i}',f'IPX-{i:03}','censored'))
            db.execute("INSERT INTO tg_work(identity,code,content_type,state) VALUES('YUJ-66','YUJ-066','kmib','unsupported')")
        manifest=[{'identity':f'IPX-{i}','code':f'IPX-{i:03}'} for i in range(1,34)]+[{'identity':'YUJ-66','code':'YUJ-066'}]
        result=selected_missing(self.config.db,self.config.covers,manifest)
        self.assertEqual(34,len(result));self.assertEqual(33,sum(s=='missing' for _,s in result));self.assertEqual('unsupported',result[-1][1])
        self.assertEqual(1,len(selected_missing(self.config.db,self.config.covers,self.manifest)))
        with self.assertRaises(ValueError):selected_missing(self.config.db,self.config.covers,[{'identity':'IPX-1','code':'IPX-002'}])
    def test_install_receipt_metadata_unchanged_no_overwrite(self):
        before=self.works()[0];r=install_missing(self.config.db,self.config.covers,self.manifest,self.image);after=self.works()[0]
        self.assertEqual(hashlib.sha256(self.data).hexdigest(),r['sha256']);self.assertEqual(before[:10],after[:10])
        self.assertEqual(0o600,(self.config.covers/r['file']).stat().st_mode&0o777)
        with self.assertRaises(FileExistsError):install_missing(self.config.db,self.config.covers,self.manifest,self.image)
        self.assertEqual(after,self.works()[0])
    def test_existing_file_or_budget_never_evicted(self):
        self.config.covers.mkdir(parents=True);p=self.config.covers/cover_name('IPX-1');p.write_bytes(b'old')
        with self.assertRaises(FileExistsError):install_missing(self.config.db,self.config.covers,self.manifest,self.image)
        self.assertEqual(b'old',p.read_bytes());p.unlink()
        for opts in [{'budget':0},{'files':0}]:
            with self.assertRaises(ValueError):install_missing(self.config.db,self.config.covers,self.manifest,self.image,**opts)
        self.assertFalse(p.exists());self.assertEqual('',self.works()[0][11])
    def test_wrong_identity_source_dimensions_size_and_broken(self):
        for image in [replace(self.image,identity='IPX-2'),replace(self.image,source='https://unapproved.example/a.jpg'),
                      replace(self.image,size=(801,600)),replace(self.image,data=b'broken'),replace(self.image,data=b'x'*(8*1048576+1))]:
            with self.assertRaises((ValueError,OSError)):install_missing(self.config.db,self.config.covers,self.manifest,image)
        other=replace(self.ipx,number='IPX-002',url='https://example.com/IPX-002')
        with self.assertRaises(ValueError):select_cover('IPX-001',[other],None)
        excluded=Found('javarchive','https://javarchive.com/1234567.html',number='FC2-PPV-1234567',covers=['https://img.javstore.net/FC2-PPV-1234567.jpg'])
        self.assertIsNone(select_cover('FC2-PPV-1234567',[excluded],None))

class RepairHttpGuards(unittest.TestCase):
    def test_all_dns_addresses_and_redirect_target_are_checked(self):
        from sefang.catalog.web import all_public, Web, Unreachable, Spacer
        with patch('sefang.catalog.web.addresses', return_value=['8.8.8.8','127.0.0.1']):
            self.assertFalse(all_public('example.com'))
        calls=[]
        def transport(req):
            calls.append(str(req.url)); return httpx.Response(302,headers={'Location':'https://127.0.0.1/private'})
        web=Web(client=httpx.Client(transport=httpx.MockTransport(transport)),spacer=Spacer(default=0))
        with patch('sefang.catalog.web.all_public',return_value=True):
            with self.assertRaises(Unreachable):web.fetch('https://public.example/start')
        self.assertEqual(['https://public.example/start'],calls);web.close()
    def test_body_limit_and_request_budget(self):
        from sefang.catalog.web import Web, Unreachable, Refused, Spacer
        web=Web(max_requests=1,client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'x'*100))),spacer=Spacer(default=0))
        with patch('sefang.catalog.web.all_public',return_value=True):
            with self.assertRaises(Unreachable):web.fetch('https://public.example/a',limit=10)
            with self.assertRaises(Refused):web.fetch('https://public.example/b')
        web.close()

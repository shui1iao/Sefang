"""Only Chinese-layer behavior; synthetic public metadata, no Telegram or real translation network."""
import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
sys.path.insert(0,str(Path(__file__).parent))
from test_site import offline,seed
from sefang.localization import Input,Store,View,Worker,inventory,protection,restore
from sefang.translation_http import Providers,TranslationError,GOOGLE
from sefang.repository import entity_id

class LocalizedTests(unittest.TestCase):
 def test_protection_read_only_view_hash_and_resume(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'localization');item=Input('title','work','静かな庭 山田花子 ABW-001',('山田花子','ABW-001'))
   masked,used=protection(item.raw,item.tokens);self.assertNotIn('山田花子',masked)
   self.assertEqual(restore('安静的花园 '+masked[masked.index('ZQX'):],used),'安静的花园 山田花子 ABW-001')
   with self.assertRaises(TranslationError):restore('安静的花园 ZQX0XQZ',used)
   store.bind([item]);store.finish(item,'machine',zh='安静的花园 山田花子 ABW-001',method='machine',provider='test')
   view=View(store.root);self.assertIsNotNone(view.project('title',item.raw,item.tokens)['zh']);self.assertFalse(Store(store.root).due(item))
   self.assertIsNone(view.project('title','新しい庭 山田花子 ABW-001',item.tokens)['zh'])
   self.assertEqual((store.root.stat().st_mode&0o777,store.path.stat().st_mode&0o777),(0o700,0o600))
 def test_public_inventory_projection_search_and_filter_scope(self):
  with tempfile.TemporaryDirectory() as d:
   config=offline(Path(d));index,repo=seed(config,3)
   values=[('静かな庭 山田花子','春の話','庭園'),('青い空','春の話','街並み'),('訳なし','夏の話','庭園')]
   with index.session() as db:
    for n,(title,series,tag) in enumerate(values,1):
     f={'title':title,'performers':['山田花子'],'studio':'テスト社','series':series,'tags':[tag]}
     s=[{'url':'https://example.com/catalog','returned_id':'public-product','fields':['title','tags','series']}]
     db.execute('UPDATE tg_work SET metadata=?,sources=? WHERE identity=?',(json.dumps(f),json.dumps(s),f'IPX-{n}'))
    original=db.execute('SELECT identity,metadata,sources FROM tg_work ORDER BY identity').fetchall()
   repo.sync_entities();items=inventory(config);store=Store(config.state/'localization');store.bind(items)
   for x in items:
    if x.kind=='title' and x.raw.startswith('静かな'):store.finish(x,'machine',zh='安静的花园 山田花子',method='machine',provider='test')
    elif x.kind=='title' and x.raw=='青い空':store.finish(x,'machine',zh='安静的蓝天',method='machine',provider='test')
    elif x.kind=='categories':store.finish(x,'machine',zh='相同译名',method='machine',provider='test')
    else:store.finish(x,'error','invalid_result')
   with patch.object(Providers,'translate',side_effect=AssertionError('GET must never translate')):
    zh=repo.videos(q='安静');self.assertEqual(zh['total'],2)
    raw=repo.videos(q='静かな');self.assertEqual(raw['total'],1);self.assertIn(raw['items'][0]['id'],[item['id'] for item in zh['items']])
    only=repo.videos(q='安静',category=entity_id('categories','庭園'));self.assertEqual(only['total'],1)
    self.assertEqual(only['items'][0]['title'],'静かな庭 山田花子');self.assertEqual(only['items'][0]['display_title'],'安静的花园 山田花子')
    self.assertEqual(repo.videos(q='春日故事')['total'],0,'global q does not gain series search')
    tags=repo.entities('categories',q='相同译名',limit=1);self.assertEqual(tags['total'],2);self.assertEqual(len(tags['items']),1)
    nextpage=repo.entities('categories',q='相同译名',page=2,limit=1);self.assertNotEqual(tags['items'][0]['id'],nextpage['items'][0]['id'])
    self.assertEqual(repo.entities('series',q='春の話')['total'],1)  # Internal original metadata remains; no new series translation.
    detail=repo.detail(123,1);self.assertEqual(detail['entities']['series'][0]['name'],'春の話');self.assertEqual(detail['entities']['studios'][0]['name'],'テスト社')
    self.assertEqual(repo.detail(123,3)['display_title'],'訳なし');self.assertIsNone(repo.detail(123,3)['title_zh'])
   with index.session() as db:self.assertEqual(db.execute('SELECT identity,metadata,sources FROM tg_work ORDER BY identity').fetchall(),original)
   repo.close()

class ProviderTests(unittest.IsolatedAsyncioTestCase):
 async def test_fixed_host_redirect_oversize_timeout_and_cooldown(self):
  with tempfile.TemporaryDirectory() as d:
   control=Store(Path(d))
   async def response(request):return httpx.Response(302,headers={'location':'https://other.invalid/'})
   p=Providers(control,transport=httpx.MockTransport(response),interval=0)
   with self.assertRaisesRegex(TranslationError,'fixed_host_required'):await p._request('https://other.invalid/')
   with self.assertRaisesRegex(TranslationError,'redirect_refused'):await p.translate('google','静かな庭','ja')
   p.transport=httpx.MockTransport(lambda r:httpx.Response(429))
   with self.assertRaisesRegex(TranslationError,'http_429'):await p.translate('google','静かな庭','ja')
   self.assertGreater(float(control.get('google_until')),0)
   with self.assertRaisesRegex(TranslationError,'cooldown'):await p.translate('google','静かな庭','ja')
   control.set('google_until','0');p.transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-length':str(2*1048576)}))
   with self.assertRaisesRegex(TranslationError,'response_too_large'):await p._request(GOOGLE)
   def timeout(r):raise httpx.ReadTimeout('no real request text')
   p.transport=httpx.MockTransport(timeout)
   with self.assertRaisesRegex(TranslationError,'timeout'):await p._request(GOOGLE)
 async def test_failed_text_not_success_and_cancel_resume(self):
  with tempfile.TemporaryDirectory() as d:
   config=offline(Path(d));worker=Worker(config,interval=0);item=Input('title','one','静かな庭')
   async def bad(*args):return '静かな庭'
   worker.providers.translate=bad
   await worker.run(items=[item]);self.assertIsNone(View(worker.store.root).project(item.kind,item.raw)['zh'])
   with worker.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM entry').fetchone()[0],0)
   worker.store.set('paused','1');self.assertEqual((await worker.run(items=[Input('title','two','新しい庭')]))['processed'],0)

if __name__=='__main__':unittest.main()

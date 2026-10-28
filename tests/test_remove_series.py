from support import auth_headers
"""Direct tests for removal only; metadata and existing localization stay intact."""
import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).parent))
from test_site import offline,seed
from sefang.app import create_app
from sefang.localization import Input,Store,Worker,inventory
from sefang.repository import entity_id

class SeriesRemovalTests(unittest.IsolatedAsyncioTestCase):
 async def test_public_routes_and_filter_removed_internal_metadata_retained(self):
  with tempfile.TemporaryDirectory() as d:
   config=offline(Path(d));index,repo=seed(config,3);ident=entity_id('series','系列')
   with index.session() as db:before=db.execute('SELECT identity,metadata,sources FROM tg_work ORDER BY identity').fetchall()
   app=create_app(config)
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://test', headers=auth_headers(app)) as client:
    base=(await client.get('/api/videos')).json();old=(await client.get('/api/videos',params={'series':ident})).json();invalid=(await client.get('/api/videos',params={'series':'bad'})).json()
    self.assertEqual(base,old);self.assertEqual(base,invalid)
    for path in ['/series','/series/'+ident,'/api/entities/series','/api/entities/series/'+ident]:self.assertEqual((await client.get(path)).status_code,404)
    self.assertEqual((await client.get('/api/entities/categories')).status_code,200);self.assertEqual((await client.get('/api/entities/studios')).status_code,200)
   self.assertIsNotNone(repo.entity('series',ident));self.assertEqual(repo.videos(series=ident)['total'],base['total'])
   with index.session() as db:self.assertEqual(db.execute('SELECT identity,metadata,sources FROM tg_work ORDER BY identity').fetchall(),before)
   app.state.repository.close();repo.close()
 async def test_no_new_series_translation_and_existing_bindings_cache_retained(self):
  with tempfile.TemporaryDirectory() as d:
   config=offline(Path(d));index,repo=seed(config,1);worker=Worker(config);old=Input('series',entity_id('series','春の話'),'春の話')
   worker.store.bind([old]);worker.store.finish(old,'machine',zh='春日故事',method='machine',provider='synthetic')
   with worker.store.connect() as db:before=db.execute('SELECT * FROM entry').fetchall();bindings=db.execute('SELECT * FROM binding').fetchall()
   self.assertFalse(any(x.kind=='series' for x in inventory(config)))
   with patch.object(worker.providers,'translate',side_effect=AssertionError('series must not be sent')):self.assertEqual((await worker.run(items=[old]))['processed'],0)
   worker.store.bind([])
   with worker.store.connect() as db:self.assertEqual(db.execute('SELECT * FROM entry').fetchall(),before);self.assertEqual(db.execute('SELECT * FROM binding').fetchall(),bindings)
   repo.close()
if __name__=='__main__':unittest.main()

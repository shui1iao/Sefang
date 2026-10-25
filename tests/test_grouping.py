import hashlib,json,os,shutil,sqlite3,tempfile,unittest
from collections import Counter
from pathlib import Path
import httpx
from sefang.config import Config
from sefang.repository import Repository,KINDS,entity_id,names_of
from sefang.app import create_app
import sys
sys.path.insert(0,str(Path(__file__).parent))
from sefang.tg.index import ChannelIndex,video_from_message
from support import FakeLink,fake_message,CHANNEL,source_cast




def part(store,mid,name,duration,document=None,caption=''):
 msg=fake_message(mid,text=caption,document=document or 5000+mid);msg.document.attributes[0].duration=duration;msg.document.attributes[-1].file_name=name
 row=video_from_message(123,msg);store.store(123,[row]);return msg

class IncrementalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);self.config=Config(root,root/'side',(123,),True)
  self.store=ChannelIndex(self.config.db);self.store.ensure_channel(123,'合成频道')
  part(self.store,1,'IPX-001(1).mp4',600.25);part(self.store,2,'IPX-001(2).mp4',300.5);part(self.store,3,'IPX-002.mp4',100)
  part(self.store,4,'ABC-123(1).mp4',50);part(self.store,5,'ABC-123(1).mp4',51)
  with self.store.session() as db:db.execute("UPDATE tg_work SET state='matched',metadata=? WHERE identity='IPX-1'",(json.dumps({'title':'合成作品','performers':['甲']}),))
  source_cast(self.store)
  self.repo=Repository(self.config);self.repo.sync_entities()
 def tearDown(self):self.repo.close();self.tmp.cleanup()
 def cards(self):return {c['id']:c for c in self.repo.videos(limit=60)['items']}
 def test_new_edit_delete_recompute_only_affected_identity(self):
  cards=self.cards();self.assertEqual(4,len(cards))
  group=[c for c in cards.values() if c['part_count']==2][0];self.assertAlmostEqual(900.75,group['duration']);self.assertTrue(group['duration_complete'])
  self.assertEqual(1,self.repo.entity('actors',entity_id('actors','甲'))['count'])
  self.assertEqual('unresolved',self.repo.snapshot().by_message[(123,4)].status)
  before=self.repo.groups.recomputed_buckets;generation=self.repo.snapshot().generation
  self.repo.refresh();self.assertEqual((before,generation),(self.repo.groups.recomputed_buckets,self.repo.snapshot().generation))
  part(self.store,6,'IPX-001(3).mp4',200)
  self.assertEqual(1,len(self.repo.refresh()));self.assertEqual(before+1,self.repo.groups.recomputed_buckets)
  g=self.repo.snapshot().by_message[(123,6)];self.assertEqual([1,2,6],[r['message_id'] for r in g.parts]);self.assertAlmostEqual(1100.75,g.total_duration)
  self.assertEqual(4,len(self.cards()));self.assertEqual(1,self.repo.entity('actors',entity_id('actors','甲'))['count'])
  # 编辑为缺号写法：整组退回独立，不跨缺号拼接。
  part(self.store,6,'IPX-001(4).mp4',200);self.repo.refresh()
  self.assertEqual(1,len(self.repo.snapshot().by_message[(123,1)].parts));self.assertEqual(6,len(self.cards()))
  self.assertEqual(3,self.repo.entity('actors',entity_id('actors','甲'))['count'])
  part(self.store,6,'IPX-001(3).mp4',200);self.repo.refresh();self.assertEqual(4,len(self.cards()))
  # 删除一段：保留组与原地址，合计只计已知可用段并标未完整。
  self.store.mark_gone(123,2);self.repo.refresh();g=self.repo.snapshot().by_message[(123,2)]
  self.assertEqual(3,len(g.parts));self.assertFalse(g.duration_complete);self.assertAlmostEqual(800.25,g.total_duration)
  detail=self.repo.detail(123,2)['group'];self.assertEqual(1,detail['index']);self.assertFalse(detail['parts'][1]['available'])
 def test_group_id_stable_across_new_segment(self):
  first=self.repo.snapshot().by_message[(123,1)].id
  part(self.store,6,'IPX-001(3).mp4',200);self.repo.refresh();self.assertEqual(first,self.repo.snapshot().by_message[(123,6)].id)

class EventApiTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);self.config=Config(root,root/'side',(123,),False)
  store=ChannelIndex(self.config.db);store.ensure_channel(123,'合成频道')
  part(store,1,'IPX-001(1).mp4',4.0);Repository(self.config).close()
  self.config.secrets_root.mkdir(parents=True);(self.config.secrets_root/'telegram').mkdir()
  (self.config.secrets_root/'telegram/account.json').write_text(json.dumps({'channels':[CHANNEL],'session':'synthetic','api_id':1,'api_hash':'x'}))
  self.app=create_app(self.config,FakeLink);self.tg=self.app.state.telegram;self.tg.state='connected'
  self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test')
 async def asyncTearDown(self):
  await self.client.aclose();await self.tg.stop();self.app.state.repository.close();self.tmp.cleanup()
 async def test_new_part_event_joins_group_without_refetch_and_legacy_link(self):
  self.assertEqual(1,(await self.client.get('/api/videos')).json()['items'][0]['part_count'])
  msg=fake_message(2,text='',document=902);msg.document.attributes[0].duration=5.0;msg.document.attributes[-1].file_name='IPX-001(2).mp4'
  calls=(self.tg.link.history_calls,self.tg.link.message_calls)
  await self.tg.on_update(123,msg,None)
  body=(await self.client.get('/api/videos')).json();self.assertEqual(1,body['total']);card=body['items'][0]
  self.assertEqual((2,9.0,True,1),(card['part_count'],card['duration'],card['duration_complete'],card['message_id']))
  self.assertEqual(calls,(self.tg.link.history_calls,self.tg.link.message_calls))
  detail=(await self.client.get('/api/videos/123/2')).json();self.assertEqual(1,detail['group']['index']);self.assertEqual(2,detail['message_id'])
  for name in ['document_id','access_hash','/opt/']:self.assertNotIn(name,json.dumps(detail))
  self.assertIn((await self.client.get('/watch/123/2')).status_code,(200,503))
  self.assertEqual(1,(await self.client.get('/api/videos?q=IPX-001(2)')).json()['total'])
  self.assertEqual([],(await self.client.get('/api/videos/123/2/related')).json()['items'])

class StrictAliasTests(unittest.TestCase):
 def row(self,mid,name='ABC-123.mp4',**fields):
  row=dict(channel_id=123,message_id=mid,document_id=str(9000+mid),title=name,code='ABC-123',identity='ABC-123',identification='identified',size=123456789,duration=321.125,width=1920,height=1080,mime='video/mp4',available=1,date='2026-01-01',metadata='{}')
  row.update(fields);return row
 def project(self,rows):
  from sefang.grouping import GroupIndex
  index=GroupIndex(json.loads);index.update(rows);return index
 def test_exact_alias_and_part_queue_count_once(self):
  a=self.row(1);b=self.row(2);g=self.project([b,a]).snapshot.groups[0]
  self.assertEqual([1],[r['message_id'] for r in g.parts]);self.assertEqual({(123,1),(123,2)},set(g.keys))
  self.assertEqual(0,g.index_of(123,2));self.assertEqual(321.125,g.total_duration)
  p1=self.row(1,'ABC-123(1).mp4');p2=self.row(2,'ABC-123(2).mp4',size=987654321,duration=200.25);alias={**p2,'message_id':3,'document_id':'9003'}
  snap=self.project([p1,p2,alias]).snapshot;self.assertEqual(1,len(snap.groups));g=snap.groups[0]
  self.assertEqual('confirmed',g.status);self.assertEqual((1,2),g.numbers);self.assertEqual(2,len(g.parts));self.assertEqual(521.375,g.total_duration)
  self.assertEqual(1,g.index_of(123,3));self.assertIs(g,snap.by_message[(123,3)])
  dto=Repository.__new__(Repository).group_detail(g,123,3)
  self.assertEqual([1,3],[p['message_id'] for p in dto['parts']]);self.assertEqual('/api/videos/123/3/stream',dto['parts'][1]['stream']);self.assertEqual('https://t.me/c/123/3',dto['parts'][1]['message_url'])
  self.assertEqual(1,dto['index']);self.assertEqual(2,dto['part_count']);self.assertEqual(521.375,dto['total_duration'])
 def test_strict_attributes_do_not_normalize_or_accept_invalid(self):
  changes=[{'title':'abc-123.mp4'},{'title':'ABC-123 .mp4'},{'title':'ABC-123-C.mp4'},{'size':123456790},{'duration':321.125001},{'width':1280},{'height':720},{'mime':'video/webm'},{'channel_id':124},{'identity':'ABC-124'},{'identification':'ambiguous'},{'identification':'unidentified'}]
  for fields in changes:
   with self.subTest(fields=fields):self.assertEqual(2,len(self.project([self.row(1),self.row(2,**fields)]).snapshot.groups))
  invalid=[{'size':0},{'size':-1},{'size':True},{'duration':0},{'duration':None},{'duration':float('nan')},{'duration':float('inf')},{'width':0},{'height':None},{'title':''},{'mime':''}]
  for fields in invalid:
   with self.subTest(invalid=fields):self.assertEqual(2,len(self.project([self.row(1,**fields),self.row(2,**fields)]).snapshot.groups))
 def test_bare_only_does_not_poison_all_valid_parts(self):
  p1=self.row(1,'ABC-123(1).mp4');p2=self.row(2,'ABC-123(2).mp4',size=987654321,duration=200.25);bare=self.row(3)
  groups=self.project([p1,p2,bare]).snapshot.groups;self.assertEqual(2,len(groups));self.assertEqual([1,2],[r['message_id'] for r in next(g for g in groups if g.status=='confirmed').parts])
  for extra in [self.row(4,'ABC-123(1).mp4',duration=322),self.row(4,'ABC-123(4).mp4')]:
   self.assertEqual(4,len(self.project([p1,p2,bare,extra]).snapshot.groups))
  for second in [self.row(2,'ABC-123(4).mp4'),self.row(2,'ABC-123-C(2).mp4'),self.row(2,'ABC-123(2).mp4',mime='video/webm')]:
   self.assertEqual(3,len(self.project([p1,second,bare]).snapshot.groups))
 def test_mixed_resolution_complete_parts_and_media_guards(self):
  a=self.row(1,'ABC-123(1).mp4',width=960,height=540,duration=533.125)
  b=self.row(2,'ABC-123(2).mp4',width=1920,height=1080,duration=133.25,size=987654321)
  snap=self.project([a,b]).snapshot;self.assertEqual(1,len(snap.groups));g=snap.groups[0]
  self.assertEqual('confirmed',g.status);self.assertEqual((1,2),g.numbers);self.assertEqual(666.375,g.total_duration)
  self.assertEqual([(960,540),(1920,1080)],[(r['width'],r['height']) for r in g.parts])
  for fields in [{'mime':'video/webm'},{'mime':'application/octet-stream'},{'duration':0},{'width':0},{'size':0},{'title':'ABC-123-C(2).mp4'},{'title':'ABC-123(4).mp4'}]:
   with self.subTest(fields=fields):self.assertEqual(2,len(self.project([a,{**b,**fields}]).snapshot.groups))
  conflict={**a,'message_id':3,'document_id':'9003','duration':534.125};self.assertEqual(3,len(self.project([a,b,conflict]).snapshot.groups))
  alias={**b,'message_id':3,'document_id':'9003'};s=self.project([a,b,alias]).snapshot;self.assertEqual(1,len(s.groups));self.assertEqual(666.375,s.groups[0].total_duration);self.assertEqual(1,s.groups[0].index_of(123,3))
 def test_incremental_add_edit_delete_and_available_representative(self):
  a=self.row(1,'ABC-123(1).mp4');b=self.row(2,'ABC-123(2).mp4',duration=200.25);other=self.row(10,'ABC-124.mp4',code='ABC-124',identity='ABC-124')
  index=self.project([a,b,other]);old=index.snapshot;stable=old.by_message[(123,1)].id;before=index.recomputed_buckets
  alias={**a,'message_id':3,'document_id':'9003'};self.assertEqual(1,len(index.update([a,b,alias,other])));self.assertEqual(before+1,index.recomputed_buckets)
  unavailable={**a,'available':0};index.update([unavailable,b,alias,other]);g=index.snapshot.by_message[(123,1)]
  self.assertEqual(stable,g.id);self.assertEqual([3,2],[r['message_id'] for r in g.parts]);self.assertEqual(0,g.index_of(123,1));self.assertTrue(g.duration_complete)
  self.assertEqual([1,2],[r['message_id'] for r in old.by_message[(123,1)].parts])
  index.update([unavailable,b,other]);g=index.snapshot.by_message[(123,1)];self.assertNotIn((123,3),index.snapshot.by_message);self.assertFalse(g.duration_complete);self.assertEqual(200.25,g.total_duration)
  edited={**a,'title':'ABC-123(4).mp4'};index.update([edited,b,other]);self.assertEqual(3,len(index.snapshot.groups));self.assertEqual('unresolved',index.snapshot.by_message[(123,1)].status)
  index.update([a,b,other]);self.assertEqual(stable,index.snapshot.by_message[(123,1)].id)

class AliasRepositoryTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);self.config=Config(root,root/'side',(123,),True)
  self.store=ChannelIndex(self.config.db);self.store.ensure_channel(123,'合成频道')
  part(self.store,1,'IPX-001(1).mp4',600.25);part(self.store,2,'IPX-001(2).mp4',300.5);part(self.store,3,'IPX-001(2).mp4',300.5);part(self.store,4,'ABC-002.mp4',100)
  with self.store.session() as db:db.execute("UPDATE tg_work SET state='matched',metadata=? WHERE identity='IPX-1'",(json.dumps({'title':'合成作品','performers':['甲'],'studio':'合成厂牌','tags':['合成分类']}),))
  source_cast(self.store)
  self.app=create_app(self.config);self.repo=self.app.state.repository;self.repo.sync_entities();self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test')
 async def asyncTearDown(self):
  await self.client.aclose();self.repo.close();self.tmp.cleanup()
 async def test_alias_dto_search_filters_entities_related(self):
  from unittest.mock import patch
  body=(await self.client.get('/api/videos')).json();self.assertEqual(2,body['total']);g=self.repo.snapshot().by_message[(123,3)]
  for mid,slot in [(1,0),(2,1),(3,1)]:
   d=(await self.client.get(f'/api/videos/123/{mid}')).json();self.assertEqual(mid,d['message_id']);self.assertEqual(f'/api/videos/123/{mid}/stream',d['stream']);self.assertEqual(f'https://t.me/c/123/{mid}',d['message_url'])
   self.assertEqual(slot,d['group']['index']);self.assertEqual(mid,d['group']['parts'][slot]['message_id']);self.assertEqual(d['stream'],d['group']['parts'][slot]['stream']);self.assertEqual(d['message_url'],d['group']['parts'][slot]['message_url']);self.assertEqual(2,d['group']['part_count']);self.assertEqual(900.75,d['group']['total_duration'])
  category=entity_id('categories','合成分类');actor=entity_id('actors','甲');studio=entity_id('studios','合成厂牌')
  result=(await self.client.get('/api/videos',params={'q':'IPX-001(2).mp4','category':category,'actor':actor,'studio':studio})).json();self.assertEqual(1,result['total']);self.assertEqual(g.id,result['items'][0]['id'])
  self.assertEqual([g.id],[c['id'] for c in self.repo.videos(q='IPX-001(1).mp4',category=category)['items']]) # actual alias/representative title search, not a removed private helper
  for kind,ident in [('categories',category),('actors',actor),('studios',studio)]:self.assertEqual(1,self.repo.entity(kind,ident)['count'])
  related=(await self.client.get('/api/videos/123/3/related')).json()['items'];ids=[v['id'] for v in related];self.assertNotIn(g.id,ids);self.assertEqual(len(ids),len(set(ids)))
 async def test_available_alias_preserves_requested_unavailable_message(self):
  self.store.mark_gone(123,2);self.repo.refresh();g=self.repo.snapshot().by_message[(123,2)];self.assertEqual([1,3],[r['message_id'] for r in g.parts])
  unavailable=(await self.client.get('/api/videos/123/2')).json();available=(await self.client.get('/api/videos/123/3')).json()
  self.assertFalse(unavailable['available']);self.assertFalse(unavailable['group']['parts'][1]['available']);self.assertEqual(2,unavailable['group']['parts'][1]['message_id']);self.assertTrue(available['group']['parts'][1]['available']);self.assertTrue(g.duration_complete);self.assertEqual(900.75,g.total_duration)

if __name__=='__main__':unittest.main()

"""Direct source-field and normal-owner/work-cover integration; all IO is local/fake."""
import asyncio,io,json,tempfile,unittest,sys,time
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).parent))
from support import FakeLink,fake_message,CHANNEL
from sefang.repository import Repository,source_performers
from sefang.config import Config
from sefang.tg.index import ChannelIndex,video_from_message
from sefang.tg.owner import ChannelOwner
from sefang.tg.works import WorkFiller,CoverShelf,cover_name,COVER_MAX
from sefang.tg.link import TgLink,TgProblem
from sefang.catalog.chain import Outcome
from sefang.thumbnails import inspect_thumbnail
from PIL import Image
from telethon import types
import httpx

def picture(color=(32,64,128),fmt='PNG',size=(320,240)):
 out=io.BytesIO();Image.new('RGB',size,color).save(out,format=fmt);return out.getvalue()
def actorrow(names=None):
 return {'identification':'identified','identity':'SYN-1','code':'SYN-001','work_code':'SYN-001','metadata_state':'partial',
  'metadata':json.dumps({'performers':names or ['みゆき','原名乙'],'field_sources':{'performers':'test'}}),
  'sources':json.dumps([{'name':'test','url':'https://example.test/SYN-001','returned_id':'SYN-001','fields':['performers']}]),
  'available':1,'channel_id':123,'message_id':1,'caption':'#extra'}

class ActorPriority(unittest.TestCase):
 def test_exact_field_boundaries_and_only_explicit_description_exception(self):
  base=actorrow();self.assertEqual(source_performers(base),('みゆき','原名乙'))
  for state in ['matched','partial']:self.assertTrue(source_performers({**base,'metadata_state':state}))
  for edits in [{'identification':'ambiguous'},{'metadata_state':'temporary_error'},{'work_code':'SYN-002'},
                {'identity':'SYN-2'},{'sources':'bad'},{'sources':'{}'},
                {'sources':json.dumps([{'name':'other','returned_id':'SYN-001','fields':['performers']}])},
                {'sources':json.dumps([{'name':'test','returned_id':'SYN-002','fields':['performers']}])},
                {'metadata':json.dumps({'performers':[]})},{'metadata':json.dumps({'performers':'みゆき'})},
                {'metadata':json.dumps({'performers':['みゆき',3]})},{'metadata':'{}'}]:
   with self.subTest(edits=edits):self.assertIsNone(source_performers({**base,**edits}))
  self.assertIsNone(source_performers(actorrow(['18歳スレンダー美女'])))
  self.assertEqual(source_performers(actorrow(['18歳スレンダー美女','あすか','ひなた'])),('あすか','ひなた'))
 def test_group_effective_source_whole_cast_not_TG_union_and_conflict_fallback(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cfg=Config(root,root/'side',(123,),True);ChannelIndex(cfg.db);repo=Repository(cfg)
   (cfg.state/'tag-roles.json').write_text(json.dumps({'actors':['extra'],'categories':{'class':'class'}}));repo.tag_roles.reload()
   row=actorrow();row['metadata']=json.dumps({**json.loads(row['metadata']),'tags':['original'],'studio':'maker'})
   row['caption']='#extra #class';g=NS(messages=[row]);self.assertEqual(repo._project(g)['performers'],('みゆき','原名乙'))
   self.assertEqual(set(repo._project(g)['tags']),{'original','class'});self.assertEqual(repo._project(g)['studio'],('maker',))
   for other in [{**row,'identity':'SYN-2'},actorrow(['different']),{**row,'metadata':'{}'}]:
    g.messages=[row,other];self.assertEqual(repo._project(g)['performers'],('extra',))
   g.messages=[actorrow(['18歳スレンダー美女'])];self.assertEqual(repo._project(g)['performers'],('extra',))
   repo.close()

class PhotoLink(FakeLink):
 def __init__(self,*a):super().__init__(*a);self.photos=[];self.image=picture();self.during=None
 async def photo(self,message,limit):
  self.photos.append((message.id,limit))
  if self.during:await self.during()
  return self.image

class NormalCover(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cfg=Config(self.root,self.root/'side',(123,),True)
  self.owner=ChannelOwner(self.cfg,link_factory=PhotoLink);self.owner.account={'channels':[CHANNEL]};self.owner.state='connected'
  self.calls=[];self.outcome=Outcome(state='not_found',cover_state='not_found')
  def fetch(*a,**kw):self.calls.append((a[0],kw.get('want_cover')));return self.outcome
  self.filler=WorkFiller(self.owner,fetch=fetch,workers=1);self.owner.on_change=self.filler.poke
 async def asyncTearDown(self):await self.filler.stop();self.tmp.cleanup()
 def video(self,mid=1,name='ABP-001.mp4',gid=9007199254740993):
  m=fake_message(mid,name=name,text='',document=mid);m.grouped_id=gid;return m
 def photo(self,mid=10,text='ABP-001',gid=9007199254740993,photo_id=100):
  return NS(id=mid,message=text,grouped_id=gid,document=None,photo=NS(id=photo_id))
 async def post(self,m):self.owner.link.posts[m.id]=m;await self.owner.on_update(123,m,[])
 async def wait(self,predicate):
  for _ in range(300):
   if predicate():return
   await asyncio.sleep(.01)
  self.fail('normal loop did not reach expected state')
 def work(self):
  with self.owner.index.session() as db:return dict(db.execute("SELECT * FROM tg_work WHERE identity='ABP-1'").fetchone())
 async def test_photo_first_history_video_later_normal_job_TG_then_new_source_upgrade(self):
  p=self.photo();self.owner.link.posts[p.id]=p;self.owner._keep(CHANNEL,[p],high_water=10)
  self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
  await self.post(self.video());await self.wait(lambda:self.filler.shelf.has('ABP-1'))
  self.assertEqual(len(self.calls),1);self.assertEqual(self.filler.shelf.rank('ABP-1'),1);self.assertEqual(self.owner.link.photos,[(10,COVER_MAX)])
  old=(self.cfg.covers/cover_name('ABP-1')).read_bytes()
  await self.post(self.video(2,'ABP-001(2).mp4'));await asyncio.sleep(.05);self.assertEqual(len(self.owner.link.photos),1)
  # An already queued normal work job later obtains and validates a catalogue image.
  new=picture((128,64,32));self.outcome=Outcome(state='partial',cover=(new,'https://example.test/ABP-001.png',(320,240)),cover_state='available')
  with self.owner.index.session() as db:db.execute("UPDATE tg_work SET state='pending' WHERE identity='ABP-1'")
  self.filler.poke();await self.wait(lambda:self.filler.shelf.rank('ABP-1')==2)
  self.assertEqual((self.cfg.covers/cover_name('ABP-1')).read_bytes(),new);self.assertNotEqual(old,new);self.assertEqual(len(self.owner.link.photos),1)
 async def test_video_first_photo_after_catalog_finished_falls_back_through_event_queue(self):
  await self.post(self.video());await self.wait(lambda:self.work()['state']=='not_found');self.assertFalse(self.filler.shelf.has('ABP-1'))
  await self.post(self.photo());await self.wait(lambda:self.filler.shelf.has('ABP-1'))
  self.assertEqual(len(self.calls),1);self.assertEqual(len(self.owner.link.photos),1)
 async def test_source_priority_no_TG_fetch_and_same_or_lower_tier_no_replacement(self):
  official=picture((12,34,56));self.outcome=Outcome(state='partial',cover=(official,'https://example.test/ABP-001.png',(320,240)),cover_state='available')
  await self.post(self.photo());await self.post(self.video());await self.wait(lambda:self.filler.shelf.has('ABP-1'))
  self.assertEqual(self.owner.link.photos,[]);path=self.cfg.covers/cover_name('ABP-1');stamp=path.stat().st_mtime_ns
  self.filler.shelf.put('ABP-1',picture(),json.dumps({'kind':'channel_photo'}),(320,240));self.assertEqual(path.read_bytes(),official);self.assertEqual(path.stat().st_mtime_ns,stamp)
 async def test_failed_source_download_keeps_TG_and_original_finite_retry(self):
  await self.post(self.photo());await self.post(self.video());await self.wait(lambda:self.filler.shelf.has('ABP-1'))
  old=(self.cfg.covers/cover_name('ABP-1')).read_bytes()
  await self.wait(lambda:self.work()['state'] not in ('pending','processing')) # let first fake job commit before requeueing
  self.outcome=Outcome(state='partial',cover=(b'invalid','https://example.test/ABP-001.png',(320,240)),cover_state='available')
  with self.owner.index.session() as db:db.execute("UPDATE tg_work SET state='pending',attempts=0 WHERE identity='ABP-1'")
  self.filler.poke();await self.wait(lambda:self.work()['next_retry']>0)
  self.assertEqual((self.cfg.covers/cover_name('ABP-1')).read_bytes(),old);self.assertEqual(self.work()['cover_state'],'installed')
  self.assertEqual(len(self.owner.link.photos),1)
  with self.owner.index.session() as db:db.execute("UPDATE tg_work SET next_retry=? WHERE identity='ABP-1'",(time.time()-1,))
  self.assertIsNotNone(self.filler._next());self.assertIsNone(self.filler._next())
 async def test_candidate_isolation_edit_delete_available_and_nonphoto_invalidation(self):
  # Disable loop start for candidate-only negative checks; still normal event/index code.
  self.owner.on_change=lambda:None
  await self.post(self.photo());await self.post(self.video());self.assertEqual(len(self.owner.index.photo_candidates('ABP-1',[123])),1)
  for p in [self.photo(text='ABP-002'),self.photo(text='ABP-001 ABP-002'),self.photo(gid=2),NS(id=10,message='ABP-001',grouped_id=9007199254740993,document=None)]:
   await self.post(p);self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
  await self.post(self.photo());await self.post(self.video(name='ABP-002.mp4'));self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
  await self.post(self.video());self.owner.index.mark_gone(123,1);self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
  await self.post(self.video());await self.owner.on_update(123,None,[10]);self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
  await self.post(self.photo());await self.owner.on_update(123,None,[1]);self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
  await self.post(self.video());await self.post(self.photo(gid=None));self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123]),[])
 async def test_real_recheck_stale_photo_edit_during_download_and_no_filename_rejected(self):
  self.owner.on_change=lambda:None;await self.post(self.photo());await self.post(self.video());candidate=self.owner.index.photo_candidates('ABP-1',[123])[0]
  self.owner.link.posts[10]=self.photo(photo_id=200)
  self.assertIsNone(await self.owner.cover_photo(candidate,COVER_MAX));self.assertEqual(self.owner.link.photos,[])
  await self.post(self.photo());candidate=self.owner.index.photo_candidates('ABP-1',[123])[0]
  async def edited():await self.post(self.photo(text='ABP-002'))
  self.owner.link.during=edited;self.assertIsNone(await self.owner.cover_photo(candidate,COVER_MAX))
  self.owner.link.during=None;await self.post(self.photo());v=self.video();v.document.attributes=[a for a in v.document.attributes if not hasattr(a,'file_name')];v.message='ABP-001';await self.post(v)
  candidate=self.owner.index.photo_candidates('ABP-1',[123])[0];count=len(self.owner.link.photos)
  self.assertIsNone(await self.owner.cover_photo(candidate,COVER_MAX));self.assertEqual(len(self.owner.link.photos),count)
 async def test_multiwork_album_multisegment_binding_and_persistent_source_rejection_keeps_TG(self):
  self.owner.on_change=lambda:None
  await self.post(self.photo());await self.post(self.video());await self.post(self.video(2,'ABP-001(2).mp4'));await self.post(self.video(3,'ABP-002.mp4'))
  self.assertEqual({x['video_id'] for x in self.owner.index.photo_candidates('ABP-1',[123])},{1})
  self.assertEqual(self.owner.index.photo_candidates('ABP-2',[123]),[]);self.assertEqual(self.owner.index.photo_candidates('ABP-1',[456]),[])
  self.owner.index.mark_gone(123,1);self.assertEqual(self.owner.index.photo_candidates('ABP-1',[123])[0]['video_id'],2)
  self.owner.on_change=self.filler.poke;self.filler.poke();await self.wait(lambda:self.filler.shelf.has('ABP-1'))
  before=(self.cfg.covers/cover_name('ABP-1')).read_bytes();reads=len(self.owner.link.photos)
  await self.wait(lambda:self.work()['state'] not in ('pending','processing')) # cover installation precedes completion of its fake work job
  self.outcome=Outcome(state='partial',cover_state='not_found') # chooser rejected all candidate hosts
  with self.owner.index.session() as db:db.execute("UPDATE tg_work SET state='pending',attempts=0 WHERE identity='ABP-1'")
  self.filler.poke();await self.wait(lambda:self.work()['state']=='partial')
  self.assertEqual((self.cfg.covers/cover_name('ABP-1')).read_bytes(),before);self.assertEqual(len(self.owner.link.photos),reads)
 async def test_MIME_budget_black_exact_and_no_video_photo_download(self):
  self.owner.on_change=lambda:None;await self.post(self.video());shelf=CoverShelf(self.root/'tiny',self.owner.index,budget=4096,files=2)
  with self.assertRaises(ValueError):shelf.put('ABP-1',b'x'*4097,'https://example.test/a',(320,240))
  for blob,size in [(b'notimage',(320,240)),(picture(fmt='GIF'),(320,240)),(picture(),(1,1))]:
   with self.assertRaises((ValueError,OSError)):shelf.put('ABP-1',blob,'https://example.test/a',size)
  self.assertEqual(inspect_thumbnail(picture((0,0,0))),(None,'black'));self.assertTrue(inspect_thumbnail(picture((1,1,1)))[0])
  with self.assertRaises(ValueError):shelf.put('ABP-1',picture((0,0,0)),json.dumps({'kind':'channel_photo'}),(320,240))
  self.assertIsNone(await TgLink({},lambda:None).photo(self.video(),COVER_MAX))

class BoundedLink(unittest.IsolatedAsyncioTestCase):
 async def test_original_link_photo_iterator_limit_and_closed(self):
  data=picture();streams=[]
  class Stream:
   def __init__(self):self.done=False;self.closed=False
   def __aiter__(self):return self
   async def __anext__(self):
    if self.done:raise StopAsyncIteration
    self.done=True;return data
   async def close(self):self.closed=True
  def iterator(*args,**kwargs):s=Stream();streams.append((s,kwargs));return s
  link=TgLink({},lambda:None);link.client=NS(iter_download=iterator)
  photo=types.Photo(id=100,access_hash=1,file_reference=b'',date=datetime.now(timezone.utc),sizes=[types.PhotoSize(type='x',w=320,h=240,size=len(data))],dc_id=1)
  self.assertEqual(await link.photo(NS(photo=photo),COVER_MAX),data);self.assertTrue(streams[0][0].closed);self.assertEqual(streams[0][1]['limit'],1)
  self.assertIsNone(await link.photo(NS(photo=photo),len(data)-1));self.assertEqual(len(streams),1)

class FallbackAPI(unittest.IsolatedAsyncioTestCase):
 async def test_explicit_skip_bypasses_corrupt_formal_then_thumb_or404(self):
  from sefang.app import create_app
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cfg=Config(root,root/'side',(123,),False);p=cfg.secrets_root/'telegram';p.mkdir(parents=True);(p/'account.json').write_text(json.dumps({'channels':[CHANNEL]}))
   idx=ChannelIndex(cfg.db);idx.store(123,[video_from_message(123,fake_message(name='SYN-001.mp4'))]);cfg.covers.mkdir(parents=True)
   (cfg.covers/cover_name('SYN-1')).write_bytes(b'bad formal')
   with idx.session() as db:db.execute("UPDATE tg_work SET cover_file=?,cover_mime='image/png' WHERE identity='SYN-1'",(cover_name('SYN-1'),))
   app=create_app(cfg,link_factory=FakeLink);calls=[];blob=picture()
   async def thumbnail(cid,mid):calls.append((cid,mid));return blob
   app.state.telegram.thumbnail=thumbnail
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
    r=await c.get('/api/videos/123/1/thumbnail');self.assertEqual(r.content,b'bad formal');self.assertEqual(calls,[])
    r=await c.get('/api/videos/123/1/thumbnail?skip_cover=true');self.assertEqual(r.content,blob);self.assertEqual(len(calls),1)
    blob=picture((0,0,0));r=await c.get('/api/videos/123/1/thumbnail?skip_cover=true');self.assertEqual(r.status_code,404);self.assertEqual(r.json()['reason'],'black')
   app.state.repository.close()
if __name__=='__main__':unittest.main()

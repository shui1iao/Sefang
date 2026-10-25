"""Final actor-label fallback, isolated local fixtures; no TG or external IO."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).parent))
from support import fake_message
from test_source_priority import actorrow
from sefang.config import Config
from sefang.repository import Repository,entity_id,AMATEUR
from sefang.avatars import Portraits
from sefang.tg.index import ChannelIndex,video_from_message

class AmateurFallback(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
  self.cfg=Config(root,root/'side',(123,),True)
  self.index=ChannelIndex(self.cfg.db);self.index.ensure_channel(123,'fixture')
  self.repo=Repository(self.cfg)
  (self.cfg.state/'tag-roles.json').write_text(json.dumps({'actors':['real','素人'],'categories':{'素人':'素人'}}))
  self.repo.tag_roles.reload()
 def tearDown(self):self.repo.close();self.tmp.cleanup()
 def add(self,mid,caption=''):
  self.index.store(123,[video_from_message(123,fake_message(mid,name=f'UNQ-{mid:03d}.mp4',document=mid,text=caption))])
 def test_source_and_TG_whole_field_placeholder_priority(self):
  def projected(names,caption='#real #素人'):
   row=actorrow(names);row['caption']=caption
   return self.repo._project(NS(messages=[row]))['performers']
  self.assertEqual(projected(['みゆき','原名乙']),('みゆき','原名乙'))
  self.assertEqual(projected(['素人','みゆき']),('みゆき',))
  self.assertEqual(projected(['素人']),('real',))
  self.assertEqual(projected(['18歳スレンダー美女']),('real',))
  self.assertEqual(projected(['素人'],''),('素人',))
  self.assertEqual(projected(['18歳スレンダー美女'],''),('素人',))
  row=actorrow();row.update(metadata='{}',caption='#素人 #real')
  self.assertEqual(self.repo._project(NS(messages=[row]))['performers'],('real',))
  row['caption']='';self.assertEqual(self.repo._project(NS(messages=[row]))['performers'],('素人',))
 def test_refresh_directory_filter_search_detail_related_and_kind(self):
  self.add(1,'#素人');self.add(2);self.add(3,'#real')
  self.repo.sync_entities();ident=entity_id('actors',AMATEUR)
  self.assertEqual(self.repo.entity('actors',ident)['count'],2)
  self.assertEqual(self.repo.videos(actor=ident)['total'],2)
  self.assertEqual(self.repo.videos(q=AMATEUR)['total'],2)
  self.assertNotEqual(ident,entity_id('categories',AMATEUR))
  self.assertEqual(self.repo.entity('categories',entity_id('categories',AMATEUR))['count'],1)
  self.assertEqual([e['name'] for e in self.repo.detail(123,1)['entities']['actors']],[AMATEUR])
  self.assertTrue(all('同演员' not in e['related_reason'] for e in self.repo.related(123,1)['items']))
  with self.index.session() as db:db.execute("UPDATE tg_video SET caption='#素人 #real' WHERE message_id=1")
  self.assertEqual([e['name'] for e in self.repo.detail(123,1)['entities']['actors']],['real'])
  self.assertEqual(self.repo.entity('actors',ident)['count'],1)
  self.assertEqual(self.repo.videos(q=AMATEUR)['total'],1)
  with self.index.session() as db:db.execute("UPDATE tg_video SET caption='#real' WHERE message_id=2")
  self.assertIsNone(self.repo.entity('actors',ident))
  self.assertEqual(self.repo.videos(actor=ident)['total'],0)
  self.assertEqual(self.repo.videos(q=AMATEUR)['total'],0)
 def test_general_search_preserves_real_actor_title_hit(self):
  self.add(1);self.add(2,'#real')
  with self.index.session() as db:db.execute("UPDATE tg_video SET title='素人 title fixture' WHERE message_id=2")
  ident=entity_id('actors',AMATEUR)
  self.assertEqual(self.repo.videos(actor=ident)['total'],1)
  self.assertEqual(self.repo.videos(q=AMATEUR)['total'],2)
  with self.index.session() as db:db.execute("UPDATE tg_video SET caption='#real' WHERE message_id=1")
  self.assertEqual(self.repo.videos(actor=ident)['total'],0)
  self.assertEqual(self.repo.videos(q=AMATEUR)['total'],1)
 def test_no_placeholder_identity_or_metadata_writes(self):
  self.add(1)
  raw=json.dumps({'performers':['素人'],'tags':['素人']})
  with self.index.session() as db:db.execute('UPDATE tg_work SET metadata=?',(raw,))
  self.repo.sync_entities();ident=entity_id('actors',AMATEUR)
  with self.repo.local() as db:
   self.assertEqual(db.execute('SELECT count(*) FROM relation WHERE entity_id=?',(ident,)).fetchone()[0],0)
   self.assertGreater(db.execute('SELECT count(*) FROM relation WHERE entity_id=?',(entity_id('categories',AMATEUR),)).fetchone()[0],0)
  def no_web():raise AssertionError('placeholder must not instantiate external client')
  portraits=Portraits(self.repo,web_factory=no_web)
  self.assertEqual(portraits.process({'id':ident,'name':AMATEUR}),'not_applicable')
  with self.repo.local() as db:
   row=db.execute('SELECT avatar_state,avatar_file,external_id FROM entity WHERE id=?',(ident,)).fetchone()
   self.assertEqual(tuple(row),('not_applicable','',''))
  with self.repo.read() as db:self.assertEqual(db.execute('SELECT metadata FROM tg_work').fetchone()[0],raw)

if __name__=='__main__':unittest.main()

"""Only album-source inheritance. Synthetic messages, no Telegram connection or media."""
import asyncio,json,tempfile,unittest,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parent))
from support import fake_message,FakeLink
from sefang.config import Config
from sefang.tg.index import ChannelIndex,video_from_message,set_album,VIDEO_COLUMNS
from sefang.tg.owner import ChannelOwner
from sefang.repository import Repository,entity_id

GID=9007199254740993
class AlbumTagsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=Config(self.root,self.root/'side',(123,456),True)
  self.config.state.mkdir();(self.config.state/'tag-roles.json').write_text(json.dumps({'categories':{'地区甲':'地区甲','独立类':'独立类'},'actors':['creator_one']}))
  self.index=ChannelIndex(self.config.db);self.repo=Repository(self.config)
 def tearDown(self):self.repo.close();self.tmp.cleanup()
 def message(self,mid,caption='',gid=GID,name=None,doc=None,seconds=60):
  m=fake_message(mid,name=name or f'未识别片{mid}.mp4',text=caption,document=doc or mid,seconds=seconds);m.grouped_id=gid;return m
 def add(self,mid,caption='',gid=GID,cid=123,**kwargs):
  self.index.store(cid,[video_from_message(cid,self.message(mid,caption,gid,**kwargs))])
 def count(self):
  e=self.repo.entity('categories',entity_id('categories','地区甲'));return e['count'] if e else 0
 def test_two_singles_inherit_only_explicit_tags_with_channel_album_isolation(self):
  self.add(1,'#地区甲 #creator_one #unknown_handle #SYN-09');self.add(2)
  self.add(3,gid=GID+1);self.add(4,cid=456);self.add(5,gid=None);self.add(6,'#独立类',gid=None)
  self.assertEqual(self.count(),2);self.assertEqual(self.repo.videos()['total'],6)
  first,second=[self.repo.detail(123,i) for i in [1,2]];self.assertNotEqual(first['group']['id'],second['group']['id'])
  self.assertEqual(second['caption'],'');self.assertEqual(first['entities'],second['entities'])
  self.assertEqual([x['name'] for x in second['entities']['actors']],['creator_one']);self.assertEqual([x['name'] for x in second['entities']['categories']],['地区甲'])
  for cid,mid in [(123,3),(456,4),(123,5)]:self.assertEqual(self.repo.detail(cid,mid)['entities']['categories'],[])
  cat=entity_id('categories','地区甲');actor=entity_id('actors','creator_one');result=self.repo.videos(category=cat,actor=actor,limit=1)
  self.assertEqual((result['total'],result['pages']),(2,2));self.assertNotEqual(result['items'][0]['id'],self.repo.videos(category=cat,actor=actor,page=2,limit=1)['items'][0]['id'])
  self.assertEqual(self.repo.videos(q='creator_one')['total'],2);self.assertEqual(self.repo.videos(q='地区甲')['total'],0)
  related=self.repo.related(123,1)['items'][0];self.assertEqual(related['message_id'],2);self.assertIn('同演员',related['related_reason'])
  with self.index.session() as db:
   self.assertEqual(db.execute('SELECT grouped_id,typeof(grouped_id) FROM tg_message_album WHERE channel_id=123 AND message_id=2').fetchone()[:],(str(GID),'text'))
   self.assertEqual(tuple(x['name'] for x in db.execute('PRAGMA table_info(tg_video)')),VIDEO_COLUMNS)
 def test_edit_availability_delete_and_relationship_only_changes_remove_stale_membership(self):
  self.add(1,'#地区甲 #creator_one');self.add(2);self.assertEqual(self.count(),2)
  generation=self.repo.snapshot().generation
  self.add(2,gid=GID+1);self.assertEqual(self.count(),1);self.assertEqual(self.repo.snapshot().generation,generation) # relationship-only commit
  self.add(2);self.assertEqual(self.count(),2)
  self.add(1,'');self.assertEqual(self.count(),0)
  self.add(1,'#地区甲 #creator_one');self.assertEqual(self.count(),2)
  self.index.mark_gone(123,1);self.assertEqual(self.count(),0);self.assertEqual([x['name'] for x in self.repo.detail(123,2)['entities']['actors']],['素人'])
  self.add(1,'#地区甲 #creator_one');self.assertEqual(self.count(),2)
  with self.index.session() as db:db.execute('DELETE FROM tg_video WHERE message_id=1 AND channel_id=123')
  self.assertEqual(self.count(),0)
  with self.repo.local() as db:self.assertEqual(db.execute('SELECT count(*) FROM group_entity WHERE entity_id=?',(entity_id('categories','地区甲'),)).fetchone()[0],0)
 def test_nonrepresentative_alias_inherits_union_once_and_keeps_metadata_id_avatar(self):
  self.add(1,gid=None,name='SYN-001(1).mp4',doc=11)
  self.add(2,gid=None,name='SYN-001(2).mp4',doc=12,seconds=61)
  self.add(3,name='SYN-001(1).mp4',doc=11) # album relation only on an alias
  self.add(10,'#地区甲 #creator_one')
  with self.index.session() as db:db.execute("UPDATE tg_work SET metadata=? WHERE identity='SYN-1'",(json.dumps({'tags':['原分类'],'performers':['原演员'],'studio':'原厂牌'}),))
  self.repo.sync_entities();ident=entity_id('actors','creator_one')
  with self.repo.local() as db:db.execute("UPDATE entity SET avatar_file='kept.jpg',external_id='verified' WHERE id=?",(ident,))
  self.assertEqual(self.count(),2);g=self.repo.snapshot().by_message[(123,1)];self.assertEqual(len(g.parts),2);self.assertEqual(len(g.keys),3)
  for mid in [1,2,3]:
   detail=self.repo.detail(123,mid);self.assertEqual({x['name'] for x in detail['entities']['categories']},{'原分类','地区甲'});self.assertEqual(detail['entities'],self.repo.card(g)['entities'])
  result=self.repo.videos(category=entity_id('categories','地区甲'),actor=ident,studio=entity_id('studios','原厂牌'));self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['part_count'],2)
  self.add(10,'');self.assertEqual(self.count(),0)
  with self.repo.local() as db:self.assertEqual(db.execute('SELECT id,avatar_file,external_id FROM entity WHERE id=?',(ident,)).fetchone()[:],(ident,'kept.jpg','verified'))
 def test_normal_owner_history_edit_and_delete_keep_exact_source_relationship(self):
  owner=ChannelOwner(self.config,link_factory=FakeLink);owner.account={'channels':[{'id':123,'title':'合成'}]}
  owner._keep(owner.channels()[0],[self.message(1,'#地区甲'),self.message(2)],high_water=2)
  self.assertEqual(self.count(),2)
  asyncio.run(owner.on_update(123,self.message(2,gid=None),[]));self.assertEqual(self.count(),1)
  asyncio.run(owner.on_update(123,self.message(2),[]));self.assertEqual(self.count(),2)
  asyncio.run(owner.on_update(123,None,[1]));self.assertEqual(self.count(),0)
  with self.index.session() as db:self.assertIsNone(db.execute('SELECT grouped_id FROM tg_message_album WHERE message_id=1 AND channel_id=123').fetchone())

 def photo(self,mid=30,text='#地区甲 #creator_one',gid=GID):
  return SimpleNamespace(id=mid,message=text,grouped_id=gid,document=None)
 def test_photo_caption_is_current_source_not_video_or_group(self):
  owner=ChannelOwner(self.config,link_factory=FakeLink);owner.account={'channels':[{'id':123,'title':'合成'},{'id':456,'title':'隔离'}]}
  owner._keep(owner.channels()[0],[self.photo(),self.message(1),self.message(2)],high_water=30)
  self.add(3,gid=GID+1);self.add(4,cid=456);self.add(5,gid=None)
  self.assertEqual(self.count(),2);self.assertEqual(self.repo.videos()['total'],5)
  for mid in [1,2]:self.assertEqual([e['name'] for e in self.repo.detail(123,mid)['entities']['actors']],['creator_one']);self.assertEqual(self.repo.detail(123,mid)['caption'],'')
  for cid,mid in [(123,3),(456,4),(123,5)]:self.assertEqual(self.repo.detail(cid,mid)['entities']['categories'],[])
  self.assertIsNone(self.repo.detail(123,30))
  with self.index.session() as db:self.assertIsNone(db.execute('SELECT 1 FROM tg_video WHERE message_id=30').fetchone())
  asyncio.run(owner.on_update(123,self.photo(text=''),[]));self.assertEqual(self.count(),0)
  asyncio.run(owner.on_update(123,self.photo(),[]));self.assertEqual(self.count(),2)
  asyncio.run(owner.on_update(123,self.photo(gid=GID+1),[]));self.assertEqual(self.count(),1)
  asyncio.run(owner.on_update(123,self.photo(gid=None),[]));self.assertEqual(self.count(),0)
  asyncio.run(owner.on_update(123,self.photo(),[]));self.assertEqual(self.count(),2)
  asyncio.run(owner.on_update(123,None,[30]));self.assertEqual(self.count(),0)
  with self.index.session() as db:self.assertIsNone(db.execute('SELECT 1 FROM tg_album_caption WHERE message_id=30').fetchone())
 def test_photo_source_respects_video_availability_alias_union_and_conversion(self):
  owner=ChannelOwner(self.config,link_factory=FakeLink);owner.account={'channels':[{'id':123,'title':'合成'}]}
  self.add(1,gid=None,name='SYN-001(1).mp4',doc=11);self.add(2,gid=None,name='SYN-001(2).mp4',doc=12,seconds=61)
  self.add(3,name='SYN-001(1).mp4',doc=11)
  owner._keep(owner.channels()[0],[self.photo()],high_water=30)
  self.assertEqual(self.count(),1);self.assertEqual(self.repo.videos()['total'],1);self.assertEqual(self.repo.detail(123,1)['group']['part_count'],2)
  for mid in [1,2,3]:self.assertEqual(self.repo.detail(123,mid)['entities'],self.repo.detail(123,1)['entities'])
  self.index.mark_gone(123,3);self.assertEqual(self.count(),0)
  self.add(3,name='SYN-001(1).mp4',doc=11);self.assertEqual(self.count(),1)
  asyncio.run(owner.on_update(123,self.message(30,gid=None),[]));self.assertEqual(self.count(),0)
  with self.index.session() as db:self.assertIsNone(db.execute('SELECT 1 FROM tg_album_caption WHERE message_id=30').fetchone())

if __name__=='__main__':unittest.main()

import unittest,tempfile,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from support import fake_message
from sefang.config import Config
from sefang.repository import Repository,entity_id
from sefang.tg.index import ChannelIndex,video_from_message
class ActorAliasesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=Config(self.root,self.root/'side',(123,),True);self.config.state.mkdir();self.policy=self.config.state/'actor-aliases.json';self.policy.write_text(json.dumps({'version':1,'groups':[{'canonical':'甲日文','aliases':['甲中文','RomanName'],'id':entity_id('actors','甲日文')}]}));(self.config.state/'tag-roles.json').write_text(json.dumps({'categories':{'类甲':'类甲'},'actors':['甲中文','乙演员']}));self.index=ChannelIndex(self.config.db);self.repo=Repository(self.config)
  for mid,caption in [(1,'#甲中文 #乙演员 #类甲'),(2,'#RomanName')]:
   msg=fake_message(mid,name=f'合成无番号{mid}.mp4',text=caption,document=mid);msg.grouped_id=None;self.index.store(123,[video_from_message(123,msg)])
 def tearDown(self):self.repo.close();self.tmp.cleanup()
 def test_union_old_id_search_details_and_avatar_are_consistent(self):
  stable=entity_id('actors','甲日文');self.repo.refresh()
  with self.repo.local() as d:d.execute('UPDATE entity SET avatar_state=?,avatar_file=?,external_id=? WHERE id=?',('ready',stable+'.img','verified-001',stable))
  avatar=self.config.state/'avatars';avatar.mkdir();(avatar/(stable+'.img')).write_bytes(b'synthetic-local-marker')
  for alias in ['甲日文','甲中文','RomanName']:
   self.assertEqual(self.repo.entity('actors',entity_id('actors',alias))['id'],stable);self.assertEqual(self.repo.videos(actor=entity_id('actors',alias))['total'],2);self.assertEqual(self.repo.videos(q=alias)['total'],2);self.assertEqual(self.repo.entities('actors',q=alias)['total'],1)
  self.assertEqual([e['name'] for e in self.repo.detail(123,1)['entities']['actors']],['甲日文','乙演员']);self.assertEqual(self.repo.entity('actors',stable)['count'],2);self.assertIn('同演员',self.repo.related(123,1)['items'][0]['related_reason'])
  with self.repo.local() as d:self.assertEqual(tuple(d.execute('SELECT name,external_id,avatar_file FROM entity WHERE id=?',(stable,)).fetchone()),('甲日文','verified-001',stable+'.img'))
 def test_refresh_policy_removal_does_not_create_persistent_identity_or_delete_rows(self):
  self.repo.refresh();stable=entity_id('actors','甲日文');self.policy.write_text(json.dumps({'version':1,'groups':[]}));self.repo.refresh();self.assertEqual(self.repo.videos(q='甲中文')['total'],1);self.assertEqual(self.repo.videos(q='RomanName')['total'],0)
  with self.repo.local() as d:self.assertIsNotNone(d.execute('SELECT id FROM entity WHERE id=?',(stable,)).fetchone())
if __name__=='__main__':unittest.main()

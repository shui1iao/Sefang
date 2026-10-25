"""Only explicit tag parsing and group-level union/filter/refresh. All names/captions are synthetic."""
import json,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
from support import fake_message
from sefang.tg.index import ChannelIndex,video_from_message
from sefang.config import Config
from sefang.caption_tags import hashtags,Roles
from sefang.repository import Repository,entity_id
from sefang.avatars import Portraits

CATEGORIES=['韩国','主播','国产','探花','糖心vlog','撸铁美女']
def rules(path,actors=('创作者甲','creator_one','creator_two','서윤')):
 data={'categories':{**{x:x for x in CATEGORIES},'韓國':'韩国'},'actors':list(actors)}
 path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False));return data

class ParserTests(unittest.TestCase):
 def test_unicode_boundaries_codes_html_and_unclassified(self):
  body='普通韩国 不带标签 word#不是 http://x/#不是 <a title="#属性">＃韩国</a> #韓國#主播 #creator_one #서윤 #creator_one #SYN-09 ＃ＳＹＮ-００７ <script>#隐藏</script> #'+('长'*129)+' #未知'
  tokens=hashtags(body);self.assertEqual(tokens,('韩国','韓國','主播','creator_one','서윤','未知'))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'roles.json';rules(path);r=Roles(path);r.reload();self.assertEqual(r.project(body),{'tags':['韩国','主播'],'performers':['creator_one','서윤']})
   self.assertEqual(r.project('#CREATOR_ONE #someone_new #SYN-09'),{'tags':[],'performers':[]})
   self.assertEqual(r.project(' '.join('#'+x for x in CATEGORIES))['tags'],CATEGORIES)

class ProjectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=Config(self.root,self.root/'side',(123,),True);rules(self.config.state/'tag-roles.json')
  self.index=ChannelIndex(self.config.db);self.index.ensure_channel(123,'合成频道')
  self.add(1,'SYN-001(1).mp4',11,'')
  self.add(2,'SYN-001(2).mp4',12,'#主播 #创作者甲')
  self.add(3,'SYN-001(1).mp4',11,'#韓國 #creator_one')  # alias alone carries these tags
  self.add(10,'未知甲.mp4',20,'#韩国 #主播 #creator_two arbitrarysecret')
  self.add(11,'未知乙.mp4',21,'#韩国 #creator_two')
  with self.index.session() as db:db.execute("UPDATE tg_work SET metadata=? WHERE identity='SYN-1'",(json.dumps({'title':'合成片名','performers':['原演员'],'tags':['原分类'],'studio':'原厂牌'}),))
  self.repo=Repository(self.config);self.repo.sync_entities()
 def tearDown(self):self.repo.close();self.tmp.cleanup()
 def add(self,mid,name,doc,caption):
  self.index.store(123,[video_from_message(123,fake_message(mid,name=name,document=doc,seconds=61 if mid==2 else 60,text=caption))])
 def ident(self,kind,name):return entity_id(kind,name)
 def test_group_alias_tag_only_union_counts_filters_search_and_related(self):
  repo=self.repo;snap=repo.snapshot();g=snap.by_message[(123,1)];self.assertIs(snap.by_message[(123,3)],g);self.assertEqual(len(g.parts),2)
  for mid in [1,2,3]:
   d=repo.detail(123,mid);self.assertEqual({x['name'] for x in d['entities']['categories']},{'原分类','韩国','主播'});self.assertEqual({x['name'] for x in d['entities']['actors']},{'创作者甲','creator_one'});self.assertEqual(len(d['group']['parts']),2)
  self.assertEqual(repo.card(g)['entities'],repo.detail(123,3)['entities']);self.assertEqual(repo.detail(123,3)['group']['parts'][0]['stream'],'/api/videos/123/3/stream')
  self.assertEqual(repo.entity('categories',self.ident('categories','韩国'))['count'],3);self.assertEqual(repo.entity('categories',self.ident('categories','主播'))['count'],2)
  result=repo.videos(category=self.ident('categories','韩国'),actor=self.ident('actors','creator_one'),studio=self.ident('studios','原厂牌'));self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['part_count'],2)
  result=repo.videos(actor=self.ident('actors','creator_two'),category=self.ident('categories','韩国'),limit=1);self.assertEqual((result['total'],result['pages']),(2,2));self.assertNotEqual(result['items'][0]['id'],repo.videos(actor=self.ident('actors','creator_two'),page=2,limit=1)['items'][0]['id'])
  self.assertEqual(repo.videos(q='creator_two')['total'],2);self.assertEqual(repo.videos(q='韩国')['total'],0);self.assertEqual(repo.videos(q='arbitrarysecret')['total'],0);self.assertEqual(repo.videos(q='SYN-001')['total'],1)
  related=repo.related(123,10);self.assertNotIn('123:10',[x['id'] for x in related['items']]);self.assertIn('同演员',related['items'][0]['related_reason'])
  with repo.local() as db:self.assertEqual(db.execute('SELECT count(*) FROM group_entity WHERE entity_id=?',(self.ident('categories','韩国'),)).fetchone()[0],3)
 def test_existing_id_avatar_and_no_tag_only_external_lookup(self):
  repo=self.repo;ident=self.ident('actors','creator_two')
  with repo.local() as db:db.execute("UPDATE entity SET avatar_file='existing.jpg',avatar_state='ready',external_id='verified' WHERE id=?",(ident,))
  repo.sync_entities()
  with repo.local() as db:r=dict(db.execute('SELECT * FROM entity WHERE id=?',(ident,)).fetchone())
  self.assertEqual((r['id'],r['avatar_file'],r['external_id']),(ident,'existing.jpg','verified'))
  class NoNetwork:
   def close(self):pass
   def fetch(self,*args,**kwargs):raise AssertionError('tag-only must not request an external source')
  portraits=Portraits(repo,web_factory=NoNetwork);self.assertEqual(portraits._works('creator_one'),[]);self.assertEqual(portraits.process({'id':self.ident('actors','creator_one'),'name':'creator_one'}),'unavailable')
 def test_caption_edit_delete_availability_and_rule_reload(self):
  repo=self.repo;ident=self.ident('actors','creator_one');self.assertIsNotNone(repo.entity('actors',ident))
  with self.index.session() as db:db.execute("UPDATE tg_video SET caption='' WHERE message_id=3")
  self.assertIsNone(repo.entity('actors',ident));self.assertNotIn('creator_one',repo.effective(repo.snapshot().by_message[(123,1)])['performers'])
  with repo.local() as db:self.assertEqual(db.execute('SELECT video_count FROM entity WHERE id=?',(ident,)).fetchone()[0],0);self.assertEqual(db.execute('SELECT count(*) FROM group_entity WHERE entity_id=?',(ident,)).fetchone()[0],0)
  with self.index.session() as db:db.execute('UPDATE tg_video SET available=0 WHERE message_id=10')
  self.assertEqual(repo.entity('categories',self.ident('categories','主播'))['count'],1)
  with self.index.session() as db:db.execute('DELETE FROM tg_video WHERE message_id=2')
  self.assertIsNone(repo.entity('actors',self.ident('actors','创作者甲')))
  generation=repo.snapshot().generation;rules(repo.tag_roles.path,actors=('creator_one',))
  self.assertEqual(repo.videos(q='creator_two')['total'],0);self.assertEqual(repo.snapshot().generation,generation)
  with repo.local() as db:self.assertIsNotNone(db.execute('SELECT id FROM entity WHERE id=?',(self.ident('actors','creator_two'),)).fetchone())

if __name__=='__main__':unittest.main()

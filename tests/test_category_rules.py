"""Approved category policy and projection; isolated fixtures, no network/real state."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).parent))
from support import fake_message
from sefang.config import Config
from sefang.repository import Repository,entity_id
from sefang.category_rules import CategoryRules
from sefang.category_data import MERGES,TRANSLATIONS,HIDDEN
from sefang.category_originals import ORIGINAL_DISPLAYS
from sefang.tg.index import ChannelIndex,video_from_message

class CategoryPolicy(unittest.TestCase):
 def test_original_display_table_is_real_member_and_never_machine_fallback(self):
  rules=CategoryRules();self.assertEqual(len(ORIGINAL_DISPLAYS),82)
  for group in MERGES:
   self.assertIn(ORIGINAL_DISPLAYS[group['canonical']],group['members'])
   for raw in group['members']:
    d=rules.display(raw);self.assertEqual(d['display_name'],ORIGINAL_DISPLAYS[group['canonical']]);self.assertEqual(d['name_original'],d['display_name']);self.assertIsNone(d['name_zh'])
  for raw in ['大生','ぶっかけ','素人','BIGセール','unapproved']:
   self.assertEqual(rules.display(raw)['display_name'],raw)
  for canonical,raw in [('姐姐','お姉さん'),('主观视角','主観'),('乳交','パイズリ'),('颜射','顔射')]:self.assertEqual(rules.display(canonical)['display_name'],raw)
 def test_all_explicit_merges_ids_and_no_inference(self):
  rules=CategoryRules();self.assertEqual(len(MERGES),82)
  for group in MERGES:
   c=group['canonical'];self.assertIn(c,group['members'])
   for raw in group['members']:
    self.assertEqual(rules.canonical(raw),c);self.assertTrue(rules.matches(c,raw))
   self.assertEqual(rules.project(group['members']),(c,))
  for raw in ['ぶっかけ','女子校生','大生','園','無','素人','never-approved']:
   self.assertEqual(rules.canonical(raw),raw)
  self.assertNotEqual(rules.canonical('第一人称摄影'),rules.canonical('主観'))
  self.assertNotEqual(rules.canonical('お姉さん'),rules.canonical('姉・妹'))
 def test_frozen_tokens_3P_and_retirement(self):
  rules=CategoryRules();self.assertEqual(len(rules.policy['merge_groups']),83);self.assertEqual(len(rules.tokens),306);self.assertEqual(len(rules.retired),128)
  for row in rules.policy['categories']:
   self.assertEqual(rules.caption_categories('#'+row['hashtag_token']),(row['canonical_name'],))
   for raw in row['raw_members']:self.assertEqual(rules.canonical(raw),row['canonical_name'])
  self.assertEqual(rules.project(['3P、4P','3P・4P','3P_4P']),('3P・4P',))
  self.assertEqual(rules.caption_categories('#ABC-123 #unknown #未批准'),())
 def test_all_translations_and_exact_hidden_scope(self):
  rules=CategoryRules();self.assertEqual(len(TRANSLATIONS),83);self.assertEqual(len(HIDDEN),21)
  for raw,zh in TRANSLATIONS.items():
   self.assertEqual(rules.display(raw)['display_name'],ORIGINAL_DISPLAYS.get(rules.canonical(raw),raw));self.assertEqual(rules.display(raw)['name_translation'],{'state':'original','method':'original'});self.assertIn(zh,rules.aliases(raw))
  self.assertEqual(rules.project(HIDDEN),())
  for raw in ['サンプル動画','特典あり','特典アリ','高画質特典','大生','素人']:
   self.assertTrue(rules.project([raw]));self.assertNotIn(raw,rules.drop)

class CategoryProjection(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);self.cfg=Config(root,root/'side',(123,),True);self.index=ChannelIndex(self.cfg.db);self.repo=Repository(self.cfg)
 def tearDown(self):self.repo.close();self.tmp.cleanup()
 def add(self,mid,tags):
  self.index.store(123,[video_from_message(123,fake_message(mid,name=f'UNQ-{mid:03d}.mp4',document=mid))])
  with self.index.session() as db:db.execute('UPDATE tg_work SET metadata=? WHERE identity=(SELECT identity FROM tg_identification WHERE message_id=?)',(json.dumps({'tags':tags}),mid))
 def test_public_directory_alias_filter_hidden_legacy_and_details(self):
  self.add(1,['パイズリ','乳交','BIGセール']);self.add(2,['乳交','BIGセール']);self.add(3,['大生','サンプル動画'])
  old=entity_id('categories','パイズリ');canonical=entity_id('categories','乳交');hidden=entity_id('categories','BIGセール')
  self.assertIsNone(self.repo.entity('categories',old));self.assertEqual(self.repo.entity('categories',canonical)['count'],2)
  self.assertEqual(self.repo.videos(category=old)['total'],0);self.assertEqual(self.repo.videos(category=canonical)['total'],2)
  self.assertIsNone(self.repo.entity('categories',hidden));self.assertEqual(self.repo.videos(category=hidden)['total'],0)
  self.assertNotIn(hidden,{x['id'] for x in self.repo.entities('categories')['items']})
  self.assertEqual([r['name'] for r in self.repo.detail(123,1)['entities']['categories']],['乳交'])
  self.assertEqual(self.repo.entities('categories',q='パイズリ')['items'][0]['id'],canonical)
  self.assertEqual(self.repo.entities('categories',q='他妈的奶')['items'][0]['id'],canonical)
  self.assertEqual(self.repo.videos(q='乳交')['total'],0) # no extra category OR in homepage search
  self.assertEqual(self.repo.videos(category=hidden,q='unmatched')['total'],0)
  with self.repo.read() as db:self.assertIn('BIGセール',json.loads(db.execute('SELECT metadata FROM tg_work LIMIT 1').fetchone()[0])['tags'])
 def test_frozen_caption_token_tg_only_and_canonical_source_relations(self):
  self.add(1,['顔射','BIGセール','3P、4P']);self.add(2,[])
  with self.index.session() as db:db.execute('UPDATE tg_video SET caption=? WHERE message_id=2',('#寝取り_寝取られ_NTR #パイズリ #3P_4P #ABC-123 #素人 #unknown',))
  self.repo.sync_entities();detail=self.repo.detail(123,2)
  self.assertEqual({x['name'] for x in detail['entities']['categories']},{'NTR','乳交','3P・4P','素人'})
  self.assertEqual([x['name'] for x in detail['entities']['actors']],['素人'])
  with self.repo.local() as db:
   for ident in self.repo.category_rules.retired:
    self.assertIsNone(db.execute('SELECT * FROM relation WHERE entity_id=?',(ident,)).fetchone());self.assertIsNone(db.execute('SELECT * FROM group_entity WHERE entity_id=?',(ident,)).fetchone());self.assertIsNone(db.execute('SELECT * FROM entity WHERE id=?',(ident,)).fetchone())
  self.assertNotIn('_hidden_tags',self.repo.effective(self.repo.snapshot().groups[0]))
 def test_approved_display_precedes_stale_translation_no_cache_write(self):
  self.repo.localized.project=lambda *args:{'display':'bad cached label','zh':'bad cached label','state':'machine','method':'machine'}
  self.assertEqual(self.repo.name_display('categories','パイズリ')['display_name'],'パイズリ')
  self.assertEqual(self.repo.name_display('categories','unapproved')['display_name'],'unapproved')
  self.assertEqual(self.repo.name_display('categories','unapproved')['aliases'],['bad cached label'])
  self.assertEqual(self.repo.name_display('series','パイズリ')['display_name'],'bad cached label')
 def test_legacy_cached_chinese_is_search_only_not_visible_or_a_synonym(self):
  self.add(1,['ランジェリー']);self.add(2,['その他フェチ'])
  self.repo.localized.project=lambda kind,name,tokens:{'display':'内衣' if name=='ランジェリー' else '其他恋物癖','zh':'内衣' if name=='ランジェリー' else '其他恋物癖','state':'canonical','method':'dictionary'}
  for raw,q in [('ランジェリー','内衣'),('その他フェチ','其他恋物癖')]:
   row=self.repo.entity('categories',entity_id('categories',raw))
   self.assertEqual(row['display_name'],raw);self.assertEqual(row['name_original'],raw);self.assertIsNone(row['name_zh']);self.assertEqual(row['name_translation'],{'state':'original','method':'original'});self.assertIn(q,row['aliases']);self.assertEqual(self.repo.category_rules.canonical(raw),raw)
   self.assertEqual(self.repo.entities('categories',q=q)['items'][0]['id'],row['id'])
  self.assertEqual(self.repo.videos(q='其他恋物癖')['total'],0)
 def test_hidden_tags_do_not_give_related_category_score(self):
  self.add(1,['BIGセール']);self.add(2,['BIGセール']);self.add(3,['unrelated'])
  result=self.repo.related(123,1);self.assertTrue(all('同分类' not in x['related_reason'] for x in result['items']))
  self.assertEqual(self.repo.videos(category=entity_id('categories','BIGセール'))['total'],0)
 def test_new_normal_projection_uses_rules_and_actor_kind_independent(self):
  self.add(1,['顔射','颜射','BIGセール','素人','mystery'])
  self.assertEqual({x['name'] for x in self.repo.detail(123,1)['entities']['categories']},{'颜射','素人','mystery'})
  self.assertEqual(self.repo.entity('actors',entity_id('actors','素人'))['count'],1)
  self.add(2,['お姉さん']);self.assertEqual(self.repo.entity('categories',entity_id('categories','姐姐'))['count'],1)

if __name__=='__main__':unittest.main()

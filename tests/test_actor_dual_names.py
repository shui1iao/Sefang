import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from sefang.actor_aliases import ActorAliases,actor_id
class DualNames(unittest.TestCase):
 def setUp(self):
  # Entirely synthetic identities; no installation actor policy is shipped.
  self.names=patch('sefang.actor_aliases.trusted_chinese',side_effect=lambda n:{'架空七緒':'架空七绪','架空夕子':'架空夕子','架空もえ':'架空萌'}.get(n,''));self.names.start();self.addCleanup(self.names.stop)
 def test_known_simplified_and_same_identity(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'policy.json';p.write_text(json.dumps({'version':1,'groups':[{'canonical':'架空七緒','aliases':['架空七绪'],'id':actor_id('架空七緒'),'name_zh':'架空七緒'}]}));a=ActorAliases(p);a.reload();self.assertEqual(a.display('架空七緒')['display_name'],'架空七緒 / 架空七绪');self.assertEqual(a.query_name('架空七绪'),'架空七緒');self.assertEqual(a.resolve_id(actor_id('架空七绪')),actor_id('架空七緒'));self.assertEqual(a.caption_names('#架空七緒 #架空七绪'),('架空七緒',))
 def test_original_fallback_same_name_and_no_guessed_chinese(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'policy.json';p.write_text(json.dumps({'version':1,'groups':[{'canonical':'架空夕子','aliases':['ExampleActor'],'id':actor_id('架空夕子'),'name_zh':'架空夕子'}]}));a=ActorAliases(p);a.reload();self.assertEqual(a.display('架空夕子')['display_name'],'架空夕子');self.assertIsNone(a.display('架空夕子')['name_zh']);self.assertEqual(a.display('架空すず')['display_name'],'架空すず');self.assertEqual(a.display('原中文主播')['display_name'],'原中文主播')
 def test_invalid_half_kana_and_refresh(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'policy.json';group={'canonical':'架空もえ','aliases':['架空萌'],'id':actor_id('架空もえ')};p.write_text(json.dumps({'version':1,'groups':[group]}));a=ActorAliases(p);a.reload();self.assertIsNone(a.display('架空もえ')['name_zh']);group['name_zh']='架空萌';p.write_text(json.dumps({'version':1,'groups':[group]}));self.assertTrue(a.reload());self.assertEqual(a.display('架空もえ')['display_name'],'架空もえ / 架空萌');group['name_zh']='架空もえ';p.write_text(json.dumps({'version':1,'groups':[group]}));self.assertRaises(ValueError,a.reload)
if __name__=='__main__':unittest.main()

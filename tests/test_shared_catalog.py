import unittest,tempfile,json
from pathlib import Path
from se_catalog.catalog import chain,found,web,covers
from sefang.catalog import chain as compat_chain,found as compat_found,web as compat_web,covers as compat_covers
from sefang import codes
from se_catalog import codes as shared_codes
from sefang.actor_aliases import ActorAliases
class SharedRuntime(unittest.TestCase):
 def test_actual_shared_modules_not_parallel_implementations(self):
  self.assertIs(codes,shared_codes)
  for a,b in [(chain,compat_chain),(found,compat_found),(web,compat_web),(covers,compat_covers)]:self.assertIs(a,b)
  self.assertIs(chain.lookup,compat_chain.lookup)
 def test_shared_names_are_display_only_no_new_alias_identity(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'actor-aliases.json';p.write_text(json.dumps({'version':1,'groups':[]}));policy=ActorAliases(p);policy.reload()
   self.assertEqual(policy.display('三上悠亜')['display_name'],'三上悠亜 / 三上悠亚')
   self.assertEqual(policy.canonical('三上悠亚'),'三上悠亚');self.assertEqual(policy.by_name,{})
   self.assertEqual(policy.display('初美なのか')['display_name'],'初美なのか')
if __name__=='__main__':unittest.main()

"""Category-only reviewed labels/equivalences. Never edits source or translation cache."""
import hashlib,json,unicodedata
from pathlib import Path
from .caption_tags import hashtags
from .category_data import MERGES,TRANSLATIONS,OLD_DISPLAYS
from .localization import folded
from .category_originals import ORIGINAL_DISPLAYS

def category_id(name):return hashlib.sha256(('categories\0'+name).encode()).hexdigest()[:24]

class CategoryRules:
 def __init__(self):
  self.policy=json.loads(Path(__file__).with_name('category_policy.json').read_text())
  self.category_names={r['canonical_id']:r['canonical_name'] for r in self.policy['categories']}
  self.by_name={raw:self.category_names[ident] for raw,ident in self.policy['raw_to_canonical_id'].items()}
  self.tokens={raw:self.category_names[ident] for raw,ident in self.policy['token_to_canonical_id'].items()}
  self.retired=frozenset(category_id(raw) for raw,canonical in self.by_name.items() if raw!=canonical)|frozenset(r['category_id'] for r in self.policy['drop'])
  self.displays={};self.names={};self.drop=frozenset(r['raw_name'] for r in self.policy['drop'])
  for group in MERGES:
   canonical=group['canonical'];self.displays[canonical]=group['display']
  for raw,display in TRANSLATIONS.items():
   canonical=self.canonical(raw)
   if canonical in self.displays and self.displays[canonical]!=display:raise ValueError('conflicting approved category display')
   self.displays[canonical]=display
  for raw,old in OLD_DISPLAYS.items():
   canonical=self.canonical(raw);names=self.names.setdefault(canonical,[])
   for text in (raw,old,self.displays.get(canonical,'')):
    if text and text not in names:names.append(text)
  for group in self.policy['merge_groups']:
   if group['ref']=='M83':self.names[group['canonical_name']]=list(group['raw_members'])
 def canonical(self,name):return self.by_name.get(name,self.tokens.get(unicodedata.normalize('NFKC',name),name))
 def caption_categories(self,caption):
  # Explicit, frozen category tokens only; actor and code policy is independent.
  return tuple(dict.fromkeys(self.tokens[n] for raw in hashtags(caption) if (n:=unicodedata.normalize('NFKC',raw)) in self.tokens))
 def project(self,names):return tuple(dict.fromkeys(self.canonical(n) for n in names if n not in self.drop))
 def display(self,name):
  canonical=self.canonical(name);value=ORIGINAL_DISPLAYS.get(canonical,canonical)
  return {'display_name':value,'name_original':value,'name_zh':None,'name_translation':{'state':'original','method':'original'}}
 def aliases(self,name):return self.names.get(self.canonical(name),())
 def matches(self,name,query):return any(folded(query) in folded(n) for n in self.aliases(name))

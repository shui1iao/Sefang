"""Exact, privately reviewed actor identities; no translation or fuzzy identity inference."""
import hashlib,json,re
from .caption_tags import hashtags
from se_catalog.names import trusted_chinese
from .localization import folded,CC

def actor_id(name):return hashlib.sha256(('actors\0'+name).encode()).hexdigest()[:24]

class ActorAliases:
 def __init__(self,path):
  self.path=path;self.stamp=None;self.by_name={};self.by_id={};self.by_query={};self.names={};self.zh={}
 def reload(self):
  try:st=self.path.stat();stamp=(st.st_mtime_ns,st.st_size)
  except FileNotFoundError:stamp=()
  if stamp==self.stamp:return False
  raw=json.loads(self.path.read_text()) if stamp else {'version':1,'groups':[]}
  if raw.get('version')!=1 or not isinstance(raw.get('groups'),list) or len(raw['groups'])>38:raise ValueError('invalid actor identity policy')
  by_name={};by_id={};by_query={};names={};zh_names={}
  for group in raw['groups']:
   name=group['canonical'];aliases=group['aliases'];ident=group['id']
   if not isinstance(name,str) or not name or not isinstance(aliases,list) or not re.fullmatch('[0-9a-f]{24}',ident):raise ValueError('invalid actor identity group')
   if name in names or ident in by_id:raise ValueError('duplicate actor identity')
   zh=group.get('name_zh') or None
   if zh is not None:
    if not isinstance(zh,str) or not re.fullmatch('[\u3400-\u9fff]+',zh):raise ValueError('invalid confirmed actor Chinese name')
    zh=CC.convert(zh)
   if zh==name:zh=None
   zh_names[name]=zh
   names[name]=tuple(dict.fromkeys([name,*aliases,*([zh] if zh else [])]))
   for token in names[name]:
    if not isinstance(token,str) or not token or token in by_name or folded(token) in by_query:raise ValueError('ambiguous actor identity alias')
    by_name[token]=name;by_query[folded(token)]=name;by_id[actor_id(token)]=ident
   by_id[ident]=ident
  self.by_name=by_name;self.by_id=by_id;self.by_query=by_query;self.names=names;self.zh=zh_names;self.stamp=stamp
  return True
 def display(self,name):
  # Explicit reviewed null remains a display veto; all nonempty Chinese
  # display values come from the very same installed table as the Bot.
  zh=None if name in self.zh and not self.zh[name] else (trusted_chinese(name) or None)
  if zh==name:zh=None
  return {'display_name':f'{name} / {zh}' if zh else name,'name_zh':zh,'name_translation':{'state':'verified_alias' if zh else 'original','method':'actor_alias' if zh else 'actor_original'}}
 def canonical(self,name):return self.by_name.get(name,name)
 def resolve_id(self,ident):return self.by_id.get(ident,ident)
 def query_name(self,q):return self.by_query.get(folded(q))
 def matches(self,name,needle):return any(needle in folded(n) for n in self.names.get(name,(name,)))
 def caption_names(self,text):return tuple(dict.fromkeys(self.by_name[n] for n in hashtags(text) if n in self.by_name))

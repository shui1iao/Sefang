"""Explicit caption hashtag projection. Roles are local, reviewed data, not inferred identities."""
from html.parser import HTMLParser
import json,re,unicodedata

MAX_TAG=128
NUMBER=re.compile(r'[a-z]{2,16}(?:[-_][a-z]{1,8})?[-_]\d{1,10}',re.I)

class _Text(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style'):self.hidden+=1
  self.parts.append(' ')
 def handle_endtag(self,tag):
  if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
  self.parts.append(' ')
 def handle_data(self,data):
  if not self.hidden:self.parts.append(data)

def _char(c):return c in '_-' or unicodedata.category(c)[0] in 'LMN'

def hashtags(caption):
 """Whole Unicode tokens; retain spelling, including underscores and code hyphens.
 NFKC is used for token boundaries/number checks, never to rename a person.
 """
 if not isinstance(caption,str):return ()
 text=_Text();text.feed(caption);text.close();body=''.join(text.parts);result=[];last_end=-1
 for match in re.finditer('[#＃]',body):
  pos=match.start()
  if pos and pos!=last_end and (_char(body[pos-1]) or body[pos-1] in '#＃/@'):continue
  end=match.end()
  while end<len(body) and all(_char(c) for c in unicodedata.normalize('NFKC',body[end])):end+=1
  last_end=end
  token=body[match.end():end];normal=unicodedata.normalize('NFKC',token)
  if not token or len(token)>MAX_TAG or len(normal)>MAX_TAG or not any(unicodedata.category(c)[0] in 'LN' for c in normal):continue
  if normal[0] in '_-' or normal[-1] in '_-' or NUMBER.fullmatch(normal):continue
  if token not in result:result.append(token)
 return tuple(result)

class Roles:
 """Small private JSON allowlist. Atomic replace + mtime reload in existing refresh.
 Missing file means no additions; unknown hashtags stay in the original caption.
 """
 def __init__(self,path):self.path=path;self.stamp=None;self.categories={};self.actors=set()
 def reload(self):
  try:s=self.path.stat();stamp=(s.st_mtime_ns,s.st_size,s.st_ino)
  except FileNotFoundError:stamp=()
  if stamp==self.stamp:return False
  data=json.loads(self.path.read_text()) if stamp else {}
  categories=data.get('categories',{});actors=data.get('actors',[])
  if not isinstance(categories,dict) or not isinstance(actors,list):raise ValueError('invalid local hashtag roles')
  if any(not isinstance(x,str) or not x or len(x)>MAX_TAG for x in [*categories,*categories.values(),*actors]):raise ValueError('invalid local hashtag name')
  self.categories={unicodedata.normalize('NFKC',raw):name for raw,name in categories.items()};self.actors=set(actors);self.stamp=stamp
  return True
 def project(self,caption):
  out={'tags':[],'performers':[]}
  for raw in hashtags(caption):
   category=self.categories.get(unicodedata.normalize('NFKC',raw))
   if category is not None and category not in out['tags']:out['tags'].append(category)
   if raw in self.actors and raw not in out['performers']:out['performers'].append(raw)
  return out

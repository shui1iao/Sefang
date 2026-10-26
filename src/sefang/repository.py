"""明确公开投影；原TG数据库只读，新实体/头像侧库独立。

列表、搜索、分类/实体页、计数和相关推荐统一基于grouping.py的播放组投影；
原消息地址和数据保持不变，播放组只在内存中由原表随时重建。
"""
from contextlib import contextmanager
import hashlib,json,sqlite3,threading
from urllib.parse import urlsplit
from .grouping import GroupIndex,PlaybackGroup,RULE_VERSION,valid_duration
from .localization import View,folded
from .caption_tags import Roles
from .actor_aliases import ActorAliases
from .category_rules import CategoryRules
from . import codes
from .catalog.found import Found
from se_catalog.catalog.stored import is_same_stored_source

# Keep internal metadata/entity synchronization intact; public filtering excludes series.
KINDS={'actors':'performers','studios':'studio','series':'series','categories':'tags'}
AMATEUR="素人"
PUBLIC_KINDS=('actors','studios','categories')
JOINS=' FROM tg_video v LEFT JOIN tg_identification i ON i.channel_id=v.channel_id AND i.message_id=v.message_id LEFT JOIN tg_work w ON w.identity=i.identity '
COLUMNS='v.*,i.code,i.identity,i.state AS identification,w.code AS work_code,w.state AS metadata_state,w.metadata,w.sources,w.checked_at,w.cover_file,w.cover_state'

def entity_id(kind,name):return hashlib.sha256((kind+'\0'+name).encode()).hexdigest()[:24]
def safe_url(value):
 try:
  u=urlsplit(str(value or ''))
  if u.scheme not in ('https','http') or not u.hostname or u.username or u.password or u.hostname in {'localhost','127.0.0.1'} or len(str(value))>4096:return None
  return str(value)
 except ValueError:return None
def load_fields(raw):
 try:value=json.loads(raw or '{}')
 except (TypeError,ValueError):return {}
 return value if isinstance(value,dict) else {}
def names_of(fields,key):
 names=fields.get(key) or [];names=[names] if isinstance(names,str) else names
 return [n for n in names if isinstance(n,str) and n.strip()] if isinstance(names,list) else []

def source_performers(row):
 """One adopted cast field, not a union or a name/portrait identity classifier."""
 if row.get('identification')!='identified' or row.get('metadata_state') not in ('matched','partial'):return None
 code=row.get('code');work=row.get('work_code');identity=row.get('identity')
 if not code or not work or not identity or codes.identity(code)!=identity or codes.identity(work)!=identity:return None
 fields=load_fields(row.get('metadata'));names=fields.get('performers')
 if not isinstance(names,list) or not names or not all(isinstance(n,str) and n.strip() for n in names):return None
 provenance=fields.get('field_sources')
 if not isinstance(provenance,dict) or not isinstance(provenance.get('performers'),str):return None
 try:sources=json.loads(row.get('sources') or '[]')
 except (ValueError,TypeError):return None
 if not isinstance(sources,list):return None
 valid=False
 for s in sources:
  if not isinstance(s,dict) or s.get('name')!=provenance['performers'] or not isinstance(s.get('fields'),list) or 'performers' not in s['fields']:continue
  if not all(isinstance(s.get(k,''),str) for k in ('url','returned_id')):continue
  try:
   if is_same_stored_source(work,Found(s['name'],s.get('url',''),content_id=s.get('returned_id',''))):valid=True
  except (ValueError,TypeError):continue
 if not valid:return None
 # Explicitly approved single descriptive value; original metadata is retained.
 names=list(dict.fromkeys(n for n in names if n!='18歳スレンダー美女'))
 return tuple(names) or None

class Repository:
 def __init__(self,config):
  self.config=config;self.path=config.db;self.root=config.state
  self.root.mkdir(parents=True,exist_ok=True,mode=0o700);self.root.chmod(0o700)
  self.side=self.root/'catalog.db'
  self.groups=GroupIndex(load_fields);self._refresh_lock=threading.Lock();self._watch=None;self._version=None
  self._entity_state=None;self.entity_generation=0;self._effective={};self._album_sources={}
  self.category_rules=CategoryRules()
  self.tag_roles=Roles(self.root/'tag-roles.json');self.actor_aliases=ActorAliases(self.root/'actor-aliases.json')
  self.localized=View(self.root/'localization');self.localized_names=set()
  with self.local() as db:
   db.executescript('''CREATE TABLE IF NOT EXISTS entity(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,video_count INTEGER DEFAULT 0,
       avatar_state TEXT DEFAULT 'pending',avatar_file TEXT DEFAULT '',avatar_mime TEXT DEFAULT '',external_id TEXT DEFAULT '',avatar_source TEXT DEFAULT '',checked_at REAL DEFAULT 0,attempts INTEGER DEFAULT 0);
       CREATE UNIQUE INDEX IF NOT EXISTS entity_name ON entity(kind,name);
       CREATE TABLE IF NOT EXISTS relation(identity TEXT,entity_id TEXT,PRIMARY KEY(identity,entity_id));
       CREATE TABLE IF NOT EXISTS group_entity(group_id TEXT,entity_id TEXT,PRIMARY KEY(group_id,entity_id));
       CREATE TABLE IF NOT EXISTS avatar_work_cache(content_id TEXT PRIMARY KEY,payload TEXT,checked_at REAL);
       ''')
  self.side.chmod(0o600)
 @contextmanager
 def read(self):
  db=sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True,timeout=10);db.row_factory=sqlite3.Row
  try:yield db
  finally:db.close()
 @contextmanager
 def local(self):
  db=sqlite3.connect(self.side,timeout=15);db.row_factory=sqlite3.Row
  try:
   with db:yield db
  finally:db.close()
 def scope(self):return 'v.channel_id IN ('+','.join('?' for _ in self.config.channels)+')',list(self.config.channels)
 def _data_version(self):
  # 常驻只读连接的data_version只在其他连接提交写入后变化；未变化时读请求不扫描原表。
  if self._watch is None:self._watch=sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True,timeout=10,check_same_thread=False)
  return self._watch.execute('PRAGMA data_version').fetchone()[0]
 def refresh(self,force=False):
  """原表有新帖/编辑/删除提交时，只重建受影响identity/消息的播放组并同步计数；从不访问来源或TG。"""
  with self._refresh_lock:
   version=self._data_version();rules_changed=self.tag_roles.reload();aliases_changed=self.actor_aliases.reload();rules_changed=rules_changed or aliases_changed
   if not force and not rules_changed and self._version==version and self.groups.snapshot.generation:return set()
   affected=set();source_changed=force or self._version!=version or not self.groups.snapshot.generation
   if source_changed:
    where,args=self.scope()
    with self.read() as db:
     rows=[dict(r) for r in db.execute('SELECT '+COLUMNS+JOINS+'WHERE '+where,args)]
     # Optional attached source table: old databases remain readable without migration here.
     exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tg_message_album'").fetchone()
     albums={(r['channel_id'],r['message_id']):r['grouped_id'] for r in db.execute('SELECT * FROM tg_message_album')} if exists else {}
     context_exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tg_album_caption'").fetchone()
     contexts=[dict(r) for r in db.execute('SELECT c.*,a.grouped_id FROM tg_album_caption c JOIN tg_message_album a USING(channel_id,message_id)')] if exists and context_exists else []
    captions={}
    for context in contexts:
     if context['channel_id'] in self.config.channels:
      captions.setdefault((context['channel_id'],context['grouped_id']),[]).append(context['caption'])
    for row in rows:
     gid=albums.get((row['channel_id'],row['message_id']))
     if gid is not None and row.get('available'):
      captions.setdefault((row['channel_id'],gid),[]).append(row.get('caption'))
    self._album_sources={key:tuple(captions.get((key[0],gid),())) for key,gid in albums.items()}
    # Albums are tag sources only, never inputs to playback grouping.
    affected=self.groups.update(rows);self._version=version
   # Relationship-only commits do not change GroupIndex rows, but do change effective entities.
   if source_changed or rules_changed or self._entity_state is None:self._write_entities()
   return affected
 def close(self):
  with self._refresh_lock:
   if self._watch is not None:self._watch.close();self._watch=None
 def snapshot(self):self.refresh();return self.groups.snapshot
 def _project(self,group):
  """One effective entity set for the whole group, including nonrepresentatives/aliases.
  Original metadata stays untouched. Only explicit, available caption tags are additions.
  """
  fields={key:[] for key in KINDS.values()};tg_actors=[]
  for row in group.messages:
   original=load_fields(row.get('metadata'))
   additions={'tags':[],'performers':[]}
   if row.get('available'):
    sources=self._album_sources.get((row['channel_id'],row['message_id']),(row.get('caption'),))
    for caption in sources:
     projected=self.tag_roles.project(caption)
     projected['tags'].extend(self.category_rules.caption_categories(caption))
     projected['performers'].extend(self.actor_aliases.caption_names(caption))
     for key in additions:
      for name in projected[key]:
       if name not in additions[key]:additions[key].append(name)
   tg_actors.extend(additions['performers'])
   for key in fields:
    if key=='performers':continue
    for name in [*names_of(original,key),*names_of(additions,key)]:
     if name not in fields[key]:fields[key].append(name)
  # The label is a final projection fallback, never a person or part of a known cast.
  source=[n for n in (self.source_cast(group) or ()) if n.strip()!=AMATEUR]
  cast=source or [self.actor_aliases.canonical(n) for n in tg_actors]
  fields['performers']=list(dict.fromkeys(n for n in cast if n.strip() and n.strip()!=AMATEUR)) or [AMATEUR]
  fields['tags']=self.category_rules.project(fields['tags'])
  return {key:tuple(names) for key,names in fields.items()}
 def source_cast(self,group):
  values=[source_performers(row) for row in group.messages]
  if not values or any(v is None for v in values) or len({r.get('identity') for r in group.messages})!=1:return None
  values=[tuple(dict.fromkeys(self.actor_aliases.canonical(n) for n in v)) for v in values]
  return values[0] if len({frozenset(v) for v in values})==1 else None
 def effective(self,group):return self._effective.get(group.id) or self._project(group)
 def _write_entities(self):
  snap=self.groups.snapshot;values={};relations=set();memberships=set();self.localized_names=set()
  self._effective={group.id:self._project(group) for group in snap.groups}
  for group in snap.groups:
   # Translation protection and verified-work relations use metadata only, not new handles.
   for row in group.messages:
    original=load_fields(row.get('metadata'))
    self.localized_names.update(names_of(original,'performers'));self.localized_names.update(names_of(original,'studio'))
    if row.get('identity'):
     for kind,key in KINDS.items():
      names=names_of(original,key)
      if kind=='categories':names=self.category_rules.project(names)
      for name in names:
       if kind!='actors' or name.strip()!=AMATEUR:relations.add((row['identity'],entity_id(kind,name)))
   for kind,key in KINDS.items():
    for name in self.effective(group)[key]:
     ident=entity_id(kind,name);values.setdefault(ident,[kind,name,0])[2]+=1;memberships.add((group.id,ident))
  state=(tuple(sorted((k,*v) for k,v in values.items())),tuple(sorted(relations)),tuple(sorted(memberships)))
  if state==self._entity_state:return
  with self.local() as db:
   db.execute('UPDATE entity SET video_count=0');db.execute('DELETE FROM relation');db.execute('DELETE FROM group_entity')
   for ident,(kind,name,count) in values.items():db.execute('''INSERT INTO entity(id,kind,name,video_count) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET video_count=excluded.video_count''',(ident,kind,name,count))
   db.executemany('INSERT OR IGNORE INTO relation VALUES(?,?)',sorted(relations))
   db.executemany('INSERT INTO group_entity VALUES(?,?)',sorted(memberships))
  self._entity_state=state;self.entity_generation+=1
 def sync_entities(self):
  self.refresh(force=True)
  return len(self._entity_state[0]) if self._entity_state else 0
 def entity(self,kind,ident):
  if kind not in KINDS or len(ident)!=24:return None
  self.refresh()
  if kind=='actors':ident=self.actor_aliases.resolve_id(ident)
  if kind=='categories' and ident in self.category_rules.retired:return None
  with self.local() as db:row=db.execute('SELECT * FROM entity WHERE id=? AND kind=? AND video_count>0',(ident,kind)).fetchone()
  return self.entity_dto(dict(row)) if row else None
 def name_display(self,kind,name):
  if kind=='actors':return self.actor_aliases.display(name)
  if kind not in ('categories','series'):return {}
  if kind=='categories':
   approved=self.category_rules.display(name)
   if approved:
    aliases=list(self.category_rules.aliases(name))
    # Preserve former category name_zh queries without making the cached label visible
    # or treating it as a reviewed synonym. View.project reads local cache only.
    if self.category_rules.canonical(name) not in self.category_rules.displays:
     legacy=self.localized.project(kind,name,self.localized_names)['zh']
     if legacy and legacy not in aliases:aliases.append(legacy)
    return {**approved,'aliases':aliases}
  value=self.localized.project(kind,name,self.localized_names)
  return {'display_name':value['display'],'name_zh':value['zh'],'name_translation':{'state':value['state'],'method':value['method']}}
 def title_display(self,row):
  f=load_fields(row.get('metadata'));raw=f.get('title')
  if not isinstance(raw,str) or not raw:return {'display_title':row['title'],'title_zh':None,'title_translation':{'state':'original','method':'original'}}
  value=self.localized.project('title',raw,[row.get('code') or '',*names_of(f,'performers'),*names_of(f,'studio')])
  return {'display_title':value['display'],'title_zh':value['zh'],'title_translation':{'state':value['state'],'method':value['method']}}
 def entity_dto(self,row):
  available=bool(row['avatar_file'] and (self.root/'avatars'/row['avatar_file']).is_file())
  return {'id':row['id'],'kind':row['kind'],'name':row['name'],'count':row['video_count'],
          'avatar':f"/api/actors/{row['id']}/image" if available else None,'avatar_state':row['avatar_state'] if not row['avatar_file'] or available else 'missing',**self.name_display(row['kind'],row['name'])}
 def entities(self,kind,q='',page=1,limit=40):
  if kind not in KINDS:return {'items':[],'total':0,'page':page,'pages':0}
  self.refresh()
  with self.local() as db:
   rows=db.execute('SELECT * FROM entity WHERE kind=? AND video_count>0 ORDER BY (avatar_file<>\'\') DESC,video_count DESC,name,id',(kind,)).fetchall()
  items=[self.entity_dto(dict(row)) for row in rows]
  if q:items=[item for item in items if (kind=='actors' and self.actor_aliases.matches(item['name'],folded(q))) or (kind=='categories' and any(folded(q) in folded(n) for n in item.get('aliases',()))) or folded(q) in folded(item['name']) or folded(q) in folded(item.get('name_zh') or '')]
  total=len(items)
  return {'items':items[(page-1)*limit:page*limit],'total':total,'page':page,'pages':(total+limit-1)//limit}
 def raw(self,cid,mid):
  if cid not in self.config.channels or not 0<mid<2**53:return None
  with self.read() as db:row=db.execute('SELECT '+COLUMNS+JOINS+'WHERE v.channel_id=? AND v.message_id=?',(cid,mid)).fetchone()
  return dict(row) if row else None
 def dto(self,row,detail=False,group=None):
  f=load_fields(row.get('metadata'));identity=row.get('identity') or '';cover=row.get('cover_file') or ''
  expected=hashlib.sha256(identity.encode()).hexdigest()+'.cover'
  has_cover=bool(cover==expected and (self.config.covers/cover).is_file())
  cid,mid=row['channel_id'],row['message_id']
  group=group or self.snapshot().by_message.get((cid,mid))
  fields=self.effective(group) if group else {key:names_of(f,key) for key in KINDS.values()}
  entities={kind:[{'id':entity_id(kind,name),'name':name,**self.name_display(kind,name)} for name in fields[key]] for kind,key in KINDS.items()}
  result={'id':f'{cid}:{mid}','channel_id':cid,'message_id':mid,'title':f.get('title') or row['title'],'code':row.get('code') or '',
          'duration':row['duration'],'width':row['width'],'height':row['height'],'size':row['size'],'mime':row['mime'],'available':bool(row['available']),
          'uploaded_at':row['date'],'release_date':f.get('release_date') or None,'state':row.get('metadata_state') or row.get('identification') or 'unidentified',
          'cover':f'/api/videos/{cid}/{mid}/cover' if has_cover else f'/api/videos/{cid}/{mid}/thumbnail','has_cover':has_cover,'entities':entities,**self.title_display(row)}
  if detail:
   result.update(original_name=row['title'],caption=row['caption'],protected=bool(row['protected']),checked_at=row.get('checked_at'),
                 message_url=f'https://t.me/c/{cid}/{mid}',sources=[{'name':s.get('name',''),'url':safe_url(s.get('url'))} for s in json.loads(row.get('sources') or '[]')],
                 stream=f'/api/videos/{cid}/{mid}/stream')
  return result
 def card(self,group):
  """一张卡一个播放组：代表消息为第1段；时长为已知合计。"""
  row=self.dto(group.representative,group=group)
  row.update(id=group.id,duration=group.total_duration,part_count=len(group.parts),duration_complete=group.duration_complete)
  return row
 def group_detail(self,group,cid,mid,requested=None):
  index=group.index_of(cid,mid);parts=list(group.parts)
  # Player消费此队列的stream；别名直链必须仍播放原请求消息，而非换成代表消息。
  if index is not None:
   requested=requested if requested is not None else next((r for r in group.messages if (r['channel_id'],r['message_id'])==(cid,mid)),None)
   if requested is not None:parts[index]=requested
  return {'id':group.id,'status':group.status,'evidence':list(group.evidence),'rule_version':RULE_VERSION,'part_count':len(group.parts),
          'index':index if index is not None else 0,'total_duration':group.total_duration,'duration_complete':group.duration_complete,
          'parts':[{'number':i+1,'label_number':n,'channel_id':r['channel_id'],'message_id':r['message_id'],
                    'duration':float(r['duration']) if valid_duration(r) else None,'available':bool(r['available']),
                    'stream':f"/api/videos/{r['channel_id']}/{r['message_id']}/stream",'message_url':f"https://t.me/c/{r['channel_id']}/{r['message_id']}"}
                   for i,(r,n) in enumerate(zip(parts,group.numbers))]}
 def detail(self,cid,mid):
  """旧/watch/{cid}/{mid}直链：返回该消息本身，并附其所属播放组和当前段位置。"""
  snap=self.snapshot();row=self.raw(cid,mid)
  if not row:return None
  group=snap.by_message.get((cid,mid));result=self.dto(row,True,group)
  # 读到比投影更新的单条（刚入库）：按单条展示，不猜测分组。
  if group is None:group=PlaybackGroup(f'{cid}:{mid}','single',(),(row,),(None,))
  result['group']=self.group_detail(group,cid,mid,row)
  return result
 def _matches(self,group,filters,q):
  fields=self.effective(group)
  if any(name not in fields[key] for key,name in filters):return False
  if not q:return True
  needle=folded(q);actor_name=self.actor_aliases.query_name(q)
  if actor_name is not None:return actor_name in fields['performers']
  # Extend only actor-name search, not genres or arbitrary caption text.
  if any(self.actor_aliases.matches(name,needle) for name in fields['performers']):return True
  for row in group.messages:
   original=load_fields(row.get('metadata'))
   if any(needle in folded(str(value or '')) for value in (row['title'],row.get('code'),original.get('title'))):return True
   zh=self.title_display(row)['title_zh']
   if zh and needle in folded(zh):return True
  return False
 def videos(self,q='',actor='',studio='',series='',category='',sort='newest',page=1,limit=36):
  snap=self.snapshot();filters=[]
  for kind,ident in [('actors',actor),('studios',studio),('categories',category)]:
   if not ident:continue
   e=self.entity(kind,ident)
   if not e:return {'items':[],'total':0,'page':page,'pages':0}
   filters.append((KINDS[kind],e['name']))
  ordered=snap.ordered(sort)
  if filters or q:ordered=[g for g in ordered if self._matches(g,filters,q)]
  total=len(ordered)
  return {'items':[self.card(g) for g in ordered[(page-1)*limit:page*limit]],'total':total,'page':page,'pages':(total+limit-1)//limit}
 def related(self,cid,mid,limit=12):
  if cid not in self.config.channels or not 0<mid<2**53:return None
  snap=self.snapshot();current=snap.by_message.get((cid,mid))
  if current is None:return None
  fields=self.effective(current);ranked=[]
  for group in snap.groups:
   if group is current or not group.available:continue
   other=self.effective(group);score=0;reasons=[]
   for key,weight,label in [('performers',8,'同演员'),('series',6,'同系列'),('studio',3,'同厂牌'),('tags',1,'同分类')]:
    a=fields.get(key);b=other.get(key)
    shared_names=set(a or [])&set(b or [])
    if key=='performers':shared_names.discard(AMATEUR)  # A shared fallback is not a shared person.
    shared=bool(shared_names)
    if shared:score+=weight;reasons.append(label)
   ranked.append((score,max(str(r['date']) for r in group.parts),max(r['message_id'] for r in group.parts),group,reasons))
  ranked.sort(key=lambda r:r[:3],reverse=True)
  return {'items':[{**self.card(g),'related_reason':' · '.join(reasons) if score else '最近加入'} for score,_,__,g,reasons in ranked[:limit]],'basis':'library_metadata' if any(r[0] for r in ranked) else 'recent_fallback'}

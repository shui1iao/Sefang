"""保守、可重建的播放组投影。

原消息/作品表只读：同频道、同一已确认发行identity的多条消息，只有在文件名显式段号
从1连续到N、去段号后的基名/显式版次/容器一致（可混分辨率）、各自是不同文件时才组成一个播放组；
严格同文件属性的重发只建立原消息别名，不增加播放段；裸名不阻断独立通过严格判据的全部显式段。
其余重号、缺号、版本/容器冲突保持独立，不猜测版本归属。
不用上传时间、近似时长或消息先后推断顺序/版本，也不在库内保存不可重建的关系。
"""
from dataclasses import dataclass
import hashlib,math,re,threading
from . import codes
from .tg.index import PLAYABLE_MIME

RULE_VERSION=3
PAREN=re.compile(r'[（(]\s*(0?[1-9]|[1-9]\d)\s*[）)](?=\.[a-z0-9]{2,4}$)',re.I)
CIRCLED='①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
TECH=[('1080p',r'(?i)(?<!\d)1080p?\b'),('720p',r'(?i)(?<!\d)720p?\b'),('2160p',r'(?i)(?<!\d)2160p?\b'),
      ('4k',r'(?i)(?<![a-z0-9])4k(?![a-z0-9])'),('8k',r'(?i)(?<![a-z0-9])8k(?![a-z0-9])'),('hevc',r'(?i)hevc|h\.?265|x265'),
      ('h264',r'(?i)h\.?264|x264'),('repair',r'修复|修復|(?i:remaster|upscale)'),('full',r'完整版|完整片|(?i:(?<![a-z])full(?![a-z]))')]
CONFIRMED_EVIDENCE=('same_channel_identity','explicit_part_numbers_1_to_n','same_base_filename','same_edition_container','distinct_documents','valid_media_metadata')

def segment_mark(row):
 """返回(显式段号, 去段号基名)；段号必须是独立尾缀且余下基名仍确认同一番号。"""
 title=str(row.get('title') or '');m=PAREN.search(title);paren=bool(m)
 if not m:m=codes.part_suffix(title)
 if not m:return None
 token=m.group(1)
 if token in CIRCLED:token=str(CIRCLED.index(token)+1)
 if not token.isdigit():return None
 # 括号写法只额外清理紧邻的分隔点（MIDV-196.(1).mp4），不删版本文字或番号数字。
 base=title[:m.start()].rstrip('. ')+title[m.end():] if paren else title[:m.start()]+title[m.end():]
 code=codes.read_filename(base)
 if not code or row.get('identification')!='identified' or not codes.same_work(code,row.get('code')):return None
 return int(token),base

def valid_duration(row):
 value=row.get('duration')
 return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0

def _edition(row,mark):
 title=str(row.get('title') or '')
 return (tuple(codes.edition_marks(title,row.get('code'))),tuple(codes.edition_marks(mark[1],row.get('code'))) if mark else (),
         tuple(name for name,pattern in TECH if re.search(pattern,title)))

def assess(rows):
 """同一identity的全部消息；返回不能自动成组的原因，空列表即确认分段组。"""
 marks=[segment_mark(r) for r in rows];numbers=[m[0] for m in marks if m];reasons=[]
 if len(rows)<2:reasons.append('single_message')
 if not numbers:reasons.append('no_explicit_order')
 elif len(numbers)<len(rows):reasons.append('bare_plus_parts')
 if len(numbers)!=len(set(numbers)):reasons.append('repeated_part_number')
 if numbers and set(numbers)!=set(range(1,max(numbers)+1)):reasons.append('missing_number')
 if len({m[1].casefold() for m in marks if m})>1:reasons.append('different_base_filename')
 # 完整明确分段可有不同尺寸；容器与有效元数据仍须逐段确认。
 if len({r.get('mime') for r in rows})>1:reasons.append('different_container')
 if any(r.get('mime') not in PLAYABLE_MIME for r in rows):reasons.append('unsupported_container')
 if any(not valid_duration(r) or any(not isinstance(r.get(k),int) or isinstance(r[k],bool) or r[k]<=0 for k in ('size','width','height')) for r in rows):reasons.append('invalid_media_metadata')
 if len({_edition(r,m) for r,m in zip(rows,marks)})>1:reasons.append('different_named_edition')
 if len({r.get('document_id') for r in rows})<len(rows):reasons.append('same_document')
 if len({(r.get('size'),r.get('duration'),r.get('width'),r.get('height')) for r in rows})<len(rows):reasons.append('identical_size_duration_shape')
 return reasons,marks

def bucket_key(row):
 if row.get('identification')=='identified' and row.get('identity'):return ('identity',row['channel_id'],row['identity'])
 return ('message',row['channel_id'],row['message_id'])

def group_id(channel_id,identity):return 'g'+hashlib.sha256(f'{channel_id}\0{identity}'.encode()).hexdigest()[:20]

@dataclass(frozen=True,eq=False)
class PlaybackGroup:
 id:str
 status:str  # confirmed | single | unresolved
 evidence:tuple
 parts:tuple  # 有序唯一播放槽的代表原消息（只读dict）
 numbers:tuple
 slot_messages:tuple=()  # 与parts同序；每槽的全部原消息，别名不成为下一段
 @property
 def representative(self):return self.parts[0]
 @property
 def messages(self):return tuple(r for slot in self.slot_messages for r in slot) if self.slot_messages else self.parts
 @property
 def keys(self):return tuple((r['channel_id'],r['message_id']) for r in self.messages)
 @property
 def total_duration(self):
  """先按原始小数秒求和；只计可用且时长有效的唯一段，不把未知当0冒充完整。"""
  if len(self.parts)==1:
   row=self.parts[0];return float(row['duration']) if valid_duration(row) else None
  seen=set();total=0.0
  for row in self.parts:
   if row.get('available') and valid_duration(row) and row.get('document_id') not in seen:seen.add(row.get('document_id'));total+=float(row['duration'])
  return total if seen else None
 @property
 def duration_complete(self):
  if len(self.parts)==1:return valid_duration(self.parts[0])
  return all(r.get('available') and valid_duration(r) for r in self.parts) and len({r.get('document_id') for r in self.parts})==len(self.parts)
 @property
 def available(self):return bool(self.representative.get('available'))
 def index_of(self,cid,mid):
  for i,slot in enumerate(self.slot_messages or tuple((r,) for r in self.parts)):
   if any((r['channel_id'],r['message_id'])==(cid,mid) for r in slot):return i
  return None

def strict_file_key(row):
 """已确认同作品的精确文件属性键；不是媒体内容hash，不做任何文件名规范化。"""
 if row.get('identification')!='identified' or not row.get('identity'):return None
 if not isinstance(row.get('title'),str) or not row['title'] or not isinstance(row.get('mime'),str) or not row['mime']:return None
 if not valid_duration(row):return None
 if any(not isinstance(row.get(k),int) or isinstance(row[k],bool) or row[k]<=0 for k in ('size','width','height')):return None
 return (row['channel_id'],row['identity'],row['title'],row['size'],row['duration'],row['width'],row['height'],row['mime'])

def build_bucket(key,rows):
 rows=sorted(rows,key=lambda r:(r['channel_id'],r['message_id']))
 slots={}
 for row in rows:
  signature=strict_file_key(row) if key[0]=='identity' else None
  slot_key=('file',signature) if signature is not None else ('message',row['channel_id'],row['message_id'])
  slots.setdefault(slot_key,[]).append(row)
 representatives=[];members={}
 for slot in slots.values():
  representative=min(slot,key=lambda r:(not bool(r.get('available')),r['message_id']))
  representatives.append(representative);members[(representative['channel_id'],representative['message_id'])]=tuple(slot)
 def make(ident,status,evidence,parts,numbers):
  originals=tuple(members[(r['channel_id'],r['message_id'])] for r in parts)
  if any(len(slot)>1 for slot in originals):evidence=tuple(evidence)+('strict_file_attributes_alias',)
  return PlaybackGroup(ident,status,tuple(evidence),tuple(parts),tuple(numbers),originals)
 def confirmed(parts,marks):
  ordered=sorted(zip(marks,parts),key=lambda pair:pair[0][0])
  return make(group_id(key[1],key[2]),'confirmed',CONFIRMED_EVIDENCE,[r for _,r in ordered],[m[0] for m,_ in ordered])
 rows=representatives
 if key[0]=='identity' and len(rows)>1:
  reasons,marks=assess(rows)
  if not reasons:return (confirmed(rows,marks),)
  # 只评估全部显式段，绝不从重号/缺号中挑子集或按上传批次猜版本。
  marked=[r for r,m in zip(rows,marks) if m];bare=[r for r,m in zip(rows,marks) if not m]
  if bare and len(marked)>1:
   part_reasons,part_marks=assess(marked)
   if not part_reasons:
    return (confirmed(marked,part_marks),)+tuple(make(f"{r['channel_id']}:{r['message_id']}",'unresolved',reasons,(r,),(None,)) for r in bare)
  status,evidence='unresolved',tuple(reasons)
 else:status,evidence='single',()
 return tuple(make(f"{r['channel_id']}:{r['message_id']}",status,evidence,(r,),(None,)) for r in rows)

def _date(row):return str(row.get('date') or '')
SORT_MODES=('newest','oldest','duration','duration_asc','release','release_asc')

class Snapshot:
 """不可变代次：所有公共读取在同一代次上计数/分页/排序，避免页面间漂移。"""
 def __init__(self,generation,groups,meta):
  self.generation=generation;self.groups=groups;self.by_message={key:g for g in groups for key in g.keys};self.by_id={g.id:g for g in groups}
  self._meta=meta;self._orders={};self._lock=threading.Lock()
 def fields(self,group):return self._meta.get(group.id,{})
 def ordered(self,sort):
  with self._lock:
   if sort not in self._orders:self._orders[sort]=tuple(self._sort(sort))
   return self._orders[sort]
 def _sort(self,sort):
  ascending=sort in ('oldest','duration_asc','release_asc')
  if sort in ('duration','duration_asc'):value=lambda g:g.total_duration
  elif sort in ('release','release_asc'):value=lambda g:str(self.fields(g).get('release_date') or '') or None
  else:value=lambda g:max(_date(r) for r in g.parts) or None
  # One field in either direction, including grouped works; unknown values always last.
  keyed=[(g,value(g)) for g in self.groups]
  tie=lambda g:(max(r['message_id'] for r in g.parts),g.id)
  known=sorted(((g,v) for g,v in keyed if v is not None),key=lambda item:(item[1],tie(item[0])),reverse=not ascending)
  unknown=sorted((g for g,v in keyed if v is None),key=tie,reverse=True)
  return [g for g,_ in known]+unknown

class GroupIndex:
 """内存投影；每次只重算行内容变化所涉及的identity/消息桶，其余桶原样复用。"""
 def __init__(self,loads):
  self.loads=loads;self.lock=threading.RLock();self.rows={};self.buckets={}
  self.snapshot=Snapshot(0,(),{});self.recomputed_buckets=0
 def update(self,rows):
  with self.lock:
   incoming={(r['channel_id'],r['message_id']):r for r in rows};affected=set()
   for key,row in incoming.items():
    old=self.rows.get(key)
    if old!=row:
     affected.add(bucket_key(row))
     if old is not None:affected.add(bucket_key(old))
   for key in self.rows.keys()-incoming.keys():affected.add(bucket_key(self.rows[key]))
   if not affected and self.snapshot.generation:return set()
   self.rows=incoming;members={}
   for key in affected:self.buckets.pop(key,None)
   for row in incoming.values():
    key=bucket_key(row)
    if key in affected:members.setdefault(key,[]).append(row)
   for key,rows_in_bucket in members.items():self.buckets[key]=build_bucket(key,rows_in_bucket);self.recomputed_buckets+=1
   groups=tuple(g for key in sorted(self.buckets,key=lambda k:(k[0],k[1],str(k[2]))) for g in self.buckets[key])
   old_meta=self.snapshot._meta;meta={}
   for g in groups:
    raw=g.representative.get('metadata')
    meta[g.id]=old_meta[g.id] if g.id in old_meta and self.snapshot.by_id.get(g.id) is not None and self.snapshot.by_id[g.id].representative.get('metadata')==raw else self.loads(raw)
   self.snapshot=Snapshot(self.snapshot.generation+1,groups,meta)
   return affected

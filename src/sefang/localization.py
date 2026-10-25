"""Private, additive Chinese display layer. Original catalogs and Telegram rows are never written.
Only inventory() supplies public metadata inputs; HTTP GET projection uses View and cannot translate.
"""
import asyncio
from collections import Counter
from contextlib import closing,contextmanager
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock,Timeout as LockTimeout
from opencc import OpenCC
from .translation_http import Providers,TranslationError
from .translation_glossary import GLOSSARY

RULE='zh-display-v1';SUCCESS={'machine','canonical','native','normalized'}
MAX_ENTRIES=2000;MAX_BYTES=8*1048576;MAX_ATTEMPTS=2
HAN=re.compile('[\u3400-\u9fff]');KANA=re.compile('[\u3040-\u30ff]')
MARK=re.compile(r'ZQX\s*(\d+)\s*XQZ',re.I)
REFUSAL=re.compile(r'(?:无法|不能|不便|不予)(?:为你|为您)?(?:协助|帮助|提供|翻译|处理|生成)|(?:无法|不能).{0,30}(?:内容|请求)|\b(?:I cannot|I can.t|I.m sorry)\b',re.I)
CC=OpenCC('t2s')
def digest(text):return hashlib.sha256(text.encode()).hexdigest()
def folded(text):return unicodedata.normalize('NFKC',str(text)).casefold().strip()
def has_kana(text):return bool(KANA.search(unicodedata.normalize('NFKC',text)))
def eid(kind,name):return digest(kind+'\0'+name)[:24]
def fields(raw):
 try:value=json.loads(raw or '{}');return value if isinstance(value,dict) else {}
 except (ValueError,TypeError):return {}
def names(value):return [value] if isinstance(value,str) and value else [x for x in value if isinstance(x,str) and x] if isinstance(value,list) else []

def protection(raw,tokens):
 tokens=sorted({t for t in tokens if isinstance(t,str) and t and t in raw},key=lambda t:(-len(t),t))
 if not tokens:return raw,[]
 used=[]
 def replace(match):used.append(match[0]);return f'ZQX{len(used)-1}XQZ'
 return re.sub('|'.join(re.escape(t) for t in tokens),replace,raw),used

def restore(masked,used):
 seen=[]
 def replace(match):
  index=int(match[1])
  if index>=len(used):raise TranslationError('protected_token_invalid')
  seen.append(index);return used[index]
 result=MARK.sub(replace,masked)
 if Counter(seen)!=Counter(range(len(used))) or re.search('ZQX|XQZ',result,re.I):raise TranslationError('protected_token_lost')
 return result

@dataclass(frozen=True)
class Input:
 kind:str
 source_id:str
 raw:str
 tokens:tuple=()
 @property
 def source_hash(self):return digest(self.raw)
 @property
 def key(self):
  _,used=protection(self.raw,self.tokens)
  return digest(json.dumps([RULE,self.kind,'zh-CN',self.raw,used],ensure_ascii=False))

def public_field(sources,key):
 for source in sources if isinstance(sources,list) else []:
  if not isinstance(source,dict) or key not in (source.get('fields') or []) or not source.get('returned_id'):continue
  try:u=urlsplit(str(source.get('url') or ''))
  except ValueError:continue
  if u.scheme in ('http','https') and u.hostname and u.hostname not in ('localhost','127.0.0.1','::1') and not u.hostname.endswith(('.local','.internal')):return True
 return False

def inventory(config):
 """Only public work fields, never v.title/caption. No Repository/TG client construction."""
 if not config.db.is_file():return []
 with closing(sqlite3.connect('file:'+str(config.db)+'?mode=ro',uri=True)) as db:
  rows=db.execute('''SELECT w.identity,w.code,w.metadata,w.sources FROM tg_work w WHERE EXISTS
   (SELECT 1 FROM tg_identification i JOIN tg_video v ON v.channel_id=i.channel_id AND v.message_id=i.message_id
   WHERE i.identity=w.identity AND v.channel_id IN ('''+','.join('?' for _ in config.channels)+'))',config.channels).fetchall()
 known=set();parsed=[]
 for identity,code,raw,sources in rows:
  f=fields(raw)
  try:s=json.loads(sources or '[]')
  except ValueError:s=[]
  parsed.append((identity,code,f,s));known.update(names(f.get('performers')));known.update(names(f.get('studio')))
 result=[];labels={}
 for identity,code,f,s in parsed:
  raw=f.get('title')
  if isinstance(raw,str) and raw.strip() and public_field(s,'title'):
   result.append(Input('title',identity,raw,tuple([code,*names(f.get('performers')),*names(f.get('studio'))])))
  for kind,key in [('categories','tags')]:
   if not public_field(s,key):continue
   for name in names(f.get(key)):labels[(kind,name)]=Input(kind,eid(kind,name),name,tuple(known))
 result.extend(labels.values());return sorted(result,key=lambda x:(x.kind,x.source_id))

class Store:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700);self.root.chmod(0o700);self.path=self.root/'translations.sqlite'
  with self.connect() as db:
   db.executescript('''CREATE TABLE IF NOT EXISTS entry(key TEXT PRIMARY KEY,kind TEXT,source_hash TEXT,zh TEXT,state TEXT,method TEXT,provider TEXT,checked_at REAL);
    CREATE TABLE IF NOT EXISTS job(key TEXT PRIMARY KEY,kind TEXT,state TEXT,reason TEXT,attempts INTEGER DEFAULT 0,next_retry REAL DEFAULT 0,checked_at REAL);
    CREATE TABLE IF NOT EXISTS binding(kind TEXT,source_id TEXT,source_hash TEXT,key TEXT,PRIMARY KEY(kind,source_id));
    CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY,value TEXT);
   ''')
  self.path.chmod(0o600)
 @contextmanager
 def connect(self):
  db=sqlite3.connect(self.path,timeout=10)
  try:
   with db:yield db
  finally:db.close()
 def get(self,key):
  with self.connect() as db:row=db.execute('SELECT value FROM control WHERE key=?',(key,)).fetchone()
  return row[0] if row else None
 def set(self,key,value):
  with self.connect() as db:db.execute('INSERT OR REPLACE INTO control VALUES(?,?)',(key,value))
 def bind(self,items):
  with self.connect() as db:
   # Series is no longer public; keep its historical bindings/cache, never schedule new translations.
   db.execute("DELETE FROM binding WHERE kind<>'series'")
   db.executemany('INSERT OR REPLACE INTO binding VALUES(?,?,?,?)',[(x.kind,x.source_id,x.source_hash,x.key) for x in items])
   for item in items:db.execute("INSERT OR IGNORE INTO job(key,kind,state,reason) VALUES(?,?,'pending','')",(item.key,item.kind))
 def due(self,item):
  with self.connect() as db:
   if db.execute('SELECT 1 FROM entry WHERE key=?',(item.key,)).fetchone():return False
   row=db.execute('SELECT state,attempts,next_retry FROM job WHERE key=?',(item.key,)).fetchone()
  return row is None or (row[0] in ('pending','error') and row[1]<MAX_ATTEMPTS and row[2]<=time.time())
 def finish(self,item,state,reason='',zh=None,method='',provider=''):
  now=time.time()
  with self.connect() as db:
   if state in SUCCESS and zh:
    count,size=db.execute('SELECT count(*),coalesce(sum(length(CAST(zh AS BLOB))),0) FROM entry').fetchone()
    exists=db.execute('SELECT 1 FROM entry WHERE key=?',(item.key,)).fetchone()
    if (count>=MAX_ENTRIES and not exists) or size+len(zh.encode())>MAX_BYTES:state='error';reason='cache_capacity';zh=None
    else:db.execute('INSERT OR REPLACE INTO entry VALUES(?,?,?,?,?,?,?,?)',(item.key,item.kind,item.source_hash,zh,state,method,provider,now))
   db.execute('''INSERT INTO job VALUES(?,?,?,?,1,?,?) ON CONFLICT(key) DO UPDATE SET state=excluded.state,reason=excluded.reason,
    attempts=job.attempts+1,next_retry=excluded.next_retry,checked_at=excluded.checked_at''',(item.key,item.kind,state,reason,now+300 if state=='error' else 0,now))
 def stats(self):
  with self.connect() as db:
   rows=db.execute('''SELECT b.kind,coalesce(e.state,j.state,'pending'),coalesce(e.method,''),coalesce(j.reason,''),count(*)
    FROM binding b LEFT JOIN entry e ON e.key=b.key LEFT JOIN job j ON j.key=b.key GROUP BY 1,2,3,4''').fetchall()
   count,size=db.execute('SELECT count(*),coalesce(sum(length(CAST(zh AS BLOB))),0) FROM entry').fetchone()
   distinct=db.execute('SELECT count(DISTINCT key) FROM binding').fetchone()[0]
  result={};reasons=Counter()
  for kind,state,method,reason,n in rows:
   item=result.setdefault(kind,{'total':0,'states':{},'methods':{},'usable_display':0});item['total']+=n;item['states'][state]=item['states'].get(state,0)+n
   if method:item['methods'][method]=item['methods'].get(method,0)+n
   if state in SUCCESS:item['usable_display']+=n
   if state not in SUCCESS and reason:reasons[reason]+=n
  return {'fields':result,'distinct_inputs':distinct,'cached_entries':count,'cache_text_bytes':size,'failure_or_keep_reasons':dict(reasons),'paused':self.get('paused')=='1'}

class View:
 """Read-only, local projection. Missing/corrupt sidecar never starts translation."""
 def __init__(self,root):self.path=Path(root)/'translations.sqlite';self.entries={};self.stamp=None;self.lock=threading.Lock()
 def refresh(self):
  try:stamp=self.path.stat().st_mtime_ns
  except OSError:return
  if stamp==self.stamp:return
  with self.lock:
   if stamp==self.stamp:return
   try:
    with closing(sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True,timeout=2)) as db:
     entries={r[0]:{'text':None,'state':r[1],'method':'original'} for r in db.execute('SELECT key,state FROM job')}
     entries.update({r[0]:{'text':r[1],'state':r[2],'method':r[3]} for r in db.execute('SELECT key,zh,state,method FROM entry') if r[2] in SUCCESS and isinstance(r[1],str) and r[1].strip()})
    self.entries=entries;self.stamp=stamp
   except sqlite3.Error:pass
 def lookup(self,kind,raw,tokens=()):
  if not isinstance(raw,str) or not raw:return None
  self.refresh();return self.entries.get(Input(kind,'',raw,tuple(tokens)).key)
 def project(self,kind,raw,tokens=()):
  value=self.lookup(kind,raw,tokens)
  return {'display':value['text'] if value and value['text'] else raw,'zh':value['text'] if value else None,'state':value['state'] if value else 'original','method':value['method'] if value else 'original'}

class Worker:
 def __init__(self,config,*,transport=None,interval=1.0):
  self.config=config;self.store=Store(config.state/'localization');self.stop=asyncio.Event();self.providers=Providers(self.store,self.stop,transport,interval)
 async def translate(self,item):
  masked,used=protection(item.raw,item.tokens);body=MARK.sub('',masked).strip()
  if not body or not re.search(r'[\w\u3400-\u9fff]',body):self.store.finish(item,'unknown','protected_names_only');return
  glossary=GLOSSARY.get(item.raw) or GLOSSARY.get(item.raw.casefold())
  if item.kind=='categories' and glossary and not used:self.store.finish(item,'canonical',zh=glossary,method='dictionary');return
  if len(masked)>6000:self.store.finish(item,'unknown','input_too_long');return
  errors=[]
  for provider in ['google','bing']:
   try:
    translated=await self.providers.translate(provider,masked,'ja' if has_kana(body) else 'auto')
    if len(translated)>6000 or REFUSAL.search(translated) or '<' in translated:raise TranslationError('refused_or_invalid_text')
    translated=CC.convert(translated);out_body=MARK.sub('',translated).strip()
    if has_kana(out_body):raise TranslationError('untranslated_kana')
    if not HAN.search(out_body) and folded(out_body)!=folded(body):raise TranslationError('no_chinese_text')
    restored=restore(translated,used)
    if folded(out_body)==folded(CC.convert(body)):
     if has_kana(body):raise TranslationError('untranslated')
     changed=restored!=item.raw
     self.store.finish(item,'normalized' if changed else 'unknown','language_unverified',zh=restored if changed else None,method='normalized_unverified' if changed else '');return
    if not HAN.search(out_body):raise TranslationError('no_chinese_text')
    self.store.finish(item,'machine',zh=restored,method='machine',provider=provider);return
   except TranslationError as error:errors.append(provider+':'+error.reason)
  self.store.finish(item,'error',';'.join(errors))
 async def run(self,limit=0,items=None):
  lock=FileLock(self.store.root/'writer.lock')
  try:lock.acquire(timeout=0)
  except LockTimeout:return {'busy':True}
  processed=0
  try:
   items=inventory(self.config) if items is None else items;self.store.bind(items)
   unique={x.key:x for x in items if x.kind!='series'}
   for item in unique.values():
    if self.stop.is_set() or self.store.get('paused')=='1':break
    if not self.store.due(item):continue
    try:await self.translate(item)
    except asyncio.CancelledError:break
    except Exception:self.store.finish(item,'error','internal_error')
    processed+=1
    if limit and processed>=limit:break
   return {'processed':processed,**self.store.stats()}
  finally:lock.release()
 async def background(self):
  while not self.stop.is_set():
   try:await self.run(limit=50)
   except Exception:pass
   try:await asyncio.wait_for(self.stop.wait(),30)
   except TimeoutError:pass

async def command(config,action,limit=0):
 worker=Worker(config)
 if action=='pause':worker.store.set('paused','1')
 elif action=='resume':worker.store.set('paused','0')
 elif action=='batch':return await worker.run(limit)
 return worker.store.stats()
